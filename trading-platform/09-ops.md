# Phase 9 — Deployment, reliability, security (weeks 24–25)

**Gate:** you destroy the production environment deliberately and restore it from backups
inside your stated RTO, with no data loss beyond your stated RPO. You have done this at least
once, with a stopwatch, and written down what went wrong.

---

## 9.1 Environments

Five, with hard promotion gates. Each one is a real deployment of the same artifacts, not a
config flag.

| Env | Data | Orders | Capital | Purpose |
|---|---|---|---|---|
| `dev` | Recorded replay | Simulated | — | Fast iteration |
| `backtest` | Historical | Simulated | — | Research, CI golden tests |
| `paper` | **Live feed** | Simulated against the live book | — | Catches everything a backtest can't |
| `shadow` | **Live feed** | **Real orders, minimum size** | ~$100 | Proves the full plumbing end to end |
| `prod` | Live | Real | Ramped | The real thing |

**`shadow` is the environment people skip, and it is the one that finds the real bugs.** A
paper environment does not exercise authentication, rate limits, partial fills, venue quirks,
reject codes, or reconciliation. Running minimum-size real orders for two weeks costs you a
few dollars in fees and finds problems that would otherwise appear at full size.

Run `paper` and `prod` **simultaneously, forever**, on the same signals. The divergence
between them is your single best early-warning signal: when live starts underperforming paper
by more than your TCA explains, something has changed and you want to know that week, not
next quarter.

---

## 9.2 Deployment

Docker Compose until it genuinely hurts, then k3s. A single-node k3s cluster is a reasonable
middle ground: you get declarative deploys, health-checked rollouts, and secret management
without operating a real cluster.

### Deploy rules, enforced by `wf-deploy` (Phase 6, E2)

1. **Never deploy into a drawdown.** If current drawdown > 2%, the deploy is blocked. Fixing
   code while losing money is how you turn one problem into two.
2. **Never deploy with open positions above a threshold** unless the change is explicitly
   flagged as a hotfix. Flatten, deploy, re-enter.
