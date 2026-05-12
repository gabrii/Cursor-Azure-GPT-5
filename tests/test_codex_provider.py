"""Codex provider tests ported into the Flask application."""

from __future__ import annotations

import base64
import json
import time

import pytest

AUTH = {"Authorization": "Bearer test-service-api-key"}


def _jwt(exp: int | None = None) -> str:
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc({'exp': exp or int(time.time()) + 3600})}.sig"


def _write_auth(path):
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "id_token": _jwt(),
                    "access_token": _jwt(),
                    "refresh_token": "refresh",
                    "account_id": "acct",
                },
            }
        )
    )


def test_codex_ready_validates_auth_when_enabled(testapp, app, tmp_path):
    """Codex readiness validates local auth state when Codex is enabled."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    app.config["CODEX_AUTH_PATH"] = auth_file
    app.config["ENABLE_CODEX"] = True

    response = testapp.get("/codex/ready", headers=AUTH, status=200)

    assert response.json == {"status": "ready"}


def test_codex_ready_reports_not_ready_for_missing_auth(testapp, app, tmp_path):
    """Codex readiness returns a local not-ready error for missing auth state."""
    app.config["CODEX_AUTH_PATH"] = tmp_path / "missing.json"
    app.config["ENABLE_CODEX"] = True

    response = testapp.get("/codex/ready", headers=AUTH, status=503)

    assert response.json["status"] == "not_ready"
    assert "Codex Login State not found" in response.json["error"]


def test_codex_ready_allows_read_only_auth_file_when_directory_is_writable(
    testapp, app, tmp_path
):
    """Codex readiness accepts read-only auth files when refresh can replace them."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    auth_file.chmod(0o400)
    tmp_path.chmod(0o700)
    app.config["CODEX_AUTH_PATH"] = auth_file
    app.config["ENABLE_CODEX"] = True

    response = testapp.get("/codex/ready", headers=AUTH, status=200)

    assert response.json == {"status": "ready"}


def test_codex_responses_forwards_to_fake_upstream(testapp, app, tmp_path, monkeypatch):
    """Codex Responses route preserves forwarding behavior."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    app.config["CODEX_AUTH_PATH"] = auth_file
    captured = {}

    def fake_post(url, headers, json_body, *, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json_body

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}
            content = b'event: response.output_text.delta\ndata: {"delta":"hi"}\n\n'

        return FakeResponse()

    monkeypatch.setattr("app.codex.adapter.post_responses", fake_post)

    response = testapp.post_json(
        "/codex/v1/responses",
        {"model": "codex-test-model", "input": "hello", "reasoning": {"effort": "low"}},
        headers=AUTH,
        status=200,
    )

    assert captured["url"] == app.config["CODEX_RESPONSES_URL"]
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert captured["headers"]["ChatGPT-Account-Id"] == "acct"
    assert captured["json"]["model"] == "codex-test-model"
    assert captured["json"]["stream"] is True
    assert "response.output_text.delta" in response.text


def test_codex_provider_refreshes_and_retries_once_after_upstream_401(
    testapp, app, tmp_path, monkeypatch
):
    """A rejected access token gets one forced refresh and upstream retry."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    app.config["CODEX_AUTH_PATH"] = auth_file
    upstream_calls = []

    class FakeUpstreamResponse:
        headers = {"content-type": "text/event-stream"}

        def __init__(self, status_code, content=b""):
            self.status_code = status_code
            self.content = content
            self.closed = False

        def close(self):
            self.closed = True

    def fake_post_responses(url, headers, json_body, *, timeout):
        del url, json_body, timeout
        upstream_calls.append(headers["Authorization"])
        if len(upstream_calls) == 1:
            return FakeUpstreamResponse(401)
        return FakeUpstreamResponse(
            200,
            (
                b"event: response.output_text.delta\n"
                b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            ),
        )

    class FakeRefreshResponse:
        status_code = 200

        def json(self):
            return {
                "id_token": _jwt(int(time.time()) + 7200),
                "access_token": _jwt(int(time.time()) + 7200),
                "refresh_token": "new-refresh",
            }

    monkeypatch.setattr("app.codex.adapter.post_responses", fake_post_responses)
    monkeypatch.setattr(
        "app.codex.auth_state.requests.post",
        lambda *args, **kwargs: FakeRefreshResponse(),
    )

    response = testapp.post_json(
        "/codex/chat/completions",
        {
            "model": "codex-test-model",
            "input": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "medium"},
        },
        headers=AUTH,
        status=200,
    )

    assert len(upstream_calls) == 2
    assert upstream_calls[0] != upstream_calls[1]
    assert json.loads(auth_file.read_text())["tokens"]["refresh_token"] == "new-refresh"
    assert '"content":"hi"' in response.text


