#!/usr/bin/env python3
"""Analyze proxy token usage from Docker Compose logs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.common.token_usage_report import (  # noqa: E402
    TokenRates,
    input_token_percentiles,
    parse_log_lines,
    summarize_usage,
)

console = Console()


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Summarize token usage from the proxy's Docker logs."
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=48,
        help="How far back to analyze, in hours (default: 48).",
    )
    parser.add_argument(
        "--input-rate",
        type=float,
        default=0.75,
        help="USD per 1M non-cached input tokens.",
    )
    parser.add_argument(
        "--cached-rate",
        type=float,
        default=0.075,
        help="USD per 1M cached input tokens.",
    )
    parser.add_argument(
        "--output-rate",
        type=float,
        default=4.50,
        help="USD per 1M output tokens.",
    )
    parser.add_argument(
        "--log-source",
        choices=["docker-compose"],
        default="docker-compose",
        help="Where to read logs from.",
    )
    parser.add_argument(
        "--compose-service",
        default="flask",
        help="Docker Compose service name to inspect.",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=0,
        help="Limit docker compose logs with --tail when set.",
    )
    return parser


def read_docker_compose_logs(service: str, tail: int, hours: int) -> list[str]:
    """Read logs from docker compose."""
    cmd = ["docker", "compose", "logs", "--timestamps", "--since", f"{hours}h"]
    if tail > 0:
        cmd.extend(["--tail", str(tail)])
    cmd.append(service)
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "docker compose logs failed"
        )
    return completed.stdout.splitlines()


def render_report(*, summary, rates: TokenRates) -> None:
    """Render an interactive report to the console."""
    console.rule("Token usage report")

    totals = Table(show_header=False, box=None)
    totals.add_column("Metric", style="cyan", no_wrap=True)
    totals.add_column("Value", style="white")
    totals.add_row("Requests", str(summary.request_count))
    totals.add_row("Input tokens", f"{summary.input_tokens:,}")
    totals.add_row("Cached input tokens", f"{summary.cached_tokens:,}")
    totals.add_row("Non-cached input tokens", f"{summary.non_cached_input_tokens:,}")
    totals.add_row("Output tokens", f"{summary.output_tokens:,}")
    totals.add_row("Reasoning tokens", f"{summary.reasoning_tokens:,}")
    totals.add_row("Billable output tokens", f"{summary.billable_output_tokens:,}")
    totals.add_row("Total tokens", f"{summary.total_tokens:,}")
    totals.add_row("Cache hit rate", f"{summary.cache_hit_rate:.1%}")
    totals.add_row("Estimated spend", f"${summary.estimated_spend:.4f}")
    console.print(totals)

    stats = input_token_percentiles(summary.records)
    percentiles = Table(title="Input tokens per request", box=None)
    percentiles.add_column("Metric", style="cyan")
    percentiles.add_column("Tokens", style="white", justify="right")
    percentiles.add_row("Min", f"{stats['min']:.0f}")
    percentiles.add_row("P50", f"{stats['p50']:.0f}")
    percentiles.add_row("P90", f"{stats['p90']:.0f}")
    percentiles.add_row("P95", f"{stats['p95']:.0f}")
    percentiles.add_row("Max", f"{stats['max']:.0f}")
    percentiles.add_row("Average", f"{summary.input_tokens_per_request_avg:.1f}")
    console.print(percentiles)

    if rates != TokenRates():
        cost_table = Table(title="Configured rates", box=None)
        cost_table.add_column("Type", style="cyan")
        cost_table.add_column("USD / 1M tokens", style="white", justify="right")
        cost_table.add_row("Input", f"{rates.input_per_million:.4f}")
        cost_table.add_row("Cached input", f"{rates.cached_per_million:.4f}")
        cost_table.add_row("Output", f"{rates.output_per_million:.4f}")
        console.print(cost_table)

    if summary.records:
        top = Table(title="Largest requests by input tokens", box=None)
        top.add_column("Timestamp", style="cyan")
        top.add_column("Input", justify="right")
        top.add_column("Cached", justify="right")
        top.add_column("Output", justify="right")
        top.add_column("Reasoning", justify="right")
        top.add_column("Total", justify="right")
        for record in sorted(
            summary.records, key=lambda r: r.input_tokens, reverse=True
        )[:10]:
            top.add_row(
                record.timestamp.isoformat(),
                f"{record.input_tokens:,}",
                f"{record.cached_tokens:,}",
                f"{record.output_tokens:,}",
                f"{record.reasoning_tokens:,}",
                f"{record.total_tokens:,}",
            )
        console.print(top)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.log_source != "docker-compose":
        raise SystemExit(f"Unsupported log source: {args.log_source}")

    lines = read_docker_compose_logs(args.compose_service, args.tail, args.hours)
    records = parse_log_lines(lines)
    summary = summarize_usage(
        records,
        rates=TokenRates(
            input_per_million=args.input_rate,
            cached_per_million=args.cached_rate,
            output_per_million=args.output_rate,
        ),
        window_hours=args.hours,
    )
    render_report(
        summary=summary,
        rates=TokenRates(
            input_per_million=args.input_rate,
            cached_per_million=args.cached_rate,
            output_per_million=args.output_rate,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
