"""The bot's own wallet, kept in an encrypted keystore file.

The bot never asks for your Trust Wallet recovery phrase. It makes a separate wallet, and you send it only
the money you want it to trade. If the bot, its computer or its password is ever compromised, only that
money is at risk, not everything in your Trust Wallet.
"""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount

MIN_PASSWORD = 10


def create_wallet(path: Path, password: str) -> str:
    """Creates a new wallet and saves it encrypted. Refuses to overwrite: that would lose the funds in it."""
    if path.exists():
        raise FileExistsError(f"{path} already exists. The bot already has a wallet; it won't replace it.")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Use a password of at least {MIN_PASSWORD} characters.")
    account = Account.create()
    keystore = Account.encrypt(account.key, password)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(keystore, f)
    return account.address


def wallet_address(path: Path) -> str:
    with open(path) as f:
        return "0x" + json.load(f)["address"].removeprefix("0x")


def load_account(path: Path, password: str) -> LocalAccount:
    if not path.exists():
        raise FileNotFoundError(f"No bot wallet at {path}. Create one with: tradebot new-wallet")
    with open(path) as f:
        keystore = json.load(f)
    try:
        return Account.from_key(Account.decrypt(keystore, password))
    except ValueError:
        raise ValueError("Wrong wallet password.") from None


def ask_password(confirm: bool = False) -> str:
    """Reads the wallet password from TRADEBOT_PASSWORD or asks for it."""
    env = os.environ.get("TRADEBOT_PASSWORD")
    if env:
        return env
    password = getpass.getpass("Bot wallet password: ")
    if confirm and getpass.getpass("Type it again: ") != password:
        raise ValueError("The passwords didn't match.")
    return password
