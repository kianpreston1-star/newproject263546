# Phase 1 — Foundation (weeks 1–2)

**Gate:** `make up` brings the whole stack live, Grafana shows a dashboard with real metrics
from a dummy service, CI passes on a pull request, and no secret exists in the repo.

---

## 1.0 The non-negotiables

Write these into `docs/INVARIANTS.md` on day one and treat violations as build failures.
Every one of them exists because its absence has destroyed a real trading system.

1. **The same code computes signals in backtest and live.** Not "equivalent code". The
   same functions, same module. If a backtest path and a live path can diverge, they will,
   and you will find out with money on the line.
2. **No lookahead, ever.** Every feature is a function of data that had *arrived* by the
   decision timestamp — not data that was *stamped* before it. These differ, and the
   difference is the single most common source of fake alpha.
3. **Every order has a deterministic, idempotent client ID** derived from
   `(strategy, instrument, intent_hash, bar_timestamp)`. Retries must never double-fill.
4. **Risk can veto anything and runs in its own process.**
5. **Default-closed.** Any unknown state — stale feed, failed reconciliation, unparseable
   response, clock skew — results in *no new risk*. Flattening is always allowed; opening
   never is.
6. **Everything is an append-only event.** Positions and PnL are projections over the event
   log, never the source of truth. You must be able to replay any trading day exactly.
7. **No secret in the repo, ever, including in n8n workflow JSON.**
8. **n8n is never in the hot path** (see the two-loop rule in the README).
9. **Wall-clock is not a source of truth.** Every event carries venue timestamp, local
   receive timestamp, and the measured offset. Alert on skew above 250 ms.
10. **Nothing goes live without a kill switch you have personally tested that week.**

---

## 1.1 Repository

```bash
mkdir kairos && cd kairos && git init
```

```
kairos/
├── Makefile
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example                    # committed; .env is NOT
├── pyproject.toml                  # uv-managed workspace
├── docs/
│   ├── INVARIANTS.md
│   ├── runbooks/                   # one markdown file per incident type
│   └── adr/                        # architecture decision records, numbered
├── libs/
│   ├── kairos-core/                # domain types: Instrument, Order, Fill, Position
│   ├── kairos-bus/                 # NATS/Redpanda publish+subscribe wrappers
│   ├── kairos-store/               # ClickHouse + Postgres + S3 access
│   └── kairos-contracts/           # pydantic models + JSON Schema, versioned
├── services/
│   ├── feedhandler/                # one process per venue
│   ├── strategy-engine/
│   ├── risk-engine/                # separate process. always.
│   ├── oms/
│   ├── control-api/                # the only door n8n may knock on
│   └── reconciler/
├── research/
│   ├── notebooks/                  # exploration only; nothing production imports these
│   ├── backtest/
│   ├── features/
│   └── experiments/                # MLflow-tracked, DVC-versioned
├── strategies/
│   ├── _template/
│   └── <your-strategies>/
├── n8n/
│   ├── workflows/                  # exported JSON, credential-stripped, in git
│   ├── nodes/                      # custom nodes for the control API
│   └── README.md
├── infra/
│   ├── grafana/{dashboards,provisioning}/
│   ├── prometheus/
│   ├── clickhouse/{init,config}/
│   ├── alertmanager/
│   └── k3s/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── chaos/                      # Phase 4 and 9 live here
│   └── golden/                     # recorded market data replays with expected outputs
└── scripts/
```

**Why `libs/` and `services/` are separate:** the libraries are importable, tested, and
versioned; the services are deployable and own no domain logic. When you later rewrite the
feedhandler in Rust, nothing else changes.

### Toolchain

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh    # uv: the only Python tool you need
uv init --package libs/kairos-core
uv add --dev pytest pytest-asyncio pytest-cov hypothesis ruff mypy pre-commit
```

`pyproject.toml` — the strictness here is not optional. In a system where a `None` reaching
an order-size calculation costs real money, the type checker is a risk control.

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E","F","I","N","UP","B","A","C4","DTZ","T20","PT","RET","SIM","ARG","PTH","ERA","PL","RUF"]
# DTZ matters most: it bans naive datetimes. Every timestamp in this system is tz-aware UTC.

[tool.mypy]
strict = true
warn_unreachable = true
disallow_any_explicit = true

[tool.pytest.ini_options]
addopts = "-q --strict-markers --cov=libs --cov=services --cov-fail-under=80"
markers = ["integration: needs the docker stack", "chaos: fault injection", "slow"]
```

