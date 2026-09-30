# tradebot

An automated trading bot for BNB Chain, the network Trust Wallet uses for BNB and BEP20 tokens. It trades between USDT and a coin (BNB by default, or BTC or ETH) on PancakeSwap. It follows the trend, sizes positions by volatility and has several layers of risk controls. It's a desktop app that runs on your own computer, and it trades from **its own wallet**, never your Trust Wallet.

> **Read this first.** No bot can guarantee a profit, and this one can lose money. The results below are simulations on past prices, and past results don't predict future ones. Start in paper mode, then fund the bot with only what you can afford to lose. **Never give your Trust Wallet recovery phrase to anyone or anything, including this bot.** Anyone offering to "trade for you" in exchange for your phrase is running the most common crypto scam there is.

## How it did in testing

The tests use hourly candles, start with $1,000 and include realistic costs: 0.1% per trade plus gas. "Worst drop" is the largest fall from a high point, the number that decides whether you'd have panicked.

**Walk-forward test (the honest one).** Before each 3-month window, the bot picks its settings using only the year before it. Then it's scored on that window, which it has never seen. The results cover Jan 2024 to Sep 2026, including the 2026 downturn:

| Coin | Bot return | Bot worst drop | Just holding | Holding's worst drop | Bot Sharpe | Holding Sharpe |
|------|-----------:|---------------:|-------------:|---------------------:|-----------:|---------------:|
| BNB  | **+163%**  | −35%           | +151%        | −60%                 | 1.24       | 0.91           |
| BTC  | +67%       | −26%           | **+100%**    | −54%                 | 0.92       | 0.79           |
| ETH  | **+101%**  | −35%           | +20%         | −69%                 | 1.03       | 0.43           |

**Plain backtest, default settings** (Dec 2022 to Sep 2026):

| Coin | Bot return | Bot worst drop | Just holding | Holding's worst drop | Trades | Avg. invested |
|------|-----------:|---------------:|-------------:|---------------------:|-------:|--------------:|
| BNB  | +129%      | −34%           | **+216%**    | −60%                 | 383    | 38%           |
| BTC  | +214%      | −23%           | **+410%**    | −54%                 | 342    | 43%           |
| ETH  | **+169%**  | −33%           | +127%        | −69%                 | 351    | 38%           |

What this means:
- **It roughly halves the worst losses.** That's the main thing trend-following buys you: it sidesteps most of a crash by moving to USDT.
- **It earned more per unit of risk** (Sharpe ratio) than holding in every test.
- **In a strong bull market it earns less than just holding.** It's only partly invested and joins rallies late. If you're sure a coin will go up, holding it beats any bot.
- **Faster strategies failed.** An early version that traded hourly swings made money before costs, then lost 50% after fees. Only the slower one-week-to-two-month trend signal survived costs.

Re-run these yourself any time on the app's Backtest tab, or with `tradebot backtest` and `tradebot walkforward` in a terminal.

## Why it has its own wallet

Trust Wallet has no API. The only way to give a program "full access" is your recovery phrase, which unlocks every coin on every chain in that wallet, forever. If a bot holds it and the bot, your laptop or a log file is ever compromised, everything is gone.

So the bot creates a **separate wallet** and stores it encrypted with a password. You send it only the amount you want traded. If anything goes wrong, only that amount is at risk, and one button sends everything back to your Trust Wallet.

## Install (Ubuntu)

Open a terminal (**Ctrl+Alt+T**), paste this and press Enter:

```bash
python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/tradebot/install.sh', '$HOME/install-tradebot.sh')" && bash ~/install-tradebot.sh
```

Run it as yourself, **not** with `sudo`. The installer shows a ✔ for each step, then:
- adds **Tradebot** (a green icon) to your app list, your desktop and the dock, and
- opens the app when it's done.

If it says Python's venv module is missing, run the `sudo apt install …` command it prints, then run the line above again. Running the same line later updates Tradebot. To uninstall, run `bash ~/.local/share/tradebot/install.sh --uninstall`. That keeps your wallet and settings in `~/.tradebot`.

## Using the app

