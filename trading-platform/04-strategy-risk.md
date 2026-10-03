# Phase 4 — Strategy engine & risk (weeks 10–13)

**Gate:** the chaos suite runs a deliberately runaway strategy — one that tries to buy
infinite size, every tick, with a stale feed, during a reconciliation break — and the risk
engine stops it every single time, in under one second, from a separate process.

If you only do one phase of this plan properly, do this one.

---

## 4.1 Separation of concerns: alpha → signal → portfolio → order

Beginners write one function that looks at a chart and returns "buy 0.5 BTC". That couples
four decisions that need to be independent, and makes it impossible to tell which one is
broken when you lose money.

```
   ALPHA MODELS            SIGNAL BLENDER          PORTFOLIO CONSTRUCTION      EXECUTION
   ───────────             ──────────────          ──────────────────────      ─────────
   alpha_momentum  ─┐
   alpha_carry     ─┼──▶  orthogonalize      ──▶  risk model (cov)       ──▶  target
   alpha_meanrev   ─┤     decorrelate             optimizer (HRP/MV)          weights
   alpha_ml        ─┘     weight by IR            constraints                 ──▶ orders
                          ──▶ expected returns    Kelly fraction × haircut
```

- An **alpha** produces a forecast with a horizon and a confidence. It knows nothing about
  position size, capital, or what else you hold.
- The **blender** converts many forecasts into one expected-return vector, orthogonalizing
  correlated alphas so you don't double-count the same bet wearing two hats.
- **Portfolio construction** turns expected returns + a covariance estimate + constraints
  into target weights. This is where diversification and sizing live.
- **Execution** turns the delta between target and current weights into orders. Phase 5.

Each layer is independently testable, and when PnL disappoints you can attribute it to
forecast quality, blending, sizing, or execution — which is the only way to improve.

---

## 4.2 Strategy SDK

Every strategy implements this and nothing else. Keep the interface small; the engine owns
the plumbing.

```python
# libs/kairos-core/kairos_core/strategy.py
from abc import ABC, abstractmethod

class Strategy(ABC):
    """
    Contract:
      - PURE with respect to time: may only read state derived from events already
        delivered. Never calls datetime.now(); uses self.clock.
      - Returns INTENTS (target weights), not orders. The engine and risk layer decide
        what orders realize that intent, which keeps risk in one place.
      - Must be restartable: all state is either derivable from replayed events or
            explicitly checkpointed. A crash must not change behaviour.
      - Identical code runs in backtest and live. The engine injects the environment.
    """
    strategy_id: str
    instruments: list[Instrument]
    max_gross_weight: Decimal       # self-declared cap; risk enforces a tighter global one

    @abstractmethod
    def on_market(self, event: MarketEvent) -> list[Intent] | None: ...

    def on_fill(self, fill: Fill) -> None: ...
    def on_order_update(self, update: OrderUpdate) -> None: ...
    def on_timer(self, event: TimerEvent) -> list[Intent] | None: ...
    def on_funding(self, event: FundingEvent) -> None: ...
    def on_halt(self, reason: str) -> None: ...          # must flatten gracefully
    def warmup_bars(self) -> int: ...                    # engine refuses to trade before this

    # --- lifecycle hooks the engine calls, which you rarely override ---
    def checkpoint(self) -> dict: ...
    def restore(self, state: dict) -> None: ...

@dataclass(frozen=True)
class Intent:
    """What the strategy WANTS. Risk and execution decide what actually happens."""
    instrument_uid: str
    target_weight: Decimal       # of strategy's allocated capital, signed. -1..1
    confidence: Decimal          # 0..1 — drives sizing, must be calibrated
    horizon_s: int               # how long this forecast is expected to hold
    urgency: str                 # "passive" | "normal" | "aggressive" | "immediate"
    reason: str                  # human-readable. ends up in the audit log and your journal.
```

