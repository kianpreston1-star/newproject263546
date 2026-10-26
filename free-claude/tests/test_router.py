"""Tests for the free-claude router. Run with: python3 -m unittest discover -s free-claude/tests

The integration tests start the router against fake OpenAI-compatible providers on localhost, so no
API keys or network access are needed."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix="free-claude-test-")
os.environ["FREE_CLAUDE_CONFIG_DIR"] = os.path.join(TMP, "config")
os.environ["FREE_CLAUDE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import router  # noqa: E402

LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sse(chunks):
    return "".join("data: %s\n\n" % json.dumps(c) for c in chunks) + "data: [DONE]\n\n"


def text_chunks(text, usage=True):
    out = [{"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}]
    out += [{"choices": [{"index": 0, "delta": {"content": part}}]} for part in text]
    out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if usage:
        out.append({"choices": [], "usage": {"prompt_tokens": 123, "completion_tokens": 7}})
    return out


def tool_chunks(name, args):
    return [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": name, "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[:5]}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[5:]}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


class FakeProvider(BaseHTTPRequestHandler):
    """Behaves according to the requested model name."""
    protocol_version = "HTTP/1.1"
    calls = []
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def reply(self, status, body, headers=None, ctype="application/json"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def stream(self, chunks, pause=0.0, raw_tail=""):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for c in chunks:
            self.wfile.write(("data: %s\n\n" % json.dumps(c)).encode())
            self.wfile.flush()
            if pause:
                time.sleep(pause)
        self.wfile.write((raw_tail or "data: [DONE]\n\n").encode())
        self.wfile.flush()
        self.close_connection = True

    def do_GET(self):
        self.reply(200, json.dumps({"data": [{"id": m} for m in ("text-a", "text-b", "tool-a")]}))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with self.lock:
            FakeProvider.calls.append((self.server.name, body["model"], body, dict(self.headers)))
        model = body["model"]
        if model.startswith("rate"):
            return self.reply(429, json.dumps({"error": {"message": "Rate limit exceeded"}}), {"Retry-After": "120"})
        if model == "daily":
            reset = int((time.time() + 7200) * 1000)
            return self.reply(429, json.dumps({"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day."}}),
                              {"X-RateLimit-Reset": str(reset)})
        if model == "toolong":
            return self.reply(400, json.dumps({"error": {"message": "This model's maximum context length is 8192 tokens. "
                                                                   "Please reduce the length of the messages."}}))
        if model == "maxtok" and body["max_tokens"] > 4096:
            return self.reply(400, json.dumps({"error": {"message": "max_tokens must be less than or equal to 4096"}}))
        if model == "needs-reasoning" and not any(m.get("reasoning_content") for m in body["messages"] if m["role"] == "assistant"):
            return self.reply(400, json.dumps({"error": {"message": "Missing reasoning_content field in the assistant message"}}))
        if model == "gone":
            return self.reply(404, json.dumps({"error": {"message": "Model not found"}}))
        if model == "badkey":
            return self.reply(401, json.dumps({"error": {"message": "Invalid API key"}}))
        if model == "down":
            return self.reply(503, json.dumps({"error": {"message": "overloaded"}}))
        if model == "empty":
            return self.stream([{"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}])
        if model == "stream-error":  # OpenRouter style: 200, then an error inside the stream
            return self.stream([{"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                                {"error": {"code": 429, "message": "Provider returned error: rate-limited upstream"}}])
        if model == "midfail":
            return self.stream(text_chunks("Hello")[:3], raw_tail='data: {"error": {"code": 502, "message": "upstream died"}}\n\n')
        if model.startswith("tool"):
            return self.stream(tool_chunks("Bash", '{"command": "ls -la"}'))
        if model == "thinker":
            return self.stream([{"choices": [{"index": 0, "delta": {"reasoning_content": "Let me think. "}}]},
                                {"choices": [{"index": 0, "delta": {"reasoning_content": "Done thinking."}}]}] + text_chunks("Answer"))
        if model == "slow":
            time.sleep(3)
        return self.stream(text_chunks("Hi from %s" % model))


def start_fake(name):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
    server.daemon_threads = True
    server.name = name
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def answer(events):
    """The text of a streamed reply, joined from its deltas."""
    return "".join(e[1]["delta"].get("text", "") for e in events if e[0] == "content_block_delta")


def read_sse(resp):
    events = []
    for block in resp.read().decode().split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:])
        if name:
            events.append((name, data))
    return events


class TranslationTests(unittest.TestCase):
    def test_messages_and_tools(self):
        body = {
            "model": "free-auto", "max_tokens": 32000, "stream": True, "temperature": 1,
            "system": [{"type": "text", "text": "You are Claude Code.", "cache_control": {"type": "ephemeral"}}],
            "tools": [{"name": "Bash", "description": "Run a command",
                       "input_schema": {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
                                        "properties": {"command": {"type": "string"}}, "required": ["command"],
                                        "additionalProperties": False}},
                      {"type": "web_search_20250305", "name": "web_search"}],
            "tool_choice": {"type": "any"},
            "messages": [
                {"role": "user", "content": "list files"},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "hmm", "signature": "x"},
                    {"type": "text", "text": "Running ls."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}}]},
                {"role": "system", "content": "<system-reminder>todo list is empty</system-reminder>"},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": [{"type": "text", "text": "a.txt"}]},
                    {"type": "text", "text": "thanks"}]},
            ]}
        p = router.build_payload(body, "m", {"name": "nvidia"}, {"max_tokens": 16000, "stream_usage": True})
        roles = [m["role"] for m in p["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "user"])
        self.assertEqual(p["messages"][0]["content"], "You are Claude Code.")
        self.assertEqual(p["messages"][2]["tool_calls"][0]["function"], {"name": "Bash", "arguments": '{"command": "ls"}'})
        self.assertNotIn("reasoning_content", p["messages"][2])
        self.assertEqual(p["messages"][3], {"role": "tool", "tool_call_id": "toolu_1", "content": "a.txt"})
        self.assertIn("todo list is empty", p["messages"][4]["content"])
        self.assertTrue(p["messages"][4]["content"].endswith("thanks"))
        self.assertEqual([t["function"]["name"] for t in p["tools"]], ["Bash"])
        self.assertNotIn("$schema", p["tools"][0]["function"]["parameters"])
        self.assertEqual(p["tool_choice"], "required")
        self.assertNotIn("temperature", p)
        self.assertEqual(p["stream_options"], {"include_usage": True})

    def test_reasoning_passback_and_images(self):
        body = {"messages": [
            {"role": "user", "content": [{"type": "text", "text": "look"},
                                         {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}}]},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "plan"}, {"type": "text", "text": "ok"}]},
            {"role": "user", "content": "go"}]}
        p = router.build_payload(body, "m", {}, {"max_tokens": 100, "passback": True})
        self.assertEqual(p["messages"][0]["content"][1], {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}})
        self.assertEqual(p["messages"][1]["reasoning_content"], "plan")

    def test_gemini_schema_and_signatures(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "mode": {"type": ["string", "null"], "format": "uri"},
            "kind": {"const": "a"},
            "n": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}}
        cleaned = router.clean_schema(schema, gemini=True)
        self.assertEqual(cleaned["properties"]["mode"], {"type": "string", "nullable": True})
        self.assertEqual(cleaned["properties"]["kind"], {"enum": ["a"]})
        self.assertEqual(cleaned["properties"]["n"], {"nullable": True, "type": "integer"})
        self.assertNotIn("additionalProperties", cleaned)
        tools = router.convert_tools([{"name": "Exit", "input_schema": {"type": "object", "properties": {}}}], gemini=True)
        self.assertNotIn("parameters", tools[0]["function"])
        msg = router.assistant_message([{"type": "tool_use", "id": "t1", "name": "a", "input": {}},
                                        {"type": "tool_use", "id": "t2", "name": "b", "input": {}}], True, {"t2": "real"}, False)
        self.assertEqual(msg["tool_calls"][0]["extra_content"]["google"]["thought_signature"], router.GEMINI_SKIP_SIGNATURE)
        self.assertEqual(msg["tool_calls"][1]["extra_content"]["google"]["thought_signature"], "real")

    def test_repair_messages(self):
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
                {"role": "tool", "tool_call_id": "b", "content": "B"},
                {"role": "tool", "tool_call_id": "zzz", "content": "stray"},
                {"role": "user", "content": "next"}]
        fixed = router.repair_messages(msgs)
        self.assertEqual([m["role"] for m in fixed], ["user", "assistant", "tool", "tool", "user"])
        self.assertEqual(fixed[2]["tool_call_id"], "a")
        self.assertIn("interrupted", fixed[2]["content"])
        self.assertEqual(fixed[3]["content"], "B")
        self.assertIn("stray", fixed[4]["content"])
        self.assertTrue(fixed[4]["content"].endswith("next"))


class StreamTests(unittest.TestCase):
    def run_chunks(self, chunks):
        tr = router.Translator("free-auto", 50)
        events = []
        for c in chunks:
            events += tr.feed(c)
        return tr, events + tr.finish()

    def test_text_and_usage(self):
        tr, events = self.run_chunks(text_chunks("Hello"))
        names = [e[0] for e in events]
        self.assertEqual(names[0], "content_block_start")
        self.assertEqual(names[-2:], ["message_delta", "message_stop"])
        self.assertEqual("".join(e[1]["delta"]["text"] for e in events if e[0] == "content_block_delta"), "Hello")
        self.assertEqual(events[-2][1]["delta"]["stop_reason"], "end_turn")
        self.assertEqual(events[-2][1]["usage"], {"input_tokens": 123, "output_tokens": 7})

    def test_think_tags_split_across_chunks(self):
        parts = ["<th", "ink>step ", "one</th", "ink>\n\nThe ", "answer"]
        chunks = [{"choices": [{"index": 0, "delta": {"content": p}}]} for p in parts]
        tr, events = self.run_chunks(chunks)
        msg = tr.message()
        self.assertEqual(msg["content"][0], {"type": "thinking", "thinking": "step one", "signature": router.SIGNATURE})
        self.assertEqual(msg["content"][1], {"type": "text", "text": "The answer"})

    def test_reasoning_field_and_tool_calls(self):
        chunks = [{"choices": [{"index": 0, "delta": {"reasoning": "I should list files"}}]},
                  {"choices": [{"index": 0, "delta": {"content": "\n\n"}}]}] + tool_chunks("Bash", '{"command": "ls"}')
        tr, events = self.run_chunks(chunks)
        msg = tr.message()
        self.assertEqual([b["type"] for b in msg["content"]], ["thinking", "tool_use"])  # bare whitespace dropped
        self.assertEqual(msg["content"][1]["input"], {"command": "ls"})
        self.assertTrue(msg["content"][1]["id"].startswith("toolu_"))
        self.assertEqual(msg["stop_reason"], "tool_use")
        deltas = [e[1]["delta"] for e in events if e[0] == "content_block_delta"]
        self.assertIn({"type": "signature_delta", "signature": router.SIGNATURE}, deltas)
        self.assertIn({"type": "input_json_delta", "partial_json": '{"command": "ls"}'}, deltas)

    def test_broken_tool_arguments_are_repaired_or_reported(self):
        self.assertEqual(router.parse_arguments('{"a": 1'), {"a": 1})
        self.assertEqual(router.parse_arguments('{"a": "x'), {"a": "x"})
        self.assertIn("_unparsed_arguments", router.parse_arguments("not json"))

    def test_gemini_signature_kept(self):
        sigs = {}
        tr = router.Translator("m", 1, sigs)
        tr.feed({"choices": [{"index": 0, "delta": {"tool_calls": [{"id": "x", "function": {"name": "Read", "arguments": "{}"},
                                                                    "extra_content": {"google": {"thought_signature": "SIG"}}}]}}]})
        tr.finish()
        self.assertEqual(list(sigs.values()), ["SIG"])


class TierTests(unittest.TestCase):
    def test_classify(self):
        cases = {
            "fix the typo in README": "fast",
            "what does this function do?": "fast",
            "commit and push": "fast",
            "add a dark mode toggle to the settings page": "main",
            "explain the architecture of this project": "main",
            "Why does the login page crash when I submit the form?": "smart",
            "design a database schema for matchmaking, thinking about performance and scalability": "smart",
            "fix this:\nTraceback (most recent call last):\n  File x\nValueError: bad": "smart",
            "ultrathink about the caching layer": "smart",
        }
        for text, tier in cases.items():
            self.assertEqual(router.classify_text(text)[0], tier, text)

    def test_pick_tier_uses_hints_and_memory(self):
        mem = router.TierMemory()
        body = {"model": "free-auto", "messages": [{"role": "user", "content": "refactor the whole codebase to async"}]}
        self.assertEqual(router.pick_tier(body, {"x-claude-code-request-class": "auxiliary"}, mem)[0], "fast")
        self.assertEqual(router.pick_tier(body, {"x-claude-code-agent-type": "Explore", "x-claude-code-request-class": "subagent"}, mem)[0], "fast")
        self.assertEqual(router.pick_tier(body, {"x-claude-code-request-class": "compaction"}, mem)[0], "main")
        self.assertEqual(router.pick_tier(dict(body, model="free-fast"), {}, mem)[0], "fast")
        self.assertEqual(router.pick_tier(dict(body, model="claude-opus-5-5"), {}, mem)[0], "smart")
        hdr = {"x-claude-code-session-id": "s1", "x-claude-code-prompt-id": "p1", "x-claude-code-request-class": "main"}
        self.assertEqual(router.pick_tier(body, hdr, mem)[0], "smart")
        # later steps of the same prompt keep the tier even though the newest message is a tool result
        later = {"model": "free-auto", "messages": body["messages"] + [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}]}
        self.assertEqual(router.pick_tier(later, hdr, mem)[0], "smart")
        follow = {"model": "free-auto", "messages": [{"role": "user", "content": "yes"}]}
        self.assertEqual(router.pick_tier(follow, dict(hdr, **{"x-claude-code-prompt-id": "p2"}), mem),
                         ("smart", "follow-up to the last request"))
        plan = {"model": "free-auto", "messages": [{"role": "user", "content": [
            {"type": "text", "text": "<system-reminder>Plan mode is active.</system-reminder>"}, {"type": "text", "text": "rename x"}]}]}
        self.assertEqual(router.pick_tier(plan, {}, mem)[0], "smart")


class ErrorTests(unittest.TestCase):
    def test_judge(self):
        now = time.time()
        f = router.judge(429, '{"error":{"message":"Too Many Requests"}}', {"Retry-After": "30"}, "nvidia", now=now)
        self.assertEqual((f.kind, f.scope, f.wait), ("rate", "provider", 30.0))
        f = router.judge(429, '{"error":{"message":"Rate limit exceeded: free-models-per-day"}}',
                         {"X-RateLimit-Reset": str(int((now + 3600) * 1000))}, "openrouter", now=now)
        self.assertEqual((f.kind, f.scope, f.daily), ("rate", "provider", True))
        self.assertAlmostEqual(f.wait, 3600, delta=2)
        f = router.judge(429, '{"error":{"message":"rate-limited upstream"}}', {}, "openrouter", now=now)
        self.assertEqual(f.scope, "model")
        f = router.judge(429, '[{"error":{"message":"Quota exceeded. Please retry in 33.5s."}}]', {}, "gemini", now=now)
        self.assertEqual((f.scope, f.wait, f.daily), ("model", 33.5, False))
        self.assertEqual(router.judge(401, "bad key", {}, "zai").kind, "auth")
        self.assertEqual(router.judge(404, '{"error":{"message":"No endpoints found matching your data policy"}}', {}, "openrouter").kind, "policy")
        self.assertEqual(router.judge(404, "Model not found", {}, "nvidia").kind, "gone")
        self.assertEqual(router.judge(400, "This model's maximum context length is 8192 tokens.", {}, "nvidia").kind, "too_long")
        f = router.judge(400, "This model's maximum context length is 32768 tokens. However, you requested 33000 tokens "
                              "(17000 in the messages, 16000 in the completion).", {}, "nvidia")
        self.assertEqual((f.kind, f.max_tokens), ("max_tokens", 32768 - 17000 - 64))
        f = router.judge(400, "max_tokens must be less than or equal to 8192", {}, "nvidia")
        self.assertEqual((f.kind, f.max_tokens), ("max_tokens", 8192))
        self.assertEqual(router.judge(503, "overloaded", {}, "nvidia").kind, "down")
        self.assertEqual(router.judge(0, "URLError: refused", {}, "nvidia").kind, "down")

    def test_parse_wait_formats(self):
        now = 1_000_000_000.0
        self.assertEqual(router.parse_wait({"x-ratelimit-reset-requests": "1m30s"}, "", now), 90)
        self.assertEqual(router.parse_wait({"x-ratelimit-reset": "6.5s"}, "", now), 6.5)
        self.assertEqual(router.parse_wait({}, '"retryDelay": "12s"', now), 12)
        self.assertIsNone(router.parse_wait({}, "nothing here", now))


class RouterTests(unittest.TestCase):
    """Starts the router against two fake providers (posing as NVIDIA and OpenRouter)."""

    @classmethod
    def setUpClass(cls):
        cls.a, cls.b = start_fake("A"), start_fake("B")

    def setUp(self):
        FakeProvider.calls.clear()
        if os.path.exists(router.STATE_PATH):
            os.remove(router.STATE_PATH)

    def start(self, tiers, **settings):
        cfg = dict(router.DEFAULTS, token="t0ken", keys={"nvidia": "ka", "openrouter": "kb"},
                   providers={"nvidia": {"base_url": "http://127.0.0.1:%d/v1" % self.a.server_port, "rpm": 0},
                              "openrouter": {"base_url": "http://127.0.0.1:%d/v1" % self.b.server_port, "rpm": 0}},
                   tiers=tiers)
        cfg.update(settings)
        os.makedirs(router.CONFIG_DIR, exist_ok=True)
        r = router.Router(cfg)
        server = router.Server(("127.0.0.1", 0), router.Handler)
        server.router = r
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.port = server.server_port
        return r

    def post(self, body, token="t0ken", headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d/v1/messages?beta=true" % self.port, data=json.dumps(body).encode(),
                                     headers=dict({"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                                                  **(headers or {})), method="POST")
        try:
            resp = LOCAL.open(req, timeout=30)
            return resp.status, resp
        except urllib.error.HTTPError as e:
            return e.code, e

    def ask(self, model="free-auto", stream=True, text="hello there", **extra):
        return self.post(dict({"model": model, "max_tokens": 32000, "stream": stream,
                               "messages": [{"role": "user", "content": text}]}, **extra))

    def models_called(self):
        return [(c[0], c[1]) for c in FakeProvider.calls]

    def test_rate_limit_swaps_to_next_model_and_remembers(self):
        r = self.start({"main": ["nvidia:rate-a", "openrouter:text-b"], "fast": [], "smart": []})
        status, resp = self.ask()
        self.assertEqual(status, 200)
        events = read_sse(resp)
        self.assertEqual(events[0][0], "message_start")
        self.assertEqual(answer(events), "Hi from text-b")
        self.assertEqual(events[-1][0], "message_stop")
        self.assertEqual(self.models_called(), [("A", "rate-a"), ("B", "text-b")])
        # NVIDIA said wait 120s: the next request goes straight to OpenRouter
        status, resp = self.ask(text="another one")
        resp.read()
        self.assertEqual(self.models_called()[-1], ("B", "text-b"))
        self.assertEqual(len(self.models_called()), 3)
        st = r.status()
        self.assertGreater(st["providers"]["nvidia"]["resting"], 100)
        self.assertEqual(FakeProvider.calls[1][3].get("Authorization"), "Bearer kb")

    def test_everything_resting_returns_429_with_retry_after(self):
        self.start({"main": ["nvidia:rate-a", "openrouter:daily"], "fast": [], "smart": []})
        status, resp = self.ask()
        self.assertEqual(status, 429)
        body = json.loads(resp.read())
        self.assertEqual(body["error"]["type"], "rate_limit_error")
        self.assertEqual(int(resp.headers["retry-after"]), 120)
        self.assertIn("busy or out of quota", body["error"]["message"])

    def test_stream_error_and_empty_reply_fall_through(self):
        self.start({"main": ["openrouter:stream-error", "nvidia:empty", "nvidia:text-a"], "fast": [], "smart": []})
        status, resp = self.ask()
        self.assertEqual(status, 200)
        self.assertEqual(answer(read_sse(resp)), "Hi from text-a")
        self.assertEqual([m for _, m in self.models_called()], ["stream-error", "empty", "text-a"])

    def test_too_long_everywhere_asks_claude_code_to_compact(self):
        self.start({"main": ["nvidia:toolong", "openrouter:toolong"], "fast": [], "smart": []})
        status, resp = self.ask()
        self.assertEqual(status, 400)
        self.assertRegex(json.loads(resp.read())["error"]["message"], r"^prompt is too long: \d+ tokens > 8192 maximum$")

    def test_max_tokens_and_reasoning_retries_on_same_model(self):
        self.start({"main": ["nvidia:maxtok"], "fast": [], "smart": []})
        status, resp = self.ask()
        self.assertEqual(status, 200)
        resp.read()
        self.assertEqual([c[2]["max_tokens"] for c in FakeProvider.calls], [16000, 4096])
        FakeProvider.calls.clear()
        self.start({"main": ["nvidia:needs-reasoning"], "fast": [], "smart": []})
        status, resp = self.post({"model": "free-auto", "max_tokens": 100, "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "t", "signature": "free-claude"},
                                              {"type": "text", "text": "hey"}]},
            {"role": "user", "content": "go on"}]})
        self.assertEqual(status, 200)
        self.assertEqual(len(FakeProvider.calls), 2)
        self.assertEqual(FakeProvider.calls[1][2]["messages"][1]["reasoning_content"], "t")

    def test_mid_stream_failure_ends_with_error_event_and_rests_model(self):
        r = self.start({"main": ["nvidia:midfail", "openrouter:text-b"], "fast": [], "smart": []})
        status, resp = self.ask()
        events = read_sse(resp)
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(events[-1][1]["error"]["type"], "overloaded_error")
        self.assertEqual(answer(events), "He")
        self.assertFalse(r.status()["tiers"]["main"][0]["ready"])
        status, resp = self.ask(text="retry")
        self.assertEqual(answer(read_sse(resp)), "Hi from text-b")

    def test_non_streaming_tool_call(self):
        self.start({"main": ["nvidia:tool-a"], "fast": [], "smart": []})
        status, resp = self.ask(stream=False, tools=[{"name": "Bash", "input_schema": {"type": "object", "properties": {}}}])
        self.assertEqual(status, 200)
        msg = json.loads(resp.read())
        self.assertEqual(msg["stop_reason"], "tool_use")
        self.assertEqual(msg["content"][0]["input"], {"command": "ls -la"})
        self.assertEqual(resp.headers["x-free-claude-model"], "nvidia:tool-a")

    def test_tiers_and_fallback_across_tiers(self):
        self.start({"fast": ["nvidia:gone"], "main": ["openrouter:text-b"], "smart": ["nvidia:thinker"]})
        status, resp = self.ask(text="fix the typo in README")   # fast tier: its only model is gone -> borrows main
        self.assertEqual(answer(read_sse(resp)), "Hi from text-b")
        status, resp = self.ask(text="ultrathink: redesign the storage layer")
        events = read_sse(resp)
        starts = [e[1]["content_block"]["type"] for e in events if e[0] == "content_block_start"]
        self.assertEqual(starts, ["thinking", "text"])
        self.assertEqual([m for _, m in self.models_called()], ["gone", "text-b", "thinker"])

    def test_auth_and_endpoints(self):
        self.start({"main": ["nvidia:text-a"], "fast": [], "smart": []})
        status, resp = self.post({"model": "x", "messages": []}, token="wrong")
        self.assertEqual(status, 401)
        with LOCAL.open("http://127.0.0.1:%d/health" % self.port, timeout=5) as r:
            self.assertEqual(json.load(r)["name"], "free-claude")
        req = urllib.request.Request("http://127.0.0.1:%d/v1/messages/count_tokens" % self.port, method="POST",
                                     data=b'{"messages":[{"role":"user","content":"hello"}]}',
                                     headers={"Authorization": "Bearer t0ken"})
        with LOCAL.open(req, timeout=5) as r:
            self.assertGreater(json.load(r)["input_tokens"], 0)
        req = urllib.request.Request("http://127.0.0.1:%d/api/hello" % self.port, method="HEAD")
        with LOCAL.open(req, timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_bad_key_rests_the_whole_provider(self):
        r = self.start({"main": ["nvidia:badkey", "nvidia:text-a", "openrouter:text-b"], "fast": [], "smart": []})
        status, resp = self.ask()
        self.assertEqual(answer(read_sse(resp)), "Hi from text-b")
        self.assertEqual([m for _, m in self.models_called()], ["badkey", "text-b"])  # text-a skipped: same bad key
        self.assertIn("key rejected", r.status()["providers"]["nvidia"]["why"])


if __name__ == "__main__":
    unittest.main()
