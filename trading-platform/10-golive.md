# Phase 10 — Going live, and staying alive (week 26+)

---

## 10.1 The ramp

Do not skip rungs. Each one has entry criteria and a minimum duration, and the duration is
there because some failure modes only appear over time (funding accrual, fee tier changes,
weekend liquidity, month-end flows).

| Rung | Capital | Min duration | Entry criteria |
|---|---|---|---|
| **0 Shadow** | $100 | 2 weeks | All phase gates passed; chaos suite green |
| **1 Pilot** | 1% of target | 4 weeks | Shadow reconciles perfectly; live slippage within 1.5× of backtest assumption |
| **2 Small** | 5% | 4 weeks | Pilot Sharpe > 0; no unexplained incidents; TCA stable |
| **3 Quarter** | 25% | 8 weeks | Live-vs-paper divergence < 20% of expected return; drawdown within 1.5× backtest expectation |
| **4 Half** | 50% | 8 weeks | Survived at least one adverse regime; capacity analysis supports the size |
| **5 Full** | 100% | — | All of the above, and you are bored of watching it |

**Total: roughly 6–7 months from first live order to full size.** If that sounds slow,
consider the alternative: most people who go from backtest to full size in a week discover
their edge was execution-cost-negative, with full size on.

### Size-down triggers — define these *before* you need them

Write these down now, while you are calm, because you will not make good decisions during a
drawdown:

- Drawdown exceeds 1.5× the worst backtest drawdown → **down one rung**
- Rolling 60-day Sharpe < 0 → down one rung
- Live slippage exceeds 2× the backtest assumption → down one rung, investigate execution
- Any unexplained reconciliation break → halt, investigate, restart at rung 1
- Three consecutive losing weeks beyond backtest expectation → full review before continuing
- You find a bug that affected live trading → halt, fix, re-run shadow for one week

### Pre-flight checklist (run through this on go-live day)

```
[ ] Withdrawal permission DISABLED on all exchange API keys          (verify in the UI)
[ ] IP allowlist active on all keys                                  (verify)
[ ] Withdrawal address allowlist + time delay configured at exchange
[ ] Hardware MFA on all exchange and cloud accounts
[ ] Kill switch tested from phone TODAY, timed under 5 seconds
[ ] Venue-side reduce-only stops resting for every open position
[ ] Cancel-on-disconnect / dead man's switch enabled and tested
[ ] Reconciliation running, clean, alerting
[ ] Drawdown ladder values set and unit-tested
[ ] Daily loss limit set and unit-tested
[ ] Alertmanager paging your phone DIRECTLY, bypassing n8n (tested)
[ ] Backups verified by an actual restore this week
[ ] Clock sync verified, skew < 50ms
[ ] Capital in the account is money you can afford to lose entirely
[ ] Paper environment running in parallel on the same signals
[ ] Live console (Phase 7) open and showing the full pipeline
[ ] Runbooks written for: recon break, venue outage, runaway strategy, total infra loss
[ ] A second person knows how to flatten your positions if you are unreachable
```

That last line matters more than it looks. If you are in hospital, someone needs to be able
to close your positions. Write the steps down, keep them somewhere that person can reach, and
include the exchange web-UI path — not just your own tooling.

---

## 10.2 Master feature checklist

Everything a complete system has. Use it to audit what you've built and to decide what's
next. `★` marks things that are genuinely optional for a solo MF operator; everything
unmarked is load-bearing.

### Data
- [ ] Multi-venue WebSocket feeds with gap detection and resync
- [ ] L2/L3 order book reconstruction
- [ ] Trade, funding, mark/index, OI, liquidation streams
- [ ] Instrument metadata polling with change events
- [ ] Bronze/silver/gold lake with immutable raw capture
- [ ] Bitemporal storage (`ts_event` + `ts_available`) on all slow data
- [ ] As-of joins everywhere; lookahead test in CI
- [ ] Survivorship-free universe snapshots
- [ ] Corporate action handling ★ (equities only)
- [ ] 15+ automated data quality checks with Prometheus export
- [ ] Feature drift monitoring (PSI)
- [ ] Clock sync with skew monitoring

### Research
- [ ] Event-driven backtester, same code as live
- [ ] Latency injection from measured distributions
- [ ] Full cost model: fees, spread, impact, funding, borrow, gas
- [ ] Queue-position-aware maker fill simulation
- [ ] Purged + embargoed CV; combinatorial (CPCV)
- [ ] Deflated Sharpe, PBO, Monte Carlo, synthetic-data control
- [ ] Walk-forward with re-fitting
- [ ] Parameter surface / plateau analysis
- [ ] Microstructure feature library (OFI, imbalance, Kyle λ, VPIN, microprice)
- [ ] Dollar/volume bars; fractional differentiation
- [ ] Triple-barrier labelling; meta-labelling; sample weights
- [ ] Model zoo tiers 0–4; calibration checks
- [ ] MLflow + DVC; manifest-reproducible runs; dirty-tree refusal