```bash
pre-commit install
```

`.pre-commit-config.yaml` must include `detect-secrets` or `gitleaks`. A leaked exchange key
is a total loss event, and it happens through commits far more often than through breaches.

---

## 1.2 The development stack

`docker-compose.yml`:

```yaml
name: kairos

x-logging: &logging
  logging:
    driver: json-file
    options: { max-size: "50m", max-file: "3" }

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: kairos
    command: >
      postgres -c max_connections=200 -c shared_buffers=512MB
               -c wal_level=logical -c max_wal_size=2GB
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./infra/postgres/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 10
    ports: ["5432:5432"]
    <<: *logging

  clickhouse:
    image: clickhouse/clickhouse-server:24.8-alpine
    environment:
      CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD}
      CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT: 1
    volumes:
      - chdata:/var/lib/clickhouse
      - ./infra/clickhouse/init:/docker-entrypoint-initdb.d:ro
    ulimits:
      nofile: { soft: 262144, hard: 262144 }
    ports: ["8123:8123", "9000:9000"]
    <<: *logging

  redis:
    image: redis:7-alpine
    command: >
      redis-server --requirepass ${REDIS_PASSWORD}
                   --appendonly yes --appendfsync everysec
                   --maxmemory 2gb --maxmemory-policy noeviction
    volumes: [redisdata:/data]
    ports: ["6379:6379"]
    <<: *logging
    # noeviction is deliberate: silently dropping a rate-limit token or an idempotency
    # key under memory pressure is far worse than an error you can see.

  nats:
    image: nats:2.10-alpine
    command: >
      -js -sd /data -m 8222
      --max_payload 8MB
    volumes: [natsdata:/data]
    ports: ["4222:4222", "8222:8222"]
    <<: *logging

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    volumes: [miniodata:/data]
    ports: ["9000:9000", "9001:9001"]
    <<: *logging

  prometheus:
    image: prom/prometheus:latest
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.retention.time=90d
      - --web.enable-lifecycle
    volumes:
      - ./infra/prometheus:/etc/prometheus:ro
      - promdata:/prometheus
    ports: ["9090:9090"]
    <<: *logging

  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
      GF_INSTALL_PLUGINS: grafana-clickhouse-datasource
      GF_USERS_DEFAULT_THEME: dark
    volumes:
      - ./infra/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./infra/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafanadata:/var/lib/grafana
    ports: ["3000:3000"]
    <<: *logging

  loki:
    image: grafana/loki:latest
    volumes: [lokidata:/loki]
    ports: ["3100:3100"]
    <<: *logging

  tempo:
    image: grafana/tempo:latest
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./infra/tempo/tempo.yaml:/etc/tempo.yaml:ro
      - tempodata:/var/tempo
    <<: *logging

  alertmanager:
    image: prom/alertmanager:latest
    volumes: [./infra/alertmanager:/etc/alertmanager:ro]
    ports: ["9093:9093"]
    <<: *logging

  vault:
    image: hashicorp/vault:latest
    cap_add: [IPC_LOCK]
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: ${VAULT_DEV_TOKEN}   # dev mode ONLY
    ports: ["8200:8200"]
    <<: *logging

volumes:
  pgdata: {}; chdata: {}; redisdata: {}; natsdata: {}; miniodata: {}
  promdata: {}; grafanadata: {}; lokidata: {}; tempodata: {}
```

n8n's own services are added in Phase 6, in `docker-compose.n8n.yml`, so you can restart the
control plane without touching the trading stack — and vice versa, which matters more.

`Makefile`:

```make
.PHONY: up down logs ps test lint fmt typecheck migrate backtest replay chaos
up:        ; docker compose --env-file .env up -d
down:      ; docker compose down
logs:      ; docker compose logs -f --tail=200
test:      ; uv run pytest -m "not integration and not chaos"
test-all:  ; uv run pytest
lint:      ; uv run ruff check . && uv run ruff format --check .
fmt:       ; uv run ruff check --fix . && uv run ruff format .
typecheck: ; uv run mypy libs services
migrate:   ; uv run alembic upgrade head
chaos:     ; uv run pytest -m chaos -v
check:     ; $(MAKE) lint typecheck test
```

---

## 1.3 Observability — build this *before* the trading logic

