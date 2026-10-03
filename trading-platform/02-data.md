# Phase 2 — Data (weeks 3–5)

**Gate:** 30 continuous days of tick + L2 data captured, with an automated gap report that
accounts for every missing second, and a point-in-time feature query that provably cannot see
the future.

Data quality is the foundation of everything downstream. A subtle data bug does not crash
anything — it produces a strategy that backtests beautifully and loses money. Spend the time
here.

---

## 2.1 Normalized schema

Every venue speaks a different dialect. Normalize *once*, at the edge, into these types, and
let nothing else in the system know what a venue is.

```python
# libs/kairos-core/kairos_core/types.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

class Venue(StrEnum):
    BINANCE_PERP = "binance-perp"
    BYBIT_PERP   = "bybit-perp"
    OKX_PERP     = "okx-perp"

class InstrumentKind(StrEnum):
    SPOT = "spot"; PERP = "perp"; FUTURE = "future"; OPTION = "option"

@dataclass(frozen=True, slots=True)
class Instrument:
    """Immutable, venue-qualified. Never pass a bare string symbol anywhere."""
    venue: Venue
    symbol: str                 # venue-native, e.g. "BTCUSDT"
    kind: InstrumentKind
    base: str
    quote: str
    tick_size: Decimal          # min price increment
    lot_size: Decimal           # min quantity increment
    min_notional: Decimal
    max_leverage: Decimal
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    contract_size: Decimal = Decimal(1)
    expiry: str | None = None

    @property
    def uid(self) -> str:
        return f"{self.venue}:{self.symbol}"

@dataclass(frozen=True, slots=True)
class Trade:
    instrument_uid: str
    ts_venue_ns: int            # exchange timestamp
    ts_recv_ns: int             # our monotonic receive time — the honest one
    price: Decimal
    size: Decimal
    aggressor: str              # "buy" | "sell" — which side took liquidity
    trade_id: str
    seq: int | None = None

@dataclass(frozen=True, slots=True)
class BookDelta:
    instrument_uid: str
    ts_venue_ns: int
    ts_recv_ns: int
    seq: int                    # for gap detection. non-negotiable.
    bids: tuple[tuple[Decimal, Decimal], ...]   # (price, size); size 0 = remove
    asks: tuple[tuple[Decimal, Decimal], ...]
    is_snapshot: bool = False

@dataclass(frozen=True, slots=True)
class FundingRate:
    instrument_uid: str
    ts_ns: int
    rate: Decimal
    next_funding_ts_ns: int
    mark_price: Decimal
    index_price: Decimal
```

**Use `Decimal` for all prices and sizes.** Floats will eventually produce an order the
exchange rejects for a tick-size violation, or a position that drifts from the venue's by
dust until reconciliation screams. The performance cost is irrelevant at MF latency.

**Both timestamps, always.** `ts_venue` is what the exchange claims; `ts_recv` is when you
could actually have acted. Features must use `ts_recv`. Backtests must use `ts_recv`. The
difference between them *is* your latency disadvantage, and pretending it's zero is the most
common way to manufacture a fake edge.

---

## 2.2 Feedhandler

One process per venue. It does exactly four things: connect, normalize, detect gaps, publish.
No strategy logic, no storage logic.

```python
# services/feedhandler/handler.py  (sketch; Rust port in Phase 9 if needed)
class FeedHandler:
    """
    Invariants:
      - Sequence numbers are checked on every message. A gap triggers resync, not a warning.
      - Book snapshots are re-fetched on any inconsistency; we never 'patch over' a gap.
      - A crossed book (bid >= ask) means our state is wrong. Discard and resync.
      - Publishes to the bus; persistence is a separate subscriber, so a slow disk
        can never stall the feed.
    """
    async def run(self) -> None:
        backoff = ExponentialBackoff(base=0.5, cap=30, jitter=True)
        while not self._stop:
            try:
                async with self._connect() as ws:
                    await self._subscribe(ws)
                    await self._resync_books()
                    backoff.reset()
                    async for raw in ws:
                        msg = self._parse(raw)          # never trust the venue's schema
                        if not self._check_sequence(msg):
                            await self._resync_books()   # gap: rebuild, don't guess
                            continue
                        if self._is_crossed(msg):
                            BOOK_CROSSED.labels(...).inc()
                            await self._resync_books()
                            continue
                        FEED_LAG.labels(self.venue).observe(
                            (msg.ts_recv_ns - msg.ts_venue_ns) / 1e9)
                        await self.bus.publish(topic_for(msg), msg)
            except Exception:
                log.exception("feed_disconnected", venue=self.venue)
                await asyncio.sleep(backoff.next())
```

### Things that will bite you, and the fix