### Strategy & portfolio
- [ ] Strategy SDK emitting intents, not orders
- [ ] Multiple independent alphas with orthogonalization
- [ ] Covariance shrinkage (Ledoit-Wolf)
- [ ] HRP / risk parity / mean-variance / CVaR optimizers
- [ ] Fractional Kelly with haircut
- [ ] Volatility targeting
- [ ] Full constraint set incl. correlation-cluster caps
- [ ] No-trade bands
- [ ] Multi-strategy capital allocation
- [ ] Regime detection as a gate ★

### Risk
- [ ] 25+ pre-trade checks
- [ ] Separate risk process with veto power and fail-closed OMS
- [ ] Per-position stops resting at the venue
- [ ] VaR, CVaR, factor exposures, concentration
- [ ] Historical stress replays + correlation-to-1 + liquidity shock
- [ ] Tiered drawdown governor (automatic de-risk, approval to re-risk)
- [ ] Daily loss limit ladder
- [ ] 12 circuit breakers
- [ ] Reconciliation every 30s, halt on break, no auto-correct
- [ ] Cancel-on-disconnect + dead man's switch
- [ ] Sub-account isolation per strategy ★
- [ ] Full chaos test suite in CI

### Execution
- [ ] Explicit order state machine with illegal-transition alarms
- [ ] Deterministic idempotent client order IDs
- [ ] Outbox pattern for exactly-once effects
- [ ] `PENDING_NEW` / `UNKNOWN` resolution protocol
- [ ] Smart order router on total cost, not price
- [ ] Adaptive limit, TWAP, VWAP, POV, IS, iceberg algos
- [ ] Multi-bucket rate limiting with emergency reserve
- [ ] Full TCA with markouts and cost decomposition
- [ ] FIFO lot accounting with zero-residual PnL attribution

### Real-time visibility
- [ ] Read-only live gateway, bounded queues, never backpressures the bus
- [ ] Unified frame schema across hot loop and n8n
- [ ] Decision tape with trace pinning
- [ ] Animated pipeline view
- [ ] Live risk-check panel
- [ ] Book ladder with own-order markers
- [ ] Gap-fill on reconnect
- [ ] Time-travel replay through the same rendering path
- [ ] Mobile view + ambient display ★

### Control plane (n8n)
- [ ] Queue mode with separate webhook and worker processes
- [ ] Safety asymmetry enforced server-side in the control API
- [ ] HMAC + timestamp + nonce on every inbound webhook
- [ ] Payload-bound, short-lived, single-use approval tokens
- [ ] Two-person rule on the most dangerous endpoints
- [ ] Idempotency keys on all mutating calls
- [ ] 24 workflows across safety, approvals, ingestion, reporting, ops
- [ ] Workflow-as-code with CI validation (including "no direct venue calls")
- [ ] Custom Kairos node
- [ ] Default error workflow set
- [ ] Kill switch tested weekly by a synthetic run

### AI
- [ ] Structured extraction with typed schemas
- [ ] Model routing by job (Haiku/Sonnet/Opus)
- [ ] Batch API + prompt caching + pre-filtering
- [ ] Prompt injection defences and adversarial CI test
- [ ] Hard bound on LLM influence, enforced downstream
- [ ] Fail-to-null semantics
- [ ] Weekly LLM analyst producing testable hypotheses
- [ ] pgvector research memory ★

### Ops
- [ ] 5 environments with hard promotion gates
- [ ] Paper running permanently in parallel with prod
- [ ] Deploy blocked during drawdown; auto-rollback
- [ ] Risk limits in code, params via audited control API
- [ ] Verified backups; quarterly DR drill
- [ ] Egress allowlist; mTLS; no public ingress but the HMAC webhook
- [ ] Append-only audit log with object-lock
- [ ] Monthly key rotation; hardware MFA; withdrawal allowlists
- [ ] Production chaos experiments on a schedule
- [ ] Runbook per incident type
- [ ] A second person who can flatten your book

---

## 10.3 Failure modes: how these systems actually die

Ordered by how often they happen. Every one is survivable with a control listed in this plan;
the point of the table is that you should be able to name the control for each row.

