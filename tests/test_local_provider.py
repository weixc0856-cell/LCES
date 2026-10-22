import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from content_studio.providers.base import GenerationRequest, Message
from content_studio.providers.factory import build_provider
from content_studio.providers.local_llama_cpp import LocalLlamaProvider
from content_studio.settings import Settings


class _FakeLlamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send({"status": "ok"})
        elif self.path == "/v1/models":
            self._send({"object": "list", "data": [{"id": "qwen-test", "object": "model"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        self._send(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": request.get("model", "qwen-test"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8},
            }
        )


@pytest.fixture
def fake_llama_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeLlamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_local_provider_roundtrip(fake_llama_server):
    provider = LocalLlamaProvider(base_url=fake_llama_server, timeout=5, discover_model=True)
    assert provider.model == "qwen-test"

    info = provider.probe()
    assert info["reachable"] is True
    assert info["models"] == ["qwen-test"]

    result = provider.generate(GenerationRequest(messages=[Message("user", "hi")], max_tokens=16))
    assert result.text == "OK"
    assert result.usage.total_tokens == 8
    provider.close()


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
