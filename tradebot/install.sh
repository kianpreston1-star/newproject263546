#!/usr/bin/env bash
# Installs the Tradebot desktop app on Ubuntu (or any Linux desktop with Python 3.10+). No sudo needed,
# unless Python's venv module is missing, in which case it tells you the one command to run.
# It adds "Tradebot" to the app list, the desktop and the dock, checks that it works, and opens it.
#
#   Install or update:
#     python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/tradebot/install.sh', '$HOME/install-tradebot.sh')" && bash ~/install-tradebot.sh
#   Run it as yourself, not as root or with sudo.
#   Uninstall (keeps your wallet and settings in ~/.tradebot):
#     bash ~/.local/share/tradebot/install.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/determined-bardeen-vvrlm3"
DEST="$HOME/.local/share/tradebot"
BIN="$HOME/.local/bin/tradebot"
MENU_FILE="$HOME/.local/share/applications/tradebot.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_FILE="$DESKTOP_DIR/tradebot.desktop"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✘\033[0m %s\n' "$*"; }

# Adds or removes Tradebot in the Ubuntu Dock (GNOME's favourite apps). Fails if there's no dock setting.
dock() {
  command -v gsettings >/dev/null 2>&1 || return 1
  local favs new
  favs="$(gsettings get org.gnome.shell favorite-apps 2>/dev/null)" || return 1
  if [[ "$1" == add ]]; then
    [[ "$favs" == *"'tradebot.desktop'"* ]] && return 0
    if [[ "$favs" == "@as []" || "$favs" == "[]" ]]; then new="['tradebot.desktop']"; else new="${favs%]}, 'tradebot.desktop']"; fi
  else
    [[ "$favs" == *"'tradebot.desktop'"* ]] || return 0
    new="$(printf '%s' "$favs" | sed -e "s/, 'tradebot.desktop'//" -e "s/'tradebot.desktop', //" -e "s/'tradebot.desktop'//")"
    [[ "$new" == "[]" ]] && new="@as []"
  fi
  gsettings set org.gnome.shell favorite-apps "$new" 2>/dev/null
}

if [[ "${1:-}" == "--uninstall" ]]; then
  [[ -x "$DEST/venv/bin/tradebot" ]] && "$DEST/venv/bin/tradebot" gui --stop >/dev/null 2>&1 || true
  dock remove || true
  rm -rf "$DEST"
  rm -f "$BIN" "$MENU_FILE" "$DESKTOP_FILE"
  say "Tradebot has been removed."
  if [[ -d "$HOME/.tradebot" ]]; then
    echo "Your settings and the bot's wallet are still in ~/.tradebot."
    echo "Withdraw any funds first before you ever delete that folder: it holds the only key to the bot wallet."
  fi
  exit 0
fi

if [[ $EUID -eq 0 && -z "${TRADEBOT_ALLOW_ROOT:-}" ]]; then
  bad "Please don't run this as root or with sudo."
  echo "    Running as root installs Tradebot for the administrator account, where you can't see or open it."
  echo "    Type exit (or open a new terminal) so the prompt ends with \$ instead of #, then run the command again."
  exit 1
fi

trap 'bad "The install stopped unexpectedly (line $LINENO: $BASH_COMMAND). Please copy everything above and ask for help."' ERR

say "Installing Tradebot"

if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is missing. Install it with: sudo apt install python3"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  bad "Tradebot needs Python 3.10 or newer; you have $(python3 --version 2>&1). Ubuntu 22.04 or newer has it."
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
    bad "Couldn't download Tradebot from GitHub. Check your internet connection and try again."
    exit 1
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/src.tgz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src/tradebot"
  ok "Downloaded Tradebot"
fi

# An update replaces the code the app is running, so close the old version first.
if [[ -x "$DEST/venv/bin/tradebot" ]]; then
  stopped="$("$DEST/venv/bin/tradebot" gui --stop 2>/dev/null || true)"
  if [[ "$stopped" == *"shutting down"* ]]; then
    ok "Closed the running Tradebot (open it again and press Start to resume trading)"
    sleep 3
  fi
fi

mkdir -p "$DEST"
rm -rf "$DEST/src"
cp -r "$SRC" "$DEST/src"
rm -rf "$DEST/src/tests" "$DEST/src/.pytest_cache" "$DEST/src/"*.egg-info
cp "$SRC/install.sh" "$DEST/install.sh"
cp "$SRC/tradebot/ui/icon.svg" "$DEST/tradebot.svg"
chmod +x "$DEST/install.sh"
ok "Copied Tradebot to $DEST"

say "Installing Python packages (a minute or two the first time)…"
[[ -d "$DEST/venv" ]] || python3 -m venv "$DEST/venv"
"$DEST/venv/bin/python" -m pip install --quiet --upgrade pip
"$DEST/venv/bin/python" -m pip install --quiet --upgrade "$DEST/src"
ok "Installed Tradebot and its libraries"

mkdir -p "$(dirname "$BIN")"
ln -sf "$DEST/venv/bin/tradebot" "$BIN"
ok "Added the tradebot command for the terminal ($BIN)"

mkdir -p "$(dirname "$MENU_FILE")"
cat > "$MENU_FILE" <<ENTRY
[Desktop Entry]
Type=Application
Name=Tradebot
Comment=Trend-following crypto trading bot for BNB Chain
Exec="$DEST/venv/bin/tradebot" gui
Icon=$DEST/tradebot.svg
Terminal=false
Categories=Office;Finance;
Keywords=trading;crypto;bot;BNB;bitcoin;
StartupNotify=true
ENTRY
chmod +x "$MENU_FILE"
update-desktop-database "$(dirname "$MENU_FILE")" >/dev/null 2>&1 || true
ok "Added Tradebot to your app list"

if [[ -d "$DESKTOP_DIR" ]]; then
  cp "$MENU_FILE" "$DESKTOP_FILE"
  chmod +x "$DESKTOP_FILE"
  # Ubuntu's desktop only runs launchers marked as trusted.
  gio set "$DESKTOP_FILE" metadata::trusted true >/dev/null 2>&1 || true
  ok "Added a Tradebot icon to your desktop"
fi

if dock add; then
  ok "Pinned Tradebot to the dock"
fi

if check="$("$DEST/venv/bin/tradebot" gui --check 2>&1)"; then
  printf '%s\n' "$check" | sed 's/^/  /'
else
  printf '%s\n' "$check" | sed 's/^/  /'
  bad "Tradebot is installed, but its app won't start. Please copy everything above and ask for help."
  exit 1
fi

echo
say "Done! To open Tradebot later:"
echo "  • Click the green Tradebot icon in the dock (the bar on the left of your screen), or"
echo "  • Press the Super (Windows) key, type “Tradebot” and press Enter, or"
echo "  • Double-click the Tradebot icon on your desktop. If Ubuntu says it isn't allowed to launch,"
echo "    right-click it and choose Allow Launching."
echo "It starts in paper mode: real prices, pretend money."
echo "To uninstall: bash $DEST/install.sh --uninstall"

# Open it now so there's nothing to hunt for.
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" && -z "${TRADEBOT_NO_LAUNCH:-}" ]]; then
  echo
  say "Opening Tradebot now…"
  nohup "$DEST/venv/bin/tradebot" gui >/dev/null 2>&1 &
  disown || true
fi
