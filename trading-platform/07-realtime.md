# Phase 7 — Real-time visibility: watching it work (weeks 20–21)

**Gate:** open one browser tab and watch, live, with sub-second lag: every tick arriving,
every feature updating, every signal firing, every risk check passing or vetoing, every order
going out and coming back filled — *and* every n8n workflow node lighting up as it runs, all
on one shared timeline. Then scrub backwards and replay yesterday's 14:32 incident at 10×
speed through the same UI.

This is not cosmetic. An autonomous system you cannot watch is a system you cannot trust,
cannot debug, and cannot develop intuition about. The single most valuable thing you will do
in the first month of running this is *watch it* and notice the things no metric was
measuring.

---

## 7.1 Three layers, one timeline

You need three different kinds of live view, because they answer different questions. The
mistake is trying to make one of them do all three jobs.

| Layer | Question it answers | Tool | Update rate |
|---|---|---|---|
| **Decision tape** | "Why did it just do that?" | Custom WebSocket console (§7.3) | Every event, 50–5000/s |
| **Metrics dashboards** | "How is it doing?" | Grafana + ClickHouse/Prometheus | 1–5s refresh |
| **Workflow runs** | "What is the control plane doing?" | n8n execution view + mirrored into the tape | Per node |

The payoff of Phase 1's invariant #6 ("everything is an append-only event") arrives here: the
bus already carries every state transition, so the live console is **just another
subscriber**. You do not instrument anything new. If you skipped that invariant, this phase
is three times the work — which is why it was an invariant.

---

## 7.2 Architecture

```
  feedhandler ─┐
  strategy    ─┤
  risk        ─┼──▶ NATS JetStream ──▶ ┌──────────────────┐
  OMS         ─┤      (durable)        │  live-gateway    │
  reconciler  ─┘                       │  (own process)   │
                                       │                  │
  n8n ──▶ exec events ──▶ webhook ─────▶  · fan-out       │──WebSocket──▶ browser
                                       │  · coalesce      │               (1..N tabs)
  ClickHouse ◀── replay queries ───────│  · downsample    │──SSE fallback─▶ phone
                                       │  · ring buffer   │
                                       └──────────────────┘
```

**The gateway is a separate process, and that is the whole safety story.** A browser on a
train with 3 bars of signal must never apply backpressure to your trading loop. Three rules
make that structural:

1. The gateway subscribes to the bus as an **ephemeral, non-durable** consumer for live
   streaming. If it falls behind, it loses messages — and that is the correct outcome.
2. Per-client **bounded queues**. Queue full → drop the oldest frame, increment a
   `dropped_frames` counter, and show it in the UI. A visibly lossy console beats a stalled
   trading engine, always.
3. The gateway is **read-only**. No control actions. Those go through the control API with
   approval tokens (Phase 6). A compromised browser tab must not be able to trade.

```python
# services/live-gateway/gateway.py
class LiveGateway:
    """
    Read-only fan-out of the event bus to browsers. Three hard rules:
      1. Never blocks the bus. Ephemeral subscription; slow consumers lose frames.
      2. Per-client bounded queue; on overflow drop oldest and report the drop.
      3. No control path. This process cannot place, cancel or size anything.
    """
    MAX_QUEUE = 2000          # ~2s of headroom at 1000 msg/s

    async def _pump(self) -> None:
        async for msg in self.bus.subscribe_ephemeral("kairos.>"):
            frame = self.to_frame(msg)
            for client in list(self.clients):
                try:
                    client.queue.put_nowait(frame)
                except asyncio.QueueFull:
                    client.queue.get_nowait()          # drop the OLDEST, keep current state
                    client.dropped += 1
                    client.queue.put_nowait(frame)

    async def _writer(self, client: Client) -> None:
        """
        Coalesce before sending. At 1000 msg/s a browser cannot render per-message,
        and does not need to: 20 frames/s is smooth to a human eye. We batch on a
        50ms tick, collapsing repeated state updates for the same key and keeping
        every discrete event (orders, fills, vetoes) intact.
        """
        while True:
            batch = await drain_for(client.queue, window_ms=50)
            if not batch:
                continue
            payload = coalesce(batch, keep_all_of={"order", "fill", "veto", "halt",
                                                   "workflow_node", "incident"})
            await client.ws.send_bytes(msgpack.packb({
                "frames": payload,
                "dropped": client.dropped,
                "server_ts": time.time_ns(),
            }))
```

