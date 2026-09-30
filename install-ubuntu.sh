#!/usr/bin/env bash
# Installs Cloud AI on Ubuntu (or any Linux desktop). No sudo needed.
# It copies the app to ~/.local/share/cloud-ai and adds a "Cloud AI" icon to the desktop and the
# app list. Clicking the icon starts a tiny local web server and opens the app in your browser.
#
#   Install or update:  wget -qO- https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/install-ubuntu.sh | bash
#   Uninstall:          bash ~/.local/share/cloud-ai/install-ubuntu.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/determined-bardeen-vvrlm3"
DEST="$HOME/.local/share/cloud-ai"
MENU_FILE="$HOME/.local/share/applications/cloud-ai.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_FILE="$DESKTOP_DIR/cloud-ai.desktop"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  pkill -f "$DEST/serve.py" 2>/dev/null || true
  rm -rf "$DEST"
  rm -f "$MENU_FILE" "$DESKTOP_FILE"
  say "Cloud AI has been removed."
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Cloud AI needs python3. Install it with: sudo apt install python3" >&2
  exit 1
fi

# Use the files next to this script when it's run from a copy of the repository; otherwise download them.
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$(dirname "$SELF")/index.html" && -d "$(dirname "$SELF")/linux" ]]; then
  SRC="$(cd "$(dirname "$SELF")" && pwd)"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  say "Downloading Cloud AI…"
  if command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP/app.tgz" "$URL"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$TMP/app.tgz" "$URL"
  else
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$URL" "$TMP/app.tgz"
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/app.tgz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src"
fi

say "Installing to $DEST…"
pkill -f "$DEST/serve.py" 2>/dev/null || true # restarted on next launch, serving the new files
rm -rf "$DEST/app"
mkdir -p "$DEST/app"
cp -r "$SRC/index.html" "$SRC/manifest.webmanifest" "$SRC/icons" "$SRC/vendor" "$DEST/app/"
cp "$SRC/linux/serve.py" "$SRC/linux/cloud-ai" "$SRC/install-ubuntu.sh" "$DEST/"
chmod +x "$DEST/cloud-ai" "$DEST/install-ubuntu.sh"

mkdir -p "$(dirname "$MENU_FILE")"
cat > "$MENU_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Cloud AI
Comment=Free AI chat that runs in the cloud
Exec="$DEST/cloud-ai"
Icon=$DEST/app/icons/icon-512.png
Terminal=false
Categories=Network;Chat;Utility;
Keywords=AI;chat;assistant;
StartupNotify=true
EOF
chmod +x "$MENU_FILE"
update-desktop-database "$(dirname "$MENU_FILE")" >/dev/null 2>&1 || true

on_desktop=false
if [[ -d "$DESKTOP_DIR" ]]; then
  cp "$MENU_FILE" "$DESKTOP_FILE"
  chmod +x "$DESKTOP_FILE"
  # Ubuntu's desktop only runs launchers marked as trusted.
  gio set "$DESKTOP_FILE" metadata::trusted true >/dev/null 2>&1 || true
  on_desktop=true
fi

echo
if $on_desktop; then
  say "Done! Double-click “Cloud AI” on your desktop, or find it in your app list."
  echo "If the desktop icon says it isn't allowed to launch, right-click it and choose “Allow Launching”."
else
  say "Done! Open “Cloud AI” from your app list."
fi
echo "To uninstall later: bash $DEST/install-ubuntu.sh --uninstall"