This is the step people skip, and it is the reason they later cannot answer "why did it do
that?" You are building a system that acts autonomously with money. If you cannot see it,
you do not control it.

### Metrics taxonomy

Instrument these from day one. Use a `kairos_` prefix and keep cardinality sane (never label
by order ID).

```python
# libs/kairos-core/kairos_core/metrics.py
from prometheus_client import Counter, Gauge, Histogram

# --- data health -------------------------------------------------------------
TICKS = Counter("kairos_ticks_total", "ticks received", ["venue", "symbol", "kind"])
FEED_LAG = Histogram("kairos_feed_lag_seconds", "venue ts -> local recv",
                     ["venue"], buckets=(.001,.005,.01,.05,.1,.5,1,5,30))
FEED_STALE = Gauge("kairos_feed_staleness_seconds", "age of last tick", ["venue","symbol"])
CLOCK_SKEW = Gauge("kairos_clock_skew_seconds", "local vs venue clock", ["venue"])
BOOK_CROSSED = Counter("kairos_book_crossed_total", "bid>=ask observed", ["venue","symbol"])
GAPS = Counter("kairos_sequence_gaps_total", "dropped sequence numbers", ["venue","symbol"])

# --- decision loop -----------------------------------------------------------
LOOP = Histogram("kairos_loop_seconds", "tick->decision", ["strategy"],
                 buckets=(.0001,.001,.01,.05,.1,.5,1,5))
SIGNAL = Gauge("kairos_signal", "raw alpha signal", ["strategy","symbol"])
TARGET = Gauge("kairos_target_weight", "desired portfolio weight", ["strategy","symbol"])

# --- risk --------------------------------------------------------------------
RISK_VETO = Counter("kairos_risk_veto_total", "orders blocked", ["rule","strategy"])
DRAWDOWN = Gauge("kairos_drawdown_pct", "from peak equity", ["scope"])
GROSS = Gauge("kairos_gross_exposure_pct", "gross/equity")
NET = Gauge("kairos_net_exposure_pct", "net/equity")
VAR = Gauge("kairos_var_pct", "1d parametric VaR", ["confidence"])
HALTED = Gauge("kairos_halted", "1 = trading halted", ["reason"])
MARGIN_RATIO = Gauge("kairos_margin_ratio", "used/available margin", ["venue"])

# --- execution ---------------------------------------------------------------
ORDERS = Counter("kairos_orders_total", "", ["venue","side","type","outcome"])
ACK_LATENCY = Histogram("kairos_ack_latency_seconds", "send->ack", ["venue"],
                        buckets=(.005,.01,.025,.05,.1,.25,.5,1,5))
SLIPPAGE_BPS = Histogram("kairos_slippage_bps", "fill vs arrival price", ["venue","algo"],
                         buckets=(-50,-20,-10,-5,-2,0,2,5,10,20,50,200))
FILL_RATIO = Gauge("kairos_fill_ratio", "filled/sent qty", ["venue","algo"])
REJECTS = Counter("kairos_rejects_total", "", ["venue","code"])
RATE_LIMIT_USED = Gauge("kairos_rate_limit_used_pct", "", ["venue","bucket"])

# --- money -------------------------------------------------------------------
EQUITY = Gauge("kairos_equity_usd", "", ["venue"])
PNL = Gauge("kairos_pnl_usd", "", ["strategy","kind"])     # kind: realized|unrealized|fees|funding
POSITION = Gauge("kairos_position_units", "", ["strategy","symbol"])
RECON_BREAK = Gauge("kairos_reconciliation_break_usd", "|internal - venue|", ["venue","symbol"])
```

### Alerts that actually matter

`infra/prometheus/rules/trading.yml` — tier them. Page for the first group, Slack the rest.

