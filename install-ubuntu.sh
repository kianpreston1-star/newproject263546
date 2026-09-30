#!/usr/bin/env bash
# Installs Cloud AI on Ubuntu (or any Linux desktop). No sudo needed.
# It copies the app to ~/.local/share/cloud-ai, adds "Cloud AI" to the app list, the desktop and the
# dock, checks that it works, and opens it. The launcher starts a tiny local web server and opens
# the app in your browser.
#
#   Install or update (uses python3, since newer Ubuntu releases no longer include wget by default):
#     python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/install-ubuntu.sh', '$HOME/install-cloud-ai.sh')" && bash ~/install-cloud-ai.sh
#   Run it as yourself, not as root or with sudo.
#   Uninstall:
#     bash ~/.local/share/cloud-ai/install-ubuntu.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/determined-bardeen-vvrlm3"
DEST="$HOME/.local/share/cloud-ai"
MENU_FILE="$HOME/.local/share/applications/cloud-ai.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_FILE="$DESKTOP_DIR/cloud-ai.desktop"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✘\033[0m %s\n' "$*"; }

# Adds or removes Cloud AI in the Ubuntu Dock (GNOME's favourite apps). Fails if there's no dock setting.
dock() {
  command -v gsettings >/dev/null 2>&1 || return 1
  local favs new
  favs="$(gsettings get org.gnome.shell favorite-apps 2>/dev/null)" || return 1
  if [[ "$1" == add ]]; then
    [[ "$favs" == *"'cloud-ai.desktop'"* ]] && return 0
    if [[ "$favs" == "@as []" || "$favs" == "[]" ]]; then new="['cloud-ai.desktop']"; else new="${favs%]}, 'cloud-ai.desktop']"; fi
  else
    [[ "$favs" == *"'cloud-ai.desktop'"* ]] || return 0
    new="$(printf '%s' "$favs" | sed -e "s/, 'cloud-ai.desktop'//" -e "s/'cloud-ai.desktop', //" -e "s/'cloud-ai.desktop'//")"
    [[ "$new" == "[]" ]] && new="@as []"
  fi
  gsettings set org.gnome.shell favorite-apps "$new" 2>/dev/null
}

if [[ "${1:-}" == "--uninstall" ]]; then
  pkill -f "^python3 $DEST/serve.py" 2>/dev/null || true
  dock remove || true
  rm -rf "$DEST"
  rm -f "$MENU_FILE" "$DESKTOP_FILE"
  say "Cloud AI has been removed."
  exit 0
fi

# Installing as root puts Cloud AI in root's account, where the normal user can't see it, and browsers
# refuse to run as root. (Uninstalling as root is allowed, to clean up such an install.)
if [[ $EUID -eq 0 && -z "${CLOUD_AI_ALLOW_ROOT:-}" ]]; then
  bad "Please don't run this as root or with sudo."
  echo "    Running as root installs Cloud AI for the administrator account, where you can't see or open it."
  echo "    Type exit (or open a new terminal) so the prompt ends with \$ instead of #, then run the command again."
  exit 1
fi

trap 'bad "The install stopped unexpectedly (line $LINENO: $BASH_COMMAND). Please copy everything above and ask for help."' ERR

say "Installing Cloud AI"

if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is missing. Install it with: sudo apt install python3"
  exit 1
fi
ok "Found $(python3 --version 2>&1)"

# Use the files next to this script when it's run from a copy of the repository; otherwise download them.
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$(dirname "$SELF")/index.html" && -d "$(dirname "$SELF")/linux" ]]; then
  SRC="$(cd "$(dirname "$SELF")" && pwd)"
  ok "Using the app files in $SRC"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  if ! python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$URL" "$TMP/app.tgz"; then
    bad "Couldn't download the app from GitHub. Check your internet connection and try again."
    exit 1
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/app.tgz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src"
  ok "Downloaded the app"
fi

pkill -f "^python3 $DEST/serve.py" 2>/dev/null || true # restarted below, serving the new files
rm -rf "$DEST/app"
mkdir -p "$DEST/app"
cp -r "$SRC/index.html" "$SRC/manifest.webmanifest" "$SRC/icons" "$SRC/vendor" "$DEST/app/"
cp "$SRC/linux/serve.py" "$SRC/linux/cloud-ai" "$SRC/install-ubuntu.sh" "$DEST/"
chmod +x "$DEST/cloud-ai" "$DEST/install-ubuntu.sh"
ok "Copied the app to $DEST"

mkdir -p "$(dirname "$MENU_FILE")"
cat > "$MENU_FILE" <<ENTRY
[Desktop Entry]
Type=Application
Name=Cloud AI
Comment=Free AI chat that runs in the cloud
Exec="$DEST/cloud-ai"
Icon=$DEST/app/icons/icon-512.png
Terminal=false
Categories=Network;Chat;
Keywords=AI;chat;assistant;
StartupNotify=true
ENTRY
chmod +x "$MENU_FILE"
update-desktop-database "$(dirname "$MENU_FILE")" >/dev/null 2>&1 || true
ok "Added Cloud AI to your app list"

if [[ -d "$DESKTOP_DIR" ]]; then
  cp "$MENU_FILE" "$DESKTOP_FILE"
  chmod +x "$DESKTOP_FILE"
  # Ubuntu's desktop only runs launchers marked as trusted.
  gio set "$DESKTOP_FILE" metadata::trusted true >/dev/null 2>&1 || true
  ok "Added a Cloud AI icon to your desktop"
fi

if dock add; then
  ok "Pinned Cloud AI to the dock"
fi

if check="$("$DEST/cloud-ai" --check 2>&1)"; then
  printf '%s\n' "$check" | sed 's/^/  /'
else
  printf '%s\n' "$check" | sed 's/^/  /'
  bad "Cloud AI is installed, but its local server won't start. Please copy everything above and ask for help."
  exit 1
fi

echo
say "Done! To open Cloud AI later:"
echo "  • Click the blue cloud icon in the dock (the bar on the left of your screen), or"
echo "  • Press the Super (Windows) key, type “Cloud AI” and press Enter."
echo "To uninstall: bash $DEST/install-ubuntu.sh --uninstall"

# Open it now so there's nothing to hunt for.
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" && -z "${CLOUD_AI_NO_LAUNCH:-}" ]]; then
  echo
  say "Opening Cloud AI now…"
  nohup "$DEST/cloud-ai" >/dev/null 2>&1 &
  disown || true
fi
