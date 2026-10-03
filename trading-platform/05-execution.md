# Phase 5 — Execution: OMS, EMS, routing, TCA (weeks 14–16)

**Gate:** paper fills reconcile to the cent against a simulated venue; the same intent
submitted 100 times concurrently produces exactly one order; TCA reports slippage against
arrival price, VWAP, and 1s/10s/60s markouts.

Execution is where measurable edge quietly leaks away. A strategy with 15 bps of gross edge
and 12 bps of avoidable execution cost is a strategy with 3 bps of edge. Most people never
measure this, which means they never find the 9 bps sitting on the table.

---

## 5.1 Order lifecycle state machine

Model it explicitly. Ad-hoc boolean flags (`is_sent`, `is_filled`, `is_cancelled`) will
eventually reach a combination you never considered, usually during a disconnect.

```python
class OrderState(StrEnum):
    CREATED        = "created"          # exists locally, risk not yet consulted
    RISK_APPROVED  = "risk_approved"
    RISK_REJECTED  = "risk_rejected"    # terminal
    PENDING_NEW    = "pending_new"      # sent; no ack. THE DANGEROUS STATE.
    WORKING        = "working"          # acked, live at venue
    PARTIALLY_FILLED = "partially_filled"
    FILLED         = "filled"           # terminal
    PENDING_CANCEL = "pending_cancel"
    CANCELLED      = "cancelled"        # terminal
    REJECTED       = "rejected"         # terminal
    EXPIRED        = "expired"          # terminal
    UNKNOWN        = "unknown"          # we lost track. must resolve before any new order.

TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CREATED:        {RISK_APPROVED, RISK_REJECTED},
    OrderState.RISK_APPROVED:  {PENDING_NEW},
    OrderState.PENDING_NEW:    {WORKING, REJECTED, UNKNOWN, PARTIALLY_FILLED, FILLED},
    OrderState.WORKING:        {PARTIALLY_FILLED, FILLED, PENDING_CANCEL, CANCELLED,
                                EXPIRED, UNKNOWN},
    OrderState.PARTIALLY_FILLED: {PARTIALLY_FILLED, FILLED, PENDING_CANCEL, CANCELLED,
                                  EXPIRED, UNKNOWN},
    OrderState.PENDING_CANCEL: {CANCELLED, FILLED, PARTIALLY_FILLED, UNKNOWN},
    OrderState.UNKNOWN:        {WORKING, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED},
}
# Illegal transitions raise. In production they also halt and page: an illegal transition
# means your model of reality is wrong, and trading on a wrong model is how you lose a lot.
```

### `PENDING_NEW` and `UNKNOWN` are the states that cost money

`PENDING_NEW` means you sent an order and don't know whether the venue has it. You must not
send a replacement — you might end up with two. The resolution path:

1. Wait up to the venue's ack SLA (measure it; typically 100–500ms).
2. On timeout, **query by your own client order ID** — never by venue ID, which you may not
   have. This is why deterministic client IDs are non-negotiable.
3. If the query says the order exists → `WORKING`. If it doesn't → safe to retry.
4. If the query itself fails → `UNKNOWN`: halt new orders for that instrument, keep
   querying with backoff, page after 60 seconds. Do **not** guess.

```python
def client_order_id(strategy_id: str, uid: str, intent_hash: str, bar_ts: int) -> str:
    """
    Deterministic and idempotent: the same intent at the same bar always produces the
    same ID. A retry after an ambiguous failure therefore cannot create a second order --
    the venue rejects the duplicate ID. This single function prevents the most expensive
    class of bug in automated trading.
    """
    raw = f"{strategy_id}|{uid}|{intent_hash}|{bar_ts}"
    return f"K{hashlib.blake2b(raw.encode(), digest_size=10).hexdigest()}"   # 21 chars
```

### The outbox pattern

Never do "write to DB, then call the venue" or "call the venue, then write to DB" — a crash
between the two corrupts your state. Instead:

1. In one Postgres transaction: insert the order row **and** an `outbox` row.
2. A separate dispatcher reads `outbox`, sends to the venue, marks sent.
3. Dispatch is idempotent via the client order ID, so re-sending after a crash is safe.

This gives you exactly-once *effects* over at-least-once delivery, which is the strongest
guarantee available when talking to someone else's API.

---

## 5.2 Smart order router

