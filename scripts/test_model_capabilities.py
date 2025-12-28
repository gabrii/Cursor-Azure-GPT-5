#!/usr/bin/env python3
"""
Model Capabilities Testing Script.

Tests model configurations independently to discover which values are supported
for each parameter. Variables are tested independently (not permuted) since they
are independent of each other.

For each model, tests:
- All reasoning effort levels (minimal, low, medium, high)
- All verbosity levels (low, medium, high)
- All truncation modes (auto, disabled)
- All summary levels (auto, detailed, concise)

Usage:
    python scripts/test_model_capabilities.py

Required environment variables (from parent environment or .env):
    AZURE_BASE_URL: Your Azure OpenAI endpoint
    AZURE_API_KEY: Your Azure API key
    SERVICE_API_KEY: API key for authenticating to this service

Optional environment variables:
    MODELS_TO_TEST: Comma-separated list of model deployment names to test
                    (default: all gpt-5 models)
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

# Load .env file if it exists
load_dotenv()

console = Console()


# =============================================================================
# Configuration
# =============================================================================

# Models to test (can be overridden via MODELS_TO_TEST env var)
DEFAULT_MODELS = [
    "gpt-5.2",
    "gpt-5.2-chat",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-5.1-codex-max",
    "gpt-5",
    # "gpt-5-chat-global",
    "gpt-5-nano",
    "gpt-5-mini-global",
    "gpt-5-pro",
    "gpt-5-codex",
]

# Base configuration (expected to work for all models)
BASE_CONFIG = {
    "AZURE_VERBOSITY_LEVEL": "medium",
    "AZURE_TRUNCATION": "disabled",
    "AZURE_SUMMARY_LEVEL": "auto",
}
BASE_REASONING_EFFORT = "medium"

# Values to test for each parameter
REASONING_EFFORTS = ["minimal", "low", "medium", "high"]
VERBOSITY_LEVELS = ["low", "medium", "high"]
TRUNCATION_MODES = ["auto", "disabled"]
SUMMARY_LEVELS = ["auto", "detailed", "concise"]

# Service configuration
SERVICE_HOST = "127.0.0.1"
STARTUP_TIMEOUT = 15  # seconds to wait for service to start
REQUEST_TIMEOUT = 60  # seconds to wait for completions request


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CapabilityTestResult:
    """Result of a single capability test case."""

    model: str
    category: str  # 'reasoning', 'verbosity', 'truncation', 'summary'
    tested_value: str
    success: bool
    error_message: str = ""
    response_snippet: str = ""


@dataclass
class ModelCapabilities:
    """Discovered capabilities for a model."""

    model: str
    supported_reasoning_efforts: set = field(default_factory=set)
    supported_verbosities: set = field(default_factory=set)
    supported_truncations: set = field(default_factory=set)
    supported_summary_levels: set = field(default_factory=set)
    results: list = field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_for_service(host: str, port: int, timeout: float = 10) -> bool:
    """Wait for the service to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"http://{host}:{port}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def start_service(env_overrides: dict[str, str], port: int) -> subprocess.Popen:
    """Start the Flask service with specified environment variables."""
    env = os.environ.copy()
    env.update(env_overrides)
    env["FLASK_ENV"] = "production"
    env["FLASK_DEBUG"] = "0"
    env["LOG_CONTEXT"] = "off"
    env["LOG_COMPLETION"] = "off"

    cmd = [
        sys.executable,
        "-m",
        "flask",
        "run",
        "--host",
        SERVICE_HOST,
        "--port",
        str(port),
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    return proc


def stop_service(proc: subprocess.Popen) -> None:
    """Gracefully stop the service."""
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def send_test_request(
    host: str, port: int, model_name: str, api_key: str
) -> tuple[bool, str, str]:
    """
    Send a simple chat completion request.

    Returns:
        (success, error_message, response_snippet)
    """
    url = f"http://{host}:{port}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "stream": True,
    }

    try:
        with requests.post(
            url, headers=headers, json=payload, stream=True, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status_code != 200:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get(
                        "message", resp.text[:2000]
                    )
                except (ValueError, KeyError):
                    error_msg = resp.text[:2000]
                return False, f"HTTP {resp.status_code}: {error_msg}", ""

            content_parts = []
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        if "error" in data:
                            return (
                                False,
                                data["error"].get("message", str(data["error"])),
                                "",
                            )
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if content := delta.get("content"):
                                content_parts.append(content)
                    except json.JSONDecodeError:
                        pass

            full_content = "".join(content_parts)
            if full_content:
                return True, "", full_content[:100]
            return True, "", "(empty response)"

    except requests.Timeout:
        return False, "Request timed out", ""
    except requests.RequestException as e:
        return False, str(e), ""


def parse_azure_error(error_msg: str) -> str:
    """Extract the relevant part of Azure error messages."""
    if "BadRequestError" in error_msg:
        return "BadRequestError - Invalid parameter"
    if "InvalidParameterValue" in error_msg:
        return "InvalidParameterValue"
    if "model_not_found" in error_msg.lower():
        return "Model not found"
    return error_msg[:1000] if len(error_msg) > 100 else error_msg


# =============================================================================
# Main Testing Logic
# =============================================================================


def run_single_test(
    host: str,
    port: int,
    api_key: str,
    model: str,
    env_config: dict[str, str],
    reasoning_effort: str,
    category: str,
    tested_value: str,
    caps: ModelCapabilities,
) -> CapabilityTestResult:
    """Run a single test and update capabilities."""
    model_name = f"gpt-{reasoning_effort}"
    success, error, snippet = send_test_request(host, port, model_name, api_key)

    result = CapabilityTestResult(
        model=model.replace("-global", ""),
        category=category,
        tested_value=tested_value,
        success=success,
        error_message=parse_azure_error(error) if error else "",
        response_snippet=snippet,
    )
    caps.results.append(result)

    if success:
        if category == "reasoning":
            caps.supported_reasoning_efforts.add(tested_value)
        elif category == "verbosity":
            caps.supported_verbosities.add(tested_value)
        elif category == "truncation":
            caps.supported_truncations.add(tested_value)
        elif category == "summary":
            caps.supported_summary_levels.add(tested_value)

    return result


def run_tests(models: list[str]) -> dict[str, ModelCapabilities]:
    """Run all tests and return results by model."""
    service_api_key = os.environ.get("SERVICE_API_KEY", "change-me")

    # Validate required env vars
    required_vars = ["AZURE_BASE_URL", "AZURE_API_KEY"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        console.print(
            f"[red]Error: Missing required environment variables: {missing}[/red]"
        )
        sys.exit(1)

    results: dict[str, ModelCapabilities] = {}
    port = find_free_port()

    # Calculate total tests:
    # Per model: 4 reasoning + 3 verbosity + 2 truncation + 3 summary = 12 tests
    # But we can batch: reasoning tests share same env, others need separate envs
    # Env configs needed per model:
    #   1 (base) for all reasoning efforts
    #   + 2 for verbosity (low, high - medium is base)
    #   + 1 for truncation (auto - disabled is base)
    #   + 2 for summary (detailed, concise - auto is base)
    # = 6 service starts per model

    tests_per_model = (
        len(REASONING_EFFORTS)
        + len(VERBOSITY_LEVELS)
        + len(TRUNCATION_MODES)
        + len(SUMMARY_LEVELS)
    )
    total_tests = len(models) * tests_per_model
    current_test = 0

    console.print("\n[bold cyan]Model Capabilities Test Suite[/bold cyan]")
    console.print(f"Models to test: {len(models)}")
    console.print(f"Tests per model: {tests_per_model}")
    console.print(f"Total tests: {total_tests}")
    console.print(f"Base config: {BASE_CONFIG}\n")

    for model in models:
        caps = ModelCapabilities(model=model)
        results[model] = caps

        console.print(f"\n[bold yellow]{'═' * 50}[/bold yellow]")
        console.print(f"[bold yellow]Testing model: {model}[/bold yellow]")
        console.print(f"[bold yellow]{'═' * 50}[/bold yellow]")

        # =====================================================================
        # Test 1: All reasoning efforts with base env config
        # =====================================================================
        console.print("\n  [cyan]Testing reasoning efforts...[/cyan]")
        env_config = {**BASE_CONFIG, "AZURE_DEPLOYMENT": model}

        proc = start_service(env_config, port)
        try:
            if not wait_for_service(SERVICE_HOST, port, STARTUP_TIMEOUT):
                console.print("    [red]✗ Service failed to start[/red]")
                for effort in REASONING_EFFORTS:
                    current_test += 1
                    result = CapabilityTestResult(
                        model=model,
                        category="reasoning",
                        tested_value=effort,
                        success=False,
                        error_message="Service failed to start",
                    )
                    caps.results.append(result)
            else:
                for effort in REASONING_EFFORTS:
                    current_test += 1
                    result = run_single_test(
                        SERVICE_HOST,
                        port,
                        service_api_key,
                        model,
                        env_config,
                        effort,
                        "reasoning",
                        effort,
                        caps,
                    )
                    status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
                    error_info = (
                        f" {result.error_message}" if not result.success else ""
                    )
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{effort}: {status}{error_info}"
                    )
        finally:
            stop_service(proc)
            time.sleep(0.3)

        # =====================================================================
        # Test 2: Verbosity levels (each needs separate service start)
        # =====================================================================
        console.print("\n  [cyan]Testing verbosity levels...[/cyan]")
        for verbosity in VERBOSITY_LEVELS:
            current_test += 1
            env_config = {
                **BASE_CONFIG,
                "AZURE_DEPLOYMENT": model,
                "AZURE_VERBOSITY_LEVEL": verbosity,
            }

            proc = start_service(env_config, port)
            try:
                if not wait_for_service(SERVICE_HOST, port, STARTUP_TIMEOUT):
                    result = CapabilityTestResult(
                        model=model,
                        category="verbosity",
                        tested_value=verbosity,
                        success=False,
                        error_message="Service failed to start",
                    )
                    caps.results.append(result)
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{verbosity}: [red]✗[/red] Service failed"
                    )
                else:
                    result = run_single_test(
                        SERVICE_HOST,
                        port,
                        service_api_key,
                        model,
                        env_config,
                        BASE_REASONING_EFFORT,
                        "verbosity",
                        verbosity,
                        caps,
                    )
                    status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
                    error_info = (
                        f" {result.error_message}" if not result.success else ""
                    )
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{verbosity}: {status}{error_info}"
                    )
            finally:
                stop_service(proc)
                time.sleep(0.3)

        # =====================================================================
        # Test 3: Truncation modes
        # =====================================================================
        console.print("\n  [cyan]Testing truncation modes...[/cyan]")
        for truncation in TRUNCATION_MODES:
            current_test += 1
            env_config = {
                **BASE_CONFIG,
                "AZURE_DEPLOYMENT": model,
                "AZURE_TRUNCATION": truncation,
            }

            proc = start_service(env_config, port)
            try:
                if not wait_for_service(SERVICE_HOST, port, STARTUP_TIMEOUT):
                    result = CapabilityTestResult(
                        model=model,
                        category="truncation",
                        tested_value=truncation,
                        success=False,
                        error_message="Service failed to start",
                    )
                    caps.results.append(result)
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{truncation}: [red]✗[/red] Service failed"
                    )
                else:
                    result = run_single_test(
                        SERVICE_HOST,
                        port,
                        service_api_key,
                        model,
                        env_config,
                        BASE_REASONING_EFFORT,
                        "truncation",
                        truncation,
                        caps,
                    )
                    status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
                    error_info = (
                        f" {result.error_message}" if not result.success else ""
                    )
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{truncation}: {status}{error_info}"
                    )
            finally:
                stop_service(proc)
                time.sleep(0.3)

        # =====================================================================
        # Test 4: Summary levels
        # =====================================================================
        console.print("\n  [cyan]Testing summary levels...[/cyan]")
        for summary in SUMMARY_LEVELS:
            current_test += 1
            env_config = {
                **BASE_CONFIG,
                "AZURE_DEPLOYMENT": model,
                "AZURE_SUMMARY_LEVEL": summary,
            }

            proc = start_service(env_config, port)
            try:
                if not wait_for_service(SERVICE_HOST, port, STARTUP_TIMEOUT):
                    result = CapabilityTestResult(
                        model=model,
                        category="summary",
                        tested_value=summary,
                        success=False,
                        error_message="Service failed to start",
                    )
                    caps.results.append(result)
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{summary}: [red]✗[/red] Service failed"
                    )
                else:
                    result = run_single_test(
                        SERVICE_HOST,
                        port,
                        service_api_key,
                        model,
                        env_config,
                        BASE_REASONING_EFFORT,
                        "summary",
                        summary,
                        caps,
                    )
                    status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
                    error_info = (
                        f" {result.error_message}" if not result.success else ""
                    )
                    console.print(
                        f"    [{current_test}/{total_tests}] "
                        f"{summary}: {status}{error_info}"
                    )
            finally:
                stop_service(proc)
                time.sleep(0.3)

    return results


