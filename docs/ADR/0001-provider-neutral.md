# ADR 0001: Provider-neutral design

Status: Accepted.

Keep business logic and content contracts independent from model SDKs. DeepSeek API, Anthropic API, local models, and desktop tools are different integration modes; do not assume a desktop app is a drop-in HTTP API. Provider IDs and endpoints belong in configuration. Tests must run in mock mode.