**Why intents, not orders.** If strategies emit orders, each one needs its own risk logic,
and you now have N places where a bug can bypass your limits. With intents, there is exactly
one path from "wanted" to "sent", and it goes through the risk engine. This is the single
most important design choice in the strategy layer.

---

## 4.3 Portfolio construction

```python
class PortfolioConstructor:
    def targets(self, expected_returns: pd.Series, cov: pd.DataFrame,
                current: pd.Series, equity: Decimal) -> pd.Series:
        # 1. Covariance estimation. The sample covariance is badly conditioned and will
        #    produce absurd, concentrated weights. Shrink it, always.
        cov = ledoit_wolf_shrink(cov)

        # 2. Optimize. HRP needs no return forecasts and no matrix inversion, so it is
        #    far more stable out-of-sample than mean-variance. Start here.
        match self.method:
            case "hrp":          w = hierarchical_risk_parity(cov)
            case "risk_parity":  w = equal_risk_contribution(cov)
            case "mean_var":     w = mean_variance(expected_returns, cov, self.max_vol)
            case "cvar":         w = min_cvar(self.return_scenarios, self.alpha)
            case "black_litt":   w = black_litterman(self.prior, expected_returns, cov)

        # 3. Kelly sizing with a large haircut. Full Kelly is the growth-optimal bet
        #    *if your estimates are exact*. They are not, and full Kelly on overestimated
        #    edge is a reliable route to ruin. Quarter-Kelly or less.
        w *= self.kelly_fraction          # 0.25 is aggressive. 0.1-0.15 is sane.

        # 4. Volatility targeting: scale the whole book so forecast vol hits target.
        port_vol = np.sqrt(w @ cov @ w) * np.sqrt(252)
        w *= min(1.0, self.target_vol / max(port_vol, 1e-9))

        # 5. Constraints, applied last so nothing above can violate them.
        w = self._apply_constraints(w)

        # 6. No-trade band. Rebalancing to a target you're already near just pays fees.
        #    Only trade the part of the delta that exceeds the band.
        delta = w - current
        return current + delta.where(delta.abs() > self.no_trade_band, 0)
```

Constraints to implement, all of them:

| Constraint | Typical value | Why |
|---|---|---|
| Max weight per instrument | 20% | Idiosyncratic blowup survival |
| Max gross exposure | 150% | Leverage ceiling |
| Max net exposure | 100% | Directional ceiling |
| Max weight per correlation cluster | 35% | Five correlated bets are one bet |
| Max sector / sub-sector (equities) | 25% | |
| Max beta to the market | 0.5 | Stops "alpha" that is just long beta |
| Max factor exposure (momentum, value, size) | ±0.3σ | Same reason |
| Max ADV participation | 5% | Capacity and impact |
| Min position notional | venue min × 3 | Dust positions cost more in fees than they earn |
| Max turnover per day | strategy-specific | Cost control |
| Illiquid instrument blacklist | — | |

**The correlation-cluster constraint is the one people skip and regret.** In March 2020 and
again in crypto's 2022 deleveraging, every "diversified" book turned out to be one trade.
Cluster your instruments by rolling correlation (hierarchical clustering on the correlation
distance matrix), recompute weekly, and cap exposure per cluster — not per instrument.

---

## 4.4 The risk engine

### Design

- **Its own process.** It must outlive the strategy engine and be able to kill it.
- **It sees everything** — subscribes to the full event bus, independently computes
  positions from fills, and compares against the venue's own reported state.
- **Veto, not advice.** No order reaches a venue without passing it. Enforce this
  structurally: the OMS accepts orders *only* on a channel the risk engine signs.
- **Fail closed.** If the risk engine is unreachable, the OMS rejects all opening orders and
  accepts only reducing ones.
- **Same code in backtest.** Backtested returns must be net of risk interventions, or your
  backtest is of a different strategy.

### Layer 1 — pre-trade checks (microseconds, on every order)

