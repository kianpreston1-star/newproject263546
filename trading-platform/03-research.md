# Phase 3 — Research & backtesting (weeks 6–9)

**Gate:** your backtester, fed a strategy you *know* is unprofitable (e.g. buy every bar,
hold one bar, pay full taker fees), reports it as unprofitable with the right magnitude. And
your validation harness, fed pure random noise, reports no significant edge — if it finds
alpha in noise, it will find alpha in anything.

This phase is where most projects quietly fail. Not loudly — they produce a great-looking
result and the failure only shows up months later in live PnL. Everything here is designed to
make overfitting *visible*.

---

## 3.1 Event-driven, not vectorized

Vectorized backtests (`df['signal'].shift(1) * df['returns']`) are fast and lie to you. They
cannot represent partial fills, queue position, rejections, latency, margin calls, or an
order that was still working when the next signal arrived. Use them for a 10-minute first
look at whether an idea is worth a day of work, and never for a go/no-go decision.

The real backtester is a single-threaded event loop over a merged, time-ordered stream:

```python
# research/backtest/engine.py
class BacktestEngine:
    """
    One rule governs everything: at simulated time t, the strategy may only see
    events whose ts_recv <= t. The event queue enforces this structurally, so
    lookahead is impossible rather than merely discouraged.
    """
    def run(self) -> BacktestResult:
        while (event := self.queue.pop()) is not None:
            self.clock.set(event.ts_recv_ns)

            match event:
                case MarketEvent():
                    self.book.apply(event)
                    # Fills are resolved BEFORE new signals. A real exchange does not
                    # wait for your next thought.
                    for fill in self.matcher.match(event, self.working_orders):
                        self.portfolio.apply(fill)
                        self.strategy.on_fill(fill)
                    for order in self.strategy.on_market(event) or []:
                        self._submit(order)

                case OrderAckEvent() | OrderRejectEvent():
                    self.strategy.on_order_update(event)

                case FundingEvent():
                    self.portfolio.apply_funding(event)   # perps: this is real money

                case TimerEvent():
                    for order in self.strategy.on_timer(event) or []:
                        self._submit(order)

            self.portfolio.mark(self.book)
            if veto := self.risk.check(self.portfolio):      # the SAME risk engine as live
                self._handle_veto(veto)
            self.recorder.snapshot(self.clock.now(), self.portfolio)

        return self.recorder.result()

    def _submit(self, order: Order) -> None:
        # Latency injection: the order does not exist at the venue until now + latency.
        delay = self.latency_model.sample(order)
        self.queue.push(OrderArrivalEvent(order, self.clock.now_ns() + delay))
```

Three details carry most of the realism:

1. **Fills resolve before new signals.** Getting this backwards lets the strategy react to
   information from a fill that hadn't happened yet.
2. **Orders arrive in the future.** Submitting at `t` means the venue sees it at
   `t + latency`. Sample latency from your *measured* live distribution, including the tail.
3. **Risk runs the same code as production.** If the backtest and live risk engines are
   different implementations, your backtest is testing a system you will never run.

---

## 3.2 The cost model — where most "alpha" dies

Be pessimistic. If a strategy only works under optimistic cost assumptions, it does not work.

```python
@dataclass
class CostModel:
    maker_fee_bps: Decimal
    taker_fee_bps: Decimal
    funding: bool = True              # perps
    borrow_bps_annual: Decimal = 0    # shorting equities

    def fill_price(self, order: Order, book: Book, participation: Decimal) -> Decimal:
        """Total cost = fee + spread crossed + impact + delay. Model all four."""
        half_spread = (book.ask - book.bid) / 2

        # Temporary impact, square-root law (Almgren): cost ~ sigma * sqrt(Q / ADV).
        # Calibrate the coefficient from your own fills in Phase 5 — until then use 1.0,
        # which is conservative-to-realistic for liquid crypto.
        sigma = book.realized_vol_1m
        impact = self.impact_coef * sigma * (order.qty / book.adv_1m).sqrt()

        # Permanent impact: a fraction of temporary, which does not decay.
        permanent = Decimal("0.3") * impact

        direction = 1 if order.side == "buy" else -1
        return book.mid * (1 + direction * (half_spread / book.mid + impact + permanent))
```

### Market-order (taker) costs
Fee + half-spread + impact. The easy case. If your edge per trade is smaller than
`taker_fee + half_spread`, you have no strategy — check this on the back of an envelope
before writing any code.

### Limit-order (maker) fills — model queue position
This is where naive backtests inflate returns by 2–5x. "My limit order at the bid filled
because price touched the bid" is false. You are behind everyone who was already there.

```python
def maker_fill_prob(self, order, book, trades_at_level) -> Decimal:
    ahead = book.size_at(order.price)                   # queue ahead of you at entry
    consumed = trades_at_level                          # volume that traded at your level
    if consumed <= ahead:
        return Decimal(0)                               # the queue absorbed it all
    return min(Decimal(1), (consumed - ahead) / order.qty)
```

