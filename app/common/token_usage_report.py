"""Utilities for analyzing token usage from proxy logs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable, List, Optional

USAGE_LINE_RE = re.compile(
    r"USAGE:\s+input=(?P<input>\d+)\s+\(cached=(?P<cached>\d+),\s+(?P<cache_pct>\d+)%\)\s+"
    r"output=(?P<output>\d+)\s+\(reasoning=(?P<reasoning>\d+)\)\s+total=(?P<total>\d+)"
)


@dataclass(frozen=True)
class UsageRecord:
    """A single request usage sample parsed from logs."""

    timestamp: datetime
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int

    @property
    def cache_pct(self) -> float:
        """Return the cache hit percentage for this request."""
        if self.input_tokens <= 0:
            return 0.0
        return (self.cached_tokens / self.input_tokens) * 100.0

    @property
    def non_cached_input_tokens(self) -> int:
        """Return the number of input tokens that were not cached."""
        return max(self.input_tokens - self.cached_tokens, 0)

    @property
    def total_output_tokens(self) -> int:
        """Return the request's output token count."""
        return self.output_tokens


@dataclass(frozen=True)
class TokenRates:
    """Per-million-token pricing assumptions."""

    input_per_million: float = 0.0
    cached_per_million: float = 0.0
    output_per_million: float = 0.0
    reasoning_per_million: float = 0.0


@dataclass(frozen=True)
class TokenUsageSummary:
    """Aggregate token usage for a time window."""

    records: List[UsageRecord]
    window_start: datetime
    window_end: datetime
    input_tokens: int
    cached_tokens: int
    non_cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    billable_output_tokens: int
    total_tokens: int
    estimated_spend: float

    @property
    def request_count(self) -> int:
        """Return the number of requests in the summary."""
        return len(self.records)

    @property
    def cache_hit_rate(self) -> float:
        """Return the overall cache hit rate for the summary."""
        if self.input_tokens <= 0:
            return 0.0
        return self.cached_tokens / self.input_tokens

    @property
    def input_tokens_per_request_avg(self) -> float:
        """Return the average input tokens per request."""
        if not self.records:
            return 0.0
        return self.input_tokens / len(self.records)


def parse_usage_line(line: str, timestamp: datetime) -> Optional[UsageRecord]:
    """Parse a single USAGE log line into a usage record."""
    match = USAGE_LINE_RE.search(line)
    if not match:
        return None

    return UsageRecord(
        timestamp=timestamp,
        input_tokens=int(match.group("input")),
        cached_tokens=int(match.group("cached")),
        output_tokens=int(match.group("output")),
        reasoning_tokens=int(match.group("reasoning")),
        total_tokens=int(match.group("total")),
    )


def parse_log_lines(lines: Iterable[str]) -> List[UsageRecord]:
    """Parse prefixed docker logs into usage records.

    Expected line format:
        flask-1  | 2026-04-24T12:34:56Z USAGE: input=...
    """
    records: List[UsageRecord] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        timestamp, message = _split_timestamp_and_message(line)
        if timestamp is None:
            continue
        record = parse_usage_line(message, timestamp)
        if record is not None:
            records.append(record)
    return records


def summarize_usage(
    records: Iterable[UsageRecord], *, rates: TokenRates, window_hours: int
) -> TokenUsageSummary:
    """Compute totals, spend, and context-window indicators."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    filtered = [record for record in records if record.timestamp >= window_start]

    input_tokens = sum(record.input_tokens for record in filtered)
    cached_tokens = sum(record.cached_tokens for record in filtered)
    output_tokens = sum(record.output_tokens for record in filtered)
    reasoning_tokens = sum(record.reasoning_tokens for record in filtered)
    billable_output_tokens = output_tokens + reasoning_tokens
    total_tokens = sum(record.total_tokens for record in filtered)
    non_cached_input_tokens = sum(record.non_cached_input_tokens for record in filtered)

    estimated_spend = (
        (non_cached_input_tokens / 1_000_000.0) * rates.input_per_million
        + (cached_tokens / 1_000_000.0) * rates.cached_per_million
        + (output_tokens / 1_000_000.0) * rates.output_per_million
        + (reasoning_tokens / 1_000_000.0) * rates.reasoning_per_million
    )

    return TokenUsageSummary(
        records=filtered,
        window_start=window_start,
        window_end=now,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        non_cached_input_tokens=non_cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        billable_output_tokens=billable_output_tokens,
        total_tokens=total_tokens,
        estimated_spend=estimated_spend,
    )


def input_token_percentiles(records: Iterable[UsageRecord]) -> dict[str, float]:
    """Return basic input-token distribution stats."""
    inputs = sorted(record.input_tokens for record in records)
    if not inputs:
        return {"min": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}

    def percentile(values: List[int], pct: float) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])
        rank = (len(values) - 1) * pct
        low = int(rank)
        high = min(low + 1, len(values) - 1)
        fraction = rank - low
        return float(values[low] + (values[high] - values[low]) * fraction)

    return {
        "min": float(inputs[0]),
        "p50": float(median(inputs)),
        "p90": percentile(inputs, 0.90),
        "p95": percentile(inputs, 0.95),
        "max": float(inputs[-1]),
    }


def _split_timestamp_and_message(line: str) -> tuple[Optional[datetime], str]:
    """Extract an ISO timestamp prefix from a docker log line."""
    match = re.match(
        r"^(?P<prefix>[^ ]+\s+\|\s+)?(?P<timestamp>\d{4}-\d{2}-\d{2}T[^ ]+)\s+(?P<message>.*)$",
        line,
    )
    if not match:
        return None, line
    timestamp_text = match.group("timestamp")
    try:
        timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError:
        return None, line
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc), match.group("message")