```python
PRE_TRADE_CHECKS = [
    # --- sanity: catch the bug, not the market ---
    Check("qty_positive",        lambda o, _: o.qty > 0),
    Check("qty_is_finite",       lambda o, _: o.qty.is_finite()),
    Check("tick_conformant",     lambda o, c: o.price % c.instrument.tick_size == 0),
    Check("lot_conformant",      lambda o, c: o.qty % c.instrument.lot_size == 0),
    Check("min_notional",        lambda o, c: o.notional >= c.instrument.min_notional),
    Check("instrument_enabled",  lambda o, c: o.instrument_uid in c.whitelist),

    # --- fat finger: the check that saves you from your own typo ---
    Check("max_order_notional",  lambda o, c: o.notional <= c.limits.max_order_usd),
    Check("max_order_vs_adv",    lambda o, c: o.qty <= Decimal("0.05") * c.adv),
    Check("max_order_vs_equity", lambda o, c: o.notional <= Decimal("0.2") * c.equity),
    Check("price_collar",        lambda o, c: abs(o.price / c.mid - 1) < Decimal("0.03")),

    # --- position and exposure ---
    Check("max_position",        lambda o, c: abs(c.position_after(o)) <= c.limits.max_pos),
    Check("gross_exposure",      lambda o, c: c.gross_after(o) <= c.limits.max_gross),
    Check("net_exposure",        lambda o, c: abs(c.net_after(o)) <= c.limits.max_net),
    Check("cluster_exposure",    lambda o, c: c.cluster_after(o) <= c.limits.max_cluster),
    Check("leverage",            lambda o, c: c.leverage_after(o) <= c.limits.max_leverage),
    Check("margin_headroom",     lambda o, c: c.margin_ratio_after(o) < Decimal("0.5")),
    Check("buying_power",        lambda o, c: o.notional <= c.available_margin),

    # --- rate and state: the runaway-loop killers ---
    Check("orders_per_min",      lambda o, c: c.order_count_1m < c.limits.max_orders_per_min),
    Check("orders_per_day",      lambda o, c: c.order_count_1d < c.limits.max_orders_per_day),
    Check("no_duplicate",        lambda o, c: o.client_id not in c.recent_client_ids),
    Check("not_self_crossing",   lambda o, c: not c.would_cross_own_order(o)),
    Check("not_halted",          lambda o, c: not c.halted),
    Check("feed_fresh",          lambda o, c: c.feed_age_s < c.limits.max_feed_age_s),
    Check("spread_sane",         lambda o, c: c.spread_bps < c.limits.max_spread_bps),
    Check("clock_ok",            lambda o, c: abs(c.clock_skew_s) < Decimal("0.5")),
    Check("recon_clean",         lambda o, c: c.reconciliation_break_usd < 25),
    Check("in_trading_window",   lambda o, c: c.now in c.schedule and not c.in_blackout),
]
```

Every veto increments `kairos_risk_veto_total{rule=...}`. **Watch that metric like a
dashboard-level signal, not an error log** — a rule that starts firing frequently is telling
you something about either a bug or a changed market.

### Layer 2 — position monitoring (per tick)

- Hard stop loss per position (place it *at the venue* as a reduce-only order, so it survives
  your process dying — this is the single highest-value reliability measure in the system)
- Trailing stop; time-based stop ("this forecast's horizon expired, exit regardless")
- Max adverse excursion limit
- Profit target / scale-out ladders
- Liquidation-distance monitor: alert at 3× maintenance margin, force-reduce at 2×

### Layer 3 — portfolio risk (per minute)