And then the harder truth: **adverse selection**. Your passive orders fill
disproportionately when the market is about to move against you — informed flow picks you
off. Measure it with *markouts*: average mid-price change 1s, 10s, and 60s after each of your
passive fills. If markouts are systematically negative, your fills are the bad half of the
distribution, and no amount of fee rebate saves you.

### Costs people forget, which add up to real money
- **Funding on perps** — can be 50%+ annualized in either direction. Dominates PnL for any
  position held through many funding periods.
- **Borrow fees and locate availability** for shorts.
- **Margin interest** on leveraged positions.
- **Liquidation penalties** — model your venue's actual liquidation math, including the
  insurance-fund fee.
- **Gas / network fees** for on-chain execution, which spike exactly when you most want to
  exit.
- **Taxes.** A high-turnover strategy at short-term rates can be strictly worse after tax
  than a low-turnover one with worse gross returns.
- **Infrastructure and data** amortized per trade. At small capital this is a meaningful
  drag — run the number.

---

## 3.3 Validation — assume you are fooling yourself

A single train/test split is not enough. Financial series are autocorrelated and
non-stationary, so standard k-fold CV leaks information across folds and gives you
confidently wrong answers.

### Purged, embargoed, combinatorial CV

From López de Prado, and the single highest-value technique in this document:

- **Purging:** when a label spans `[t, t+h]`, drop training samples whose label windows
  overlap the test window. Otherwise the model trains on partially-known outcomes.
- **Embargo:** additionally drop training samples for a period *after* the test window
  (~1–2% of the series) to kill residual serial correlation.
- **Combinatorial (CPCV):** split into `N` groups, test on all `C(N,k)` combinations. This
  gives you a *distribution* of backtest paths, not one number. The distribution is the
  point: a strategy whose Sharpe is 1.8 on one path and -0.4 on another is not a Sharpe-1.8
  strategy.

```python
from sklearn.model_selection import BaseCrossValidator

class PurgedKFold(BaseCrossValidator):
    def __init__(self, n_splits=6, label_end: pd.Series = None, embargo_pct=0.01):
        self.n_splits, self.label_end, self.embargo = n_splits, label_end, embargo_pct

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits

    def split(self, X, y=None, groups=None):
        idx = X.index
        embargo = int(len(X) * self.embargo)
        blocks = np.array_split(np.arange(len(X)), self.n_splits)
        for block in blocks:
            start, stop = block[0], block[-1] + 1
            test_idx = np.arange(start, stop)
            t0, t1 = idx[start], idx[stop - 1]

            # Purge: a training sample is only usable if its LABEL finished before the
            # test block began, or the sample itself starts after the block ended.
            train_mask = (self.label_end < t0) | (idx > t1)

            # Embargo: and it must not sit in the window immediately after the test block,
            # where serial correlation still leaks test information into training.
            if stop + embargo < len(X):
                embargo_end = idx[stop + embargo]
                train_mask &= ~((idx > t1) & (idx <= embargo_end))

            yield np.flatnonzero(train_mask), test_idx
```

### Metrics that account for selection bias

Report all of these for every candidate. The first number anyone quotes is Sharpe; the
others are what tell you whether the Sharpe is real.

| Metric | What it tells you | Rough bar |
|---|---|---|
| Sharpe (net of all costs) | Risk-adjusted return | >1.0 to be interesting; >2.0 be suspicious |
| **Deflated Sharpe Ratio** | Sharpe adjusted for how many variants you tried, plus skew/kurtosis | **DSR > 0 is the real test** |
| **Probability of Backtest Overfitting** | Chance the in-sample best is out-of-sample mediocre | **PBO < 0.3** |
| Sortino / Calmar | Downside-only risk; return per unit of max drawdown | Calmar > 0.5 |
| Max drawdown & duration | Will you actually sit through it? | Duration matters more than depth |
| Turnover & cost ratio | Costs ÷ gross PnL | **>50% means you are trading for your broker** |
| Hit rate × payoff ratio | Edge decomposition | Either can be low, not both |
| Capacity | AUM at which impact kills the edge | Must exceed your target capital with margin |
| Regime breakdown | Performance in bull/bear/chop/high-vol | **Flat-to-positive in ≥3 of 4** |
| Tail dependence | Correlation to the market *in crashes* | The number that decides survival |

**The parameter-count discipline:** every parameter you tune is a chance to overfit. Record
the *total* number of configurations you have ever evaluated on a dataset, and feed it into
the DSR calculation. Most people forget the hundreds of variants they discarded, which is
exactly the information DSR needs. Keep a counter in MLflow. It will be sobering.

### Also run

- **Monte Carlo on trade order.** Bootstrap-resample your trade sequence 10,000 times. If
  the equity curve only looks good in the actual historical ordering, you got lucky.
- **Synthetic data.** Generate paths with the same volatility and autocorrelation structure
  but no real edge. Your strategy should make ~nothing. If it makes money, you are fitting
  structure, not signal.
- **Noise injection.** Perturb every input by 1 basis point. A strategy whose returns
  collapse is sitting on a knife edge and will not survive live microstructure.
