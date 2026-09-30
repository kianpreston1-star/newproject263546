"""Command line: `tradebot <command>`. Run `tradebot --help` for the list."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from .config import Config, home_dir, load_config
from .data import MarketData, interval_seconds

WARNING = """\
Heads-up: this bot can lose money. Nothing can guarantee a profit, and past results don't predict future
ones. Only fund the bot wallet with money you can afford to lose. Never give anyone, or any bot, your
Trust Wallet recovery phrase."""


def setup_logging(verbose: bool = False, to_file: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if to_file:
        home_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(home_dir() / "bot.log", maxBytes=5_000_000, backupCount=3))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for noisy in ("urllib3", "web3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def market(cfg: Config) -> MarketData:
    return MarketData(cfg.market.data_url, home_dir() / "data")


def pct(x: float) -> str:
    return "n/a" if x != x else f"{x:+.1%}"


def print_metrics(bot: dict, hold: dict, symbol: str) -> None:
    rows = [("Total return", "total_return", pct), ("Yearly return (CAGR)", "cagr", pct),
            ("Worst drop (max drawdown)", "max_drawdown", pct), ("Volatility (yearly)", "volatility", lambda x: f"{x:.1%}"),
            ("Sharpe ratio", "sharpe", lambda x: f"{x:.2f}"), ("Sortino ratio", "sortino", lambda x: f"{x:.2f}"),
            ("Calmar ratio", "calmar", lambda x: f"{x:.2f}"), ("Months that made money", "positive_months", lambda x: f"{x:.0%}")]
    print(f"\n{'':28s}{'Bot':>12s}{'Just hold ' + symbol.removesuffix('USDT'):>18s}")
    for label, key, fmt in rows:
        print(f"{label:28s}{fmt(bot[key]):>12s}{fmt(hold[key]):>18s}")


def cmd_gui(args) -> None:
    from . import gui

    if not (home_dir() / "config.toml").exists():
        cmd_init(args, quiet=True)
    gui.main(args)


def cmd_init(args, quiet: bool = False) -> None:
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    target = home / "config.toml"
    if target.exists():
        print(f"{target} already exists; leaving it alone.")
    else:
        target.write_text((Path(__file__).parent / "config.example.toml").read_text())
        target.chmod(0o600)
        if quiet:
            return
        print(f"Wrote {target}. It starts in paper mode (real prices, pretend money).")
    print("\nNext:\n  tradebot gui            open the app\n"
          "  tradebot backtest       see how the strategy did on the last 4 years\n"
          "  tradebot run            paper-trade with live prices\n"
          "  tradebot new-wallet     when you're ready for real money (see README)")


def cmd_new_wallet(args) -> None:
    from .wallet import ask_password, create_wallet

    print("Choose a password for the bot's wallet (at least 10 characters). You'll need it to start the bot.")
    address = create_wallet(home_dir() / "keystore.json", ask_password(confirm=True))
    print(f"""
Bot wallet created: {address}
Saved (encrypted) in {home_dir() / 'keystore.json'}.
Back up that file and your password. Without both, money in the bot wallet can't be recovered.

To fund it from Trust Wallet, send to that address on "BNB Smart Chain" (BEP20):
  - the USDT you want the bot to trade, and
  - about 0.01 BNB for transaction fees.
Start small. You can pull everything back any time with: tradebot withdraw --to <your Trust Wallet address>