```python
class PortfolioRisk:
    def assess(self, pf: Portfolio, returns: pd.DataFrame) -> RiskAssessment:
        return RiskAssessment(
            var_95   = self.parametric_var(pf, returns, 0.95),
            var_99   = self.parametric_var(pf, returns, 0.99),
            cvar_95  = self.historical_cvar(pf, returns, 0.95),   # trust this over VaR
            vol_fcst = self.ewma_vol(returns, halflife=20),
            beta     = self.market_beta(pf, returns),
            factors  = self.factor_exposures(pf),
            # Stress: not statistics, but actual historical catastrophes replayed
            # against TODAY'S book. This is the number that tells you if you survive.
            stress   = {
                "covid_2020_03":      self.replay_shock(pf, "2020-03-09", "2020-03-23"),
                "luna_2022_05":       self.replay_shock(pf, "2022-05-07", "2022-05-13"),
                "ftx_2022_11":        self.replay_shock(pf, "2022-11-07", "2022-11-11"),
                "yen_carry_2024_08":  self.replay_shock(pf, "2024-08-02", "2024-08-06"),
                "instant_-30pct":     self.instant_shock(pf, Decimal("-0.30")),
                "corr_to_1":          self.correlation_breakdown(pf),   # all corr → 1
                "liquidity_halved":   self.liquidity_shock(pf, Decimal("0.5")),
            },
            concentration = self.herfindahl(pf),
            margin_usage  = pf.used_margin / pf.available_margin,
        )
```

Run the `corr_to_1` scenario weekly and read the number. Correlations going to 1 in a crisis
is not a tail assumption — it is the base case, and it is how "diversified" books die.

### Layer 4 — the drawdown governor

Tiered de-risking, applied automatically, with no human in the loop. The entire point is that
it acts while you are asleep or panicking.

```python
DRAWDOWN_LADDER = [
    #  DD from peak        action                               auto-resume?
    (Decimal("0.03"), "notify + log",                           True),
    (Decimal("0.05"), "halve new position sizes",               True),   # scale to 50%
    (Decimal("0.08"), "no new positions; manage existing only", True),
    (Decimal("0.10"), "reduce all positions by 50%",            False),  # needs approval
    (Decimal("0.15"), "flatten everything; halt; page",         False),
]

DAILY_LOSS_LADDER = [
    (Decimal("0.01"), "notify",                                 True),
    (Decimal("0.02"), "halt new entries for the rest of today",  True),
    (Decimal("0.03"), "flatten and halt until manual resume",    False),
]
```

The asymmetry is deliberate and important: **de-risking is automatic and instant;
re-risking always requires a human approval** (which Phase 6 delivers to your phone). This
asymmetry is the core safety property of the whole system.

### Layer 5 — circuit breakers

Each of these halts trading immediately on trip, independent of PnL:

| Breaker | Trip condition | Action |
|---|---|---|
| Feed staleness | no tick for >30s on a traded symbol | halt that symbol |
| Spread blowout | spread > 5× trailing 1h median | halt that symbol |
| Volatility spike | 1m realized vol > 10× 1d median | reduce sizes 75% |
| Venue degradation | reject rate >10%, or ack p99 >5s | halt that venue, SOR routes elsewhere |
| Reconciliation break | internal vs. venue mismatch >$25 | halt all, page, snapshot state |
| Clock skew | >500ms | halt all |
| Order storm | >60 orders/min from one strategy | halt that strategy, page |
| PnL anomaly | 1m PnL move >5σ | halt all, page |
| Position anomaly | position exists with no originating fill | halt all, page |
| Margin ratio | used/available > 70% | force-reduce to 50% |
| Self-trade detected | own buy matched own sell | halt all, page (regulatory issue too) |
| Deploy guard | new code version <1h old AND DD >2% | auto-rollback |

### Layer 6 — exchange-side protection

Software you control can die. Configure protection that lives *at the venue*:

- **Cancel-on-disconnect** where offered. Your working orders vanish if your connection dies,
  rather than sitting there executing a strategy that no longer exists.
- **Dead man's switch** — Binance-style `/fapi/v1/listenKey` style heartbeats, or
  exchange-native auto-cancel timers. Send a heartbeat every few seconds; if it stops, the
  venue cancels everything.
