"""Live trading on PancakeSwap (BNB Chain).

Each trade:
1. asks every PancakeSwap v3 fee tier and v2 for a price and takes the best one,
2. refuses the trade if that price is too far from the market price (a manipulated or broken pool),
3. sets an on-chain minimum output, so the swap reverts instead of filling at a bad price (sandwich bots),
4. approves only the exact amount being swapped (never an unlimited allowance),
5. simulates the transaction before sending it, and checks the receipt afterwards.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

from .broker import Fill, TradeSkipped
from .config import WBNB, Config
from .risk import Order, Portfolio

log = logging.getLogger(__name__)

TRANSFER_TOPIC = bytes(Web3.keccak(text="Transfer(address,address,uint256)"))


def hexstr(value) -> str:
    return "0x" + bytes(value).hex()


def _fn(name, inputs, outputs=(), mutability="view"):
    return {"type": "function", "name": name, "stateMutability": mutability,
            "inputs": [{"name": n, "type": t} for n, t in inputs],
            "outputs": [{"name": "", "type": t} for t in outputs]}


ERC20_ABI = [
    _fn("balanceOf", [("owner", "address")], ["uint256"]),
    _fn("decimals", [], ["uint8"]),
    _fn("symbol", [], ["string"]),
    _fn("allowance", [("owner", "address"), ("spender", "address")], ["uint256"]),
    _fn("approve", [("spender", "address"), ("amount", "uint256")], ["bool"], "nonpayable"),
    _fn("transfer", [("to", "address"), ("amount", "uint256")], ["bool"], "nonpayable"),
    _fn("withdraw", [("amount", "uint256")], [], "nonpayable"),  # WBNB only: unwrap to BNB
]
V2_ROUTER_ABI = [
    _fn("getAmountsOut", [("amountIn", "uint256"), ("path", "address[]")], ["uint256[]"]),
    _fn("swapExactTokensForTokens", [("amountIn", "uint256"), ("amountOutMin", "uint256"), ("path", "address[]"),
                                     ("to", "address"), ("deadline", "uint256")], ["uint256[]"], "nonpayable"),
]
_V3_QUOTE_PARAMS = {"name": "params", "type": "tuple", "components": [
    {"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"},
    {"name": "amountIn", "type": "uint256"}, {"name": "fee", "type": "uint24"},
    {"name": "sqrtPriceLimitX96", "type": "uint160"}]}
V3_QUOTER_ABI = [{"type": "function", "name": "quoteExactInputSingle", "stateMutability": "nonpayable",
                  "inputs": [_V3_QUOTE_PARAMS],
                  "outputs": [{"name": "amountOut", "type": "uint256"}, {"name": "sqrtPriceX96After", "type": "uint160"},
                              {"name": "initializedTicksCrossed", "type": "uint32"},
                              {"name": "gasEstimate", "type": "uint256"}]}]
_V3_SWAP_PARAMS = {"name": "params", "type": "tuple", "components": [
    {"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"}, {"name": "fee", "type": "uint24"},
    {"name": "recipient", "type": "address"}, {"name": "amountIn", "type": "uint256"},
    {"name": "amountOutMinimum", "type": "uint256"}, {"name": "sqrtPriceLimitX96", "type": "uint160"}]}
V3_ROUTER_ABI = [
    {"type": "function", "name": "exactInputSingle", "stateMutability": "payable", "inputs": [_V3_SWAP_PARAMS],
     "outputs": [{"name": "amountOut", "type": "uint256"}]},
    _fn("multicall", [("deadline", "uint256"), ("data", "bytes[]")], ["bytes[]"], "payable"),
]


@dataclass
class Route:
    kind: str  # "v3" or "v2"
    amount_out: int
    fee: int = 0  # v3 pool fee in hundredths of a basis point (100 = 0.01%)
    path: tuple = ()  # v2 token path

    def describe(self) -> str:
        return f"PancakeSwap v3 {self.fee / 1_000_000:.2%} pool" if self.kind == "v3" else f"PancakeSwap v2 ({len(self.path) - 1} hop)"


def best_route(routes: list[Route]) -> Route | None:
    return max(routes, key=lambda r: r.amount_out, default=None)


def min_out(amount_out: int, slippage_bps: float) -> int:
    return amount_out * (10_000 - int(slippage_bps)) // 10_000


def price_deviation(dex_price: float, market_price: float) -> float:
    return abs(dex_price / market_price - 1)


class Token:
    def __init__(self, w3: Web3, address: str):
        self.address = Web3.to_checksum_address(address)
        self.contract = w3.eth.contract(self.address, abi=ERC20_ABI)
        self.decimals = self.contract.functions.decimals().call()
        self.symbol = self.contract.functions.symbol().call()

    def to_units(self, amount: float) -> int:
        return int(amount * 10**self.decimals)

    def to_float(self, units: int) -> float:
        return units / 10**self.decimals

    def balance(self, owner: str) -> int:
        return self.contract.functions.balanceOf(owner).call()


class Chain:
    """A connection to BNB Chain, the two tokens being traded and the PancakeSwap contracts."""

    def __init__(self, cfg: Config, account: LocalAccount | None = None):
        c = self.cfg = cfg.chain
        self.w3 = Web3(Web3.HTTPProvider(c.rpc_url, request_kwargs={"timeout": 30}))
        self.send_w3 = Web3(Web3.HTTPProvider(c.send_rpc_url, request_kwargs={"timeout": 30})) if c.send_rpc_url else self.w3
        chain_id = self.w3.eth.chain_id
        if chain_id != c.chain_id:
            raise RuntimeError(f"The RPC at {c.rpc_url} is chain {chain_id}, expected {c.chain_id} (BNB Chain)")
        self.account = account
        self.quote = Token(self.w3, c.quote_token)
        self.asset = Token(self.w3, c.asset_token)
        self.wbnb = Web3.to_checksum_address(WBNB)
        self.v2 = self.w3.eth.contract(Web3.to_checksum_address(c.v2_router), abi=V2_ROUTER_ABI)
        self.v3 = self.w3.eth.contract(Web3.to_checksum_address(c.v3_router), abi=V3_ROUTER_ABI)
        self.quoter = self.w3.eth.contract(Web3.to_checksum_address(c.v3_quoter), abi=V3_QUOTER_ABI)
        self._next_nonce = 0

    @property
    def address(self) -> str:
        return self.account.address

    def native_balance(self, address: str | None = None) -> float:
        return self.w3.eth.get_balance(address or self.address) / 1e18

    # ---- prices ----------------------------------------------------------------------------------

    def quotes(self, token_in: Token, token_out: Token, amount_in: int) -> list[Route]:
        routes = []
        for fee in self.cfg.v3_fee_tiers:
            try:
                out = self.quoter.functions.quoteExactInputSingle(
                    (token_in.address, token_out.address, amount_in, fee, 0)).call()[0]
                routes.append(Route("v3", out, fee=fee))
            except (ContractLogicError, BadFunctionCallOutput):
                pass  # no pool at this fee tier, or it can't take the trade
        if self.cfg.use_v2:
            paths = [(token_in.address, token_out.address)]
            if self.wbnb not in paths[0]:
                paths.append((token_in.address, self.wbnb, token_out.address))
            for path in paths:
                try:
                    out = self.v2.functions.getAmountsOut(amount_in, list(path)).call()[-1]
                    routes.append(Route("v2", out, path=path))
                except (ContractLogicError, BadFunctionCallOutput):
                    pass
        return routes

    # ---- transactions ----------------------------------------------------------------------------

    def gas_price(self) -> int:
        price = self.w3.eth.gas_price
        if price > Web3.to_wei(self.cfg.max_gas_gwei, "gwei"):
            raise TradeSkipped(f"Gas price {price / 1e9:.2f} gwei is above the {self.cfg.max_gas_gwei} gwei limit")
        return price

    def send(self, fn, what: str, value: int = 0) -> dict:
        """Simulates, signs, sends and confirms a contract call. Raises if it would revert or did revert."""
        nonce = max(self.w3.eth.get_transaction_count(self.address, "pending"), self._next_nonce)
        tx = {"from": self.address, "nonce": nonce, "chainId": self.cfg.chain_id, "gasPrice": self.gas_price(),
              "value": value}
        try:
            tx["gas"] = int(fn.estimate_gas(tx) * 1.3)
        except ContractLogicError as e:
            raise TradeSkipped(f"{what} would fail on-chain, so it wasn't sent: {e}") from e
        return self._sign_and_send(fn.build_transaction(tx), what)

    def _sign_and_send(self, tx: dict, what: str) -> dict:
        signed = self.account.sign_transaction(tx)
        tx_hash = self.send_w3.eth.send_raw_transaction(signed.raw_transaction)
        self._next_nonce = tx["nonce"] + 1
        log.info("%s sent: %s", what, hexstr(tx_hash))
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.cfg.tx_timeout)
        if receipt["status"] != 1:
            raise RuntimeError(f"{what} reverted on-chain (tx {hexstr(tx_hash)})")
        return receipt

    def approve_exact(self, token: Token, spender: str, amount: int) -> None:
        if token.contract.functions.allowance(self.address, spender).call() >= amount:
            return
        self.send(token.contract.functions.approve(spender, amount), f"Approve {token.symbol}")
        # Load-balanced public RPCs can lag a block; wait until the node we simulate against sees it.
        for _ in range(15):
            if token.contract.functions.allowance(self.address, spender).call() >= amount:
                return
            time.sleep(1)

    def swap(self, route: Route, token_in: Token, token_out: Token, amount_in: int, minimum_out: int) -> tuple[str, int]:
        deadline = int(time.time()) + 300
        if route.kind == "v3":
            spender = self.v3.address
            call = self.v3.encode_abi("exactInputSingle", args=[(
                token_in.address, token_out.address, route.fee, self.address, amount_in, minimum_out, 0)])
            fn = self.v3.functions.multicall(deadline, [call])
        else:
            spender = self.v2.address
            fn = self.v2.functions.swapExactTokensForTokens(amount_in, minimum_out, list(route.path), self.address, deadline)
        self.approve_exact(token_in, spender, amount_in)
        receipt = self.send(fn, f"Swap {token_in.symbol}→{token_out.symbol}")
        return hexstr(receipt["transactionHash"]), self.received(receipt, token_out)

    def received(self, receipt: dict, token: Token) -> int:
        """Tokens this wallet received in a transaction, read from its Transfer events."""
        me = self.address.lower()[2:].rjust(64, "0")
        total = 0
        for entry in receipt["logs"]:
            topics = entry["topics"]
            if (entry["address"].lower() == token.address.lower() and len(topics) == 3
                    and bytes(topics[0]) == TRANSFER_TOPIC and bytes(topics[2]).hex() == me):
                total += int.from_bytes(bytes(entry["data"]), "big")
        return total

    def withdraw_all(self, to: str) -> list[str]:
        """Sends everything back to `to` (e.g. your Trust Wallet). WBNB is unwrapped so it arrives as BNB."""
        to = Web3.to_checksum_address(to)
        done = []
        for token in {self.quote.address: self.quote, self.asset.address: self.asset}.values():
            amount = token.balance(self.address)
            if amount == 0:
                continue
            if token.address == self.wbnb:
                self.send(token.contract.functions.withdraw(amount), "Unwrap WBNB")
                continue
            receipt = self.send(token.contract.functions.transfer(to, amount), f"Send {token.symbol}")
            done.append(f"{token.to_float(amount):,.6f} {token.symbol} (tx {hexstr(receipt['transactionHash'])})")
        gas_price = self.gas_price()
        gas = 21_000 if not self.w3.eth.get_code(to) else int(self.w3.eth.estimate_gas(
            {"from": self.address, "to": to, "value": 1}) * 1.3)
        amount = self.w3.eth.get_balance(self.address) - gas * gas_price
        if amount > 0:
            nonce = max(self.w3.eth.get_transaction_count(self.address, "pending"), self._next_nonce)
            receipt = self._sign_and_send({"to": to, "value": amount, "gas": gas, "gasPrice": gas_price,
                                           "nonce": nonce, "chainId": self.cfg.chain_id}, "Send BNB")
            done.append(f"{amount / 1e18:,.6f} BNB (tx {hexstr(receipt['transactionHash'])})")
        return done


class LiveBroker:
    """Trades real funds from the bot's own wallet."""

    def __init__(self, chain: Chain, cfg: Config):
        self.chain = chain
        self.risk = cfg.risk

    def portfolio(self, price: float) -> Portfolio:
        c = self.chain
        return Portfolio(c.quote.to_float(c.quote.balance(c.address)), c.asset.to_float(c.asset.balance(c.address)), price)

    def execute(self, order: Order, market_price: float) -> Fill:
        c = self.chain
        if c.native_balance() < c.cfg.min_gas_bnb:
            raise TradeSkipped(f"The bot wallet has less than {c.cfg.min_gas_bnb} BNB for fees. Send it a little BNB.")
        if order.side == "buy":
            token_in, token_out, wanted = c.quote, c.asset, order.quote_amount
        else:
            token_in, token_out, wanted = c.asset, c.quote, order.asset_amount
        balance = token_in.balance(c.address)
        amount_in = token_in.to_units(wanted)
        if amount_in >= balance * 0.999:  # float rounding would otherwise leave dust behind
            amount_in = balance
        if amount_in == 0:
            raise TradeSkipped(f"No {token_in.symbol} to {order.side} with")

        route = best_route(c.quotes(token_in, token_out, amount_in))
        if route is None or route.amount_out == 0:
            raise TradeSkipped(f"No PancakeSwap pool quoted a price for {token_in.symbol}→{token_out.symbol}")
        amt_in, amt_out = token_in.to_float(amount_in), token_out.to_float(route.amount_out)
        dex_price = amt_in / amt_out if order.side == "buy" else amt_out / amt_in
        deviation = price_deviation(dex_price, market_price)
        if deviation > self.risk.max_price_deviation:
            raise TradeSkipped(f"DEX price ${dex_price:,.4f} is {deviation:.1%} away from the market price "
                               f"${market_price:,.4f}; the pool may be manipulated or broken")

        tx_hash, got = c.swap(route, token_in, token_out, amount_in, min_out(route.amount_out, self.risk.max_slippage_bps))
        got_f = token_out.to_float(got)
        if order.side == "buy":
            price = amt_in / got_f if got_f else dex_price
            return Fill("buy", got_f, amt_in, price, amt_in - got_f * market_price, tx_hash, route.describe())
        price = got_f / amt_in
        return Fill("sell", amt_in, got_f, price, amt_in * market_price - got_f, tx_hash, route.describe())