| Problem | Symptom | Fix |
|---|---|---|
| Silent disconnect (TCP open, no data) | Stale prices, bot trades on old book | Application-level heartbeat; if no message in `N` seconds, force reconnect. Never rely on TCP keepalive. |
| Book desync after reconnect | Crossed or empty book | Always re-snapshot then replay buffered deltas from `snapshot.seq + 1` |
| Venue rewrites history | Trade IDs reappear with different prices | Dedupe by `(trade_id, venue)` in Redis with TTL; log and alert on contradictions |
| Out-of-order delivery | Negative lag, nonsense features | Buffer and sort by `seq` within a small window; drop anything older than the window |
| Rate-limited on resubscribe | Cascading reconnect storm | Token bucket on *connection* attempts, not just requests; jittered backoff |
| Daylight saving / venue maintenance | Mystery gaps every Sunday | Maintain a per-venue calendar; expected gaps are suppressed in the gap report |
| Symbol delisted or renamed | Orders rejected forever | Poll instrument metadata hourly; emit `InstrumentChanged`; strategies must handle it |
| Clock drift | Lag metrics meaningless | `chrony` with multiple NTP sources; for HF, PTP. Measure offset against venve server time and export it. |

Run `chronyd` on every host from day one and alert on skew. If your clock is wrong, every
latency measurement and every timestamp-ordered feature is wrong, and you will not notice.

---

## 2.3 Storage: the medallion lake

```
s3://kairos/
├── bronze/                     # raw venue payloads, exactly as received, compressed
│   └── venue=binance-perp/date=2026-10-03/hour=14/*.jsonl.zst
├── silver/                     # normalized, deduped, validated, Parquet, partitioned
│   ├── trades/venue=.../symbol=.../date=.../
│   ├── book_snapshots/         # periodic L2 snapshots at 100ms
│   └── funding/
└── gold/                       # research-ready: bars, features, labels
    ├── bars_1m/ bars_1h/
    └── features/version=v3/
```

**Never delete bronze.** It is your only defence against "my normalizer had a bug for three
months." Compressed raw JSON is about $1/month per venue-symbol. Cheapest insurance you will
ever buy.

ClickHouse holds the hot analytical copy:

```sql
CREATE TABLE trades (
    instrument_uid LowCardinality(String),
    ts_venue       DateTime64(9, 'UTC'),
    ts_recv        DateTime64(9, 'UTC'),
    price          Decimal64(8),
    size           Decimal64(8),
    aggressor      Enum8('buy' = 1, 'sell' = 2),
    trade_id       String,
    seq            Nullable(UInt64)
) ENGINE = ReplacingMergeTree(ts_recv)
ORDER BY (instrument_uid, ts_venue, trade_id)
PARTITION BY toYYYYMM(ts_venue)
TTL toDateTime(ts_venue) + INTERVAL 2 YEAR TO VOLUME 'cold';

-- Bars are a materialized view, so they can never disagree with the trades that built them.
CREATE MATERIALIZED VIEW bars_1m_mv TO bars_1m AS
SELECT
    instrument_uid,
    toStartOfMinute(ts_venue)                        AS bucket,
    argMinState(price, ts_venue)                     AS open_state,
    maxState(price)                                  AS high_state,
    minState(price)                                  AS low_state,
    argMaxState(price, ts_venue)                     AS close_state,
    sumState(size)                                   AS volume_state,
    sumState(price * size)                           AS notional_state,
    sumState(if(aggressor = 'buy', size, 0))         AS buy_volume_state,
    countState()                                     AS trade_count_state
FROM trades GROUP BY instrument_uid, bucket;
```

`ReplacingMergeTree` keyed on `trade_id` gives you idempotent ingestion: replaying a bronze
file is always safe. Build everything so that **re-running any ingestion job is a no-op**,
because you will re-run all of them.

---

## 2.4 Point-in-time correctness

This is the section that decides whether your backtest means anything.

**The rule:** a feature row for decision time `t` may only contain data where
`ts_available <= t`. Note `ts_available`, not `ts_event`. An economic release stamped
13:30:00 that your vendor delivered at 13:30:04 was *available* at 13:30:04. A company's
quarterly revenue "for Q2" became available on the filing date, not the quarter end. A
restated figure became available on the restatement date — and your backtest must see the
*original* figure before that date, not the restated one.

Every slow-moving table therefore gets bitemporal columns:

```sql
CREATE TABLE fundamentals (
    instrument_uid  String,
    metric          String,
    period_end      Date,          -- what period it describes
    value           Decimal64(6),
    ts_available    DateTime64(3, 'UTC'),   -- when WE could first see it
    revision        UInt8,                  -- 0 = original, 1+ = restatements
    source          LowCardinality(String)
) ENGINE = ReplacingMergeTree(ts_available)
ORDER BY (instrument_uid, metric, period_end, revision);
```