```python
class SmartOrderRouter:
    def route(self, intent: Intent, qty: Decimal) -> list[ChildOrder]:
        venues = [v for v in self.venues_for(intent.instrument_uid)
                  if v.healthy and not v.halted]
        if not venues:
            raise NoVenueAvailable(intent.instrument_uid)

        scored = sorted(venues, key=lambda v: self._cost(v, intent, qty))
        # Cost, not price: fee tier + expected slippage at this size + latency penalty
        # + an inventory/counterparty-concentration penalty. The cheapest *quoted* price
        # on a venue where you cannot get size out is not cheap.
        return self._split(scored, qty, intent.urgency)

    def _cost(self, v: Venue, intent: Intent, qty: Decimal) -> Decimal:
        book = self.books[v.name][intent.instrument_uid]
        return (
            v.fee_bps(intent.urgency)                       # maker vs taker, your tier
            + book.walk_cost_bps(qty, intent.side)          # eat the book, honestly
            + v.latency_penalty_bps(intent.urgency)         # slow venue = more adverse move
            + v.reject_rate * Decimal(50)                   # unreliability has a price
            + self.concentration_penalty_bps(v)             # don't park everything in one place
        )
```

Also worth routing on: available borrow (shorts), funding rate differential (perps — this is
itself a source of edge), withdrawal/transfer friction, and whether the venue's insurance
fund has recently been drained.

---

## 5.3 Execution algorithms

| Algo | Mechanism | Use when |
|---|---|---|
| **Market** | Immediate taker | Urgency dominates; flattening in a crisis |
| **Limit (post-only)** | Rest at or inside touch | You can wait and want the rebate |
| **Adaptive limit** | Start passive, step toward the touch as the clock runs out | The default for most MF strategies |
| **TWAP** | Equal slices over a window, with randomized timing | Low urgency, hide intent |
| **VWAP** | Slices weighted by the historical volume curve | Benchmarked against VWAP |
| **POV** | Hold a fixed % of realized volume | Large order, unknown duration |
| **Implementation Shortfall** | Optimize impact vs. timing risk (Almgren–Chriss) | Large order, decaying alpha |
| **Iceberg** | Small visible slice, hidden remainder | Large size, visible book |
| **Sniper** | Rest hidden, take only when a target price prints | Patient, price-sensitive |
| **Peg** | Track mid/bid/ask with an offset | Market making |
| **Liquidation-seeking** | Rest where liquidation cascades will hit you | Crypto perps, opportunistic |

The one to build first is **adaptive limit**, because it is what you'll use 80% of the time:

```python
class AdaptiveLimitAlgo:
    """
    Walks from passive to aggressive as the alpha horizon burns down.
    The core tradeoff: a passive fill saves ~spread+fee, but an unfilled order
    means the whole forecast is wasted. So urgency rises with elapsed time, and
    jumps if the market starts running away from you.
    """
    async def execute(self, parent: Order) -> None:
        deadline = self.clock.now() + timedelta(seconds=parent.horizon_s)
        arrival = self.book.mid
        while parent.remaining > 0 and self.clock.now() < deadline:
            elapsed = (self.clock.now() - parent.created_at).total_seconds()
            progress = elapsed / parent.horizon_s

            adverse = (self.book.mid - arrival) / arrival * parent.direction
            if adverse > self.panic_bps / 10_000:       # it's getting away: take it
                await self._cross(parent.remaining); return

            # offset in ticks: 2 ticks behind touch at the start, at the touch by the end
            offset_ticks = max(0, round(2 * (1 - progress)))
            px = self.book.best(parent.side) - offset_ticks * self.tick * parent.direction

            await self._replace(parent, px, self._slice_size(parent, progress))
            await asyncio.sleep(self.repricing_interval_s)

        if parent.remaining > 0:
            await self._cross(parent.remaining)         # deadline hit: finish the job
```

**Watch your cancel-replace rate.** Repricing every 100ms looks clever and will get you
rate-limited, flagged for excessive message traffic, and on some venues charged for it.
Reprice on *meaningful* book changes, not on a timer.

---

## 5.4 Rate limiting

Getting banned mid-position is a genuinely dangerous failure: you hold risk you cannot
manage. Treat venue rate limits as a hard resource you budget, not a wall you discover.

```python
class VenueRateLimiter:
    """
    Per-venue, per-bucket token buckets. Venues meter several dimensions at once
    (requests/min, order-weight/10s, orders/10s, WS messages/s) -- model each.

    Reserve 30% of every budget as emergency headroom usable ONLY by cancels and
    reduce-only orders. If you exhaust your limit placing orders, you must still be
    able to cancel them; that headroom is what makes flattening possible under stress.
    """
    def __init__(self, buckets: dict[str, TokenBucket], emergency_reserve=Decimal("0.3")):
        self.buckets, self.reserve = buckets, emergency_reserve

    async def acquire(self, weights: dict[str, int], *, emergency: bool = False) -> None:
        for name, w in weights.items():
            b = self.buckets[name]
            limit = b.capacity if emergency else b.capacity * (1 - self.reserve)
            await b.acquire(w, soft_limit=limit)
            RATE_LIMIT_USED.labels(venue=self.venue, bucket=name).set(b.used_pct)
```

