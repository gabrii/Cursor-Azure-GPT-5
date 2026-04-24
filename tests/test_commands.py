"""Tests for click commands defined in app.commands."""

from click.testing import CliRunner

import app.commands as commands


def test_test_command_calls_pytest_with_coverage_and_exits(mocker):
    """Invoke `test` command with defaults and ensure subprocess call args include coverage."""
    mock_call = mocker.patch("app.commands.call", return_value=0)

    runner = CliRunner()
    result = runner.invoke(commands.test)

    assert result.exit_code == 0
    mock_call.assert_called_once()
    cmdline = mock_call.call_args[0][0]
    assert cmdline == [
        "pytest",
        commands.TEST_PATH,
        "--verbose",
        "--cov=app",
        "--cov-branch",
        "--cov-report=xml",
        "--cov-report=html",
        "--cov-report=term",
    ]


def test_test_command_no_coverage_and_filter(mocker):
    """Invoke `test` with no coverage and a filter; ensure subprocess call args are correct."""
    mock_call = mocker.patch("app.commands.call", return_value=5)

    runner = CliRunner()
    result = runner.invoke(commands.test, ["-C", "-k", "unit and not e2e"])

    assert result.exit_code == 5
    mock_call.assert_called_once()
    cmdline = mock_call.call_args[0][0]
    assert cmdline == [
        "pytest",
        commands.TEST_PATH,
        "--verbose",
        "-k",
        "unit and not e2e",
    ]


def test_lint_command_invokes_tools_with_expected_order(mocker):
    """Invoke `lint` and ensure isort, black, flake8 are called in order."""
    mock_call = mocker.patch("app.commands.call", return_value=0)

    runner = CliRunner()
    result = runner.invoke(commands.lint)

    assert result.exit_code == 0
    # Expect three calls: isort, black, flake8
    assert mock_call.call_count == 3

    first_cmd = mock_call.call_args_list[0].args[0]
    second_cmd = mock_call.call_args_list[1].args[0]
    third_cmd = mock_call.call_args_list[2].args[0]

    assert first_cmd[0] == "isort"
    assert "--check" not in first_cmd

    assert second_cmd[0] == "black"
    assert "--check" not in second_cmd

    assert third_cmd[0] == "flake8"


def test_lint_command_check_mode_adds_check_flags(mocker):
    """Invoke `lint -c` and ensure --check is added to isort and black only."""
    mock_call = mocker.patch("app.commands.call", return_value=0)

    runner = CliRunner()
    result = runner.invoke(commands.lint, ["-c"])  # --check

    assert result.exit_code == 0
    assert mock_call.call_count == 3

    first_cmd = mock_call.call_args_list[0].args[0]
    second_cmd = mock_call.call_args_list[1].args[0]
    third_cmd = mock_call.call_args_list[2].args[0]

    # isort and black should receive --check
    assert first_cmd[0] == "isort"
    assert "--check" in first_cmd

    assert second_cmd[0] == "black"
    assert "--check" in second_cmd

    # flake8 should be called without --check
    assert third_cmd[0] == "flake8"
    assert "--check" not in third_cmd


def test_lint_command_exits_on_nonzero_return(mocker):
    """Ensure lint exits with the tool's non-zero code and stops after first call."""
    mock_call = mocker.patch("app.commands.call", return_value=2)

    runner = CliRunner()
    result = runner.invoke(commands.lint)

    assert result.exit_code == 2
    assert mock_call.call_count == 1
    first_cmdline = mock_call.call_args[0][0]
    assert first_cmdline[0] == "isort"