def print_summary(results: dict[str, ModelCapabilities]) -> None:
    """Print a summary table of results."""
    console.print("\n")
    console.print("[bold cyan]═" * 60)
    console.print("[bold cyan]CAPABILITIES SUMMARY[/bold cyan]")
    console.print("[bold cyan]═" * 60)

    for model, caps in results.items():
        console.print(f"\n[bold yellow]{model}[/bold yellow]")

        # Reasoning efforts
        re_status = []
        for effort in REASONING_EFFORTS:
            if effort in caps.supported_reasoning_efforts:
                re_status.append(f"[green]✓ {effort}[/green]")
            else:
                re_status.append(f"[red]✗ {effort}[/red]")
        console.print(f"  Reasoning:  {' '.join(re_status)}")

        # Verbosity
        verb_status = []
        for verb in VERBOSITY_LEVELS:
            if verb in caps.supported_verbosities:
                verb_status.append(f"[green]✓ {verb}[/green]")
            else:
                verb_status.append(f"[red]✗ {verb}[/red]")
        console.print(f"  Verbosity:  {' '.join(verb_status)}")

        # Truncation
        trunc_status = []
        for trunc in TRUNCATION_MODES:
            if trunc in caps.supported_truncations:
                trunc_status.append(f"[green]✓ {trunc}[/green]")
            else:
                trunc_status.append(f"[red]✗ {trunc}[/red]")
        console.print(f"  Truncation: {' '.join(trunc_status)}")

        # Summary Level
        summary_status = []
        for summary in SUMMARY_LEVELS:
            if summary in caps.supported_summary_levels:
                summary_status.append(f"[green]✓ {summary}[/green]")
            else:
                summary_status.append(f"[red]✗ {summary}[/red]")
        console.print(f"  Summary:    {' '.join(summary_status)}")


