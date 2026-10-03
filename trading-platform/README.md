# Kairos — build plan for a professional-grade algorithmic trading platform

A complete, ordered build plan for a multi-venue, multi-strategy automated trading system
with **n8n as its control plane** and a **real-time console** you can watch it think in.
Rename `kairos` to whatever you like; it is used throughout as the service prefix.

This is a greenfield design. It does not reuse or depend on any existing code in this
repository.

---

## Read this before anything else

Four things are true, and the plan is shaped by all four.

1. **Code is the easy part.** A system like this is maybe 25% engineering. The other 75% is
   finding an edge that survives costs, and not blowing up while you look for it. The build
   order below is deliberately *risk-and-measurement first, alpha second* — because a
   mediocre strategy with excellent risk control survives to be improved, and a brilliant
   strategy with bad risk control dies once.

2. **n8n must never be in the trading hot path.** This is the single most important
   architectural decision in this document. n8n is a general workflow engine: it runs on
   Node, queues jobs through Redis, and has execution latencies in the tens-to-hundreds of
   milliseconds with no hard guarantees. It is superb at the *slow loop* — research
   ingestion, alerting, approvals, reporting, retraining, ops automation, human-in-the-loop
   gates. It is the wrong tool for anything measured in microseconds or anything that must
   be deterministic and replayable. So:

   > **The two-loop rule.** The *hot loop* (market data → features → signal → risk → order)
   > is compiled, typed, in-process, and has zero network hops it does not need. The
   > *control loop* (everything else) is n8n. They communicate over one narrow, versioned,
   > authenticated API and an event bus. n8n can always make the system *safer* without
   > asking; it can never make it *riskier* without a signed human approval.

3. **Backtest overfitting is the default outcome, not a risk.** If you run enough
   parameter sweeps you will find something that looks wonderful and is noise. Phase 3
   spends serious effort on purged cross-validation, deflated Sharpe, and probability of
   backtest overfitting specifically because the naive version of this step is what kills
   most projects — silently, with a beautiful equity curve.

4. **Most of these systems lose money.** Not because the code is bad, but because
   after fees, slippage, financing and adverse selection, the edge wasn't there. Plan the
   ramp in Phase 10 as if you expect to fail the criteria, because that's the modal
   outcome, and the ramp is what makes failure cheap.

Nothing in this plan requires a licence for trading your own capital on your own account.
The moment you take outside money, or trade on anyone else's behalf, you are in regulated
territory in essentially every jurisdiction — that is a lawyer conversation, not an
engineering one, and it comes before the first external dollar, not after.

---

## Architecture

```
                         ┌───────────────── CONTROL LOOP (n8n) ──────────────────┐
                         │  research ingest · alerting · approvals · reporting   │
                         │  retraining · deployments · ops runbooks · audit      │
                         └───────┬──────────────────────────────────┬────────────┘
                                 │ scoped JWT, HMAC, idempotent     │ subscribes
                                 ▼                                  │
  ┌──────────────────────────────────────────────────────────────────┴───────────┐
  │                       kairos-control (FastAPI, gRPC)                         │
  │   the ONLY door into the hot loop · every call audited · safety asymmetry    │
  └──────┬──────────────────────┬───────────────────┬──────────────────┬─────────┘
         │                      │                   │                  │
  ┌──────▼──────┐   ┌───────────▼────────┐   ┌──────▼───────┐   ┌──────▼───────┐
  │ feedhandler │──▶│  strategy engine   │──▶│ risk engine  │──▶│ OMS / EMS    │
  │ per venue   │   │  alpha→signal→pf   │   │ VETO POWER   │   │ SOR + algos  │
  │ WS, L2/L3   │   │                    │   │ own process  │   │ idempotent   │
  └──────┬──────┘   └───────────┬────────┘   └──────┬───────┘   └──────┬───────┘
         │                      │                   │                  │
         └──────────────────────┴───────────────────┴──────────────────┘
                                 │  NATS / Redpanda event bus (all state transitions)
         ┌───────────────────────┼───────────────────────┬──────────────────┐
         ▼                       ▼                       ▼                  ▼
   ClickHouse            Postgres (state,          Redis (hot cache,    S3/MinIO
   (ticks, L2, TCA)       orders, audit)            rate limits)        (parquet lake)
         │                       │
         └───────────────┬───────┘
                         ▼
        Prometheus · Grafana · Loki · Tempo · Alertmanager ──▶ n8n (incidents)

  ┌───────────────────────────────────────────────────────────────────────────┐
  │  live-gateway (read-only) ──WebSocket──▶ the console: decision tape,      │
  │  animated pipeline, live risk checks, n8n node runs — one timeline,       │
  │  plus time-travel replay of any past window. See 07-realtime.md.          │
  └───────────────────────────────────────────────────────────────────────────┘
```

