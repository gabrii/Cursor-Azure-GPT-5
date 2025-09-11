import json
import os
import time
from typing import Any, Dict, Iterable, Optional

import requests
from flask import Request, Response
from loguru import logger
from rich.panel import Panel

from .common.logging import console, log_event
from .common.sse import SSEDecoder

SENSITIVE_HEADER_KEYS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "api_key",
}


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def should_redact() -> bool:
    return os.environ.get("LOG_REDACT", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def redact_value(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return value[:4] + "…" + value[-4:]


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    if not should_redact():
        return dict(headers)
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADER_KEYS:
            out[k] = redact_value(v)
        else:
            out[k] = v
    return out


def copy_request_headers(
    src: Request, *, override_auth: Optional[str]
) -> Dict[str, str]:
    headers: Dict[str, str] = {k: v for k, v in src.headers.items()}
    headers.pop("Host", None)
    if override_auth is not None:
        headers["Authorization"] = override_auth
    return headers


def filter_response_headers(
    headers: Dict[str, str], *, streaming: bool
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in HOP_BY_HOP_HEADERS:
            continue
        if streaming and k.lower() == "content-length":
            continue
        out[k] = v
    return out


class Backend:
    def forward(self, req: Request) -> Response:
        raise NotImplementedError


class OpenAIBackend(Backend):
    def __init__(
        self,
        base_url: str = "https://api.openai.com",
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    def _build_url(self, req: Request) -> str:
        path = req.path or "/"
        url = f"{self.base_url}{path}"
        if req.query_string:
            url = f"{url}?{req.query_string.decode('utf-8', 'ignore')}"
        return url

    def _parse_json(self, req: Request, body: bytes) -> Optional[Any]:
        if not body:
            return None
        try:
            data = req.get_json(silent=True, force=False)
            if data is not None:
                return data
        except Exception:
            pass
        try:
            return json.loads(body.decode(req.charset or "utf-8", errors="replace"))
        except Exception:
            return None

    @staticmethod
    def _clean_json_for_log(payload: Any) -> Any:
        if isinstance(payload, dict):
            return {k: v for k, v in payload.items() if k not in {"messages", "tools"}}
        return payload

    def forward(self, req: Request) -> Response:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return Response("Missing OPENAI_API_KEY", status=500, mimetype="text/plain")

        method = req.method.upper()
        url = self._build_url(req)
        body = req.get_data(cache=True)
        payload = self._parse_json(req, body)
        if payload:
            payload["model"] = "gpt-4.1-2025-04-14"
        is_stream = bool(payload.get("stream")) if isinstance(payload, dict) else False

        override_auth = f"Bearer {api_key}"
        upstream_headers = copy_request_headers(req, override_auth=override_auth)

        logger.info("OpenAI forward → {} {} stream={}", method, url, is_stream)
        console.print(Panel.fit("Upstream Request Headers (OpenAI)"))
        console.print(redact_headers(upstream_headers))
        if payload is not None:
            console.print(Panel.fit("Upstream Request JSON (clean)"))
            console.print(self._clean_json_for_log(payload))

        timeout_connect = float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT", "10"))
        timeout_read = (
            None if is_stream else float(os.environ.get("UPSTREAM_READ_TIMEOUT", "60"))
        )

        started = time.perf_counter()
        resp = self.session.request(
            method=method,
            url=url,
            headers=upstream_headers,
            json=payload,
            stream=is_stream,
            timeout=(timeout_connect, timeout_read),
        )
        took_ms = (time.perf_counter() - started) * 1000

        console.print(
            Panel.fit(f"Upstream Response — {resp.status_code} in {took_ms:.1f} ms")
        )
        console.print(filter_response_headers(dict(resp.headers), streaming=is_stream))
        if resp.status_code >= 400:
            try:
                err_json = resp.json()
                console.print(Panel.fit(f"Upstream Error JSON ({resp.status_code})"))
                console.print_json(data=err_json)
            except Exception:
                pass

        if is_stream:

            def generate() -> Iterable[bytes]:
                nonlocal resp
                decoder = SSEDecoder()
                try:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        # Pass-through
                        yield chunk

                        # Parse SSE for logging
                        for ev in decoder.feed(chunk):
                            if ev.is_done:
                                logger.info("OpenAI stream: [DONE]")
                                continue
                            log_event(ev)
                finally:
                    try:
                        # Flush any pending event for logging completeness
                        for ev in decoder.end_of_input():
                            if ev.is_done:
                                logger.info("OpenAI stream: [DONE]")
                                continue
                            log_event(ev)
                        resp.close()
                    except Exception:
                        pass

            headers = filter_response_headers(dict(resp.headers), streaming=True)
            return Response(generate(), status=resp.status_code, headers=headers)

        content = resp.content or b""
        if resp.status_code >= 400:
            try:
                err_json = resp.json()
                console.print(Panel.fit(f"Upstream Error JSON ({resp.status_code})"))
                console.print_json(data=err_json)
            except Exception:
                pass
        headers = filter_response_headers(dict(resp.headers), streaming=False)
        return Response(content, status=resp.status_code, headers=headers)
