"""Tiny LLM client using only the standard library.

Supports four providers. The first key found in the environment wins
(or force one with LLM_PROVIDER=openai|anthropic|gemini|groq):

    OPENAI_API_KEY     + OPENAI_MODEL      (OpenAI chat completions)
    ANTHROPIC_API_KEY  + ANTHROPIC_MODEL   (Anthropic messages API)
    GEMINI_API_KEY     + GEMINI_MODEL      (Gemini's OpenAI-compatible endpoint)
    GROQ_API_KEY       + GROQ_MODEL        (Groq's OpenAI-compatible endpoint)
    OPENROUTER_API_KEY + OPENROUTER_MODEL  (OpenRouter, OpenAI-compatible, any model it hosts)

LLM_MODEL, if set, overrides the per-provider model.
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request

PROVIDERS = {
    "openai": {"key": "OPENAI_API_KEY", "model": "OPENAI_MODEL", "default_model": "gpt-4o-mini",
               "base_url": "https://api.openai.com/v1"},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "model": "ANTHROPIC_MODEL", "default_model": "claude-haiku-4-5",
                  "base_url": "https://api.anthropic.com/v1"},
    "gemini": {"key": "GEMINI_API_KEY", "model": "GEMINI_MODEL", "default_model": "gemini-2.5-flash",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "groq": {"key": "GROQ_API_KEY", "model": "GROQ_MODEL", "default_model": "llama-3.3-70b-versatile",
             "base_url": "https://api.groq.com/openai/v1"},
    "openrouter": {"key": "OPENROUTER_API_KEY", "model": "OPENROUTER_MODEL", "default_model": "openai/gpt-4o-mini",
                   "base_url": "https://openrouter.ai/api/v1"},
}


class LLMNotConfigured(Exception):
    pass


class LLMError(Exception):
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal  # True for bad key / bad model: no point retrying


def active_provider():
    """Return (provider_name, config) for the configured provider, or (None, None)."""
    forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
    order = [forced] if forced in PROVIDERS else list(PROVIDERS)
    for name in order:
        if os.environ.get(PROVIDERS[name]["key"], "").strip():
            return name, PROVIDERS[name]
    return None, None


def is_configured():
    return active_provider()[0] is not None


def describe():
    name, cfg = active_provider()
    if not name:
        return {"configured": False, "provider": None, "model": None}
    return {"configured": True, "provider": name, "model": _model(cfg)}


def _model(cfg):
    return (os.environ.get("LLM_MODEL") or os.environ.get(cfg["model"]) or cfg["default_model"]).strip()


def _post(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def chat_json(system, user, *, max_tokens=8000, retries=4, timeout=180):
    """Send one prompt, return the parsed JSON object the model replied with.

    Retries on rate limits / server errors / unparsable JSON with exponential backoff.
    """
    name, cfg = active_provider()
    if not name:
        raise LLMNotConfigured("No LLM key configured")
    key = os.environ[cfg["key"]].strip()
    model = _model(cfg)
    base = (os.environ.get("LLM_BASE_URL") or cfg["base_url"]).rstrip("/")

    last_error = None
    json_mode = True
    for attempt in range(retries):
        try:
            if name == "anthropic":
                data = _post(f"{base}/messages",
                             {"x-api-key": key, "anthropic-version": "2023-06-01"},
                             {"model": model, "max_tokens": max_tokens, "temperature": 0, "system": system,
                              "messages": [{"role": "user", "content": user}]}, timeout)
                text = "".join(b.get("text", "") for b in data.get("content", []))
            else:
                body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                data = _post(f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}, body, timeout)
                text = data["choices"][0]["message"]["content"] or ""
            return parse_json(text)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 400 and json_mode and name != "anthropic":
                json_mode = False  # model doesn't support JSON mode: ask again without it
                continue
            fatal = e.code in (400, 401, 402, 403, 404)  # bad request, bad key, no credit or unknown model: retrying won't help
            last_error = LLMError(f"{name} HTTP {e.code}: {detail}", fatal=fatal)
            if fatal:
                raise last_error
            wait = float(e.headers.get("Retry-After") or 0) or 2 ** attempt * 3
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            last_error = LLMError(f"{name}: {e}")
            wait = 2 ** attempt * 2
        time.sleep(min(wait, 60) + random.random())
    raise last_error


def parse_json(text):
    """Parse a JSON object from model output, tolerating ```json fences or extra prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError(f"Model did not return JSON: {text[:200]}")