**Why the risk engine is its own process:** it must be able to kill the strategy engine. A
risk check that lives inside the thing it polices dies with it. Risk runs separately, holds
the exchange-side kill switch, and is the component you test most aggressively.

---

## Decisions to make before you write a line of code

Write your answers down. Every later phase depends on them, and changing them at week 14 is
expensive.

| # | Decision | Options | How to choose |
|---|---|---|---|
| 1 | **Asset class** | Crypto spot · crypto perps · equities · futures · FX · options | Crypto perps: best API access, 24/7, free data, high leverage, worst counterparty risk. Equities: cleanest regulation, hardest data (corporate actions, survivorship), market hours. **Start with one.** |
| 2 | **Latency class** | Ultra-LF (daily) · LF (minutes–hours) · MF (seconds) · HF (sub-ms) | This decides your whole stack. HF needs colo, kernel bypass, C++/Rust, and a seven-figure budget to be competitive. **Pick MF or LF unless you have that.** Everything below assumes MF/LF; the HF deltas are flagged. |
| 3 | **Strategy family** | Trend/momentum · stat-arb/mean-reversion · market making · basis/funding carry · event-driven · vol/options | Carry and basis are the most robust for crypto and the easiest to validate. Market making is highest Sharpe and hardest — it is an inventory and adverse-selection problem, not a prediction problem. |
| 4 | **Venues** | 1 to start, 3+ by Phase 6 | Multi-venue is where real edge lives (basis, funding spread, SOR), but each venue is ~2 weeks of integration and a permanent maintenance tax. |
| 5 | **Capital & risk budget** | — | Write the number you can lose entirely without changing your life, then the max daily loss (suggest 2%), max drawdown before full stop (suggest 15%), and target vol. These become hard-coded constants in Phase 5. |
| 6 | **Hot-path language** | Python+uvloop · Go · Rust · C++ | Python is fine to ~100ms budgets and gets you the whole scientific stack. Rust for the feedhandler and OMS when you outgrow it. Recommendation: **Python for research and strategy, Rust for feedhandler + OMS from Phase 6**, which is also exactly what NautilusTrader gives you if you'd rather not write it. |
| 7 | **Build vs. adopt the backbone** | From scratch · NautilusTrader · Lean · Hummingbot | Adopt **NautilusTrader** unless you have a specific reason not to: Rust core, Python API, event-driven, the same code runs backtest and live (which eliminates an entire class of bugs). Writing your own backbone costs ~3 months and buys you very little. This plan is written so it works either way. |

---

## Stack

| Layer | Choice | Why this one |
|---|---|---|
| Hot-path runtime | Python 3.12 + uvloop, or NautilusTrader | Same code backtest/live |
| Feedhandler | Rust (`tokio` + `tungstenite`), or Nautilus adapters | WS handling under load |
| Tick/analytics store | **ClickHouse** | Columnar, absurd scan speed, cheap. QuestDB if you prefer a time-series-native API; TimescaleDB if you want one less database |
| Transactional state | **Postgres 16** | Orders, positions, audit, n8n backend |
| Cache / locks / rate limits | **Redis 7** | Also n8n's queue |
| Event bus | **NATS JetStream** (simple) or **Redpanda** (Kafka API, replay) | Redpanda if you want event-sourced replay of production, which you will want |
| Data lake | **MinIO** → S3, Parquet, medallion layout | Cheap history, reproducible research |
| Orchestration (control loop) | **n8n** (queue mode) | The subject of Phase 6 |
| Batch/DAG orchestration | **Dagster** (or Prefect) | Data pipelines with lineage — n8n is the wrong tool for a 40-step DAG with backfills |
| Feature store | **Feast**, or a Postgres/ClickHouse table with strict as-of joins | Point-in-time correctness is the whole point |
| ML | LightGBM, PyTorch, scikit-learn, `river` (online) | |
| Experiments | **MLflow** + **DVC** | Every backtest reproducible from a commit hash |
| Observability | **Prometheus + Grafana + Loki + Tempo + Alertmanager** | |
| Secrets | **HashiCorp Vault** (or SOPS+age for solo) | n8n never holds an exchange key |
| Deploy | Docker Compose → **k3s** | Compose until it hurts |
| CI | GitHub Actions | |
| LLM layer | **Claude API** — `claude-opus-5-5`, with `claude-haiku-4-5` for bulk | Phase 8 |