**Coalescing rule, which matters a lot:** collapse *state* (book, position, PnL, signal
values — you only want the latest), but never collapse *events* (orders, fills, vetoes,
halts, workflow nodes — every one is meaningful and losing one makes the tape lie). Getting
this backwards produces a console that looks fine and silently hides the moment you needed
to see.

### The unified frame schema

One schema for everything on the timeline — hot loop and control plane alike. This is what
makes "see the workflow happening" actually work: an n8n node firing and an order going out
appear in the same tape, in the same order, with the same correlation ID.

```python
@dataclass(frozen=True)
class Frame:
    seq: int                   # gateway-assigned, monotonic; UI detects gaps
    ts_ns: int                 # event time (ts_recv, NOT wall clock at send)
    kind: str                  # tick|book|feature|signal|intent|risk|order|fill|
                               # position|pnl|workflow|incident|log
    source: str                # "feedhandler:binance" | "n8n:wf-macro-calendar" | ...
    trace_id: str | None       # ties a tick -> feature -> signal -> order -> fill together
    severity: str              # debug|info|warn|error|critical
    payload: dict              # kind-specific
```

`trace_id` is the magic. Propagate it from tick receipt all the way to venue ack (Phase 1
set up OpenTelemetry for exactly this). In the UI, clicking any row filters the tape to that
trace, and you see the complete causal chain of one decision: *this* tick updated *this*
feature, which moved *this* signal past threshold, which produced *this* intent, which passed
*these nine* risk checks, which became *this* order, which filled *here* at *this* slippage.
That view is worth more than any dashboard.

---

## 7.3 The console