| # | Failure | Root cause | Your defence |
|---|---|---|---|
| 1 | Backtest looked great, live loses | Overfitting; optimistic costs | CPCV, DSR, PBO, pessimistic cost model, paper-parallel |
| 2 | Lookahead bias | `ts_event` used instead of `ts_available` | Bitemporal storage, as-of joins, CI lookahead test |
| 3 | Costs ate the edge | Fees + spread + impact underestimated | Full cost model; TCA vs. backtest; cost-ratio metric |
| 4 | Runaway loop placed 10,000 orders | Missing rate limit; retry bug | Order-rate breakers, idempotent IDs, order-storm alert |
| 5 | Double-fill on retry | Non-idempotent order submission | Deterministic client IDs, outbox pattern |
| 6 | Traded on stale data | Silent WebSocket disconnect | Heartbeats, staleness breaker, default-closed |
| 7 | Position state wrong | Missed fill during reconnect | 30s reconciliation, halt on break, no auto-correct |
| 8 | Liquidated | Leverage + gap move + no stop | Venue-side stops, margin monitor, stress tests |
| 9 | Two instances running | Accidental double deploy | Distributed lock with heartbeat, chaos test |
| 10 | API key leaked | Committed, logged, or in a workflow | gitleaks in CI, log redaction, no-withdrawal keys, IP allowlist |
| 11 | Exchange failed | Insolvency, freeze, hack | Multi-venue, counterparty limits, withdraw profits regularly |
| 12 | Strategy decayed silently | Alpha crowded out | Rolling Sharpe monitor, decay alerts, weekly review |
| 13 | "Diversified" book was one trade | Correlations → 1 in stress | Cluster caps, correlation-breakdown stress test |
| 14 | Fat-finger config change | Manual edit at 3am | Limits in code, approval gates, param audit workflow |
| 15 | Deployed a bug into a drawdown | Panic-fixing while losing | Deploy blocked during drawdown; auto-rollback |
| 16 | Adverse selection on maker fills | Picked off by informed flow | Markout monitoring, toxicity filters, quote wider |
| 17 | Funding costs dominated PnL | Perp carry ignored | Funding in the cost model and in PnL attribution |
| 18 | Rate-limited while holding risk | No emergency reserve | 30% reserve for cancels and reduce-only |
| 19 | Backup didn't restore | Never tested | Weekly automated restore verification |
| 20 | Operator burnout | Watching it 24/7 manually | This entire control plane. Automate, then trust it. |

---

## 10.4 Ongoing cadence

Once live, the work changes shape. Put these in n8n so they happen without your memory being
involved:

**Daily** — read the morning brief and the overnight report; glance at the console; check
nothing is halted.
**Weekly** — review TCA and slippage trends; read the LLM postmortem; test the kill switch;
check live-vs-paper divergence.
**Monthly** — rotate keys; full strategy review against backtest expectations; capacity
re-estimate; cost review; dependency audit.
**Quarterly** — DR drill; re-validate every live strategy on the newest data (edges decay and
you want to find out from a test, not from PnL); review and update every risk limit; re-read
your own invariants document and check you still obey it.

---

## 10.5 Reading list

The short list, in the order that will help most.

**Essential**
- *Advances in Financial Machine Learning* — Marcos López de Prado. Purged CV, meta-labelling,
  triple-barrier, PBO, DSR. Phase 3 is largely an implementation of this book.
- *Trading and Exchanges* — Larry Harris. How markets actually work mechanically. The best
  single book on market microstructure for practitioners.
- *Algorithmic Trading* — Ernie Chan. Pragmatic, honest about what doesn't work.
- *Machine Learning for Asset Managers* — López de Prado. Shorter, denser, excellent on
  covariance estimation and clustering.

**Execution and microstructure**
- *Optimal Trading Strategies* — Kissell & Glantz. Impact models and TCA.
- Almgren & Chriss, "Optimal Execution of Portfolio Transactions" (2000). The IS algo.
- *Empirical Market Microstructure* — Hasbrouck.
- Easley, López de Prado & O'Hara on VPIN and order-flow toxicity.

**Risk and portfolio**
- *Active Portfolio Management* — Grinold & Kahn. The fundamental law; information ratio.
- *The Volatility Surface* — Gatheral ★ (options only).
- Thorp on Kelly sizing — and specifically on why you should use a fraction of it.

**Engineering**
- *Designing Data-Intensive Applications* — Kleppmann. The outbox pattern, exactly-once,
  event sourcing. Directly applicable to Phase 5.
- *Database Internals* — Petrov ★
- NautilusTrader's source. The best open-source reference for a production-grade
  event-driven trading architecture, and worth reading even if you build your own.

**Read with scepticism**
Anything promising a specific return. Anything selling a strategy — if it worked, it would be
traded, not sold. Most "AI trading" content. Backtests without cost assumptions stated
explicitly.

---

## 10.6 A final word on expectations

A realistic good outcome for a competent solo operator building this properly: a Sharpe
between 1 and 2 on a strategy with real capacity limits, needing continuous maintenance as
edges decay, with occasional drawdowns that will make you question the whole project.

That is a genuinely good outcome. It is also substantially less exciting than the version in
your head right now, and knowing that in advance is what will keep you building the
unglamorous parts — the reconciliation loop, the gap report, the approval tokens — that
actually determine whether you are still running in two years.

The plan is deliberately front-loaded with risk controls and measurement because those are
the parts that let you survive being wrong, and you will be wrong about the strategy several
times before you are right. Build the machine that lets you be wrong cheaply, and the rest
becomes a research problem instead of a gamble.
