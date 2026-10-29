"""The AI writer. Tries each provider in turn (Gemini's free tier, any OpenAI-compatible API, then a local
Ollama model) and returns parsed JSON, so one being down or rate-limited never stops a run."""
from __future__ import annotations

import json
import logging
import re

import requests

from .config import AIConfig

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def parse_json(text: str):
    """Pulls the JSON out of a model reply, tolerating ```json fences and chatter around it."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise LLMError("The AI didn't reply with JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"The AI's JSON was broken ({e.msg})") from None


class LLM:
    def __init__(self, cfg: AIConfig, session: requests.Session | None = None):
        self.cfg = cfg
        self.http = session or requests.Session()
        self.used = ""  # which provider answered last

    def available(self) -> list[str]:
        ready = {
            "gemini": lambda: bool(self.cfg.gemini_api_key),
            "openai": lambda: bool(self.cfg.openai_base_url and self.cfg.openai_model),
            "ollama": lambda: bool(self.cfg.ollama_model) and self._ollama_up(),
        }
        return [p for p in self.cfg.providers if p in ready and ready[p]()]

    def json(self, system: str, prompt: str, temperature: float = 0.8):
        errors = []
        providers = self.available()
        if not providers:
            raise LLMError("No AI writer is set up. Add a free Gemini key with `trendclips setup`, "
                           "or install Ollama (see the README).")
        for name in providers:
            try:
                text = getattr(self, f"_{name}")(system, prompt, temperature)
                result = parse_json(text)
                self.used = name
                return result
            except (requests.RequestException, LLMError, KeyError, IndexError, ValueError) as e:
                msg = _safe_error(e)
                log.warning("AI writer %s failed: %s", name, msg)
                errors.append(f"{name}: {msg}")
        raise LLMError("Every AI writer failed. " + "; ".join(errors))

    def _gemini(self, system: str, prompt: str, temperature: float) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.cfg.gemini_model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
        }
        r = self.http.post(url, json=body, headers={"x-goog-api-key": self.cfg.gemini_api_key}, timeout=120)
        if r.status_code == 429:
            raise LLMError("Gemini's free-tier limit was hit; it resets within a minute to a day")
        if r.status_code in (400, 403) and "API key" in r.text:
            raise LLMError("Gemini rejected the API key; check ai.gemini_api_key")
        r.raise_for_status()
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise LLMError(f"Gemini returned nothing (finish reason: {cand.get('finishReason', 'unknown')})")
        return text

    def _openai(self, system: str, prompt: str, temperature: float) -> str:
        url = self.cfg.openai_base_url.rstrip("/") + "/chat/completions"
        body = {"model": self.cfg.openai_model, "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {self.cfg.openai_api_key}"} if self.cfg.openai_api_key else {}
        r = self.http.post(url, json=body, headers=headers, timeout=180)
        if r.status_code == 400 and "response_format" in r.text:  # some providers don't support JSON mode
            body.pop("response_format")
            r = self.http.post(url, json=body, headers=headers, timeout=180)
        if r.status_code == 429:
            raise LLMError("rate limit hit")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _ollama(self, system: str, prompt: str, temperature: float) -> str:
        body = {"model": self.cfg.ollama_model, "stream": False, "format": "json",
                "keep_alive": "2m",  # frees the laptop's memory soon after, before video rendering starts
                "options": {"temperature": temperature, "num_ctx": 8192},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        # A small model on an older laptop's CPU can take a few minutes for a long reply.
        r = self.http.post(self.cfg.ollama_url.rstrip("/") + "/api/chat", json=body, timeout=900)
        if r.status_code == 404:
            raise LLMError(f"Ollama doesn't have {self.cfg.ollama_model}; run: ollama pull {self.cfg.ollama_model}")
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _ollama_up(self) -> bool:
        try:
            return self.http.get(self.cfg.ollama_url.rstrip("/") + "/api/version", timeout=2).ok
        except requests.RequestException:
            return False


def _safe_error(e: Exception) -> str:
    """Error text without URLs, which can contain API keys."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    if isinstance(e, requests.RequestException):
        return type(e).__name__
    return str(e)