A single-page app with five regions. Build it with the layout fixed and the panels
independently subscribable, so you can mute the noisy ones.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ● LIVE  binance-perp ✓  bybit ✓  okx ⚠   equity $104,230  DD -1.2%  ▸ 2ms   │  status bar
├───────────────────────────────┬──────────────────────────────────────────────┤
│  PIPELINE (animated)          │  DECISION TAPE                     [filter] │
│                               │                                              │
│  tick ──▶ feat ──▶ signal     │  14:32:07.412 ▸ SIGNAL  mom_btc  0.42→0.71  │
│   1.2k/s   ▓▓▓     +0.71      │  14:32:07.418 ▸ INTENT  BTCUSDT  w=0.18     │
│     │                         │  14:32:07.419 ✓ RISK    9/9 passed          │
│     ▼                         │  14:32:07.421 ▸ ORDER   BUY 0.42 @ 67,412   │
│  risk ──▶ order ──▶ fill      │  14:32:07.498 ✓ ACK     77ms                │
│   ✓9/9     3 live   12 today  │  14:32:08.104 ● FILL    0.42 @ 67,415  -0.4bp│
│                               │  14:32:09.002 ✗ VETO    max_order_vs_adv    │
├───────────────────────────────┤  14:32:12.330 ⚙ n8n     wf-venue-health ▸ 3/7│
│  RISK PANEL                   │  14:32:15.881 ⚠ WARN    okx ack p99 2.1s    │
│  gross   84% ▓▓▓▓▓▓▓░░        │                                              │
│  net     31% ▓▓▓░░░░░░        ├──────────────────────────────────────────────┤
│  VaR95  2.1% ▓▓░░░░░░░        │  BOOK LADDER        │  BLOTTER               │
│  margin  22% ▓▓░░░░░░░        │  67,418  ░░ 2.1     │  3 working             │
│  ──────────────────────       │  67,415  ░  0.8     │  12 filled today       │
│  vetoes 1h: adv 4, spread 1   │  ─────── 67,413 ─── │  0 rejected            │
│  breakers: all armed          │  67,412  ▓  1.4  ◀● │  avg slip  -0.8bp      │
│                               │  67,409  ▓▓ 3.2     │  fill rate 94%         │
└───────────────────────────────┴─────────────────────┴──────────────────────────┘
```

**Region by region, and why each earns its space:**

1. **Status bar** — connection state per venue, equity, drawdown, and the gateway's own lag.
   If `dropped_frames > 0` it turns amber. You must always know whether you are seeing
   everything.
2. **Pipeline** — an animated flow diagram of the hot loop with live rates and the current
   state of each stage. This is the "see the workflow happening" view for the trading loop:
   stages pulse as data moves, and turn red when they stall. A glance tells you *where*
   things are stuck, which no number does as fast.
3. **Decision tape** — the scrolling log of typed events, colour-coded, filterable by kind,
   strategy, instrument, severity, or trace. Click a row to pin its trace and see only that
   decision's causal chain. This is the panel you will spend the most hours in.
4. **Risk panel** — live gauges plus, crucially, **every risk check rendered as a row that
   flashes green on pass and red on veto**. Watching your risk rules fire in real time is how
   you learn which ones are too tight, too loose, or dead code.
5. **Book ladder + blotter** — the live L2 ladder with your own resting orders marked, and
   the order blotter. Seeing your order's position in the queue teaches you more about
   execution than any backtest.

### n8n in the same timeline

Two complementary things, and you want both:

**(a) n8n's native live execution view.** n8n already renders a running execution with nodes
lighting up as they complete. To get that reliably, set:

```yaml
EXECUTIONS_DATA_SAVE_ON_PROGRESS: "true"   # lets you watch a RUNNING execution node-by-node
N8N_PUSH_BACKEND: websocket                # not SSE; far better through a reverse proxy
```

Note the tradeoff: `SAVE_ON_PROGRESS: true` writes every node's output to Postgres as it
runs, which costs I/O and grows the DB. Keep it **on while you are building and watching**
(this phase, and whenever you are debugging a workflow), and consider turning it off once
a workflow is boring and stable. If you use it in steady state, tighten
`EXECUTIONS_DATA_MAX_AGE` to compensate. If n8n is behind Caddy/Traefik, the proxy must not
buffer the push connection or the live view silently stops updating — that is the usual cause
of "my n8n executions view is frozen."

**(b) Mirror n8n execution events into the tape.** Add a Code node at the start and end of
every workflow (or a reusable sub-workflow you call) that POSTs a `workflow` frame to the
gateway:

```javascript
// n8n Code node — "Emit Frame" — drop at the start/end of each workflow
await this.helpers.httpRequest({
  method: 'POST',
  url: `${$env.KAIROS_GATEWAY_URL}/frames`,
  body: {
    kind: 'workflow',
    source: `n8n:${$workflow.name}`,
    trace_id: $json.trace_id ?? null,      // propagate if the trigger carried one
    severity: 'info',
    payload: {
      workflow_id: $workflow.id,
      execution_id: $execution.id,
      node: $prevNode.name ?? 'start',
      status: 'running',
      // deep-link straight to the live execution in n8n
      url: `${$env.N8N_BASE_URL}/workflow/${$workflow.id}/executions/${$execution.id}`,
    },
  },
  json: true,
});
return $input.all();
```

Now a `wf-macro-calendar` run that posts a blackout window appears in the tape **immediately
before** the risk vetoes it causes, with a clickable link into the n8n execution. That
unified causal view — "the control plane did X, which is why the hot loop then did Y" — is the
thing that makes an automated system comprehensible, and it is why both halves share one
schema.

Mark these frame emissions **fire-and-forget with a 1-second timeout**. Observability must
never fail a workflow: wrap the call so an unreachable gateway is a logged warning, not a
failed macro-blackout.

---

## 7.4 Frontend: making it fast enough

A naive React app re-rendering on every message dies at about 50 messages/second. You need
500–5000. Four techniques, in order of impact:

```typescript
// 1. Ring buffer outside React. Never put the tape in useState.
class FrameBuffer {
  private buf: Frame[] = new Array(50_000);
  private head = 0;
  private count = 0;
  push(f: Frame) { this.buf[this.head] = f; this.head = (this.head + 1) % 50_000;
                   this.count = Math.min(this.count + 1, 50_000); }
  slice(n: number): Frame[] { /* newest n, no allocation in steady state */ }
}