def print_detailed_table(results: dict[str, ModelCapabilities]) -> None:
    """Print a detailed table of all test results."""
    console.print("\n")
    console.print("[bold cyan]═" * 60)
    console.print("[bold cyan]DETAILED RESULTS[/bold cyan]")
    console.print("[bold cyan]═" * 60)

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Model", style="cyan")
    table.add_column("Category")
    table.add_column("Value")
    table.add_column("Status")
    table.add_column("Error/Response", max_width=40)

    for model, caps in results.items():
        for result in caps.results:
            status = "[green]✓ OK[/green]" if result.success else "[red]✗ FAIL[/red]"
            detail = result.response_snippet if result.success else result.error_message
            table.add_row(
                result.model,
                result.category,
                result.tested_value,
                status,
                detail,
            )

    console.print(table)


def generate_markdown_table(results: dict[str, ModelCapabilities]) -> str:
    """Generate a transposed markdown table with models as columns."""
    # Get model names without gpt- prefix and -global suffix for column headers
    model_names = []
    for model in results.keys():
        short_name = model.replace("gpt-", "").replace("-global", "")
        model_names.append(short_name)

    # Build header row
    header = "| Variable | Value | " + " | ".join(model_names) + " |"
    separator = "| --- | --- |" + " --- |" * len(model_names)

    lines = [header, separator]

    # Define all variable/value combinations to test
    test_rows = [
        ("Reasoning Effort", "minimal", "supported_reasoning_efforts"),
        ("Reasoning Effort", "low", "supported_reasoning_efforts"),
        ("Reasoning Effort", "medium", "supported_reasoning_efforts"),
        ("Reasoning Effort", "high", "supported_reasoning_efforts"),
        ("Verbosity", "low", "supported_verbosities"),
        ("Verbosity", "medium", "supported_verbosities"),
        ("Verbosity", "high", "supported_verbosities"),
        ("Truncation", "auto", "supported_truncations"),
        ("Truncation", "disabled", "supported_truncations"),
        ("Summary", "auto", "supported_summary_levels"),
        ("Summary", "detailed", "supported_summary_levels"),
        ("Summary", "concise", "supported_summary_levels"),
    ]

    for variable, value, attr_name in test_rows:
        cells = []
        for model, caps in results.items():
            supported_set = getattr(caps, attr_name)
            if value in supported_set:
                cells.append("✅")
            else:
                cells.append("❌")

        row = f"| {variable} | `{value}` | " + " | ".join(cells) + " |"
        lines.append(row)

    return "\n".join(lines)


# =============================================================================
# Entry Point
# =============================================================================


def main() -> None:
    """Main entry point."""
    models_env = os.environ.get("MODELS_TO_TEST", "")
    if models_env:
        models = [m.strip() for m in models_env.split(",") if m.strip()]
    else:
        models = DEFAULT_MODELS

    console.print("[bold]Starting Model Capabilities Testing[/bold]")
    console.print(f"Testing models: {models}")

    try:
        results = run_tests(models)

        print_summary(results)
        print_detailed_table(results)

        console.print("\n")
        console.print("[bold cyan]═" * 60)
        console.print("[bold cyan]MARKDOWN TABLE (for README)[/bold cyan]")
        console.print("[bold cyan]═" * 60)
        console.print("\n```markdown")
        console.print(generate_markdown_table(results))
        console.print("```\n")

    except KeyboardInterrupt:
        console.print("\n[yellow]Testing interrupted by user[/yellow]")
        sys.exit(1)


if __name__ == "__main__":
    main()