Open Tradebot from the dock, the app list (press Super and type "Tradebot") or the desktop icon. If Ubuntu says the desktop icon isn't allowed to launch, right-click it and choose **Allow Launching**. It opens in its own window with four tabs:

- **Dashboard:** Start, Pause and **Emergency sell & stop** buttons. It also shows your account value and profit, how far you are below your peak, and how much is in the coin now vs the bot's target. A chart compares the bot with just holding, and panels show the current trend signal, recent trades and a live activity log.
- **Backtest:** pick BNB, BTC or ETH and a period, then run a backtest or the honest walk-forward test. It shows a growth chart against just holding, the full numbers, and every unseen 3-month window.
- **Wallet:** creates the bot's own wallet and shows its address with a **QR code you can scan with Trust Wallet** on your phone. It also shows live balances (USDT, the coin, BNB for fees) and has a withdraw form that sends everything back to your Trust Wallet.
- **Settings:** paper or live mode, which coin, the paper starting balance, risk limits (max invested, kill switch, daily loss limit) and optional Telegram phone alerts.

**The bot keeps running when you close the window**, so it can trade around the clock. Opening Tradebot again shows it. **Quit** (top right) stops it; your coins stay where they are. After restarting the computer, open Tradebot and press **Start**.

### Getting started

1. **Check the evidence.** On the Backtest tab, run the walk-forward test for BNB.
2. **Paper trade for a few weeks.** On the Dashboard, press **Start**. It uses live prices and $1,000 of pretend money, and nothing touches the blockchain. It checks the market at the end of every hour.
3. **Go live, with a small amount first.**
   - On the Wallet tab, create the bot's wallet. Choose a password of at least 10 characters and keep it safe.
   - In Trust Wallet, tap Send, choose **USDT on BNB Smart Chain** (BEP20) and scan the QR code. Also send about **0.01 BNB** for transaction fees; each trade costs a few cents.
   - On the Settings tab, switch to **Live** and save.
   - Press **Start** on the Dashboard. It asks for the wallet password and a confirmation before it touches real funds.
4. **Keep the computer on.** The bot only trades while the computer is on and awake, so turn off automatic suspend on a laptop.

**Getting your money back:** pause the bot, then use the Withdraw form on the Wallet tab. It sends all the USDT, the coin and the leftover BNB to your Trust Wallet address, converting WBNB to normal BNB first so it shows up in Trust Wallet without extra steps.

### From the terminal instead

Everything the app does also works as a command (see the table below). `tradebot run` trades in the terminal, reading paper or live mode from `~/.tradebot/config.toml`. `tradebot withdraw --to <address>` sends the funds back. The app and `tradebot run` share a lock, so they can never both trade the same wallet at once.

## Commands

| Command | What it does |
|---|---|
| `tradebot gui` | Opens the app (what the Tradebot icon runs). `--stop` quits it, `--check` just checks that it starts |
| `tradebot init` | Creates `~/.tradebot` with a starter config (the installer does this for you) |
| `tradebot backtest` | Replays the strategy over the last 4 years (`--symbol`, `--days`, `--csv` to save the equity curve) |
| `tradebot walkforward` | Tests on unseen data with settings picked from the past only |
| `tradebot run` | Starts trading (paper or live, per the config). `--once` does a single check |
| `tradebot status` | Mode, account value, drawdown, last signal and last trades |
| `tradebot quote --usd 100` | Live PancakeSwap prices across all pools (no wallet needed) |
| `tradebot new-wallet` | Creates the bot's encrypted wallet (never overwrites an existing one) |
| `tradebot stop` | Kill switch: the running bot sells to USDT within about 10 seconds and stays out |
| `tradebot resume` | Undoes a stop or kill switch |
| `tradebot withdraw --to ADDR` | Sends everything back to your Trust Wallet |

## How the strategy works

Every hour it looks at the last ~3½ months of hourly candles for the coin, from Binance's free public price feed:

