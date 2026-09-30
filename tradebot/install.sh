#!/usr/bin/env bash
# Installs tradebot on Ubuntu (or any Linux with Python 3.10+). No sudo needed, unless Python's venv
# module is missing, in which case it tells you the one command to run.
#
#   Install or update:
#     python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/tradebot/install.sh', '$HOME/install-tradebot.sh')" && bash ~/install-tradebot.sh
#   Uninstall (keeps your wallet and settings in ~/.tradebot):
#     bash ~/.local/share/tradebot/install.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/determined-bardeen-vvrlm3"
DEST="$HOME/.local/share/tradebot"
BIN="$HOME/.local/bin/tradebot"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✘\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$DEST"
  rm -f "$BIN"
  say "tradebot has been removed."
  if [[ -d "$HOME/.tradebot" ]]; then
    echo "Your settings and the bot's wallet are still in ~/.tradebot."
    echo "Withdraw any funds first (tradebot withdraw) before you ever delete that folder: it holds the only key to the bot wallet."
  fi
  exit 0
fi

if [[ $EUID -eq 0 && -z "${TRADEBOT_ALLOW_ROOT:-}" ]]; then
  bad "Please don't run this as root or with sudo. Open a normal terminal (the prompt ends in \$) and run it again."
  exit 1
fi

trap 'bad "The install stopped unexpectedly (line $LINENO: $BASH_COMMAND). Please copy everything above and ask for help."' ERR

say "Installing tradebot"

if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is missing. Install it with: sudo apt install python3"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  bad "tradebot needs Python 3.10 or newer; you have $(python3 --version 2>&1). Ubuntu 22.04 or newer has it."
  exit 1
fi
ok "Found $(python3 --version 2>&1)"

# Ubuntu leaves out Python's venv module by default.
PROBE="$(mktemp -d)"
if ! python3 -m venv "$PROBE/venv" >/dev/null 2>&1; then
  rm -rf "$PROBE"
  PYVER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  bad "Python's venv module is missing. Install it with this command, then run the installer again:"
  echo "      sudo apt install python${PYVER}-venv"
  exit 1
fi
rm -rf "$PROBE"
ok "Python's venv module is available"

# Use the files next to this script when run from a copy of the repository; otherwise download them.
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$(dirname "$SELF")/pyproject.toml" && -d "$(dirname "$SELF")/tradebot" ]]; then
  SRC="$(cd "$(dirname "$SELF")" && pwd)"
  ok "Using the files in $SRC"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  if ! python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$URL" "$TMP/src.tgz"; then
    bad "Couldn't download tradebot from GitHub. Check your internet connection and try again."
    exit 1
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/src.tgz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src/tradebot"
  ok "Downloaded tradebot"
fi

mkdir -p "$DEST"
rm -rf "$DEST/src"
cp -r "$SRC" "$DEST/src"
rm -rf "$DEST/src/tests" "$DEST/src/.pytest_cache"
cp "$SRC/install.sh" "$DEST/install.sh"
chmod +x "$DEST/install.sh"
ok "Copied tradebot to $DEST"

say "Installing Python packages (a minute or two the first time)…"
[[ -d "$DEST/venv" ]] || python3 -m venv "$DEST/venv"
"$DEST/venv/bin/python" -m pip install --quiet --upgrade pip
"$DEST/venv/bin/python" -m pip install --quiet "$DEST/src"
ok "Installed tradebot and its libraries"

mkdir -p "$(dirname "$BIN")"
ln -sf "$DEST/venv/bin/tradebot" "$BIN"
ok "Added the tradebot command ($BIN)"

"$BIN" init | sed 's/^/  /'

if ! "$BIN" --help >/dev/null 2>&1; then
  bad "tradebot is installed but won't start. Please copy everything above and ask for help."
  exit 1
fi
ok "tradebot runs"

echo
say "Done! Try these in a terminal:"
echo "  tradebot backtest       how the strategy did over the last 4 years"
echo "  tradebot walkforward    the honest test: settings picked from the past, scored on unseen data"
echo "  tradebot run            paper trading: live prices, pretend money"
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo
  echo "If 'tradebot' isn't found, log out and back in once (Ubuntu adds ~/.local/bin to your PATH at login),"
  echo "or use the full path: $BIN"
fi