3. **Rolling, health-checked, one service at a time.** The risk engine goes last, and the
   OMS refuses opening orders while it is restarting (fail closed — Phase 1, invariant #5).
4. **Automatic rollback** if error rate or drawdown rises within one hour of deploy.
5. **Deploy windows.** For anything but crypto, deploy outside market hours. For crypto,
   deploy during the lowest-volume hour of your week (measure it; usually weekend UTC
   mornings).
6. **Every deploy is announced** to the tape and the journal, with the commit range, so a
   later postmortem can correlate a behaviour change with a deploy.

### Configuration

- **Config is code.** Pydantic `BaseSettings` with strict validation; the process refuses to
  start on an invalid config rather than falling back to a default. A silent default is how
  you end up trading with `max_leverage=10` because you typo'd the key.
- **Risk limits live in code, not config.** The hard ceilings (max order notional, max
  drawdown halt, max leverage) should require a code change, a review, and a deploy. Anything
  editable at runtime will eventually be edited at 3am by someone who is losing money. That
  someone is you.
- **Runtime-tunable parameters** (strategy params, allocation weights) go through the control
  API, are versioned, audited, and diffed by `wf-param-change-audit`. Every change is
  attributable.
- **Feature flags** for new strategies and new code paths, so you can disable a misbehaving
  component without a deploy.

---

## 9.3 Reliability

### Failure domains and what you actually do about each

| Domain | Failure | Mitigation |
|---|---|---|
| Process | Strategy engine crashes | Systemd/k8s restart; state rebuilt from the event log; **resting venue stops protect the position meanwhile** |
| Process | Risk engine crashes | OMS fails closed: reduce-only orders accepted, opens rejected |
| Process | OMS crashes | Venue cancel-on-disconnect kills working orders; on restart, reconcile before anything else |
| Host | Server dies | Hot standby in a second region; DNS/health-check failover; **positions protected by venue-side stops, not by your software** |
| Network | Partition from venue | Dead man's switch at the venue cancels everything |
| Network | Partition from your own DB | Trade on in-memory state; queue writes; halt if the queue exceeds a bound |
| Venue | Exchange goes down | SOR routes to alternatives; halt the affected instruments |
| Venue | Exchange halts withdrawals | Counterparty-risk alert; this is the FTX scenario. Reduce exposure to that venue. |
| Data | Feed corrupted | Cross-venue validation catches it; blacklist and halt |
| Human | You make a mistake | Approval gates, two-person rule, idempotency, and the ability to replay what happened |

**The load-bearing insight:** your software's availability should not determine whether your
positions are protected. Resting reduce-only stop orders at the venue, plus cancel-on-disconnect,
plus a dead man's switch, mean a total loss of your infrastructure degrades to "flat or
stopped out" rather than "unmanaged leveraged position". Build those three things before you
build a hot standby.

### Hot standby, if you want one

Active-passive, with a distributed lock (Redis or etcd) as the arbiter. The passive node runs
everything *except* order placement, keeping warm state. Failover is: lock acquired → start
placing orders → reconcile with the venue first. **Never run active-active**; two instances
racing to manage one position is a reliably expensive bug, which is why Phase 4's chaos suite
tests for exactly that.

### Backups

| What | Frequency | Retention | RPO |
|---|---|---|---|
| Postgres (orders, audit, state) | Continuous WAL archiving + daily base | 90 days | <1 min |
| ClickHouse (ticks, TCA) | Daily incremental to S3 | 2 years | 24 h |
| Bronze lake | Immutable on write | Forever | 0 |
| n8n DB + `N8N_ENCRYPTION_KEY` | Daily, **key stored separately** | 90 days | 24 h |
| Vault | Daily snapshot, encrypted, offline copy of unseal keys | Forever | 24 h |
| Config and code | Git, mirrored to a second remote | Forever | 0 |

`wf-backup-verify` (Phase 6, E4) restores into a scratch environment weekly and checks
integrity. **An unverified backup is a rumour.**

### Disaster recovery targets

Write these down, then prove them with a drill:

- **RTO 15 minutes** to flat (you can always close positions from the exchange web UI — know
  the exact steps, write them in a runbook, and practise them)
- **RTO 2 hours** to trading again
- **RPO 1 minute** for order and position state
- **RPO 24 hours** for research data

Run a full drill quarterly: destroy the environment, restore from backup, reconcile against
the venue, resume paper trading. Time it. The first drill always fails somewhere; that is the
entire point of doing it before you need it.

---

## 9.4 Security

The threat model is specific: an attacker who gets in wants to move your money, and a system
that trades autonomously is an unusually attractive target.

### Keys and credentials

- **Withdrawal permission disabled on every exchange key.** This single setting converts
  "total loss" into "some trading losses". Do it before anything else.
- **IP allowlist every key.** Static IP on your server, or a NAT gateway.
- **Separate read-only and trade keys**; only the OMS process ever loads a trade key.
- **Rotate monthly** via `wf-key-rotation`, verifying the new key works before revoking the old.
- **Hardware MFA** on every exchange account and cloud console. A TOTP app on a phone that
  also receives your SMS is not two factors.
- **Withdrawal allowlists** at the exchange: even a manual withdrawal can only go to
  addresses you pre-registered, with a time delay. Set this up now, not after an incident.

### Infrastructure

- **mTLS between all internal services.** The control API in particular must not trust the
  network.
- **No public ingress** except the n8n webhook endpoint (HMAC-verified, rate-limited, behind
  a WAF). Everything else is on a VPN or Tailscale.
- **Audit log is append-only**, ideally to S3 with object-lock, so an attacker who gets in
  cannot erase what they did.
- **SSH: keys only**, no passwords, no root login, fail2ban, non-standard port.
- **Minimal container images**, non-root users, read-only filesystems where possible,
  dropped capabilities, no Docker socket mounts.
- **Egress allowlist.** Your trading host should be able to reach your venues, your data
  providers, and nothing else. This is the control that turns a code-execution bug into a
  non-event, and it is unusually cheap to implement.
- **Dependency scanning** weekly via `wf-dependency-audit`; pinned and hash-verified
  dependencies; review any new dependency that touches the order path as carefully as you
  would review your own code.

### Supply chain

A compromised Python package in your order path is a total loss. Pin everything with hashes
(`uv.lock`), use a private index mirror or vendored wheels for the hot path, generate an SBOM
per build, and set a policy: **no new dependency in the hot path without reading its source**.
The hot path should have a deliberately small dependency tree — that constraint is a security
control, not an aesthetic preference.

### The insider/compromise scenario

Assume an attacker has your n8n instance. What can they do? With the Phase 6 design:
halt, flatten, de-risk, blacklist — all *safe-direction* actions. They cannot resume, raise
limits, deploy, or place an order, because those need an approval token signed by a key n8n
never holds, bound to a specific payload, short-lived and single-use.

**That is the whole reason for the safety-asymmetry design.** Test it: take your n8n
credentials and try to increase risk with them. You should fail.

---

## 9.5 Chaos engineering in production

Scheduled, deliberate fault injection against `paper` weekly and `prod` monthly during low
volume. If you have never tested a failure, you do not know what it does.

```python
PRODUCTION_CHAOS = [
    Experiment("kill_strategy_engine",   "SIGKILL; assert state recovery and no orphan orders"),
    Experiment("kill_risk_engine",       "assert OMS fails closed within 1s"),
    Experiment("sever_venue_connection", "iptables DROP; assert dead man's switch fires"),
    Experiment("inject_500ms_latency",   "tc netem; assert algos adapt, no timeout cascade"),
    Experiment("freeze_market_data",     "assert staleness breaker halts in <30s"),
    Experiment("fill_the_disk",          "assert graceful degradation, not corruption"),
    Experiment("exhaust_rate_limit",     "assert emergency reserve still permits cancels"),
    Experiment("phantom_venue_position", "assert reconciliation halts, does not auto-correct"),
    Experiment("clock_jump_backward",    "assert no double-trigger, no negative durations"),
    Experiment("double_deploy",          "assert the distributed lock makes the second a no-op"),
    Experiment("n8n_total_outage",       "assert trading and critical paging are unaffected"),
    Experiment("llm_provider_outage",    "assert strategies trade on with null LLM features"),
]
```

Run them from n8n on a schedule so they cannot be quietly forgotten, and alert if an
experiment has not run in 30 days. The `n8n_total_outage` experiment is the one that keeps
the two-loop rule honest over time — it will catch the day someone makes the control plane
load-bearing.

---

**Gate check:** full DR drill completed and timed, with the failures written up. Production
chaos suite green. An attempt to raise risk limits using only n8n's credentials fails. Egress
allowlist is on and you've confirmed nothing broke.