1. **Trend score (−1 to +1).** It measures the return over 1 week, 2 weeks, 1 month and 2 months, each divided by how much the price normally moves over that period. That turns "up 10%" into "up an unusually large amount" or "up by noise", and averaging the four horizons makes the signal steady. The stronger and more consistent the uptrend, the more of the account goes into the coin. When the trend turns down, it moves to USDT.
2. **Dip-buying.** During a long-term uptrend, a sharp dip below the 2-day average adds a little extra exposure.
3. **Volatility targeting.** When the market gets unusually wild, the position shrinks.
4. **Smoothing and a no-trade band.** Changes smaller than 15 percentage points are ignored, so it doesn't pay fees to chase noise.

It never borrows, uses leverage or shorts. The worst case for the coin part is the coin going to zero, and the kill switch sells well before that.

## Safety features

**Market and strategy**
- Only uses finished candles, and won't trade if the price feed is more than two hours old.
- Never more than 90% of the account in the coin. Gains that push it past that are trimmed back.
- No single trade larger than 50% of the account, and no trades under $10.

**Loss limits**
- **Daily loss limit:** after losing 5% in a day (UTC), it only sells until the next day.
- **Kill switch:** at a 40% fall from the account's peak, it sells everything to USDT and halts until you run `tradebot resume`. The strategy's worst drop in 4 years of testing was 35%, so reaching 40% means something unusual is happening. You can lower it in the config.
- Hard limit of 12 trades a day.

**Trade execution**
- **Best price:** each trade compares all PancakeSwap v3 pools (0.01%, 0.05%, 0.25% fees) and v2, and uses the best.
- **Price sanity check:** it refuses to trade if the DEX price is more than 2% away from the Binance price, which would mean a manipulated or broken pool.
- **On-chain slippage limit:** each swap reverts rather than fill more than 0.5% worse than quoted. This protects against sandwich bots.
- **Exact approvals:** the router may only spend the amount of each trade, never an unlimited amount.
- **Simulated first:** every transaction is simulated before it's sent. One that would fail is never sent, so it costs no gas.
- **Gas limits:** it won't trade if fees spike above 3 gwei, and it keeps a BNB reserve for gas.

**Wallet and process**
- **Encrypted wallet:** the key is stored encrypted (scrypt) with owner-only file permissions, outside this repository. The bot never accepts a recovery phrase.
- **Single instance:** a lock stops two copies of the bot from trading the same wallet.
- **App security:** the app's window talks to a small server that only this computer can reach (127.0.0.1). Every request needs a secret token that only the window has, so a website open in your browser can't press the app's buttons. The wallet password is never saved, and the wallet is only unlocked in memory while live trading runs.
- **Alerts:** optional Telegram notifications for every trade, error and kill-switch event (see `config.toml`).

## Settings

Everything lives in `~/.tradebot/config.toml`. Only the settings you write there change; everything else uses the defaults in [`tradebot/config.py`](tradebot/config.py), which explains each one. To trade BTC or ETH instead of BNB, change `signal_symbol` and `asset_token` as shown in the config file. After changing strategy or risk settings, run `backtest` and `walkforward` before trusting the change with money.

The wallet password can come from the `TRADEBOT_PASSWORD` environment variable instead of a prompt, which is handy for unattended starts. It's less safe, because anyone who can read your environment gets the password.

## What can still go wrong

- **The market does something new.** A trend-follower loses in choppy markets that keep reversing. It takes a series of small losses, as in mid-2024 and mid-2026 in the tests above.
- **Smart-contract or chain risk.** PancakeSwap, USDT and BNB Chain are among the most-used contracts on the chain, but none is risk-free. USDT could lose its $1 peg.
- **Your computer.** If it's hacked, the bot wallet (only) is at risk. If it's off, the bot isn't watching. Keep the system updated and back up `~/.tradebot/keystore.json` and your password: without both, the bot wallet's funds can't be recovered.

## Development

```bash
cd tradebot
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

The tests cover:
- that signals never look ahead,
- the risk rules and the kill switch,
- the cost model and the backtest's fill timing,
- walk-forward testing,
- the config, wallet and state handling,
- the bot loop,
- the app server: its token and host checks, and every button from Start to Withdraw.

The live-trading path was also rehearsed end to end on a local fork of BNB Chain mainnet (Foundry's `anvil`): a real swap on the PancakeSwap v3 0.01% pool, the price-deviation and simulation guards, the kill switch selling to USDT, and `withdraw` emptying the wallet.