---

## Build order and timeline

Realistic for one strong engineer working full time. Double it if part time. The phases are
ordered by dependency, and the gates are hard — do not start a phase before its gate passes.

| Phase | Weeks | Deliverable | Gate to pass before moving on |
|---|---|---|---|
| **1 Foundation** | 1–2 | Repo, compose stack, CI, observability, secrets | `make up` gives you a green Grafana and a passing CI run |
| **2 Data** | 3–5 | Feedhandlers, normalized schema, lake, quality monitors | 30 days of tick data with a documented gap report and zero silent gaps |
| **3 Research** | 6–9 | Event-driven backtester, cost model, CPCV harness | Backtest of a *known-bad* strategy correctly shows it as bad after costs |
| **4 Strategy & risk** | 10–13 | Strategy SDK, portfolio construction, risk engine | Risk engine kills a deliberately runaway strategy in chaos tests, every time |
| **5 Execution** | 14–16 | OMS/EMS, SOR, algos, TCA | Paper fills reconcile to the cent; TCA reports slippage vs. arrival |
| **6 n8n control plane** | 17–19 | 24 workflows, HITL approvals, workflow-as-code | Kill switch from your phone halts live trading in under 5 seconds |
| **7 Real-time visibility** | 20–21 | Live decision tape, animated pipeline, replay | Watch a decision's full causal chain live, then replay it at 10× |
| **8 AI layer** | 22–23 | News/filings pipeline, LLM postmortems, guardrails | LLM output cannot move position size beyond its capped bound |
| **9 Ops & security** | 24–25 | k3s, DR drill, chaos suite, key hygiene | Full restore from backup inside your stated RTO |
| **10 Go live** | 26+ | Shadow → pilot → ramp | 4 weeks paper with live-vs-backtest divergence under threshold |

**Running cost**, roughly, for a single-box MF crypto setup: $40–80/mo VPS near your venue
(Tokyo for Binance, Ashburn for CME), $0–200/mo data, $20–100/mo LLM, $10/mo object storage.
Call it **$100–400/month**. Equities market data is the thing that explodes this — a real
L2 feed is $500–5,000/mo.

---

## The phase documents

| File | Contents |
|---|---|
| [`01-foundation.md`](01-foundation.md) | Non-negotiables, repo layout, Docker stack, observability, secrets, CI |
| [`02-data.md`](02-data.md) | Feedhandlers, normalization, the lake, point-in-time correctness, quality monitors |
| [`03-research.md`](03-research.md) | Backtester, cost/impact models, CPCV, deflated Sharpe, PBO, feature and model zoo |
| [`04-strategy-risk.md`](04-strategy-risk.md) | Strategy SDK, alpha combination, portfolio construction, and the full risk engine |
| [`05-execution.md`](05-execution.md) | OMS state machine, idempotency, SOR, execution algos, rate limiting, TCA |
| [`06-n8n.md`](06-n8n.md) | **The control plane**: queue-mode n8n, the security model, all 24 workflows, workflow-as-code |
| [`07-realtime.md`](07-realtime.md) | **Watching it work live**: the decision tape, animated pipeline, n8n runs on the same timeline, time-travel replay |
| [`08-ai.md`](08-ai.md) | Claude integration, structured extraction, LLM postmortems, hard guardrails |
| [`09-ops.md`](09-ops.md) | Deployment, reliability, chaos engineering, DR, security hardening |
| [`10-golive.md`](10-golive.md) | Shadow→live ramp, master feature checklist, failure-mode table, reading list |

Work them in order. Each one ends with its own gate.
