"""Canonical Zero-Dependency LLM & Ollama HTTP Client (`forge/llm_client.py`).

Shared by `agent_team_hub.py` and `agent_engine.py` (single source of truth):
- Enforces non-redirecting HTTP (`_NoRedirectHandler`) so 301/302 redirects can NEVER bypass SSRF checks.
- Validates every LLM `base_url` against `validate_navigation_url` and locks `probe_ollama` strictly to
  loopback hosts (`127.0.0.1`, `localhost`, `::1`), excluding Luminara control/CDP ports.
- Safely handles Gemini multi-part / safety blocks, Anthropic thinking / multi-block content, OpenAI
  `content: null`, OpenRouter `X-Title` + `response_format` 400 fallback, and 20s local Ollama timeouts.
"""

from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .cdp_client import CDPError, validate_navigation_url

ENCODING = "utf-8"
DEFAULT_INTERNAL_PORTS = frozenset({8795, 8796, 9229})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

SUPPORTED_LLM_PROVIDERS = frozenset({"ollama", "openrouter", "gemini", "anthropic", "openai", "custom"})
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "ollama": ("http://127.0.0.1:11434", "llama3.2"),
    "openrouter": ("https://openrouter.ai/api/v1", "anthropic/claude-3.5-sonnet"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"),
    "anthropic": ("https://api.anthropic.com/v1", "claude-3-5-haiku-latest"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "custom": ("", "default"),
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail-closed redirect blocker preventing HTTP 3xx SSRF pivots to metadata or loopback control ports."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        raise urllib.error.HTTPError(req.full_url, code, f"Blocked HTTP {code} redirect in LLM client", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def validate_llm_base_url(base_url: str, *, blocked_ports: frozenset[int] | None = None) -> str:
    """Validate an LLM endpoint URL against scheme/metadata/internal-control-port SSRF rules."""
    cleaned = (base_url or "").strip()
    if not cleaned:
        return ""
    ports = DEFAULT_INTERNAL_PORTS | (blocked_ports or frozenset())
    return validate_navigation_url(cleaned, allow_file=False, blocked_ports=ports)


def probe_ollama(
    base_url: str = "http://127.0.0.1:11434",
    *,
    timeout: float = 1.0,
    blocked_ports: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Probe a loopback Ollama daemon (`/api/tags`) without following redirects; return `{running, models}`."""
    try:
        clean = validate_llm_base_url(base_url or "http://127.0.0.1:11434", blocked_ports=blocked_ports).rstrip("/")
        parsed = urllib.parse.urlparse(clean)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in _LOOPBACK_HOSTS:
            return {"running": False, "models": []}
        if clean.endswith("/v1"):
            clean = clean[:-3]
        req = urllib.request.Request(f"{clean}/api/tags", method="GET")
        with _NO_REDIRECT_OPENER.open(req, timeout=max(0.2, min(float(timeout), 5.0))) as resp:
            if getattr(resp, "status", 200) != 200:
                return {"running": False, "models": []}
            data = json.loads(resp.read().decode(ENCODING))
        raw_models = data.get("models") if isinstance(data, dict) else []
        models = [
            str(m["name"]).strip()
            for m in (raw_models or [])
            if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"].strip()
        ]
        return {"running": True, "models": models}
    except Exception:  # noqa: BLE001
        return {"running": False, "models": []}


def _post_json_no_redirect(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(ENCODING), headers=headers, method="POST")
    with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode(ENCODING))
    if not isinstance(data, dict):
        raise ValueError("LLM provider returned non-object JSON payload")
    return data


def _extract_gemini_text(data: dict[str, Any]) -> str:
    cands = data.get("candidates")
    if not isinstance(cands, list) or not cands:
        raise ValueError("Gemini returned no candidates")
    content = (cands[0] or {}).get("content") if isinstance(cands[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError("Gemini returned no content parts")
    texts = [
        p["text"]
        for p in parts
        if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip() and not p.get("thought")
    ]
    if not texts:
        texts = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip()]
    joined = "\n".join(texts).strip()
    if not joined:
        raise ValueError("Gemini returned empty text content")
    return joined


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    blocks = data.get("content")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("Anthropic returned no content blocks")
    texts = [
        b["text"]
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip()
    ]
    if not texts:
        texts = [b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str) and b["text"].strip()]
    joined = "\n".join(texts).strip()
    if not joined:
        raise ValueError("Anthropic returned empty text content")
    return joined


def _extract_openai_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("OpenAI-compatible provider returned no choices")
    msg = choices[0].get("message")
    if not isinstance(msg, dict):
        raise ValueError("OpenAI-compatible provider returned malformed message")
    content = msg.get("content")
    if content is None:
        raise ValueError("OpenAI-compatible provider returned null content")
    if isinstance(content, str):
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("OpenAI-compatible provider returned empty content")
        return cleaned
    if isinstance(content, list):
        parts = [
            p["text"]
            for p in content
            if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip()
        ]
        joined = "\n".join(parts).strip()
        if joined:
            return joined
    raise ValueError("OpenAI-compatible provider returned unsupported content payload")


def call_llm_completion(
    provider: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
    user_prompt: str,
    system_prompt: str = "",
    json_mode: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 900,
    timeout: float | None = None,
    blocked_ports: frozenset[int] | None = None,
) -> str:
    """Execute one non-redirecting LLM completion request across Gemini, Anthropic, or OpenAI-compatible APIs."""
    prov = (provider or "").strip().lower()
    if prov not in SUPPORTED_LLM_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider!r}")
    def_base, def_model = PROVIDER_DEFAULTS.get(prov, ("", "default"))
    eff_model = (model or "").strip() or def_model
    eff_timeout = float(timeout) if timeout is not None else (20.0 if prov == "ollama" else 15.0)
    raw_base = (base_url or "").strip() or def_base
    if not raw_base:
        raise ValueError(f"Missing base_url for provider {prov!r}")
    eff_base = validate_llm_base_url(raw_base, blocked_ports=blocked_ports).rstrip("/")
    if not eff_base:
        raise CDPError(f"Invalid base_url for provider {prov!r}")

    if prov == "gemini":
        url = f"{eff_base}/models/{urllib.parse.quote(eff_model, safe='')}:generateContent"
        gen_cfg: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": gen_cfg,
        }
        if system_prompt.strip():
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        data = _post_json_no_redirect(url, body, {"Content-Type": "application/json", "x-goog-api-key": api_key}, eff_timeout)
        return _extract_gemini_text(data)

    if prov == "anthropic":
        body = {
            "model": eff_model,
            "max_tokens": max(64, int(max_tokens)),
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system_prompt.strip():
            body["system"] = system_prompt
        hdrs = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
        data = _post_json_no_redirect(f"{eff_base}/messages", body, hdrs, eff_timeout)
        return _extract_anthropic_text(data)

    if prov == "ollama" and not eff_base.endswith("/v1"):
        eff_base = f"{eff_base}/v1"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'ollama'}"}
    if prov == "openrouter":
        headers["X-Title"] = "Luminara Browser"
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    body = {"model": eff_model, "temperature": temperature, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    endpoint = f"{eff_base}/chat/completions"
    try:
        data = _post_json_no_redirect(endpoint, body, headers, eff_timeout)
    except urllib.error.HTTPError as exc:
        if json_mode and exc.code in (400, 422):
            body.pop("response_format", None)
            data = _post_json_no_redirect(endpoint, body, headers, eff_timeout)
        else:
            raise
    return _extract_openai_text(data)


__all__ = [
    "DEFAULT_INTERNAL_PORTS",
    "PROVIDER_DEFAULTS",
    "SUPPORTED_LLM_PROVIDERS",
    "call_llm_completion",
    "probe_ollama",
    "validate_llm_base_url",
]
