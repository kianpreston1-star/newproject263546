#!/usr/bin/env python3
"""free-claude router: run Claude Code on free models, with automatic fallback.

Claude Code speaks the Anthropic Messages API. This small server listens on 127.0.0.1, takes
those requests, decides how demanding each one is (fast, main or smart) and sends it to free
OpenAI-compatible providers: NVIDIA NIM, OpenRouter, Google AI Studio and Z.ai. It translates
the request and the streamed reply in both directions.

When a provider answers "rate limited" or "quota used up", that provider or model rests until
its limit resets and the next model on the list takes over, so a session keeps going.

Only the Python standard library is used (Python 3.8 or newer). Run `router.py help` for the
list of commands.
"""
import collections
import email.utils
import getpass
import hashlib
import json
import math
import os
import queue
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

VERSION = "1.0.0"

HOME = os.path.expanduser("~")
CONFIG_DIR = os.environ.get("FREE_CLAUDE_CONFIG_DIR") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "free-claude")
STATE_DIR = os.environ.get("FREE_CLAUDE_STATE_DIR") or os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local", "state"), "free-claude")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
LOG_PATH = os.path.join(STATE_DIR, "router.log")
PID_PATH = os.path.join(STATE_DIR, "router.pid")
INSTALL_DIR = os.path.join(HOME, ".local", "share", "free-claude")
BIN_DIR = os.path.join(HOME, ".local", "bin")
SERVICE = "free-claude-router"
UNIT_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"),
                         "systemd", "user", SERVICE + ".service")
OLD_OPENROUTER_ENV = os.path.join(HOME, ".claude-openrouter.env")  # from the earlier one-provider script
DEFAULT_PORT = 8749
RAW_URL = "https://raw.githubusercontent.com/kianpreston1-star/newproject263546/{ref}/free-claude/{name}"
REFS = ("HEAD", "claude/keen-dirac-yp8pmx")  # the default branch first, then the branch it was built on
USER_AGENT = "free-claude/%s (+https://github.com/kianpreston1-star/newproject263546)" % VERSION
SIGNATURE = "free-claude"  # placeholder signature on thinking blocks; only this router reads them back
GEMINI_SKIP_SIGNATURE = "skip_thought_signature_validator"

# Settings a config file can override. Times are in seconds.
DEFAULTS = {
    "port": DEFAULT_PORT,
    "max_output_tokens": 16000,   # per reply; models with a lower cap get retried with less
    "context_window": 128000,     # what Claude Code assumes; it compacts the chat before this
    "first_token_timeout": 150,   # how long one model may take to start answering
    "idle_timeout": 180,          # how long a started answer may go silent
    "request_budget": 420,        # total time spent trying models for one request
    "permission_mode": "bypassPermissions",  # how claude-free starts Claude Code; "default" asks before acting
}

PROVIDERS = {
    "nvidia": {
        "label": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "signup": "https://build.nvidia.com (sign in, then press 'Get API Key'; it asks to verify a phone number)",
        "about": "the biggest free allowance: about 40 requests a minute and 10,000 a day",
        "key_prefix": "nvapi-",
        "rpm": 40,
        "account_wide_limits": True,  # one 429 means every NVIDIA model is throttled for this account
        "catalog": True,              # GET /models lists what's hosted, without a key
        "test_model": "z-ai/glm-5.3-flash",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "signup": "https://openrouter.ai/keys",
        "about": "free models: 50 requests a day, or 1,000 a day after a one-time $10 top-up",
        "key_prefix": "sk-or-",
        "rpm": 20,
        "headers": {"HTTP-Referer": "https://github.com/kianpreston1-star/newproject263546", "X-Title": "free-claude"},
        "catalog": True,
        "test_model": "openrouter/free",
    },
    "gemini": {
        "label": "Google AI Studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "signup": "https://aistudio.google.com/apikey",
        "about": "Gemini Flash, with a 1M-token memory; small daily limits per model",
        "key_prefix": "AIza",
        "gemini": True,
        "test_model": "gemini-flash-lite-latest",
    },
    "zai": {
        "label": "Z.ai",
        "base_url": "https://api.z.ai/api/paas/v4",
        "signup": "https://z.ai/manage-apikey/apikey-list",
        "about": "GLM-4.7-Flash is free with no daily cap, one request at a time",
        "max_concurrent": 1,
        "test_model": "glm-4.7-flash",
    },
}
PROVIDER_ORDER = ["nvidia", "openrouter", "gemini", "zai"]

# The models each tier tries, best first, as "provider:model". Models whose provider has no key
# are skipped, and models a provider stops listing are skipped too. If a whole tier is resting,
# the other tiers' models are tried after it, so a request only fails when everything is busy.
TIERS = {
    "fast": [
        "nvidia:z-ai/glm-5.3-flash",
        "nvidia:nvidia/nemotron-3.5-lightning-30b-a3b",
        "zai:glm-4.7-flash",
        "gemini:gemini-flash-lite-latest",
        "openrouter:nvidia/nemotron-3.5-lightning:free",
        "openrouter:poolside/laguna-xs-2.1:free",
        "nvidia:openai/gpt-oss-20b",
        "openrouter:openrouter/free",
    ],
    "main": [
        "nvidia:deepseek-ai/deepseek-v4.1-flash",
        "nvidia:z-ai/glm-5.3",
        "nvidia:minimaxai/minimax-m3.1-flash",
        "nvidia:moonshotai/kimi-k2.6",
        "gemini:gemini-flash-latest",
        "openrouter:poolside/laguna-s-2.1:free",
        "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter:cohere/north-mini-code:free",
        "openrouter:openrouter/free",
        "zai:glm-4.7-flash",
    ],
    "smart": [
        "nvidia:z-ai/glm-5.3",
        "nvidia:moonshotai/kimi-k2.6",
        "gemini:gemini-flash-latest",
        "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia:deepseek-ai/deepseek-v4.1-flash",
        "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
        "openrouter:poolside/laguna-s-2.1:free",
        "openrouter:openrouter/free",
        "zai:glm-4.7-flash",
    ],
}
TIER_FALLBACK = {"fast": ("fast", "main", "smart"), "main": ("main", "smart", "fast"), "smart": ("smart", "main", "fast")}

# The model names Claude Code sends, set through ANTHROPIC_DEFAULT_*_MODEL by `router.py env`.
ALIASES = {"free-fast": "fast", "free-auto": "auto", "free-smart": "smart"}
PICKER = {
    "HAIKU": ("free-fast", "Free · Fast", "Small, quick free models for simple jobs"),
    "SONNET": ("free-auto", "Free · Auto", "Picks a quick or a strong free model for each task"),
    "OPUS": ("free-smart", "Free · Smart", "Always the strongest free models (slower)"),
}

LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never send localhost through a proxy
UPSTREAM = urllib.request.build_opener()                             # honours HTTPS_PROXY like other tools
LOG_LOCK = threading.Lock()


def log(line):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_LOCK:
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 1_000_000:
                os.replace(LOG_PATH, LOG_PATH + ".1")
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (stamp, line))
        except OSError:
            pass


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        cfg = {}
    except (OSError, ValueError) as e:
        raise SystemExit("free-claude: can't read %s: %s" % (CONFIG_PATH, e))
    if not isinstance(cfg, dict):
        raise SystemExit("free-claude: %s should hold a JSON object" % CONFIG_PATH)
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)
    cfg.setdefault("keys", {})
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in cfg.items() if not (k in DEFAULTS and DEFAULTS[k] == v and k != "port")}, f, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)


def provider_settings(cfg, name):
    """The built-in settings for a provider, with the config file's overrides and key applied."""
    base = dict(PROVIDERS.get(name) or {})
    base.update((cfg.get("providers") or {}).get(name) or {})
    base["name"] = name
    base["key"] = (cfg.get("keys") or {}).get(name) or ""
    return base