Also: respect `Retry-After` headers; back off exponentially with jitter on 429/418; treat an
IP ban as a venue-level circuit-breaker trip (halt that venue, let SOR route around it); and
run order placement and market data on **separate connections**, so saturating one does not
blind the other.

---

## 5.5 Transaction cost analysis

TCA is how you find the leak. Compute it for every fill, store it in ClickHouse, dashboard it.

```sql
CREATE TABLE tca_fills (
    fill_id          String,
    client_order_id  String,
    strategy_id      LowCardinality(String),
    instrument_uid   LowCardinality(String),
    venue            LowCardinality(String),
    algo             LowCardinality(String),
    ts               DateTime64(9, 'UTC'),
    side             Enum8('buy'=1,'sell'=2),
    qty              Decimal64(8),
    fill_price       Decimal64(8),

    -- benchmarks: each answers a different question
    arrival_mid      Decimal64(8),   -- mid when the DECISION was made (the honest one)
    decision_mid     Decimal64(8),   -- mid when the signal fired (includes your own latency)
    interval_vwap    Decimal64(8),   -- VWAP over the order's life (was the algo any good?)
    close_price      Decimal64(8),

    -- costs, decomposed, in bps
    slippage_bps     Decimal64(4),   -- vs arrival: TOTAL cost of trading
    delay_bps        Decimal64(4),   -- decision -> arrival: your latency, in money
    impact_bps       Decimal64(4),   -- arrival -> fill: what your own order moved
    fee_bps          Decimal64(4),
    spread_paid_bps  Decimal64(4),

    -- markouts: did the market keep moving your way after you filled?
    markout_1s_bps   Decimal64(4),
    markout_10s_bps  Decimal64(4),
    markout_60s_bps  Decimal64(4),

    was_maker        UInt8,
    queue_ahead      Decimal64(8),
    book_imbalance   Decimal64(6)
) ENGINE = MergeTree ORDER BY (strategy_id, instrument_uid, ts);
```

### How to read it

- **Slippage vs. arrival** is your true all-in trading cost. Compare it with the cost model
  in your backtest. If live slippage exceeds backtest assumptions, your backtested edge is
  overstated by the difference — recalibrate the cost model and re-run, before doing anything
  else.
- **Delay cost** is latency expressed in money. It tells you whether optimizing
  infrastructure is worth anything for *this* strategy. Often it isn't, which saves you weeks.
- **Markouts are the adverse-selection detector.** If `markout_10s_bps` on your maker fills
  is persistently negative, you are being picked off: informed traders fill you right before
  the move. Fixes: quote wider, pull quotes on high order-flow imbalance, add a toxicity
  (VPIN) filter, or stop quoting that instrument.
- **Maker fill ratio by queue position** tells you whether your passive strategy is viable at
  all at your latency. If you need to be top-of-queue and you're never top-of-queue, the
  strategy is not for you.
- **Cost ratio** = total costs ÷ gross PnL. Above 50%, you are mainly a fee generator.

Feed all of this into the nightly n8n reporting workflow (Phase 6) so you read it every
morning without having to remember to look.

---

## 5.6 Position and PnL accounting

Get this exactly right; everything downstream depends on it.

- **FIFO lots** per instrument, with a separate realized/unrealized split.
- **PnL attribution**: price change, funding, fees, financing, slippage vs. decision price,
  and a residual. **The residual must be ~0.** A growing residual means your accounting is
  wrong, which means your risk numbers are wrong.
- **Mark-to-market** on the venue's mark price for perps (that's what liquidation uses),
  mid for spot. Never mark to last trade — a single print on a thin book can move your
  reported equity enough to trip a drawdown rung.
- **Currency conversion** at the rate used at the time, stored, not recomputed later.
- **Reconcile PnL against the venue's own reported PnL daily.** They will differ slightly
  (funding timing, fee tiers); the difference must be explainable and bounded.

---

**Gate check:** 100 concurrent duplicate intents → exactly one venue order. Kill the OMS
mid-flight; on restart it recovers exact state from the venue. TCA dashboard renders real
slippage and markout distributions. Simulated venue reconciles to the cent.
