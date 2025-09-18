"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

from .replay_base import ReplyBase


class TestError400(ReplyBase):
    """Test a single ping-pong interaction, no tool calls."""

    upstream_status_code = 400
    expected_downstream_status_code = 400
    upstream_response_body = b'{"foo": "bar"}'
    expected_downstream_response_body = b"""
Check "azure_response" for the error details:
\t{
\t    "endpoint": "https://t***e.openai.azure.com/openai/responses?api-version=2025-04-01-preview",
\t    "azure_status_code": 400,
\t    "azure_response": {
\t        "foo": "bar"
\t    },
\t    "request_body": {
\t        "instructions": "REDACTE...",
\t        "input": "...redacted 2 input items...",
\t        "model": "gpt-5",
\t        "tools": "...redacted 11 tools...",
\t        "tool_choice": "auto",
\t        "prompt_cache_key": "RED***TED",
\t        "stream": true,
\t        "reasoning": {
\t            "effort": "minimal",
\t            "summary": "detailed"
\t        },
\t        "store": false,
\t        "stream_options": {
\t            "include_obfuscation": false
\t        },
\t        "truncation": "auto"
\t    }
\t}
If the issue persists, report it to:
\thttps://github.com/gabrii/Cursor-Azure-GPT-5/issues
Including all the details above"""


class TestError401(ReplyBase):
    """Test a single ping-pong interaction, no tool calls."""

    upstream_status_code = 401
    expected_downstream_status_code = 400
    upstream_response_body = b'{"error": "Bad API Key or whatever"}'
    expected_downstream_response_body = b"""
Check "azure_response" for the error details:
\t{
\t    "endpoint": "https://t***e.openai.azure.com/openai/responses?api-version=2025-04-01-preview",
\t    "azure_status_code": 401,
\t    "azure_response": {
\t        "error": "Bad API Key or whatever"
\t    },
\t    "request_body": {
\t        "instructions": "REDACTE...",
\t        "input": "...redacted 2 input items...",
\t        "model": "gpt-5",
\t        "tools": "...redacted 11 tools...",
\t        "tool_choice": "auto",
\t        "prompt_cache_key": "RED***TED",
\t        "stream": true,
\t        "reasoning": {
\t            "effort": "minimal",
\t            "summary": "detailed"
\t        },
\t        "store": false,
\t        "stream_options": {
\t            "include_obfuscation": false
\t        },
\t        "truncation": "auto"
\t    }
\t}
If the issue persists, report it to:
\thttps://github.com/gabrii/Cursor-Azure-GPT-5/issues
Including all the details above"""


class TestError500(ReplyBase):
    """Test an error response where the response body is not json."""

    upstream_status_code = 500
    expected_downstream_status_code = 500
    upstream_response_body = b"Internal Server Error"
    expected_downstream_response_body = b"""
Check "azure_response" for the error details:
\t{
\t    "endpoint": "https://t***e.openai.azure.com/openai/responses?api-version=2025-04-01-preview",
\t    "azure_status_code": 500,
\t    "azure_response": "Internal Server Error",
\t    "request_body": {
\t        "instructions": "REDACTE...",
\t        "input": "...redacted 2 input items...",
\t        "model": "gpt-5",
\t        "tools": "...redacted 11 tools...",
\t        "tool_choice": "auto",
\t        "prompt_cache_key": "RED***TED",
\t        "stream": true,
\t        "reasoning": {
\t            "effort": "minimal",
\t            "summary": "detailed"
\t        },
\t        "store": false,
\t        "stream_options": {
\t            "include_obfuscation": false
\t        },
\t        "truncation": "auto"
\t    }
\t}
If the issue persists, report it to:
\thttps://github.com/gabrii/Cursor-Azure-GPT-5/issues
Including all the details above"""