def human_time(seconds):
    seconds = int(max(0, seconds))
    if seconds < 90:
        return "%ds" % seconds
    if seconds < 5400:
        return "%dm" % round(seconds / 60)
    hours, rest = divmod(seconds, 3600)
    return "%dh%02dm" % (hours, rest // 60)


# ---------------------------------------------------------------- picking a tier

CONTINUE_RE = re.compile(
    r"^\s*(y|yes|yep|yeah|ok|okay|k|sure|go|go ahead|do it|proceed|continue|keep going|carry on|next|"
    r"sounds good|lgtm|please do|yes please|yes do it|ok do it|go for it|\d{1,2})\s*[.!]*\s*$", re.I)
THINK_RE = re.compile(r"\b(ultrathink|megathink|think (?:very )?(?:hard|harder|deeply|carefully|step by step))\b", re.I)
HARD_RE = re.compile(
    r"\b(architect\w*|design\w*|refactor\w*|debug\w*|diagnos\w*|root cause|investigat\w*|race conditions?|"
    r"deadlocks?|memory leaks?|concurren\w*|thread.?safe\w*|performance|optimi[sz]\w*|profil\w*|scalab\w*|"
    r"security|vulnerab\w*|exploit\w*|migrat\w*|rewrite|from scratch|implement\w*|integrat\w*|algorithms?|"
    r"complex\w*|tricky|entire|whole (?:codebase|project|repo\w*|app\w*|program)|across (?:the|all|every)|"
    r"every file|end.to.end|test suite|edge.cases?|strateg\w*|trade.?offs?|"
    r"why (?:does|is|do|are|did|isn'?t|doesn'?t|won'?t|can'?t)|doesn'?t work|does not work|not working|broken|"
    r"failing|fails|crash\w*|exceptions?|stack ?traces?|traceback|segfault\w*|regressions?|flaky|bugs?|"
    r"build (?:a|an|me)|create (?:a|an) (?:new )?(?:app|game|site|website|api|server|service|tool|bot|program|"
    r"project|system|library|cli|extension|plugin))\b", re.I)
SIMPLE_RE = re.compile(
    r"(^\s*(?:what|what'?s|whats|where|which|who|when|show|list|print|display|explain|describe|summari[sz]e|"
    r"tell me|how do i|how to|can you explain|hi|hello|hey|thanks|thank you)\b)|"
    r"\b(rename\w*|typos?|spelling|reformat|format(?:ting)?|indent\w*|comments?|docstrings?|readme|changelog|"
    r"bump|commit|push|pull|git (?:status|log|diff|add)|run (?:the )?tests?|translate)\b", re.I)
CODEY_RE = re.compile(r"```|Traceback \(most recent call last\)|\b\w*(?:Error|Exception):|^\s+at \S+ \(", re.M)
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
PLAN_RE = re.compile(r"plan mode (?:is )?(?:active|on)\b", re.I)


def classify_text(text):
    """Guesses how demanding a prompt is. Returns (tier, reason)."""
    t = (text or "").strip()
    if not t:
        return "main", "no prompt text"
    if THINK_RE.search(t):
        return "smart", "asked to think hard"
    hard = sorted({m.group(0).lower() for m in HARD_RE.finditer(t)})
    simple = sorted({m.group(0).strip().lower() for m in SIMPLE_RE.finditer(t)})
    code = bool(CODEY_RE.search(t))
    if len(hard) >= 2 or (hard and (len(t) > 400 or code)) or len(t) > 1500:
        return "smart", "looks complex (%s)" % ", ".join(hard[:3] or ["long prompt"])
    if not hard and simple and len(t) < 300 and not code:
        return "fast", "looks simple (%s)" % ", ".join(simple[:3])
    return "main", "normal task" + (" (%s)" % hard[0] if hard else "")


def block_texts(content):
    if isinstance(content, str):
        return [content]
    return [b.get("text") or "" for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def human_text(messages):
    """The newest text a person typed: skips tool results and Claude Code's reminders."""
    for m in reversed(messages or []):
        if m.get("role") != "user":
            continue
        text = "\n".join(REMINDER_RE.sub("", p) for p in block_texts(m.get("content"))).strip()
        if text:
            return text
    return ""


def in_plan_mode(messages):
    for m in (messages or [])[-4:]:
        if m.get("role") in ("user", "system") and any(PLAN_RE.search(p) for p in block_texts(m.get("content"))):
            return True
    return False


class TierMemory:
    """Keeps one decision per prompt, so every step of a task uses the same tier."""

    def __init__(self, size=2000):
        self.lock = threading.Lock()
        self.prompts = collections.OrderedDict()
        self.sessions = collections.OrderedDict()
        self.size = size

    def _put(self, table, key, value):
        table[key] = value
        table.move_to_end(key)
        while len(table) > self.size:
            table.popitem(last=False)

    def get(self, key):
        with self.lock:
            return self.prompts.get(key)

    def session_tier(self, session):
        with self.lock:
            return self.sessions.get(session) if session else None

    def put(self, key, decision, session=None):
        with self.lock:
            self._put(self.prompts, key, decision)
            if session:
                self._put(self.sessions, session, decision[0])


def pick_tier(body, hdr, memory):
    """Returns (tier, reason) for a request, using Claude Code's hint headers where present."""
    alias = str(body.get("model") or "").lower()
    asked = ALIASES.get(alias)
    if not asked:
        asked = "fast" if "haiku" in alias else "smart" if ("opus" in alias or "fable" in alias) else "auto"
    kind = hdr.get("x-claude-code-request-class", "")
    agent = hdr.get("x-claude-code-agent-type", "")
    if kind == "auxiliary":
        return "fast", "background task"
    if kind == "compaction" or hdr.get("x-claude-code-compaction"):
        return ("smart" if asked == "smart" else "main"), "summarizing the conversation"
    if asked != "auto":
        return asked, "chosen with /model"
    if agent == "Explore":
        return "fast", "Explore subagent"
    if agent == "Plan":
        return "smart", "Plan subagent"
    messages = body.get("messages") or []
    if in_plan_mode(messages):
        return "smart", "plan mode"
    text = human_text(messages)
    session = hdr.get("x-claude-code-session-id", "")
    key = hdr.get("x-claude-code-prompt-id") or hashlib.sha1(
        (session + "\0" + text).encode("utf-8", "replace")).hexdigest()
    remembered = memory.get(key)
    if remembered:
        return remembered
    previous = memory.session_tier(session)
    if previous and CONTINUE_RE.match(text):
        decision = (previous, "follow-up to the last request")
    else:
        decision = classify_text(text)
    memory.put(key, decision, session if kind in ("", "main") else None)
    return decision


# ---------------------------------------------------------------- Anthropic request -> OpenAI request

GEMINI_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable",
                      "anyOf", "minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "pattern",
                      "default", "title", "minProperties", "maxProperties", "propertyOrdering"}


def clean_schema(node, gemini):
    """Drops JSON Schema keywords providers reject. Gemini accepts only a small subset."""
    if isinstance(node, list):
        return [clean_schema(x, gemini) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "$schema":
            continue
        if gemini:
            if k == "const":
                out["enum"] = [v]
                continue
            if k == "type" and isinstance(v, list):
                kinds = [x for x in v if x != "null"]
                out["type"] = kinds[0] if kinds else "string"
                if "null" in v:
                    out["nullable"] = True
                continue
            if k == "format" and v not in ("enum", "date-time"):
                continue
            if k == "oneOf":
                k = "anyOf"
            if k not in GEMINI_SCHEMA_KEYS:
                continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {name: clean_schema(s, gemini) for name, s in v.items()}
        else:
            out[k] = clean_schema(v, gemini)
    if gemini and isinstance(out.get("anyOf"), list):
        options = [o for o in out["anyOf"] if not (isinstance(o, dict) and o.get("type") == "null")]
        if len(options) < len(out["anyOf"]):
            out["nullable"] = True
        if len(options) == 1 and isinstance(options[0], dict):
            del out["anyOf"]
            for key, value in options[0].items():
                out.setdefault(key, value)
        else:
            out["anyOf"] = options
    return out


def convert_tools(tools, gemini):
    out = []
    for t in tools or []:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        if t.get("type") not in (None, "custom"):
            continue  # server tools such as Anthropic's web search only run on Anthropic's API
        fn = {"name": t["name"], "description": t.get("description") or ""}
        params = clean_schema(t.get("input_schema") or {"type": "object", "properties": {}}, gemini)
        if not (gemini and params.get("type") == "object" and not params.get("properties")):
            fn["parameters"] = params  # Gemini rejects an object with no properties, so it gets none
        out.append({"type": "function", "function": fn})
    return out


def convert_tool_choice(choice):
    if not isinstance(choice, dict):
        return None
    kind = choice.get("type")
    if kind == "tool" and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    return {"auto": "auto", "any": "required", "none": "none"}.get(kind)


def as_blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def image_part(block):
    src = block.get("source") or {}
    if src.get("type") == "base64" and src.get("data"):
        url = "data:%s;base64,%s" % (src.get("media_type") or "image/png", src["data"])
    elif src.get("type") == "url" and src.get("url"):
        url = src["url"]
    else:
        return None
    return {"type": "image_url", "image_url": {"url": url}}


def document_text(block):
    src = block.get("source") or {}
    if src.get("type") == "text":
        return src.get("data") or ""
    if src.get("type") == "content":
        return "\n".join(block_texts(src.get("content")))
    return "[A %s document was attached, but this model can't read it.]" % (src.get("media_type") or "binary")


def tool_result_parts(block):
    content = block.get("content")
    if isinstance(content, str):
        return content, []
    texts, images = [], []
    for b in as_blocks(content):
        if b.get("type") == "text":
            texts.append(b.get("text") or "")
        elif b.get("type") == "image":
            img = image_part(b)
            if img:
                images.append(img)
        elif b.get("type") == "document":
            texts.append(document_text(b))
    return "\n".join(texts), images


def user_parts(blocks):
    tool_msgs, parts, images = [], [], []
    for b in blocks:
        kind = b.get("type")
        if kind == "tool_result":
            text, imgs = tool_result_parts(b)
            if b.get("is_error"):
                text = "Error: " + text if text else "Error"
            tool_msgs.append({"role": "tool", "tool_call_id": str(b.get("tool_use_id") or ""), "content": text or "(no output)"})
            images.extend(imgs)
        elif kind == "image":
            img = image_part(b)
            if img:
                parts.append(img)
        elif kind == "document":
            parts.append({"type": "text", "text": document_text(b)})
        elif isinstance(b.get("text"), str) and b["text"]:
            parts.append({"type": "text", "text": b["text"]})
    return tool_msgs, parts, images


def compact_parts(parts):
    if all(p.get("type") == "text" for p in parts):
        return "\n\n".join(p["text"] for p in parts)
    return parts


def assistant_message(blocks, gemini, signatures, passback):
    text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
    reasoning = "".join(b.get("thinking") or "" for b in blocks if b.get("type") == "thinking")
    calls = []
    for b in blocks:
        if b.get("type") != "tool_use":
            continue
        call = {"id": str(b.get("id") or ""), "type": "function",
                "function": {"name": b.get("name") or "", "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
        if gemini:
            sig = signatures.get(call["id"]) if signatures is not None else None
            if sig or not calls:  # Gemini wants a signature on the first call of each turn
                call["extra_content"] = {"google": {"thought_signature": sig or GEMINI_SKIP_SIGNATURE}}
        calls.append(call)
    msg = {"role": "assistant", "content": text if text else (None if calls else "")}
    if calls:
        msg["tool_calls"] = calls
    if passback and reasoning:
        msg["reasoning_content"] = reasoning
    return msg


def repair_messages(msgs):
    """Makes the history valid for strict providers: every tool call gets exactly one reply right after
    it, stray tool replies become notes, empty turns go, and back-to-back user turns are merged."""
    fixed, i = [], 0
    while i < len(msgs):
        m = msgs[i]
        i += 1
        if m["role"] == "assistant" and not m.get("tool_calls") and not m.get("content"):
            continue
        if m["role"] == "tool":
            fixed.append({"role": "user", "content": "Tool result: %s" % m.get("content")})
            continue
        fixed.append(m)
        if m["role"] == "assistant" and m.get("tool_calls"):
            replies = collections.OrderedDict()
            while i < len(msgs) and msgs[i]["role"] == "tool":
                replies.setdefault(msgs[i]["tool_call_id"], msgs[i])
                i += 1
            for call in m["tool_calls"]:
                fixed.append(replies.pop(call["id"], None) or {
                    "role": "tool", "tool_call_id": call["id"], "content": "(no result: the tool call was interrupted)"})
            for extra in replies.values():
                fixed.append({"role": "user", "content": "Tool result: %s" % extra.get("content")})
    merged = []
    for m in fixed:
        if merged and m["role"] == "user" and merged[-1]["role"] == "user":
            a, b = merged[-1]["content"], m["content"]
            if isinstance(a, str) and isinstance(b, str):
                merged[-1] = {"role": "user", "content": a + "\n\n" + b}
            else:
                to_parts = lambda c: [{"type": "text", "text": c}] if isinstance(c, str) else list(c)
                merged[-1] = {"role": "user", "content": to_parts(a) + to_parts(b)}
            continue
        merged.append(m)
    return merged


def build_payload(body, model, prov, opts, signatures=None):
    """Turns an Anthropic Messages request into an OpenAI chat-completions request."""
    gemini = bool(prov.get("gemini"))
    msgs = []
    system = "\n\n".join(t for t in block_texts(body.get("system")) if t.strip())
    if system:
        msgs.append({"role": "system", "content": system})
    carry = []  # reminders Claude Code sends as mid-conversation system turns
    for m in body.get("messages") or []:
        role, blocks = m.get("role"), as_blocks(m.get("content"))
        if role == "system":
            text = "\n".join(block_texts(blocks)).strip()
            if text:
                carry.append(text)
        elif role == "assistant":
            msgs.append(assistant_message(blocks, gemini, signatures, opts.get("passback")))
        else:
            tool_msgs, parts, images = user_parts(blocks)
            msgs.extend(tool_msgs)
            if carry:
                parts.insert(0, {"type": "text", "text": "\n\n".join(carry)})
                carry = []
            if images:
                parts.append({"type": "text", "text": "(Images returned by the tool calls above.)"})
                parts.extend(images)
            if parts:
                msgs.append({"role": "user", "content": compact_parts(parts)})
    if carry:
        msgs.append({"role": "user", "content": "\n\n".join(carry)})
    payload = {"model": model, "messages": repair_messages(msgs), "stream": True, "max_tokens": opts["max_tokens"]}
    if opts.get("stream_usage", True):
        payload["stream_options"] = {"include_usage": True}
    tools = convert_tools(body.get("tools"), gemini)
    if tools:
        payload["tools"] = tools
        choice = convert_tool_choice(body.get("tool_choice"))
        if choice is not None:
            payload["tool_choice"] = choice
        if (body.get("tool_choice") or {}).get("disable_parallel_tool_use") and not gemini:
            payload["parallel_tool_calls"] = False
    # Claude Code sends Anthropic's default temperature of 1; each model's own default suits it better.
    for k in ("temperature", "top_p"):
        if isinstance(body.get(k), (int, float)) and body[k] != 1:
            payload[k] = body[k]
    if body.get("stop_sequences"):
        payload["stop"] = list(body["stop_sequences"])[:4]
    payload.update(prov.get("extra_body") or {})
    return payload


def estimate_tokens(body):
    size = sum(len(json.dumps(body.get(k) or "", ensure_ascii=False)) for k in ("system", "messages", "tools"))
    return int(size / 3.6) + 1


def has_images(body):
    for m in body.get("messages") or []:
        for b in as_blocks(m.get("content")):
            if b.get("type") == "image":
                return True
            if b.get("type") == "tool_result" and any(x.get("type") == "image" for x in as_blocks(b.get("content"))):
                return True
    return False


# ---------------------------------------------------------------- OpenAI stream -> Anthropic stream

def parse_arguments(raw):
    raw = (raw or "").strip()
    if not raw:
        return {}
    for attempt in (raw, raw + "}", raw + '"}', raw + "]}", raw[: raw.rfind("}") + 1]):
        try:
            value = json.loads(attempt)
        except ValueError:
            continue
        return value if isinstance(value, dict) else {"value": value}
    # Hand the text back so Claude Code reports the bad input to the model, which then retries.
    return {"_unparsed_arguments": raw[:4000]}


class Translator:
    """Turns OpenAI chat-completion stream chunks into Anthropic Messages stream events.

    Text and reasoning stream through as they arrive. Tool calls are collected and sent when the
    reply ends, because OpenAI streams may interleave several calls while Anthropic's can't."""

    def __init__(self, alias, input_estimate, signatures=None):
        self.alias = alias
        self.input_estimate = input_estimate
        self.signatures = signatures  # Gemini's thought signatures, kept per tool call
        self.id = "msg_" + uuid.uuid4().hex[:24]
        self.blocks = []
        self.cur = None
        self.held_space = ""
        self.tools = collections.OrderedDict()
        self.finish_reason = None
        self.usage = {}
        self.started = False
        self.mode = "start"   # start: may still see <think>; think: inside it; text: plain text
        self.pending = ""
        self.done = None

    def message_start(self):
        return ("message_start", {"type": "message_start", "message": {
            "id": self.id, "type": "message", "role": "assistant", "model": self.alias, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": self.input_estimate, "output_tokens": 1}}})

    def feed(self, chunk):
        out = []
        if isinstance(chunk.get("usage"), dict):
            self.usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                out += self._emit("thinking", reasoning)
            content = delta.get("content")
            if isinstance(content, list):
                content = "".join(p.get("text") or "" for p in content if isinstance(p, dict))
            if isinstance(content, str) and content:
                out += self._content(content)
            for call in delta.get("tool_calls") or []:
                if isinstance(call, dict):
                    self._tool(call)
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]
        return out

    def _content(self, text):
        if self.mode == "text":
            return self._emit("text", text)
        self.pending += text
        if self.mode == "start":
            stripped = self.pending.lstrip()
            if not stripped or (len(stripped) < 7 and "<think>".startswith(stripped)):
                return []  # might be the start of a <think> tag
            if not stripped.startswith("<think>"):
                self.mode, text, self.pending = "text", self.pending, ""
                return self._emit("text", text)
            self.mode, self.pending = "think", stripped[7:]
        out = []
        end = self.pending.find("</think>")
        if end >= 0:
            out += self._emit("thinking", self.pending[:end])
            rest = self.pending[end + 8:].lstrip("\n")
            self.mode, self.pending = "text", ""
            return out + self._emit("text", rest)
        keep = next((k for k in range(min(7, len(self.pending)), 0, -1) if "</think>".startswith(self.pending[-k:])), 0)
        ready = self.pending[: len(self.pending) - keep]
        self.pending = self.pending[len(self.pending) - keep:]
        return self._emit("thinking", ready)

    def _emit(self, kind, text):
        if not text:
            return []
        if kind == "text" and (not self.cur or self.cur["type"] != "text"):
            if not text.strip():
                self.held_space += text  # don't open a text block for bare whitespace
                return []
            text, self.held_space = self.held_space + text, ""
        self.started = True
        out = []
        if not self.cur or self.cur["type"] != kind:
            out += self._close()
            block = {"type": "thinking", "thinking": "", "signature": ""} if kind == "thinking" else {"type": "text", "text": ""}
            self.cur = {"type": kind, "index": len(self.blocks), "block": block}
            self.blocks.append(block)
            out.append(("content_block_start", {"type": "content_block_start", "index": self.cur["index"],
                                                "content_block": {"type": "thinking", "thinking": ""} if kind == "thinking"
                                                else {"type": "text", "text": ""}}))
        if kind == "thinking":
            self.cur["block"]["thinking"] += text
            delta = {"type": "thinking_delta", "thinking": text}
        else:
            self.cur["block"]["text"] += text
            delta = {"type": "text_delta", "text": text}
        out.append(("content_block_delta", {"type": "content_block_delta", "index": self.cur["index"], "delta": delta}))
        return out

    def _close(self):
        if not self.cur:
            return []
        out = []
        if self.cur["type"] == "thinking":
            self.cur["block"]["signature"] = SIGNATURE
            out.append(("content_block_delta", {"type": "content_block_delta", "index": self.cur["index"],
                                                "delta": {"type": "signature_delta", "signature": SIGNATURE}}))
        out.append(("content_block_stop", {"type": "content_block_stop", "index": self.cur["index"]}))
        self.cur = None
        return out

    def _tool(self, call):
        fn = call.get("function") or {}
        index = call.get("index")
        if not isinstance(index, int):
            known = [s["upstream_id"] for s in self.tools.values()]
            new = call.get("id") and call["id"] not in known
            index = len(self.tools) if (new or not self.tools) else next(reversed(self.tools))
        slot = self.tools.get(index)
        if slot is None:
            slot = self.tools[index] = {"id": "toolu_" + uuid.uuid4().hex[:24], "upstream_id": call.get("id"), "name": "", "args": ""}
        if fn.get("name") and not slot["name"]:
            slot["name"] = fn["name"]
        args = fn.get("arguments")
        if isinstance(args, dict):
            slot["args"] = json.dumps(args)
        elif isinstance(args, str):
            slot["args"] += args
        sig = ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature")
        if sig:
            slot["signature"] = sig
        if slot["name"]:
            self.started = True

    def stop_reason(self):
        if any(b["type"] == "tool_use" for b in self.blocks):
            return "tool_use"
        return "max_tokens" if self.finish_reason == "length" else "end_turn"

    def final_usage(self):
        written = sum(len(b.get("text") or b.get("thinking") or json.dumps(b.get("input") or "")) for b in self.blocks)
        return {"input_tokens": int(self.usage.get("prompt_tokens") or self.input_estimate),
                "output_tokens": int(self.usage.get("completion_tokens") or written // 4 + 1)}

    def finish(self):
        """Closes the reply: flushes held text, sends the tool calls, then the stop events."""
        if self.done is not None:
            return self.done
        out = []
        if self.pending:
            out += self._emit("thinking" if self.mode == "think" else "text", self.pending)
            self.pending = ""
        out += self._close()
        for slot in self.tools.values():
            if not slot["name"]:
                continue
            arguments = parse_arguments(slot["args"])
            index = len(self.blocks)
            self.blocks.append({"type": "tool_use", "id": slot["id"], "name": slot["name"], "input": arguments})
            if self.signatures is not None and slot.get("signature"):
                self.signatures[slot["id"]] = slot["signature"]
            out.append(("content_block_start", {"type": "content_block_start", "index": index, "content_block": {
                "type": "tool_use", "id": slot["id"], "name": slot["name"], "input": {}}}))
            out.append(("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {
                "type": "input_json_delta", "partial_json": json.dumps(arguments, ensure_ascii=False)}}))
            out.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
        out.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": self.stop_reason(), "stop_sequence": None},
                                      "usage": self.final_usage()}))
        out.append(("message_stop", {"type": "message_stop"}))
        self.done = out
        return out

    def message(self):
        """The whole reply as one Anthropic message, for requests that didn't ask for streaming."""
        self.finish()
        content = [b for b in self.blocks if not (b["type"] == "text" and not b["text"].strip())]
        return {"id": self.id, "type": "message", "role": "assistant", "model": self.alias,
                "content": content or [{"type": "text", "text": ""}], "stop_reason": self.stop_reason(),
                "stop_sequence": None, "usage": self.final_usage()}


# ---------------------------------------------------------------- reading provider errors

DAILY_RE = re.compile(r"per[ _-]?day|perday|daily|requests? per day|\brpd\b|free-models-per-day", re.I)
TOO_LONG_RE = re.compile(
    r"context.{0,20}(?:length|window|limit)|maximum context|too many (?:input )?tokens|prompt is too long|"
    r"input is too long|reduce the length|exceeds? the (?:model'?s )?(?:maximum|max)|longer than the model|"
    r"context_length_exceeded|request too large|payload too large", re.I)
MAX_TOKENS_RE = re.compile(r"max_tokens|max_completion_tokens|max_new_tokens|maximum (?:output|completion) tokens", re.I)
KEY_RE = re.compile(r"api[ _-]?key|unauthori[sz]ed|authenticat|invalid (?:token|key|credential)|credential|expired", re.I)
GONE_RE = re.compile(
    r"not found|does not exist|no endpoints found|unknown model|invalid model|no such model|deprecated|"
    r"decommissioned|retired|model .{0,40}not (?:available|supported)", re.I)
POLICY_RE = re.compile(r"data policy|privacy|may train", re.I)
NO_TOOLS_RE = re.compile(
    r"(?:does not|doesn'?t|not) support (?:tools|tool[ _]?(?:use|calling|choice)|function[ _]?calling)|"
    r"tools? (?:are|is) not supported", re.I)


class Failure:
    def __init__(self, kind, scope=None, wait=None, detail="", status=0, daily=False, max_tokens=None, limit=None):
        self.kind = kind          # rate, down, auth, policy, gone, no_tools, too_long, max_tokens, ...
        self.scope = scope        # "provider", "model" or None (nothing to rest)
        self.wait = wait          # seconds the provider asked us to wait, if it said
        self.detail = detail
        self.status = status
        self.daily = daily
        self.max_tokens = max_tokens
        self.limit = limit

    def label(self):
        names = {"rate": "daily limit reached" if self.daily else "rate limited", "down": "not answering",
                 "auth": "key rejected", "policy": "free models blocked by your OpenRouter privacy settings",
                 "gone": "model unavailable", "no_tools": "can't use tools", "bad": "rejects requests"}
        return "%s: %s" % (names.get(self.kind, self.kind), self.detail) if self.detail else names.get(self.kind, self.kind)


def parse_wait(headers, text, now):
    """Seconds until a limit resets, from Retry-After, x-ratelimit-reset or the error text."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    value = h.get("retry-after")
    if value:
        try:
            return max(1.0, float(value))
        except ValueError:
            try:
                return max(1.0, email.utils.parsedate_to_datetime(value).timestamp() - now)
            except (TypeError, ValueError, IndexError, OverflowError):
                pass
    for name in ("x-ratelimit-reset", "x-ratelimit-reset-requests", "ratelimit-reset"):
        value = (h.get(name) or "").strip()
        if not value:
            continue
        try:
            number = float(value)
        except ValueError:
            m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:(\d+)ms)?", value)
            if m and any(m.groups()):
                hrs, mins, secs, ms = (float(g or 0) for g in m.groups())
                return max(1.0, hrs * 3600 + mins * 60 + secs + ms / 1000)
            continue
        if number > 1e12:
            return max(1.0, number / 1000 - now)  # epoch milliseconds, as OpenRouter sends
        if number > 1e9:
            return max(1.0, number - now)         # epoch seconds
        return max(1.0, number)
    m = re.search(r'retryDelay"?\s*[:=]\s*"?(\d+(?:\.\d+)?)s', text or "")
    if m:
        return max(1.0, float(m.group(1)))
    m = re.search(r"(?:try again|retry) (?:in|after) (\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?|h|hours?)\b",
                  text or "", re.I)
    if m:
        unit = m.group(2).lower()
        scale = 0.001 if unit.startswith("ms") or unit.startswith("milli") else 60 if unit.startswith("m") else 3600 if unit.startswith("h") else 1
        return max(1.0, float(m.group(1)) * scale)
    return None


def error_text(body):
    """A short human-readable message from an error body."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return re.sub(r"\s+", " ", str(body or "")).strip()[:300]
    if isinstance(data, list) and data:
        data = data[0]
    err = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg") or err.get("detail") or json.dumps(err)
        raw = (err.get("metadata") or {}).get("raw") if isinstance(err.get("metadata"), dict) else None
        if raw and isinstance(raw, str):
            msg = "%s (%s)" % (msg, raw[:200])
        return re.sub(r"\s+", " ", str(msg)).strip()[:300]
    return re.sub(r"\s+", " ", str(err)).strip()[:300]


def parse_context_fit(text):
    """For "context is N, you asked for M in messages" errors: a smaller max_tokens that fits, if any."""
    limit = re.search(r"maximum context length is (\d+)", text or "")
    used = re.search(r"(\d+) (?:in the messages|input tokens|prompt tokens)|request has (\d+) input tokens", text or "")
    if not (limit and used):
        return None
    room = int(limit.group(1)) - int(used.group(1) or used.group(2)) - 64
    return room if room >= 1024 else None


def judge(status, body, headers, provider, had_tools=False, had_images=False, now=None):
    """Decides what a failed call means: who should rest, for how long, and what to try next."""
    now = now or time.time()
    text = body or ""
    detail = error_text(text) or ("HTTP %d" % status if status else "no connection")
    low = text.lower()
    wait = parse_wait(headers, text, now)
    if status == 401 or (status == 403 and KEY_RE.search(text)):
        return Failure("auth", "provider", 6 * 3600, detail, status)
    if status == 429 or "rate limit" in low or "rate-limit" in low or "too many requests" in low:
        account_wide = PROVIDERS.get(provider, {}).get("account_wide_limits") or "free-models-per" in low
        return Failure("rate", "provider" if account_wide else "model", wait, detail, status, daily=bool(DAILY_RE.search(text)))
    if status == 402:
        return Failure("rate", "model", wait or 3600, detail, status, daily=True)
    if status == 413 or TOO_LONG_RE.search(text):
        fit = parse_context_fit(text)
        if fit:
            return Failure("max_tokens", detail=detail, status=status, max_tokens=fit)
        limit = re.search(r"(?:maximum context length is|context (?:length|window) (?:is|of)) (\d+)", text)
        return Failure("too_long", detail=detail, status=status, limit=int(limit.group(1)) if limit else None)
    if status in (400, 422):
        if "stream_options" in low:
            return Failure("stream_options", detail=detail, status=status)
        if "reasoning_content" in low:
            return Failure("reasoning", detail=detail, status=status)
        if MAX_TOKENS_RE.search(text):
            cap = re.search(r"(?:<=|less than or equal to|at most|maximum(?: value)? (?:is|of)) ?(\d{3,6})", text)
            return Failure("max_tokens", detail=detail, status=status, max_tokens=int(cap.group(1)) if cap else None)
    if status == 404 and provider == "openrouter" and POLICY_RE.search(text):
        return Failure("policy", "provider", 3600, detail, status)
    if status in (404, 410) or (status in (400, 403, 422) and GONE_RE.search(text)):
        return Failure("gone", "model", 6 * 3600, detail, status)
    if status in (400, 422) and had_tools and NO_TOOLS_RE.search(text):
        return Failure("no_tools", "model", 6 * 3600, detail, status)
    if status in (400, 422) and had_images and re.search(r"image|vision|multimodal", low):
        return Failure("no_images", detail=detail, status=status)
    if status in (400, 422):
        return Failure("bad", detail=detail, status=status)
    if status == 403:
        return Failure("gone", "model", 3600, detail, status)  # e.g. a model the free tier can't use
    return Failure("down", "model", wait, detail, status)      # 5xx, 529, timeouts, dropped connections


# ---------------------------------------------------------------- remembering who is resting

def utc_day(now=None):
    return time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))


class Health:
    """Which providers and models are resting, request counts, and what each session last used."""

    def __init__(self, path=STATE_PATH):
        self.lock = threading.RLock()
        self.path = path
        self.rest = {}                    # "p:nvidia" or "m:nvidia:model" -> [until, why]
        self.strikes = collections.Counter()
        self.bad = collections.Counter()
        self.passback = {}                # model key -> send reasoning back to it
        self.recent = collections.defaultdict(collections.deque)
        self.inflight = collections.Counter()
        self.day = utc_day()
        self.counts = {}                  # model key -> [ok, failed] today
        self.errors = {}                  # model key -> last error
        self.sessions = collections.OrderedDict()
        self.last = None
        self.saved_at = 0.0
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        now = time.time()
        self.rest = {k: v for k, v in (data.get("rest") or {}).items() if isinstance(v, list) and v and v[0] > now}
        self.passback = data.get("passback") or {}
        self.errors = data.get("errors") or {}
        if data.get("day") == self.day:
            self.counts = data.get("counts") or {}

    def save(self, force=False):
        with self.lock:
            now = time.time()
            if not force and now - self.saved_at < 5:
                return
            self.saved_at = now
            data = {"day": self.day, "rest": self.rest, "counts": self.counts, "errors": self.errors, "passback": self.passback}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _count(self, key, column):
        if utc_day() != self.day:
            self.day, self.counts = utc_day(), {}
        self.counts.setdefault(key, [0, 0])[column] += 1

    def check(self, provider, model, prov, now):
        """Returns (usable, seconds until usable, reason)."""
        with self.lock:
            for key in ("p:" + provider, "m:%s:%s" % (provider, model)):
                until, why = (self.rest.get(key) or [0, ""])[:2]
                if until > now:
                    return False, until - now, why
            if prov.get("rpm"):
                stamps = self.recent[provider]
                while stamps and stamps[0] <= now - 60:
                    stamps.popleft()
                if len(stamps) >= prov["rpm"]:
                    return False, stamps[0] + 60 - now, "used its %d requests for this minute" % prov["rpm"]
            if prov.get("max_concurrent") and self.inflight[provider] >= prov["max_concurrent"]:
                return False, 3.0, "busy with another request"
            return True, 0.0, ""

    def begin(self, provider, now):
        with self.lock:
            self.recent[provider].append(now)
            self.inflight[provider] += 1

    def end(self, provider):
        with self.lock:
            self.inflight[provider] = max(0, self.inflight[provider] - 1)

    def succeeded(self, provider, model):
        key = "m:%s:%s" % (provider, model)
        with self.lock:
            self.strikes.pop(key, None)
            self.strikes.pop("p:" + provider, None)
            self.bad.pop(key, None)
            self._count(key, 0)
        self.save()

    def failed(self, provider, model, failure, now):
        key = "m:%s:%s" % (provider, model)
        with self.lock:
            self._count(key, 1)
            self.errors[key] = failure.label()
            if failure.kind == "bad":
                self.bad[key] += 1
                if self.bad[key] >= 3:  # one odd request is fine; a model that rejects everything rests
                    self.rest[key] = [now + 600, failure.label()]
                    self.bad[key] = 0
            elif failure.scope:
                target = "p:" + provider if failure.scope == "provider" else key
                strikes = self.strikes[target]
                self.strikes[target] = strikes + 1
                if failure.kind == "rate":
                    wait = failure.wait or min(20 * 2 ** strikes, 900)
                    if failure.daily and not failure.wait:
                        wait = max(wait, 3600)  # check again hourly; providers don't all say when a day resets
                elif failure.kind == "down":
                    wait = failure.wait or min(15 * 2 ** strikes, 300)
                else:
                    wait = failure.wait or 600
                self.rest[target] = [now + max(1.0, min(wait, 24 * 3600)), failure.label()]
        self.save()

    def remember_session(self, session, info):
        with self.lock:
            self.last = info
            if session:
                self.sessions[session] = info
                self.sessions.move_to_end(session)
                while len(self.sessions) > 200:
                    self.sessions.popitem(last=False)


# ---------------------------------------------------------------- talking to providers

def open_upstream(prov, payload, timeout):
    """Starts a streaming chat-completions call. Returns (response, None) or (None, (status, body, headers))."""
    url = prov["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": USER_AGENT,
               "Authorization": "Bearer " + prov["key"]}
    headers.update(prov.get("headers") or {})
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        return UPSTREAM.open(req, timeout=timeout), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read(65536).decode("utf-8", "replace")
        except Exception:
            body = ""
        return None, (e.code, body, dict(e.headers or {}))
    except Exception as e:  # DNS, refused, TLS, timeout
        return None, (0, "%s: %s" % (type(e).__name__, e), {})


def pump(resp, lines):
    """Reads the provider's stream on its own thread so the main loop can send keep-alive pings."""
    try:
        for raw in resp:
            lines.put(raw)
    except Exception as e:
        lines.put(e)
    finally:
        lines.put(None)


class Outcome:
    def __init__(self, ok=False, delivered=False, failure=None):
        self.ok = ok                # the provider gave a full answer
        self.delivered = delivered  # Claude Code got an answer (maybe cut short), so stop trying others
        self.failure = failure


class ClientGone(Exception):
    pass


class Router:
    def __init__(self, cfg):
        self.cfg = cfg
        self.config_mtime = self._mtime()
        self.health = Health()
        self.memory = TierMemory()
        self.catalog = {}                 # provider -> {model id: context length or None}
        self.signatures = collections.OrderedDict()
        self.sig_lock = threading.Lock()

    def _mtime(self):
        try:
            return os.stat(CONFIG_PATH).st_mtime
        except OSError:
            return 0

    def maybe_reload(self):
        """Picks up keys added with `router.py keys` without a restart."""
        mtime = self._mtime()
        if mtime and mtime != self.config_mtime:
            self.config_mtime = mtime
            try:
                fresh = load_config()
            except SystemExit as e:
                log("config: %s" % e)
                return
            fresh["port"] = self.cfg["port"]  # the only setting that needs a restart
            fresh["token"] = fresh.get("token") or self.cfg.get("token")
            self.cfg = fresh
            log("config: reloaded (providers with keys: %s)" % (", ".join(self.configured()) or "none"))

    def configured(self):
        return [p for p in PROVIDER_ORDER if (self.cfg.get("keys") or {}).get(p)]

    def refresh_catalog(self):
        for name in self.configured():
            prov = provider_settings(self.cfg, name)
            if not prov.get("catalog"):
                continue
            try:
                req = urllib.request.Request(prov["base_url"].rstrip("/") + "/models", headers={"User-Agent": USER_AGENT})
                with UPSTREAM.open(req, timeout=30) as r:
                    data = json.load(r)
                found = {m["id"]: m.get("context_length") for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")}
            except Exception as e:
                log("catalog: couldn't list %s models (%s); using the built-in list" % (name, e))
                continue
            if found:
                self.catalog[name] = found
                listed = {c.split(":", 1)[1] for tier in TIERS for c in self.tier_entries(tier) if c.startswith(name + ":")}
                missing = sorted(m for m in listed if m not in found)
                if missing:
                    log("catalog: %s no longer offers %s; skipping them" % (name, ", ".join(missing)))

    def catalog_loop(self):
        while True:
            self.refresh_catalog()
            time.sleep(6 * 3600)

    def tier_entries(self, tier):
        custom = (self.cfg.get("tiers") or {}).get(tier)
        return list(custom) if isinstance(custom, list) else list(TIERS[tier])

    def candidates(self, tier, tokens):
        """Every usable (provider, model, settings), best first: this tier's list, then the others."""
        seen, out = set(), []
        for t in TIER_FALLBACK[tier]:
            for entry in self.tier_entries(t):
                name, _, model = str(entry).partition(":")
                if not model or (name, model) in seen or name not in PROVIDERS:
                    continue
                seen.add((name, model))
                prov = provider_settings(self.cfg, name)
                if not prov["key"]:
                    continue
                listed = self.catalog.get(name)
                if listed is not None and model not in listed:
                    continue
                window = (listed or {}).get(model)
                if isinstance(window, int) and window and tokens + 1024 > window:
                    continue
                out.append((name, model, prov))
        return out

    def remember_signature(self, tool_id, sig):
        with self.sig_lock:
            self.signatures[tool_id] = sig
            while len(self.signatures) > 5000:
                self.signatures.popitem(last=False)

    # -- one request from Claude Code

    def handle(self, h, body):
        self.maybe_reload()
        started = time.time()
        hdr = {k.lower(): v for k, v in h.headers.items()}
        tier, why = pick_tier(body, hdr, self.memory)
        tokens = estimate_tokens(body)
        session = hdr.get("x-claude-code-session-id", "")
        kind = hdr.get("x-claude-code-request-class") or "main"
        if self.cfg.get("debug"):
            log("debug: model=%s hints=%s fields=%s" % (body.get("model"), json.dumps(
                {k: v for k, v in hdr.items() if k.startswith("x-claude-code-")}), ",".join(sorted(body))))
        cands = self.candidates(tier, tokens)
        if not cands:
            if not self.configured():
                return h.send_error_json(503, "api_error", "free-claude has no API keys yet. Run: claude-free-router keys")
            if not self.candidates(tier, 0):
                return h.send_error_json(503, "api_error", "free-claude: none of the listed models are offered by the "
                                         "providers you have keys for. Run: claude-free-router status")
            return h.send_error_json(400, "invalid_request_error",
                                     "prompt is too long: %d tokens > %d maximum" % (tokens, int(tokens * 0.9)))
        tried, too_long_limit = [], None
        for name, model, prov in cands:
            if time.time() - started > self.cfg["request_budget"]:
                break
            usable, _, _ = self.health.check(name, model, prov, time.time())
            if not usable:
                continue
            outcome = self.attempt(h, body, name, model, prov, tokens)
            if outcome.ok or outcome.delivered:
                swaps = len(tried)
                info = {"tier": tier, "why": why, "provider": name, "model": model, "swaps": swaps,
                        "ok": outcome.ok, "when": time.time(), "kind": kind}
                self.health.remember_session(session, info)
                log("%-9s %-5s %s -> %s:%s %s %.1fs%s" % (
                    kind, tier, why, name, model, "ok" if outcome.ok else "cut short", time.time() - started,
                    (" after " + ", ".join(tried)) if tried else ""))
                return None
            f = outcome.failure
            tried.append("%s:%s (%s)" % (name, model, f.label()[:80]))
            if f.kind == "too_long":
                too_long_limit = f.limit or too_long_limit or int(tokens * 0.9)
        self.reply_failure(h, tier, why, tokens, tried, too_long_limit, kind, session, started)
        return None

    def attempt(self, h, body, name, model, prov, tokens):
        key = "m:%s:%s" % (name, model)
        opts = {"max_tokens": max(256, min(int(body.get("max_tokens") or 4096), int(self.cfg["max_output_tokens"]),
                                           int(prov.get("max_output") or 10 ** 9))),
                "stream_usage": not prov.get("no_stream_usage"),
                "passback": bool(self.health.passback.get(key))}
        had_tools, had_images = bool(body.get("tools")), has_images(body)
        outcome = None
        for _ in range(3):  # the same model may get a reshaped retry before we move on
            payload = build_payload(body, model, prov, opts, self.signatures if prov.get("gemini") else None)
            self.health.begin(name, time.time())
            try:
                outcome = self.exchange(h, body, payload, name, model, prov, tokens, had_tools, had_images)
            finally:
                self.health.end(name)
            if outcome.ok:
                self.health.succeeded(name, model)
                return outcome
            f = outcome.failure
            if outcome.delivered:
                break
            if f.kind == "max_tokens" and opts["max_tokens"] > 1024:
                smaller = f.max_tokens if f.max_tokens and f.max_tokens < opts["max_tokens"] else opts["max_tokens"] // 2
                opts["max_tokens"] = max(1024, smaller)
                continue
            if f.kind == "stream_options" and opts["stream_usage"]:
                opts["stream_usage"] = False
                continue
            if f.kind == "reasoning":
                opts["passback"] = not opts["passback"]
                self.health.passback[key] = opts["passback"]
                continue
            break
        if outcome.failure and outcome.failure.kind not in ("too_long", "no_images"):
            self.health.failed(name, model, outcome.failure, time.time())
        return outcome

    def exchange(self, h, body, payload, name, model, prov, tokens, had_tools, had_images):
        timeout = float(self.cfg["first_token_timeout"])
        resp, err = open_upstream(prov, payload, timeout)
        if err:
            status, text, headers = err
            return Outcome(failure=judge(status, text, headers, name, had_tools, had_images))
        lines = queue.Queue()
        threading.Thread(target=pump, args=(resp, lines), daemon=True).start()
        sigs = {} if prov.get("gemini") else None
        tr = Translator(body.get("model") or "free-auto", tokens, sigs)
        streaming = bool(body.get("stream"))
        committed = False
        deadline = time.time() + timeout
        last_byte = last_write = time.time()
        try:
            while True:
                now = time.time()
                if not tr.started and now > deadline:
                    return Outcome(failure=Failure("down", "model", None, "no answer within %ds" % timeout, 0))
                if tr.started and now - last_byte > self.cfg["idle_timeout"]:
                    return self.cut_short(h, committed, Failure("down", "model", None, "the answer stalled", 0))
                try:
                    item = lines.get(timeout=2)
                except queue.Empty:
                    if committed and now - last_write >= 10:
                        h.write_event("ping", {"type": "ping"})
                        last_write = now
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    f = Failure("down", "model", None, "connection lost: %s" % item, 0)
                    return self.cut_short(h, committed, f) if tr.started else Outcome(failure=f)
                last_byte = time.time()
                line = item.decode("utf-8", "replace").strip()
                if not line or line.startswith(":") or line.startswith("event:"):
                    continue
                data = line[5:].strip() if line.startswith("data:") else line
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    err = chunk["error"]
                    code = err.get("code") if isinstance(err, dict) else None
                    status = code if isinstance(code, int) and 100 <= code < 600 else 502
                    f = judge(status, json.dumps(chunk), {}, name, had_tools, had_images)
                    return self.cut_short(h, committed, f) if (tr.started and streaming) else Outcome(failure=f)
                events = tr.feed(chunk)
                if streaming and tr.started and not committed:
                    h.start_stream(name, model)
                    h.write_event(*tr.message_start())
                    committed = True
                if committed:
                    for ev in events:
                        h.write_event(*ev)
                    if events:
                        last_write = time.time()
            if not tr.started:
                return Outcome(failure=Failure("down", "model", None, "the model sent an empty reply", 200))
            if streaming:
                for ev in tr.finish():
                    h.write_event(*ev)
                h.end_stream()
            else:
                h.send_json(200, tr.message(), {"x-free-claude-model": "%s:%s" % (name, model)})
            if sigs:
                for tool_id, sig in sigs.items():
                    self.remember_signature(tool_id, sig)
            return Outcome(ok=True, delivered=True)
        except ClientGone:
            return Outcome(ok=True, delivered=True)  # Claude Code hung up (the person pressed Esc)
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def cut_short(self, h, committed, failure):
        """The model failed after part of its answer reached Claude Code: end the stream with an error
        Claude Code understands. The model rests, so Claude Code's retry goes to another one."""
        if committed:
            try:
                h.write_event("error", {"type": "error", "error": {"type": "overloaded_error",
                                                                   "message": "free-claude: the model stopped mid-answer (%s)" % failure.detail}})
                h.end_stream()
            except ClientGone:
                pass
            return Outcome(delivered=True, failure=failure)
        return Outcome(failure=failure)

    def reply_failure(self, h, tier, why, tokens, tried, too_long_limit, kind, session, started):
        now = time.time()
        waits, reasons = [], collections.OrderedDict()
        for name, model, prov in self.candidates(tier, tokens):
            usable, wait, reason = self.health.check(name, model, prov, now)
            if not usable:
                waits.append(wait)
                reasons.setdefault(prov.get("label") or name, "%s (free again in %s)" % (reason, human_time(wait)))
        log("%-9s %-5s %s -> FAILED after %.1fs: %s" % (kind, tier, why, now - started, "; ".join(tried) or "everything resting"))
        self.health.remember_session(session, {"tier": tier, "why": why, "provider": "", "model": "", "swaps": len(tried),
                                               "ok": False, "when": now, "kind": kind})
        if too_long_limit and (not waits or min(waits) > 30):
            # Claude Code recognizes this wording and compacts the conversation, which beats waiting.
            return h.send_error_json(400, "invalid_request_error", "prompt is too long: %d tokens > %d maximum" % (
                max(tokens, too_long_limit + 1), too_long_limit))
        if waits:
            secs = max(1, int(math.ceil(min(waits))))
            detail = "; ".join("%s: %s" % kv for kv in list(reasons.items())[:4])
            return h.send_error_json(429, "rate_limit_error", "free-claude: every free model is busy or out of quota. "
                                     "Next one is free in about %s. %s" % (human_time(secs), detail), {"retry-after": str(secs)})
        last = tried[-1] if tried else "nothing to try"
        return h.send_error_json(529, "overloaded_error", "free-claude: no free model answered (%s)." % last, {"retry-after": "5"})

    def status(self, session=None):
        now = time.time()
        with self.health.lock:
            rest = {k: [v[0] - now, v[1]] for k, v in self.health.rest.items() if v[0] > now}
            counts = dict(self.health.counts)
            errors = dict(self.health.errors)
            sess = dict(self.health.sessions.get(session) or {}) if session else None
            last = dict(self.health.last or {}) if self.health.last else None
        providers = {}
        for name in PROVIDER_ORDER:
            prov = provider_settings(self.cfg, name)
            usable, wait, reason = self.health.check(name, "", prov, now)
            ok = sum(v[0] for k, v in counts.items() if k.startswith("m:%s:" % name))
            bad = sum(v[1] for k, v in counts.items() if k.startswith("m:%s:" % name))
            providers[name] = {"label": prov["label"], "configured": bool(prov["key"]), "resting": 0 if usable else round(wait),
                               "why": reason, "ok_today": ok, "failed_today": bad}
        tiers = {}
        for tier in TIERS:
            own = {tuple(str(e).split(":", 1)) for e in self.tier_entries(tier)}
            tiers[tier] = []
            for name, model, prov in self.candidates(tier, 0):
                if (name, model) not in own:
                    continue  # the other tiers' models, which this tier only borrows when it's all resting
                usable, wait, reason = self.health.check(name, model, prov, now)
                tiers[tier].append({"provider": name, "model": model, "ready": usable, "resting": round(wait),
                                    "why": reason, "last_error": errors.get("m:%s:%s" % (name, model), "")})
        return {"name": "free-claude", "version": VERSION, "port": self.cfg["port"], "providers": providers,
                "tiers": tiers, "session": sess, "last": last}


# ---------------------------------------------------------------- the HTTP server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "free-claude/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, obj, headers=None):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            raise ClientGone()

    def send_error_json(self, status, etype, message, headers=None):
        self.send_json(status, {"type": "error", "error": {"type": etype, "message": message}}, headers)

    def start_stream(self, provider, model):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("x-free-claude-model", "%s:%s" % (provider, model))
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            raise ClientGone()

    def write_event(self, name, data):
        payload = ("event: %s\ndata: %s\n\n" % (name, json.dumps(data, ensure_ascii=False))).encode("utf-8")
        try:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            raise ClientGone()

    def end_stream(self):
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            raise ClientGone()

    def read_body(self):
        length = self.headers.get("Content-Length")
        if length:
            return self.rfile.read(int(length))
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            data = b""
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if not size:
                    self.rfile.readline()
                    return data
                data += self.rfile.read(size)
                self.rfile.readline()
        return b""

    def authorized(self):
        self.server.router.maybe_reload()
        token = self.server.router.cfg.get("token") or ""
        if not token:
            return True
        bearer = (self.headers.get("Authorization") or "").encode("utf-8", "replace")
        key = (self.headers.get("x-api-key") or "").encode("utf-8", "replace")
        return secrets.compare_digest(bearer, ("Bearer " + token).encode()) or secrets.compare_digest(key, token.encode())

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path in ("/", "/health"):
                return self.send_json(200, {"name": "free-claude", "version": VERSION, "ok": True})
            if url.path == "/status":  # no secrets in here; the statusline reads it
                session = (parse_qs(url.query).get("session") or [None])[0]
                return self.send_json(200, self.server.router.status(session))
            if url.path == "/v1/models":
                if not self.authorized():
                    return self.send_error_json(401, "authentication_error", "free-claude: wrong token")
                return self.send_json(200, {"data": [{"id": a, "display_name": n, "description": d, "type": "model"}
                                                     for a, n, d in {v for v in PICKER.values()}], "has_more": False})
            return self.send_error_json(404, "not_found_error", "free-claude: unknown path %s" % url.path)
        except ClientGone:
            pass

    def do_POST(self):
        url = urlsplit(self.path)
        try:
            raw = self.read_body()
            if not self.authorized():
                return self.send_error_json(401, "authentication_error", "free-claude: wrong token. Start Claude Code "
                                            "with the claude-free command; if you do, run: claude-free-router restart")
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return self.send_error_json(400, "invalid_request_error", "free-claude: the request isn't valid JSON")
            if url.path == "/v1/messages":
                return self.server.router.handle(self, body)
            if url.path == "/v1/messages/count_tokens":
                return self.send_json(200, {"input_tokens": estimate_tokens(body)})
            return self.send_error_json(404, "not_found_error", "free-claude: unknown path %s" % url.path)
        except ClientGone:
            pass


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------- commands

def router_alive(port, timeout=1.5):
    try:
        with LOCAL.open("http://127.0.0.1:%d/health" % port, timeout=timeout) as r:
            return json.load(r).get("name") == "free-claude"
    except Exception:
        return False


def fetch_status(port, session=None, timeout=3.0):
    url = "http://127.0.0.1:%d/status" % port + ("?session=" + urllib.request.quote(session) if session else "")
    with LOCAL.open(url, timeout=timeout) as r:
        return json.load(r)


def systemd_ok():
    if not shutil.which("systemctl") or not os.path.exists(UNIT_PATH):
        return False
    return subprocess.run(["systemctl", "--user", "show-environment"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def wait_alive(port, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if router_alive(port, 1.0):
            return True
        time.sleep(0.3)
    return False


def start_router(cfg):
    if router_alive(cfg["port"]):
        return True
    if systemd_ok():
        subprocess.run(["systemctl", "--user", "start", SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait_alive(cfg["port"], 12):
            return True
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "server-output.log"), "ab") as out:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve"], stdin=subprocess.DEVNULL, stdout=out,
                         stderr=out, start_new_session=True, close_fds=True)
    return wait_alive(cfg["port"], 15)


def stop_router(cfg):
    if systemd_ok():
        subprocess.run(["systemctl", "--user", "stop", SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    end = time.time() + 5
    while time.time() < end and router_alive(cfg["port"], 0.5):
        time.sleep(0.2)


def ensure_token(cfg):
    if not cfg.get("token"):
        cfg["token"] = "fc-" + secrets.token_urlsafe(24)
        save_config(cfg)
    return cfg


def cmd_serve(args):
    cfg = ensure_token(load_config())
    router = Router(cfg)
    try:
        server = Server(("127.0.0.1", int(cfg["port"])), Handler)
    except OSError as e:
        if router_alive(cfg["port"]):
            print("free-claude: already running on port %d" % cfg["port"])
            return 0
        print("free-claude: can't listen on 127.0.0.1:%d (%s). Set another \"port\" in %s" % (cfg["port"], e, CONFIG_PATH))
        return 1
    server.router = router
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))
    threading.Thread(target=router.catalog_loop, daemon=True).start()

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log("started v%s on 127.0.0.1:%d with keys for: %s" % (VERSION, cfg["port"], ", ".join(router.configured()) or "nobody yet"))
    print("free-claude router v%s listening on http://127.0.0.1:%d" % (VERSION, cfg["port"]), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        router.health.save(force=True)
        server.server_close()
        try:
            os.remove(PID_PATH)
        except OSError:
            pass
        log("stopped")
    return 0


def cmd_ensure(args):
    cfg = ensure_token(load_config())
    if start_router(cfg):
        return 0
    print("free-claude: the router didn't start. See %s and %s" % (LOG_PATH, os.path.join(STATE_DIR, "server-output.log")),
          file=sys.stderr)
    return 1


def env_pairs(cfg):
    no_proxy = ",".join(x for x in [os.environ.get("NO_PROXY") or os.environ.get("no_proxy"), "127.0.0.1", "localhost"] if x)
    statusline = {"statusLine": {"type": "command", "padding": 0,
                                 "command": "%s %s statusline" % (shlex.quote(sys.executable), shlex.quote(os.path.abspath(__file__)))}}
    pairs = [("ANTHROPIC_BASE_URL", "http://127.0.0.1:%d" % cfg["port"]), ("ANTHROPIC_AUTH_TOKEN", cfg["token"]),
             ("ANTHROPIC_MODEL", "sonnet")]
    for family, (model, name, about) in PICKER.items():
        pairs += [("ANTHROPIC_DEFAULT_%s_MODEL" % family, model), ("ANTHROPIC_DEFAULT_%s_MODEL_NAME" % family, name),
                  ("ANTHROPIC_DEFAULT_%s_MODEL_DESCRIPTION" % family, about)]
    pairs += [("CLAUDE_CODE_GATEWAY_HINT_HEADERS", "1"),          # tells the router what each request is for
              ("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "1"),    # Anthropic-only extras other models reject
              ("CLAUDE_CODE_ATTRIBUTION_HEADER", "0"),
              ("CLAUDE_CODE_MAX_CONTEXT_TOKENS", str(cfg["context_window"])),
              ("CLAUDE_CODE_MAX_OUTPUT_TOKENS", str(cfg["max_output_tokens"])),
              ("DISABLE_TELEMETRY", "1"), ("DISABLE_ERROR_REPORTING", "1"),
              ("NO_PROXY", no_proxy), ("FREE_CLAUDE_SETTINGS", json.dumps(statusline)),
              ("FREE_CLAUDE_PERMISSION_MODE", os.environ.get("FREE_CLAUDE_PERMISSION_MODE") or cfg["permission_mode"])]
    return pairs


def cmd_env(args):
    cfg = ensure_token(load_config())
    print("unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_USE_FOUNDRY")
    for k, v in env_pairs(cfg):
        print("export %s=%s" % (k, shlex.quote(v)))
    return 0


def tick(ok):
    return "\033[32m✔\033[0m" if ok else "\033[31m✘\033[0m"


def cmd_status(args):
    cfg = load_config()
    try:
        st = fetch_status(cfg["port"])
    except Exception:
        print("free-claude router is not running (port %d). Start it with: claude-free-router start" % cfg["port"])
        print("Providers with keys: %s" % (", ".join(p for p in PROVIDER_ORDER if cfg["keys"].get(p)) or "none"))
        return 1
    print("\033[1mfree-claude router %s\033[0m on http://127.0.0.1:%d\n" % (st["version"], st["port"]))
    print("\033[1mProviders\033[0m (today: answered / failed)")
    for name in PROVIDER_ORDER:
        p = st["providers"][name]
        if not p["configured"]:
            print("  \033[2m–  %-17s no key (add one with: claude-free-router keys)\033[0m" % p["label"])
        elif p["resting"]:
            print("  \033[33m⏸\033[0m  %-17s %4d / %-4d resting %s: %s" % (p["label"], p["ok_today"], p["failed_today"],
                                                                      human_time(p["resting"]), p["why"]))
        else:
            print("  %s  %-17s %4d / %-4d ready" % (tick(True), p["label"], p["ok_today"], p["failed_today"]))
    for tier in ("fast", "main", "smart"):
        print("\n\033[1m%s tier\033[0m (first ready model answers)" % tier.capitalize())
        rows = st["tiers"][tier]
        if not rows:
            print("  no models: add a key with claude-free-router keys")
        for r in rows:
            state = "ready" if r["ready"] else "resting %s: %s" % (human_time(r["resting"]), r["why"])
            print("  %s  %-48s %s" % (tick(r["ready"]), "%s (%s)" % (r["model"], r["provider"]), state[:90]))
    if st.get("last"):
        last = st["last"]
        print("\n\033[1mLast request\033[0m: %s tier (%s) -> %s" % (last["tier"], last["why"],
              "%s (%s)" % (last["model"], last["provider"]) if last.get("model") else "nothing was free"))
    print("\nLog: %s" % LOG_PATH)
    return 0


def cmd_statusline(args):
    try:
        info = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        info = {}
    cfg = load_config()
    try:
        st = fetch_status(cfg["port"], info.get("session_id"), timeout=0.6)
    except Exception:
        print("\033[31mfree-claude router offline\033[0m · run claude-free-router start")
        return 0
    s = st.get("session") or {}
    if not s:
        print("\033[2mfree · auto-routing ready\033[0m")
        return 0
    if not s.get("model"):
        print("\033[33mfree · %s · every model busy, retrying\033[0m" % s.get("tier"))
        return 0
    label = PROVIDERS.get(s["provider"], {}).get("label", s["provider"])
    swaps = " · \033[33mswapped %d×\033[0m" % s["swaps"] if s.get("swaps") else ""
    print("\033[2mfree ·\033[0m %s \033[2m→\033[0m %s \033[2m(%s)\033[0m%s" % (s["tier"], s["model"].split("/")[-1], label, swaps))
    return 0


def test_key(name, key, cfg=None):
    """Sends one tiny request. Returns (verdict, message): verdict is ok, warn or bad."""
    prov = provider_settings(cfg or load_config(), name)
    prov["key"] = key
    payload = {"model": prov["test_model"], "messages": [{"role": "user", "content": "Reply with the word OK."}],
               "max_tokens": 16, "stream": True}
    resp, err = open_upstream(prov, payload, 60)
    if resp:
        resp.close()
        return "ok", "key works"
    status, body, headers = err
    f = judge(status, body, headers, name)
    if f.kind == "auth":
        return "bad", "the key was rejected (%s)" % f.detail
    if f.kind == "policy":
        return "warn", ("the key works, but OpenRouter blocks free models with your privacy settings. Open "
                        "https://openrouter.ai/settings/privacy and turn on the options that allow free endpoints, "
                        "including ones that may train on inputs.")
    if f.kind == "rate":
        return "warn", "the key works but is rate limited right now (%s)" % f.detail
    if status == 0:
        return "warn", "couldn't reach %s to check the key (%s)" % (prov["label"], f.detail)
    return "warn", "the test model answered with an error, so the key couldn't be confirmed (%s)" % f.detail


def cmd_test_key(args):
    if not args:
        print("usage: FREE_CLAUDE_KEY=... router.py test-key <%s>" % "|".join(PROVIDER_ORDER))
        return 2
    verdict, message = test_key(args[0], os.environ.get("FREE_CLAUDE_KEY", ""))
    print(message)
    return {"ok": 0, "warn": 3, "bad": 1}[verdict]


def old_openrouter_key():
    try:
        with open(OLD_OPENROUTER_ENV, encoding="utf-8") as f:
            m = re.search(r'ANTHROPIC_AUTH_TOKEN="?([^"\s]+)"?', f.read())
            return m.group(1) if m else ""
    except OSError:
        return ""


def ask(prompt, default="y"):
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return default == "y"
    return (answer or default).startswith("y")


def cmd_keys(args):
    cfg = ensure_token(load_config())
    keys = cfg.setdefault("keys", {})
    print("\033[1mAPI keys\033[0m — every provider below is free. More keys mean more free requests a day:")
    print("when one runs out, the router moves on to the next.\n")
    for name in PROVIDER_ORDER:
        prov = PROVIDERS[name]
        print("\033[1m%s\033[0m: %s" % (prov["label"], prov["about"]))
        current = keys.get(name)
        if not current and name == "openrouter" and old_openrouter_key():
            if ask("  Use the OpenRouter key from your earlier setup? [Y/n] "):
                keys[name] = old_openrouter_key()
                print("  %s\n" % test_key(name, keys[name], cfg)[1])
                continue
        if current and ask("  Keep the saved key (%s…%s)? [Y/n] " % (current[:6], current[-4:])):
            print()
            continue
        keys.pop(name, None)
        print("  Get a key: %s" % prov["signup"])
        for _ in range(3):
            try:
                key = getpass.getpass("  Paste the key (it stays hidden), or press Enter to skip: ").strip()
            except EOFError:
                key = ""
            if not key:
                print("  skipped")
                break
            if prov.get("key_prefix") and not key.startswith(prov["key_prefix"]):
                print("  \033[33mNote:\033[0m %s keys usually start with %s" % (prov["label"], prov["key_prefix"]))
            print("  checking…", end="", flush=True)
            verdict, message = test_key(name, key, cfg)
            mark = {"ok": tick(True), "warn": "\033[33m!\033[0m", "bad": tick(False)}[verdict]
            print("\r  %s %s" % (mark, message))
            if verdict != "bad":
                keys[name] = key
                break
        print()
    save_config(cfg)
    have = [PROVIDERS[p]["label"] for p in PROVIDER_ORDER if keys.get(p)]
    if not have:
        print("\033[31mNo keys saved.\033[0m Add at least one with: claude-free-router keys")
        return 1
    print("Saved keys for: %s (in %s, readable only by you)" % (", ".join(have), CONFIG_PATH))
    return 0


def post_local(cfg, body, timeout=240):
    req = urllib.request.Request("http://127.0.0.1:%d/v1/messages" % cfg["port"], data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["token"],
                                          "anthropic-version": "2023-06-01"}, method="POST")
    try:
        with LOCAL.open(req, timeout=timeout) as r:
            return r.status, json.load(r), r.headers.get("x-free-claude-model", "")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), ""


def cmd_selftest(args):
    cfg = ensure_token(load_config())
    if not start_router(cfg):
        print("✘ the router isn't running")
        return 1
    status, reply, used = post_local(cfg, {"model": "free-fast", "max_tokens": 64, "messages": [
        {"role": "user", "content": "Reply with just the word OK."}]})
    if status != 200:
        print("%s simple request failed: %s" % (tick(False), (reply.get("error") or {}).get("message", reply)))
        return 1
    text = " ".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text").strip()
    print("%s simple request answered by %s: %r" % (tick(True), used, text[:60]))
    tool = {"name": "get_time", "description": "Returns the current time in a timezone.",
            "input_schema": {"type": "object", "properties": {"timezone": {"type": "string"}}, "required": ["timezone"]}}
    status, reply, used = post_local(cfg, {"model": "free-auto", "max_tokens": 512, "tools": [tool], "messages": [
        {"role": "user", "content": "What time is it in UTC? Use the get_time tool."}]})
    if status != 200:
        print("%s tool request failed: %s" % (tick(False), (reply.get("error") or {}).get("message", reply)))
        return 1
    calls = [b for b in reply.get("content", []) if b.get("type") == "tool_use"]
    if calls:
        print("%s tool calling works (%s called %s)" % (tick(True), used, calls[0].get("name")))
    else:
        print("\033[33m!\033[0m %s answered without calling the tool; Claude Code may still work" % used)
    return 0


def cmd_logs(args):
    if not os.path.exists(LOG_PATH):
        print("No log yet (%s)" % LOG_PATH)
        return 0
    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    sys.stdout.write("".join(lines[-40:]))
    if "-f" in args or "--follow" in args:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            try:
                while True:
                    line = f.readline()
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    return 0


def cmd_start(args):
    return cmd_ensure(args)


def cmd_stop(args):
    stop_router(load_config())
    print("free-claude router stopped")
    return 0


def cmd_restart(args):
    cfg = load_config()
    stop_router(cfg)
    return cmd_ensure(args)


def download(name):
    last = None
    for ref in REFS:
        try:
            with UPSTREAM.open(RAW_URL.format(ref=ref, name=name), timeout=60) as r:
                return r.read()
        except Exception as e:
            last = e
    raise RuntimeError("couldn't download %s: %s" % (name, last))


def cmd_update(args):
    me = os.path.abspath(__file__)
    try:
        fresh = download("router.py")
        compile(fresh, "router.py", "exec")
    except Exception as e:
        print("✘ update failed: %s" % e)
        return 1
    tmp = me + ".new"
    with open(tmp, "wb") as f:
        f.write(fresh)
    os.chmod(tmp, 0o755)
    os.replace(tmp, me)
    print("✔ router updated")
    return subprocess.call([sys.executable, me, "restart"])


def cmd_uninstall(args):
    cfg = load_config()
    stop_router(cfg)
    if shutil.which("systemctl") and os.path.exists(UNIT_PATH):
        subprocess.run(["systemctl", "--user", "disable", SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(UNIT_PATH)
        subprocess.run(["systemctl", "--user", "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for name in ("claude-free", "claude-free-router"):
        path = os.path.join(BIN_DIR, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                ours = "free-claude" in f.read()
            if ours:
                os.remove(path)
        except OSError:
            pass
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    if "--keep-keys" not in args and ask("Also delete your saved API keys and the router's logs? [y/N] ", "n"):
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(STATE_DIR, ignore_errors=True)
    print("free-claude has been removed. Claude Code itself is still installed (the plain `claude` command).")
    return 0


def cmd_help(args):
    print(__doc__.strip().split("\n\n")[0])
    print("""
Commands:
  serve       run the router in this terminal (normally it runs in the background)
  start       start the router in the background if it isn't running
  stop        stop it            restart   restart it
  status      providers, tiers, and which models are resting and why
  logs [-f]   recent requests: which tier and model each one used
  keys        add or change provider API keys
  selftest    send two tiny requests through the router
  update      download the newest router.py and restart
  uninstall   remove free-claude (Claude Code stays installed)
  env         print the settings the claude-free command uses
  version     print the version

Files: config %s · log %s""" % (CONFIG_PATH, LOG_PATH))
    return 0


COMMANDS = {"serve": cmd_serve, "ensure": cmd_ensure, "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart,
            "env": cmd_env, "status": cmd_status, "statusline": cmd_statusline, "keys": cmd_keys,
            "test-key": cmd_test_key, "selftest": cmd_selftest, "logs": cmd_logs, "update": cmd_update,
            "uninstall": cmd_uninstall, "help": cmd_help, "--help": cmd_help, "-h": cmd_help,
            "version": lambda a: print(VERSION) or 0, "--version": lambda a: print(VERSION) or 0}


def main(argv):
    command = argv[1] if len(argv) > 1 else "help"
    if command not in COMMANDS:
        print("unknown command %r\n" % command)
        cmd_help([])
        return 2
    return COMMANDS[command](argv[2:]) or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
