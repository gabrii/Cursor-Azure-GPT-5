"""Tests for token usage log analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.common.token_usage_report import (
    TokenRates,
    UsageRecord,
    input_token_percentiles,
    parse_log_lines,
    summarize_usage,
)


def test_parse_log_lines_extracts_usage_records():
    """Parse docker log lines with timestamps and usage payloads."""
    lines = [
        "flask-1  | 2026-04-24T10:00:00+00:00 USAGE: input=100 (cached=25, 25%) output=50 (reasoning=10) total=150",
        "flask-1  | 2026-04-24T10:01:00+00:00 something else",
        "flask-1  | 2026-04-24T10:02:00Z USAGE: input=200 (cached=0, 0%) output=80 (reasoning=20) total=280",
    ]

    records = parse_log_lines(lines)

    assert len(records) == 2
    assert records[0].input_tokens == 100
    assert records[0].cached_tokens == 25
    assert records[0].output_tokens == 50
    assert records[0].reasoning_tokens == 10
    assert records[0].total_tokens == 150
    assert records[1].input_tokens == 200


def test_summarize_usage_filters_to_window_and_calculates_spend():
    """Summarize a 48-hour window using configured per-million rates."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=72)
    recent = now - timedelta(hours=12)
    records = [
        UsageRecord(
            timestamp=old,
            input_tokens=10,
            cached_tokens=5,
            output_tokens=2,
            reasoning_tokens=1,
            total_tokens=12,
        ),
        UsageRecord(
            timestamp=recent,
            input_tokens=1000,
            cached_tokens=250,
            output_tokens=400,
            reasoning_tokens=100,
            total_tokens=1400,
        ),
    ]

    summary = summarize_usage(
        records,
        rates=TokenRates(
            input_per_million=2.0,
            cached_per_million=0.5,
            output_per_million=10.0,
        ),
        window_hours=48,
    )

    assert summary.request_count == 1
    assert summary.input_tokens == 1000
    assert summary.cached_tokens == 250
    assert summary.non_cached_input_tokens == 750
    assert summary.output_tokens == 400
    assert summary.reasoning_tokens == 100
    assert summary.billable_output_tokens == 500
    assert summary.total_tokens == 1400
    assert summary.estimated_spend == (
        750 / 1_000_000 * 2.0 + 250 / 1_000_000 * 0.5 + 400 / 1_000_000 * 10.0
    )


def test_input_token_percentiles_capture_distribution():
    """Compute basic request-size stats for context-window analysis."""
    now = datetime.now(timezone.utc)
    records = [
        UsageRecord(
            timestamp=now,
            input_tokens=100,
            cached_tokens=0,
            output_tokens=10,
            reasoning_tokens=0,
            total_tokens=110,
        ),
        UsageRecord(
            timestamp=now,
            input_tokens=200,
            cached_tokens=0,
            output_tokens=10,
            reasoning_tokens=0,
            total_tokens=210,
        ),
        UsageRecord(
            timestamp=now,
            input_tokens=300,
            cached_tokens=0,
            output_tokens=10,
            reasoning_tokens=0,
            total_tokens=310,
        ),
        UsageRecord(
            timestamp=now,
            input_tokens=400,
            cached_tokens=0,
            output_tokens=10,
            reasoning_tokens=0,
            total_tokens=410,
        ),
    ]

    stats = input_token_percentiles(records)

    assert stats["min"] == 100.0
    assert stats["p50"] == 250.0
    assert stats["p90"] == 370.0
    assert stats["p95"] == 385.0
    assert stats["max"] == 400.0
