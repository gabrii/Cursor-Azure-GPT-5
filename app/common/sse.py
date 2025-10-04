"""Server-Sent Events (SSE) utilities.

This module provides helpers to decode and encode SSE streams, including:
- An incremental decoder that turns byte chunks into parsed events
- Convenience iterators to yield JSON payloads from SSE streams
- Helpers to encode Python values back into SSE-formatted bytes
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional

from requests.exceptions import ChunkedEncodingError

from .recording import record_sse


@dataclass
class SSEEvent:
    """A parsed Server-Sent Event.

    Attributes:
        event: Optional event type name sent by the server.
        data: Raw data payload for the event (possibly multi-line).
        id: Optional event ID, if provided by the server.
        retry: Optional reconnection delay in milliseconds.
        index: Monotonic sequence number assigned by the decoder.
    """

    event: Optional[str]
    data: str
    id: Optional[str] = None
    retry: Optional[int] = None
    # Monotonic sequence number (1-based) within a stream, set by the decoder
    index: int = 0

    @property
    def json(self) -> Optional[Any]:
        """Return the data parsed as JSON, caching the result.

        Returns None if the data is empty, invalid JSON, or the [DONE] sentinel.
        """
        if not self.data:
            print("Got empty data:", repr(self.data))
        text = (self.data or "").strip()
        val: Optional[Any] = json.loads(text)
        return val


class SSEDecoder:
    """Incremental SSE decoder.

    Feed incoming bytes and iterate parsed events. The decoder keeps state
    across feeds and yields events when a blank line delimiter is encountered.
    """

    def __init__(self, encoding: str = "utf-8") -> None:
        """Initialize the decoder with the given text encoding."""
        self.encoding = encoding
        self.buffer: bytes = b""
        self.full_buffer: bytes = b""
        self._event_lines: List[bytes] = []
        self._seq: int = 0

    def _parse_event(self, lines: List[bytes]) -> SSEEvent:
        ev_type: Optional[str] = None
        data_parts: List[bytes] = []
        ev_id: Optional[str] = None
        retry: Optional[int] = None

        for line in lines:
            if line.startswith(b"event:"):
                ev_type = (
                    line.split(b":", 1)[1]
                    .strip()
                    .decode(self.encoding, errors="replace")
                )
            else:
                if not line.startswith(b"data:"):
                    print("Got non-data line:", repr(line))
                data_parts.append(line[5:].strip())

        data_text = (
            b"\n".join(data_parts).decode(self.encoding, errors="replace")
            if data_parts
            else ""
        )
        return SSEEvent(event=ev_type, data=data_text, id=ev_id, retry=retry)

    def feed(self, chunk: bytes) -> Iterator[SSEEvent]:
        """Feed a new bytes chunk and yield any complete parsed events."""
        if not chunk:
            print("Got empty chunk!")
        self.buffer += chunk
        self.full_buffer += chunk
        while True:
            idx = self.buffer.find(b"\n")
            if idx == -1:
                break
            line = self.buffer[: idx + 1]
            self.buffer = self.buffer[idx + 1 :]
            stripped = line.rstrip(b"\r\n")
            if stripped == b"":
                if not self._event_lines:
                    print("Got empty event lines!")
                ev = self._parse_event(self._event_lines)
                self._seq += 1
                ev.index = self._seq
                yield ev
                self._event_lines = []
            else:
                self._event_lines.append(stripped)
        record_sse(self.full_buffer, "upstream_response")

    def end_of_input(self) -> Iterator[SSEEvent]:
        """Flush and yield a trailing event if the stream ended mid-message."""
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
    """Convert an SSE byte-stream into parsed SSEEvent objects."""
    decoder = SSEDecoder(encoding=encoding)
    try:
        for chunk in stream:
            yield from decoder.feed(chunk)
    except ChunkedEncodingError:
        print("Got ChunkedEncodingError! Here is the buffer so far:")
        print(decoder.full_buffer)
        import sys

        sys.exit(1)
        raise
    yield from decoder.end_of_input()


def encode_sse_data(data: str) -> bytes:
    """Encode a single SSE message into bytes.

    If the data contains newlines, they are split into multiple "data:" lines
    as per the SSE spec. Optionally include event and id.
    """
    out = bytearray()
    if not data:
        print("Got empty data to encode!")
    for line in data.splitlines():
        out.extend(b"data: ")
        out.extend(line.encode("utf-8"))
        out.extend(b"\n")
    out.extend(b"\n")
    return bytes(out)


def encode_sse_json(obj: Any) -> bytes:
    """Encode a Python object as JSON in SSE format and return bytes."""
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return encode_sse_data(payload)


def chunks_to_sse(chunks: Iterable[Dict[str, Any]]) -> Iterator[bytes]:
    """Encode an iterator of JSON-able dicts into SSE byte messages.

    If add_done is True, a final [DONE] sentinel event is yielded.
    """
    buffer = b""
    try:
        for obj in chunks:
            sse = encode_sse_json(obj)
            buffer += sse
            yield sse
        sse = done_event_bytes()
        buffer += sse
        yield sse
    finally:
        record_sse(buffer, "downstream_response")


def done_event_bytes() -> bytes:
    """Return the SSE-encoded [DONE] sentinel as bytes."""
    return encode_sse_data("[DONE]")
