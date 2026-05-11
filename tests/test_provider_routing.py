"""Provider routing tests for Azure root and Codex path prefixes."""

from flask import Response

from app.blueprint import _provider_for_path

AUTH = {"Authorization": "Bearer test-service-api-key"}


def test_root_and_azure_models_return_azure_models(testapp):
    """Root and explicit Azure model routes expose the Azure model list."""
    root = testapp.get("/v1/models", headers=AUTH, status=200).json
    azure = testapp.get("/azure/v1/models", headers=AUTH, status=200).json

    root_ids = [item["id"] for item in root["data"]]
    azure_ids = [item["id"] for item in azure["data"]]

    assert root_ids == azure_ids
    assert "gpt-5.5" in root_ids


def test_codex_models_return_codex_models(testapp):
    """Codex model routes expose the Codex provider model list."""
    response = testapp.get("/codex/v1/models", headers=AUTH, status=200)

    assert [item["id"] for item in response.json["data"]] == [
        "codex-test-model",
        "codex-other-model",
    ]


def test_provider_path_resolution_keeps_root_azure_only():
    """Provider resolution is path-prefix based and root never falls through to Codex."""
    assert _provider_for_path("v1/chat/completions") == ("azure", "v1/chat/completions")
    assert _provider_for_path("azure/v1/chat/completions") == (
        "azure",
        "v1/chat/completions",
    )
    assert _provider_for_path("codex/v1/chat/completions") == (
        "codex",
        "v1/chat/completions",
    )


def test_root_and_azure_routes_call_azure_adapter(testapp, monkeypatch):
    """Root and /azure proxy traffic use Azure behavior."""
    calls = []

    def fake_forward(self, req):
        calls.append(req.path)
        return Response("azure", status=200)

    monkeypatch.setattr("app.azure.adapter.AzureAdapter.forward", fake_forward)

    testapp.post_json(
        "/v1/chat/completions",
        {"model": "gpt-5.4"},
        headers=AUTH,
        status=200,
    )
    testapp.post_json(
        "/azure/v1/chat/completions",
        {"model": "gpt-5.4"},
        headers=AUTH,
        status=200,
    )

    assert calls == ["/v1/chat/completions", "/azure/v1/chat/completions"]


def test_codex_route_calls_codex_adapter(testapp, monkeypatch):
    """Codex proxy traffic uses Codex behavior."""
    calls = []

    def fake_forward(self, req, provider_path):
        calls.append((req.path, provider_path))
        return Response("codex", status=200)

    monkeypatch.setattr("app.codex.adapter.CodexAdapter.forward", fake_forward)

    testapp.post_json(
        "/codex/v1/chat/completions",
        {"model": "codex-test-model"},
        headers=AUTH,
        status=200,
    )

    assert calls == [("/codex/v1/chat/completions", "v1/chat/completions")]


def test_disabled_provider_returns_local_error_without_fallback(
    testapp, app, monkeypatch
):
    """Disabled provider routes fail locally and do not call another provider."""
    app.config["ENABLE_CODEX"] = False

    def fail_forward(*args, **kwargs):  # pragma: no cover - only called on fallback bug
        raise AssertionError("disabled Codex provider must not forward")

    monkeypatch.setattr("app.azure.adapter.AzureAdapter.forward", fail_forward)

    response = testapp.post_json(
        "/codex/v1/responses",
        {"model": "codex-test-model", "input": "hello"},
        headers=AUTH,
        status=400,
    )

    assert "Codex provider is disabled" in response.text