{WARNING}""")


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    setup_logging(args.verbose, to_file=True)
    print(WARNING + "\n")
    from .engine import build_bot
    from .wallet import ask_password

    bot, chain = build_bot(cfg, ask_password() if cfg.mode == "live" else None)
    bot.store.acquire_lock()
    try:
        _run(bot, chain, cfg, args)
    finally:
        bot.store.release_lock()


def _run(bot, chain, cfg: Config, args) -> None:
    if cfg.mode == "live":
        port = bot.broker.portfolio(1.0)
        print(f"LIVE mode. Bot wallet {chain.address} holds {port.quote:,.2f} {chain.quote.symbol}, "
              f"{port.asset:,.6f} {chain.asset.symbol} and {chain.native_balance():.4f} BNB.")
        if not args.yes and input('Type "live" to trade these funds for real: ').strip().lower() != "live":
            print("Not started.")
            return
    else:
        print(f"Paper mode: real prices, pretend money (${cfg.paper.starting_cash:,.0f} to start). "
              "Nothing is sent to the blockchain.")
    if args.once:
        print(bot.tick())
        return
    print(f"Checking the market every {interval_seconds(cfg.market.interval) // 60} minutes. Press Ctrl+C to stop "
          "(your coins stay where they are; use `tradebot stop` to sell to stablecoin).")
    bot.notifier.send(f"Started in {cfg.mode} mode")
    try:
        bot.run_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_status(args) -> None:
    from .store import Store

    cfg = load_config(args.config)
    store = Store(home_dir())
    saved = store.load()
    print(f"Mode: {cfg.mode}   Pair: {cfg.market.signal_symbol}   Candles: {cfg.market.interval}   Home: {home_dir()}")
    halt = store.halt_reason()
    print(f"Halted: {halt}" if halt else "Halted: no")
    if (home_dir() / "keystore.json").exists():
        from .wallet import wallet_address

        print(f"Bot wallet: {wallet_address(home_dir() / 'keystore.json')}")
    saved = saved.get(cfg.mode, {})
    if "last_tick" in saved:
        s, r = saved["last_signal"], saved["risk"]
        print(f"Last check: {saved['last_tick'][:19]} UTC   price ${s['close']:,.2f}   trend {s['trend']:+.2f}   "
              f"target {saved.get('last_target', s['target']):.0%} of the account in the coin")
        dd = 1 - saved["last_equity"] / r["peak_equity"] if r.get("peak_equity") else 0
        print(f"Account: ${saved['last_equity']:,.2f}   peak ${r['peak_equity']:,.2f}   down {dd:.1%} from peak   "
              f"trades today {r['trades_today']}")
    else:
        print("The bot hasn't run yet. Start it with: tradebot run")
    if store.trades_path.exists():
        lines = store.trades_path.read_text().strip().splitlines()[1:]
        print(f"\nLast trades ({len(lines)} in total, full log in {store.trades_path}):")
        for line in lines[-5:]:
            print("  " + line)


def cmd_backtest(args) -> None:
    from .backtest import run_backtest

    cfg = load_config(args.config)
    symbol = args.symbol or cfg.market.signal_symbol
    print(f"Loading {args.days} days of {symbol} {cfg.market.interval} candles…")
    df = market(cfg).history(symbol, cfg.market.interval, args.days)
    r = run_backtest(df, cfg, kill_switch=not args.no_kill_switch)
    m = r.metrics
    print(f"\nBacktest {r.equity.index[0]:%Y-%m-%d} → {r.equity.index[-1]:%Y-%m-%d}, starting with "
          f"${cfg.paper.starting_cash:,.0f}. Costs included: {cfg.paper.fee_bps + cfg.paper.slippage_bps:.0f} bps per "
          f"trade plus ${cfg.paper.gas_usd} gas.")
    print_metrics(m, r.benchmark, symbol)
    print(f"\nEnded with ${m['final_equity']:,.2f} (just holding: ${r.benchmark['final_equity']:,.2f}). "
          f"{m['trades']} trades, ${m['costs_paid']:,.2f} in costs, {m['avg_exposure']:.0%} invested on average.")
    if r.halted_at is not None:
        print(f"The kill switch tripped on {r.halted_at:%Y-%m-%d}: {r.halt_reason}. It stayed in stablecoin after that.")
    if args.csv:
        r.equity.to_frame().join(r.exposure).assign(buy_and_hold=df["close"] / df["close"].loc[r.equity.index[0]]
                                                    * cfg.paper.starting_cash).to_csv(args.csv)
        print(f"Saved the equity curve to {args.csv}")
    print("\n" + WARNING)


def cmd_walkforward(args) -> None:
    from .backtest import walk_forward

    cfg = load_config(args.config)
    symbol = args.symbol or cfg.market.signal_symbol
    per_day = 86400 // interval_seconds(cfg.market.interval)
    print(f"Loading {args.days} days of {symbol} candles…")
    df = market(cfg).history(symbol, cfg.market.interval, args.days)
    print("Walk-forward test: settings are chosen using only past data, then scored on the next, unseen window.")
    wf = walk_forward(df, cfg, args.train_days * per_day, args.test_days * per_day)
    for f in wf.folds:
        p = ", ".join(f"{k.split('.')[1]}={v}" for k, v in f["params"].items())
        print(f"  {f['from']:%Y-%m-%d} → {f['to']:%Y-%m-%d}  bot {f['test_return']:+7.1%}  hold {f['hold_return']:+7.1%}  ({p})")
    print(f"\nUnseen-data results, {wf.equity.index[0]:%Y-%m-%d} → {wf.equity.index[-1]:%Y-%m-%d}:")
    print_metrics(wf.metrics, wf.benchmark, symbol)
    print("\n" + WARNING)


def cmd_quote(args) -> None:
    from .dex import Chain, best_route

    cfg = load_config(args.config)
    chain = Chain(cfg)
    amount = chain.quote.to_units(args.usd)
    routes = sorted(chain.quotes(chain.quote, chain.asset, amount), key=lambda r: -r.amount_out)
    print(f"Buying {chain.asset.symbol} with {args.usd:,.2f} {chain.quote.symbol} on BNB Chain:")
    for r in routes:
        got = chain.asset.to_float(r.amount_out)
        print(f"  {r.describe():34s} {got:.6f} {chain.asset.symbol}  (${args.usd / got:,.2f} each)")
    best = best_route(routes)
    if best:
        print(f"Best: {best.describe()}")


def cmd_stop(args) -> None:
    from .store import Store

    Store(home_dir()).halt(args.reason)
    print("Halt requested. A running bot sells to stablecoin within about 10 seconds and then stays out of the market.\n"
          "If the bot isn't running, start it (tradebot run) and it will do the selling first.\n"
          "Undo with: tradebot resume")


def cmd_resume(args) -> None:
    from .store import Store

    Store(home_dir()).resume()
    print("Resumed. The bot will trade again on its next check.")


def cmd_withdraw(args) -> None:
    from web3 import Web3

    cfg = load_config(args.config)
    if not Web3.is_address(args.to):
        sys.exit(f"{args.to} isn't a valid BNB Chain address.")
    setup_logging(args.verbose)
    from .store import Store

    store = Store(home_dir())
    store.acquire_lock()  # refuses if the bot is running, so the two can't send conflicting transactions
    try:
        _withdraw(cfg, store, args)
    finally:
        store.release_lock()


def _withdraw(cfg: Config, store, args) -> None:
    from web3 import Web3

    from .engine import load_live
    from .wallet import ask_password

    chain, broker = load_live(cfg, ask_password())
    to = Web3.to_checksum_address(args.to)
    if to == chain.address:
        sys.exit("That's the bot's own address. Use your Trust Wallet's BNB Smart Chain address.")
    port = broker.portfolio(1.0)
    print(f"This sends {port.quote:,.4f} {chain.quote.symbol}, {port.asset:,.6f} {chain.asset.symbol} and the BNB "
          f"(minus fees) from the bot wallet to:\n  {to}")
    if not args.yes and input("Type the last 4 characters of that address to confirm: ").strip().lower() != to[-4:].lower():
        print("Cancelled.")
        return
    store.halt("Funds withdrawn")
    for line in chain.withdraw_all(to):
        print("Sent " + line)
    print("Done. The bot is halted so it won't try to trade an empty wallet.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="tradebot", description="Trend-following trading bot for BNB Chain (PancakeSwap).")
    ap.add_argument("--config", help="config file (default: ~/.tradebot/config.toml)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gui", help="open the desktop app (the bot keeps running in the background)")
    p.add_argument("--check", action="store_true", help="start the app server if needed and report, without a window")
    p.add_argument("--stop", action="store_true", help="quit the background app and stop its bot")
    p.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_gui)

    sub.add_parser("init", help="create ~/.tradebot with a starter config").set_defaults(func=cmd_init)
    sub.add_parser("new-wallet", help="create the bot's own encrypted wallet").set_defaults(func=cmd_new_wallet)
    sub.add_parser("status", help="show the bot's state, account and last trades").set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="start trading (paper or live, as set in the config)")
    p.add_argument("--once", action="store_true", help="do one check and exit")
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation in live mode")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("backtest", help="replay the strategy over past prices")
    p.add_argument("--symbol", help="Binance pair, e.g. BTCUSDT (default: the configured one)")
    p.add_argument("--days", type=int, default=1460)
    p.add_argument("--no-kill-switch", action="store_true", help="ignore the max-drawdown kill switch")
    p.add_argument("--csv", help="save the equity curve to this CSV file")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("walkforward", help="test on unseen data with settings picked from the past only")
    p.add_argument("--symbol")
    p.add_argument("--days", type=int, default=1460)
    p.add_argument("--train-days", type=int, default=365)
    p.add_argument("--test-days", type=int, default=90)
    p.set_defaults(func=cmd_walkforward)

    p = sub.add_parser("quote", help="show live PancakeSwap prices for a buy (no wallet needed)")
    p.add_argument("--usd", type=float, default=100.0)
    p.set_defaults(func=cmd_quote)

    p = sub.add_parser("stop", help="kill switch: sell to stablecoin and halt")
    p.add_argument("--reason", default="Stopped by you (tradebot stop)")
    p.set_defaults(func=cmd_stop)
    sub.add_parser("resume", help="undo a halt and trade again").set_defaults(func=cmd_resume)

    p = sub.add_parser("withdraw", help="send everything in the bot wallet back to your Trust Wallet")
    p.add_argument("--to", required=True, help="your Trust Wallet BNB Smart Chain address")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_withdraw)

    args = ap.parse_args(argv)
    if args.command not in ("run", "withdraw", "gui"):
        setup_logging(args.verbose)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError, FileExistsError, RuntimeError) as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