def test_codex_chat_completions_adapts_responses_sse_to_chat_sse(
    testapp, app, tmp_path, monkeypatch
):
    """Codex Chat Completions route adapts upstream Responses SSE to Chat SSE."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    app.config["CODEX_AUTH_PATH"] = auth_file

    def fake_post(url, headers, json_body, *, timeout):
        del url, headers
        assert json_body["model"] == "codex-test-model"

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}
            content = (
                b"event: response.output_text.delta\n"
                b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            )

        return FakeResponse()

    monkeypatch.setattr("app.codex.adapter.post_responses", fake_post)

    response = testapp.post_json(
        "/codex/chat/completions",
        {
            "model": "codex-test-model",
            "input": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "medium"},
        },
        headers=AUTH,
        status=200,
    )

    assert "chat.completion.chunk" in response.text
    assert (
        '"choices":[{"index":0,"delta":{"role":"assistant","content":"hi"}'
        in response.text
    )
    assert "response.output_text.delta" not in response.text


def test_codex_chat_completions_streams_without_buffering_content(
    testapp, app, tmp_path, monkeypatch
):
    """Codex streaming must not read response.content before yielding bytes."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    app.config["CODEX_AUTH_PATH"] = auth_file

    class FakeStreamingResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        @property
        def content(self):
            raise AssertionError("streaming adapter must use iter_content")

        def iter_content(self, chunk_size=8192):
            del chunk_size
            yield (
                b"event: response.output_text.delta\n"
                b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        "app.codex.adapter.post_responses",
        lambda *args, **kwargs: FakeStreamingResponse(),
    )

    response = testapp.post_json(
        "/codex/v1/chat/completions",
        {
            "model": "codex-test-model",
            "input": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "medium"},
        },
        headers=AUTH,
        status=200,
    )

    assert "chat.completion.chunk" in response.text
    assert '"content":"hi"' in response.text


def test_codex_model_rewrite_changes_only_upstream_model(
    testapp, app, tmp_path, monkeypatch
):
    """Configured Codex model rewrites affect only the upstream model field."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)
    app.config["CODEX_AUTH_PATH"] = auth_file
    app.config["CODEX_MODEL_REWRITES"] = {"codex-test-model": "codex-upstream-model"}
    app.config["CODEX_SUPPORTED_MODELS"] = (
        "codex-test-model",
        "codex-upstream-model",
    )
    captured = {}

    def fake_post(url, headers, json_body, *, timeout):
        del url, headers
        captured["json"] = json_body

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}
            content = (
                b"event: response.output_text.delta\n"
                b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            )

        return FakeResponse()

    monkeypatch.setattr("app.codex.adapter.post_responses", fake_post)

    response = testapp.post_json(
        "/codex/v1/chat/completions",
        {
            "model": "codex-test-model",
            "input": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "medium"},
        },
        headers=AUTH,
        status=200,
    )

    assert captured["json"]["model"] == "codex-upstream-model"
    assert captured["json"]["reasoning"] == {"effort": "medium"}
    assert '"model":"codex-upstream-model"' in response.text


@pytest.mark.parametrize("provider_path", ["/codex/v1/models", "/codex/ready"])
def test_codex_routes_require_shared_service_api_key(testapp, provider_path):
    """Codex provider uses the same Cursor-facing bearer secret."""
    testapp.get(provider_path, status=400)