- **Reduce-only stop orders resting at the venue** for every open position.
- **Sub-account isolation** per strategy, so one strategy's liquidation cannot cascade into
  another's margin.
- **Venue-level position and leverage limits** set in the exchange UI as a second ceiling
  below your software limits. Belt and braces, with the braces outside your codebase.

### Layer 7 — reconciliation

Runs every 30 seconds. This is how you find out your state is wrong *before* it costs you.

```python
async def reconcile(venue: VenueClient, internal: PositionStore) -> list[Break]:
    """
    Compares, in order of how badly a mismatch hurts:
      1. positions (qty per instrument)   — a phantom position is an unhedged bet
      2. open orders (id, price, qty)     — a forgotten order is a live landmine
      3. balances / margin                — tells you if fees or funding drifted
      4. recent fills                     — catches fills we never processed
    A break above threshold halts trading. It does NOT auto-correct: a bug that
    creates phantom positions will happily 'correct' you into a real one.
    """
    breaks = []
    venue_pos = await venue.positions()
    for uid, qty in internal.positions().items():
        vq = venue_pos.get(uid, Decimal(0))
        if abs(vq - qty) * price(uid) > RECON_THRESHOLD_USD:
            breaks.append(Break(uid, internal=qty, venue=vq))
            RECON_BREAK.labels(venue=venue.name, symbol=uid).set(float(abs(vq - qty)))
    if breaks:
        await risk.halt(f"reconciliation break: {breaks}")
        await bus.publish("alerts.critical", ReconBreakAlert(breaks))   # → n8n → your phone
    return breaks
```

---

## 4.5 Chaos tests — the actual gate

`tests/chaos/` — these must pass before any live capital. Each one asserts that the system
takes *no new risk* under the fault.

```python
@pytest.mark.chaos
class TestRiskEngineUnderFault:
    def test_runaway_strategy_is_stopped(self):
        """A strategy that requests infinite size every tick must be capped and halted."""

    def test_stale_feed_blocks_entries_but_allows_exits(self):
        """Default-closed: can always reduce, never open."""

    def test_risk_engine_death_blocks_all_opening_orders(self):
        """Kill the risk process. OMS must reject opens, permit reduce-only."""

    def test_duplicate_client_id_never_double_fills(self):
        """Submit the same intent 100x concurrently. Exactly one order reaches the venue."""

    def test_venue_rejects_everything(self):
        """100% reject rate trips the venue breaker rather than retrying forever."""

    def test_venue_returns_garbage(self):
        """Malformed JSON, nulls, wrong types, HTML error pages. No crash, no bad state."""

    def test_partial_fill_then_disconnect(self):
        """Reconnect must discover the partial fill and reconcile, not re-send."""

    def test_clock_jumps_backwards(self):
        """NTP correction mid-session. No negative-duration maths, no double-trigger."""

    def test_reconciliation_break_halts_within_one_cycle(self):
        """Inject a phantom venue position. Halt in <=30s. No auto-correction."""

    def test_drawdown_ladder_fires_in_order(self):
        """Walk equity down. Assert each rung fires exactly once, at the right level."""

    def test_flatten_under_no_liquidity(self):
        """Empty book. Flatten must not place absurd market orders into a vacuum."""

    def test_restart_mid_flight_recovers_exact_state(self):
        """SIGKILL with working orders. Restart. State must match the venue exactly."""

    def test_two_instances_do_not_double_trade(self):
        """Accidental double deployment. Distributed lock must make the second a no-op."""
```

That last test matters more than it sounds. "I accidentally ran two copies" is a genuinely
common and expensive incident. Take a Redis lock keyed on `(strategy_id, env)` with a TTL
heartbeat, and refuse to start without it.

---

**Gate check:** the whole chaos suite is green, repeatedly, and you have watched the risk
engine kill the runaway strategy with your own eyes. `make chaos` runs in CI nightly.
