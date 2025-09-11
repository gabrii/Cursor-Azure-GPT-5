import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


@dataclass
class SSEEvent:
    event: Optional[str]
    data: str
    id: Optional[str] = None
    retry: Optional[int] = None
    # Monotonic sequence number (1-based) within a stream, set by the decoder
    index: int = 0
    # Lazy JSON cache (computed on first access of .json)
    _json_cached: bool = field(default=False, init=False, repr=False)
    _json_value: Optional[Any] = field(default=None, init=False, repr=False)

    @property
    def is_done(self) -> bool:
        try:
            return self.data.strip() == "[DONE]"
        except Exception:
            return False

    @property
    def json(self) -> Optional[Any]:
        """
        Parse the data as JSON once and cache the result.
        Returns None if not valid JSON or if this is the [DONE] sentinel.
        """
        if not self._json_cached:
            val: Optional[Any]
            text = (self.data or "").strip()
            if self.is_done or not text:
                val = None
            else:
                try:
                    val = json.loads(self.data)
                except Exception:
                    val = None
            self._json_value = val
            self._json_cached = True
        return self._json_value


class SSEDecoder:
    """
    Incremental SSE decoder. Feed incoming bytes and iterate parsed events.
    Keeps state across feeds and yields events when a blank line delimiter is encountered.
    """

    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding
        self.buffer: bytes = b""
        self._event_lines: List[bytes] = []
        self._seq: int = 0

    def _parse_event(self, lines: List[bytes]) -> SSEEvent:
        ev_type: Optional[str] = None
        data_parts: List[bytes] = []
        ev_id: Optional[str] = None
        retry: Optional[int] = None

        for l in lines:
            if not l:
                continue
            if l.startswith(b"event:"):
                ev_type = (
                    l.split(b":", 1)[1].strip().decode(self.encoding, errors="replace")
                )
            elif l.startswith(b"data:"):
                part = l[5:]
                if part.startswith(b" "):
                    part = part[1:]
                data_parts.append(part)
            elif l.startswith(b"id:"):
                val = l.split(b":", 1)[1]
                if val.startswith(b" "):
                    val = val[1:]
                ev_id = val.decode(self.encoding, errors="replace")
            elif l.startswith(b"retry:"):
                val = l.split(b":", 1)[1]
                if val.startswith(b" "):
                    val = val[1:]
                try:
                    retry = int(val.strip())
                except Exception:
                    retry = None
            elif l.startswith(b":"):
                # Comment line, ignore
                pass

        data_text = (
            b"\n".join(data_parts).decode(self.encoding, errors="replace")
            if data_parts
            else ""
        )
        return SSEEvent(event=ev_type, data=data_text, id=ev_id, retry=retry)

    def feed(self, chunk: bytes) -> Iterator[SSEEvent]:
        if not chunk:
            return
        self.buffer += chunk
        while True:
            idx = self.buffer.find(b"\n")
            if idx == -1:
                break
            line = self.buffer[: idx + 1]
            self.buffer = self.buffer[idx + 1 :]
            stripped = line.rstrip(b"\r\n")
            if stripped == b"":
                if self._event_lines:
                    ev = self._parse_event(self._event_lines)
                    self._seq += 1
                    ev.index = self._seq
                    yield ev
                self._event_lines = []
            else:
                self._event_lines.append(stripped)

    def end_of_input(self) -> Iterator[SSEEvent]:
        # Flush any pending event if the stream ended without a final blank line
        if self._event_lines:
            ev = self._parse_event(self._event_lines)
            self._seq += 1
            ev.index = self._seq
            yield ev
            self._event_lines = []


def sse_to_events(
    stream: Iterable[bytes], encoding: str = "utf-8"
) -> Iterator[SSEEvent]:
    decoder = SSEDecoder(encoding=encoding)
    for chunk in stream:
        yield from decoder.feed(chunk)
    yield from decoder.end_of_input()


def sse_to_chunks(
    stream: Iterable[bytes], *, skip_done: bool = True, encoding: str = "utf-8"
) -> Iterator[Dict[str, Any]]:
    """
    Convert an SSE byte-stream to an iterator of JSON dicts.
    - Collects multi-line data fields per SSE spec
    - Uses event.json to avoid repeated json.loads
    - Skips the [DONE] sentinel by default
    """
    for ev in sse_to_events(stream, encoding=encoding):
        if skip_done and ev.is_done:
            continue
        if ev.json is None:
            continue
        yield ev.json


def sse_to_json_events(
    stream: Iterable[bytes], *, skip_done: bool = True, encoding: str = "utf-8"
) -> Iterator[Tuple[Optional[str], Dict[str, Any]]]:
    """
    Like sse_to_chunks, but yields (event, json_obj) pairs for events whose data parses as JSON.
    Non-JSON events (and [DONE] if skip_done) are skipped.
    """
    for ev in sse_to_events(stream, encoding=encoding):
        if skip_done and ev.is_done:
            continue
        obj = ev.json
        if obj is None:
            continue
        yield (ev.event, obj)


def encode_sse_data(
    data: str, *, event: Optional[str] = None, id: Optional[str] = None
) -> bytes:
    """
    Encode a single SSE message. If the data contains newlines, they are split into
    multiple data: lines as per the SSE spec. Optionally include event and id.
    """
    out = bytearray()
    if id is not None:
        out.extend(b"id: ")
        out.extend(id.encode("utf-8"))
        out.extend(b"\n")
    if event is not None:
        out.extend(b"event: ")
        out.extend(event.encode("utf-8"))
        out.extend(b"\n")

    if data == "":
        out.extend(b"data:\n")
    else:
        for line in data.splitlines():
            out.extend(b"data: ")
            out.extend(line.encode("utf-8"))
            out.extend(b"\n")
    out.extend(b"\n")
    return bytes(out)


def encode_sse_json(
    obj: Any, *, event: Optional[str] = None, id: Optional[str] = None
) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return encode_sse_data(payload, event=event, id=id)


def chunks_to_sse(
    chunks: Iterable[Dict[str, Any]], *, add_done: bool = True
) -> Iterator[bytes]:
    try:
        for obj in chunks:
            yield encode_sse_json(obj)
    finally:
        if add_done:
            yield done_event_bytes()


def done_event_bytes() -> bytes:
    return encode_sse_data("[DONE]")