- **Walk-forward with re-fitting.** Re-fit parameters on a rolling window and trade the next
  window out-of-sample, repeatedly. This is the closest thing to an honest simulation of what
  you will actually do, and it is usually much worse than the static backtest.
- **Parameter surface plots.** A good strategy sits on a broad plateau. If optimal
  performance is a sharp spike surrounded by losses, you found noise.

---

## 3.4 Feature engineering

### Microstructure features (the highest signal-to-noise for MF)
These exploit mechanical, repeatable structure rather than trying to predict the world.

- **Order flow imbalance (OFI)** — the single most consistently predictive short-horizon
  feature across asset classes. Change in bid depth minus change in ask depth, summed over
  book updates.
- **Book imbalance** — `(bid_vol − ask_vol) / (bid_vol + ask_vol)` at depths 1, 5, 10.
- **Trade flow imbalance** — signed volume over trailing windows.
- **Kyle's lambda** — regression of price change on signed volume. A direct estimate of
  liquidity and impact.
- **VPIN** — volume-synchronized probability of informed trading. A toxicity gauge.
- **Realized vol** at multiple scales; **bipower variation** to separate jumps from diffusion.
- **Spread and depth dynamics**; **queue imbalance**; **cancel-to-trade ratio**.
- **Microprice** — depth-weighted mid, a better fair-value estimate than the mid.

### Cross-sectional and derived
- Time-series and cross-sectional momentum across multiple lookbacks
- Basis (perp − spot), funding rate and its term structure, cross-venue funding spread
- Implied vol level, skew, term structure; IV−RV spread
- Open interest changes; long/short account ratios; liquidation clustering
- Correlation and dispersion regimes; principal-component loadings

### Transformations that matter
- **Fractional differentiation** — makes a series stationary while *preserving memory*, which
  plain differencing destroys. Use it instead of returns where you can.
- **Volume/dollar bars instead of time bars.** Time bars under-sample active periods and
  over-sample dead ones, and have worse statistical properties. Dollar bars are the single
  cheapest improvement most people never make.
- **Triple-barrier labeling** — label by which of {profit target, stop loss, time limit} is
  hit first, instead of a fixed-horizon return. This makes labels match how you actually trade.
- **Meta-labeling** — a primary model decides direction; a secondary model decides *whether
  to take the trade and how large*. Reliably improves precision and gives natural sizing.
- **Sample weights** by label uniqueness, so overlapping labels don't triple-count.

---

## 3.5 Model zoo

Work up this ladder. Do not skip to the bottom; if a linear model finds nothing, a
transformer will find noise and present it convincingly.

| Tier | Approach | Use for |
|---|---|---|
| 0 | Single-feature threshold rules | Sanity baseline. Beat this or stop. |
| 1 | Linear / ridge / elastic net | Interpretable, hard to overfit, often sufficient |
| 2 | **LightGBM / XGBoost** | The workhorse. Tabular features → return forecast. Where most real ML alpha lives. |
| 3 | HMM / change-point detection | Regime identification used as a *gate*, not a predictor |
| 4 | Temporal CNN, LSTM, Transformer | Sequence structure. Needs a lot of data; usually disappoints vs. tier 2. |
| 5 | RL (PPO/SAC) | **Execution optimization**, not direction. This is where RL genuinely earns its keep. |
| 6 | Ensembles, stacking, online learning | Combining uncorrelated weak signals — the actual path to robust Sharpe |

**Calibration over accuracy.** You need `P(up)` to be *trustworthy*, because position size
is a function of confidence. A model that is 55% accurate with well-calibrated probabilities
is worth far more than a 58%-accurate model that is overconfident. Check with reliability
diagrams; fix with isotonic regression or Platt scaling.

---

## 3.6 Reproducibility

Every backtest result must be reconstructible from a commit hash, forever.

```python
@dataclass(frozen=True)
class ExperimentManifest:
    git_sha: str
    dirty: bool                  # fail the run if True
    dataset_dvc_hash: str
    config_hash: str
    random_seed: int
    cost_model_version: str
    universe_as_of: date         # survivorship control
    started_at: datetime
    n_configs_evaluated_to_date: int   # feeds DSR. be honest with yourself.
```

- **MLflow** for runs, params, metrics, artifacts (equity curves, trade logs).
- **DVC** for dataset versioning, so "the data I used" is a hash, not a vague memory.
- **Refuse to run on a dirty working tree** unless `--allow-dirty`. Non-negotiable: an
  unreproducible result that looks good is worse than no result, because you will act on it.
- Seed everything: `numpy`, `random`, `torch`, and any venue simulator.

---

**Gate check:** the known-bad strategy is correctly reported as losing. A pure-noise input
produces DSR ≤ 0 and PBO ≥ 0.5. CPCV produces a *distribution* of Sharpes you can plot. The
lookahead test from Phase 2 still passes against the full feature pipeline. You can re-run
last week's backtest from its manifest and get bit-identical numbers.