// 2. Batch renders with requestAnimationFrame, capped at ~20fps for the tape.
//    The socket fills the buffer continuously; the UI samples it on a frame tick.
function useFrames(buffer: FrameBuffer, fps = 20) {
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    let raf = 0, last = 0;
    const loop = (t: number) => {
      if (t - last > 1000 / fps) { last = t; tick(); }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [fps]);
  return buffer;
}

// 3. Virtualize the tape (TanStack Virtual). Render ~60 rows, not 50,000.
// 4. Canvas, not DOM, for the book ladder and high-frequency charts.
//    uPlot for time series (handles 100k points), lightweight-charts for candles.
```

**Transport:** WebSocket with MessagePack. Binary + coalescing cuts bandwidth roughly 5×
versus pretty-printed JSON, which matters on mobile. Provide an SSE fallback for restrictive
networks, and auto-reconnect with exponential backoff plus a **gap-fill on reconnect**: the
client sends its last `seq`, and the gateway replays the missing frames from its ring buffer
if they are still there, or tells the client to do a full state resync if they are not. A
console that silently misses the thirty seconds you were in a tunnel is a console that lies.

**Stack recommendation:** React + Vite + TypeScript, TanStack Virtual, uPlot,
lightweight-charts, Tailwind. Dark theme by default — you will stare at this at 3am. Serve it
from the gateway process so there is one thing to deploy.

If you would rather not build a frontend at all, you can get maybe 60% of this from **Grafana
Live** (streaming panels over its own WebSocket, fed by the gateway pushing to Grafana's
`/api/live/push` endpoint) plus ClickHouse-backed tables. You lose the pipeline animation,
the trace-pinning, and the risk-check flash — which are precisely the parts that build
intuition. Build the console; it is two weeks and it changes how well you understand your own
system.

---

## 7.5 Time travel — the same UI, replaying the past

Because every event is append-only and persisted (Phase 1, invariant #6), the console can
replay any past window through exactly the same rendering path:

```
GET /replay?from=2026-10-02T14:30:00Z&to=2026-10-02T14:40:00Z&speed=10
```

The gateway reads frames from ClickHouse instead of the bus and emits them with scaled
inter-arrival times. The UI cannot tell the difference, which is the point: **one rendering
path for live and historical means your replay is never subtly different from what actually
happened.**

Controls: play/pause, 0.1× to 1000× speed, step-one-event, jump-to-next-veto,
jump-to-next-fill, and a scrubber over the equity curve. Deep-link a timestamp so an incident
report can contain a URL that reopens the exact moment.

This single feature pays for the whole phase. "Replay 14:32 at 10× and watch the risk panel"
turns a two-hour log-grep into a thirty-second answer, and it is how you will do every
postmortem from here on. It also doubles as your demo, your debugger, and the fastest way to
build a feel for how your strategy behaves in regimes you have not lived through yet.

---

## 7.6 Mobile and ambient awareness

You will not have a laptop open 24/7, and you should not need to.

- **Mobile view** — a stripped single column: status, equity, drawdown, open positions, last
  20 tape events, and a prominent halt button (which still goes through the control API's
  approval policy, so the button is safe to expose).
- **Push notifications** via the Phase 6 alert router, not from the console. The console is
  for looking; alerting is for being told.
- **An ambient display** is genuinely worth it if you run this seriously: a spare tablet or
  small monitor on the battle-station dashboard. Peripheral vision catches "that red thing
  wasn't there this morning" long before a threshold-based alert fires. Half the incidents you
  catch early, you will catch this way.

---

**Gate check:** one tab shows live ticks, signals, risk checks, orders, fills, and n8n node
executions on a single timeline with sub-second lag. Clicking a fill reveals its full causal
trace back to the originating tick. Pulling your network cable and reconnecting gap-fills
rather than silently skipping. `GET /replay` of yesterday renders identically to live. The
gateway can be killed without the trading system noticing.