```yaml
groups:
  - name: kairos-critical          # wake you up at 4am
    rules:
      - alert: TradingHalted
        expr: kairos_halted == 1
        for: 0m
        labels: { severity: critical }
      - alert: ReconciliationBreak
        expr: kairos_reconciliation_break_usd > 50
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "Internal position disagrees with {{ $labels.venue }} by ${{ $value }}"
          runbook: docs/runbooks/reconciliation-break.md
      - alert: DrawdownBreach
        expr: kairos_drawdown_pct > 10
        for: 1m
        labels: { severity: critical }
      - alert: FeedDead
        expr: kairos_feed_staleness_seconds > 30
        for: 30s
        labels: { severity: critical }
      - alert: MarginDanger
        expr: kairos_margin_ratio > 0.70
        for: 1m
        labels: { severity: critical }
      - alert: OrderStorm          # the classic runaway-loop signature
        expr: rate(kairos_orders_total[1m]) > 60
        for: 1m
        labels: { severity: critical }

  - name: kairos-warning
    rules:
      - alert: ClockSkew
        expr: abs(kairos_clock_skew_seconds) > 0.25
        for: 5m
      - alert: SlippageDegraded    # your edge leaking away through execution
        expr: histogram_quantile(0.5, rate(kairos_slippage_bps_bucket[1h])) > 8
        for: 15m
      - alert: RejectRateHigh
        expr: rate(kairos_rejects_total[5m]) / rate(kairos_orders_total[5m]) > 0.05
        for: 5m
      - alert: RateLimitPressure
        expr: kairos_rate_limit_used_pct > 80
        for: 2m
      - alert: SequenceGaps
        expr: rate(kairos_sequence_gaps_total[5m]) > 0
        for: 5m
```

Route Alertmanager → n8n webhook (Phase 6), and n8n decides whether to page, auto-remediate,
or de-risk. Alertmanager also goes **directly** to your phone for the critical group, with
n8n bypassed entirely — never make your paging path depend on a component that can be down.

### Structured logging and tracing

Every log line is JSON with `trace_id`, `strategy`, `symbol`, `event`. Use
`structlog` + OpenTelemetry; propagate the trace ID from tick receipt through to venue ack,
so one Tempo trace shows you the full life of a decision. When you ask "why did it buy at
09:31:02", this is the answer, in one click.

### Grafana dashboards to provision

1. **Battle station** — equity curve, drawdown, position map, halted flag, feed health, PnL
   by strategy. This is the one you keep open.
2. **Execution quality** — slippage distribution, fill ratios, ack latency per venue, reject
   codes, rate-limit headroom.
3. **Data health** — staleness, gaps, crossed books, clock skew, tick rates per venue.
4. **Risk** — VaR, gross/net, factor exposures, correlation heatmap, margin ratios.
5. **Strategy detail** — one row per strategy: signal, target vs. actual, turnover, hit rate.

---

## 1.4 Secrets

```
Vault
├── kairos/venues/binance/{read,trade}      # separate keys per permission level
├── kairos/venues/bybit/{read,trade}
├── kairos/databases/*
├── kairos/llm/anthropic
└── kairos/n8n/control-api-token            # scoped. NOT an exchange key.
```

Rules:

- **Withdrawal permission is disabled on every exchange key. No exceptions.** If a key
  cannot withdraw, a full compromise costs you trading losses, not your balance.
- **IP-allowlist every key** to your server's static address.
- **Separate read-only and trade keys.** Research, dashboards, and reconciliation use
  read-only. Only the OMS process ever loads a trade key.
- **n8n never receives an exchange key.** It gets a JWT for the control API, scoped to
  specific endpoints, rotated weekly. This is the whole reason the control API exists.
- Services fetch secrets at startup via Vault AppRole, keep them in memory, never write them
  to disk or logs. Add a log filter that redacts anything matching key patterns.

For a solo operator, `sops` + `age` with the key on a hardware token is an acceptable
simpler substitute — the discipline matters more than the tool.

---

## 1.5 CI

`.github/workflows/ci.yml` — fast on every push, heavier nightly.

```yaml
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: uv run ruff check . && uv run ruff format --check .
      - run: uv run mypy libs services
      - run: uv run pytest -m "not integration and not chaos" --cov-fail-under=80
      - uses: gitleaks/gitleaks-action@v2        # blocks the leaked-key failure mode

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose up -d --wait
      - run: uv run pytest -m integration
      - run: uv run pytest tests/golden -v        # replay recorded data, assert outputs

  n8n-workflows:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/validate_n8n_workflows.py n8n/workflows/
        # asserts: no embedded credentials, every workflow has an error workflow set,
        # every HTTP node targets an allowlisted host, every webhook verifies HMAC
```

The `golden` test suite is your most valuable regression net: recorded market data in,
expected signals and orders out, byte-identical. It catches the "harmless refactor" that
silently changes a signal by 0.3%.

---

**Gate check:** `make up && make check` is green. Grafana renders the battle station from a
dummy publisher. A deliberately committed fake API key is rejected by CI. You can answer
"what is the p99 feed lag right now?" from a dashboard.
