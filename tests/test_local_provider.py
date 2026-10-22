from content_studio.providers.factory import build_provider
from content_studio.providers.local_llama_cpp import LocalLlamaProvider
from content_studio.settings import Settings


def test_local_provider_needs_no_api_key():
    provider = LocalLlamaProvider(model="qwen-local", discover_model=False)
    assert provider.name == "local"
    assert provider.model == "qwen-local"
    assert provider.native_json_mode is True
    assert "Authorization" not in provider._headers()


def test_local_provider_sends_key_when_configured():
    provider = LocalLlamaProvider(model="qwen-local", api_key="secret-token", discover_model=False)
    assert provider._headers()["Authorization"] == "Bearer secret-token"


def test_local_provider_probe_reports_unreachable():
    provider = LocalLlamaProvider(
        base_url="http://127.0.0.1:9/v1", model="qwen-local", discover_model=False
    )
    info = provider.probe()
    assert info["reachable"] is False
    assert info["models"] == []
    assert info["error"]


def test_factory_builds_local_without_network():
    settings = Settings(
        _env_file=None,
        provider="local",
        local_model="qwen-local",
        local_base_url="http://127.0.0.1:9/v1",
    )
    provider = build_provider(settings)
    assert isinstance(provider, LocalLlamaProvider)
    assert provider.model == "qwen-local"


def test_settings_accepts_vendor_api_key_alias(monkeypatch):
    monkeypatch.delenv("LCES_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "alias-key")
    settings = Settings(_env_file=None, provider="deepseek")
    assert settings.deepseek_api_key == "alias-key"