And every join is an as-of join with an explicit availability filter:

```python
def features_as_of(uid: str, t: datetime) -> dict:
    """The ONLY way production or research reads slow data. No exceptions."""
    return ch.query("""
        SELECT metric, argMax(value, ts_available) AS value
        FROM fundamentals
        WHERE instrument_uid = {uid:String} AND ts_available <= {t:DateTime64(3)}
        GROUP BY metric
    """, {"uid": uid, "t": t})
```

**Write a lookahead test and run it in CI.** Take a feature pipeline, run it twice: once with
the full dataset, once with all data after `t` physically deleted. If any feature value for
time `t` differs, you have lookahead. This test has found bugs in every system I've seen it
applied to.

Other point-in-time traps, in rough order of how much damage they do:

- **Survivorship bias.** Your symbol universe must be the universe *as it existed then*,
  including the tokens that went to zero and the companies that were delisted. Backtesting
  today's top-100 coins over 2021 produces spectacular, entirely fictional returns.
- **Corporate actions** (equities). Splits, dividends, mergers. Store raw prices plus an
  adjustment factor table, and apply adjustments *as of* the decision date. Using today's
  adjusted series is lookahead.
- **Index/universe reconstitution** published before it takes effect.
- **Vendor backfill.** Many providers quietly populate history for a symbol from before you
  subscribed, with fields they computed later. Treat vendor `ts_available` as suspect and
  prefer your own capture timestamp.
- **Funding and borrow rates** are forward-looking announcements; know exactly which window
  each rate applies to.

---

## 2.5 Data sources

Start with the venue's own feeds (free, authoritative, lowest latency) and add alternative
data only when you have a specific hypothesis for it.

**Core (do these first)**
- Venue WebSocket: trades, L2 book, mark/index price, funding, liquidations, open interest
- Venue REST: instrument metadata, historical klines for warmup, account state
- Your own order and fill history — the most valuable proprietary dataset you will ever have

**High value, moderate effort**
- Cross-venue basis and funding spread (needs ≥2 venues; a real, durable crypto edge)
- Aggregate open interest and liquidation cascades
- Options-implied vol surface (Deribit is free), skew, term structure — excellent regime signal
- Macro calendar (FRED, Trading Economics) → drives automatic blackout windows in Phase 6
- Stablecoin flows, exchange reserve changes (Glassnode, Dune)

**Speculative — only with a prior hypothesis**
- News and filings (Benzinga, EDGAR full-text) → Phase 8
- Social sentiment. Treat with deep suspicion: mostly noise, trivially manipulated, and the
  reason a great many "AI trading bots" lose money.
- On-chain mempool, whale wallet tracking
- Satellite/shipping/alt data. Real edge exists here, at institutional price points.

---

## 2.6 Data quality monitors

Run these continuously; wire failures to n8n in Phase 6, which attempts automated backfill
before paging you.

```python
QUALITY_CHECKS = [
    # completeness
    Check("gap_detect",      "no gap > 5s during venue trading hours"),
    Check("seq_continuity",  "no missing sequence numbers"),
    Check("bar_coverage",    "expected_bars - actual_bars == 0 per day"),
    # validity
    Check("price_positive",  "price > 0 and size > 0"),
    Check("spread_sane",     "0 <= (ask-bid)/mid < 0.10"),
    Check("book_uncrossed",  "best_bid < best_ask"),
    Check("tick_conformance","price % tick_size == 0"),
    # consistency
    Check("cross_venue_dev", "|price - median(other_venues)| / median < 0.02"),
    Check("bar_vs_trades",   "bar OHLCV reconciles to underlying trades exactly"),
    Check("funding_window",  "funding timestamps align to venue schedule"),
    # distributional drift — the subtle one
    Check("return_outlier",  "|log return| < 12 * rolling_std(1d)"),
    Check("volume_regime",   "daily volume within [0.05x, 20x] of 30d median"),
    Check("feature_drift",   "PSI(today, trailing_30d) < 0.25 per feature"),
]
```

The last one — population stability index on your features — is what tells you your model's
inputs have changed character *before* your PnL tells you. Export each check's result as a
Prometheus gauge so it's alertable and graphable, and write every failure to a
`data_quality_incidents` table so you can later ask "was this backtest window clean?"

---

**Gate check:** 30 days captured. `scripts/gap_report.py --last 30d` prints a report where
every missing second is either accounted for by a known venue maintenance window or
explained. The lookahead test passes in CI. You can reconstruct the L2 book at any arbitrary
past timestamp and get an uncrossed, plausible book.
