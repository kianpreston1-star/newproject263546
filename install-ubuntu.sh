#!/usr/bin/env bash
# Installs Cloud AI on Ubuntu (or any Linux desktop). No sudo needed.
# It copies the app to ~/.local/share/cloud-ai and adds a "Cloud AI" icon to the desktop and the
# app list. Clicking the icon starts a tiny local web server and opens the app in your browser.
#
#   Install or update:  wget -nv -O /tmp/install-cloud-ai.sh https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/install-ubuntu.sh && bash /tmp/install-cloud-ai.sh
#   Uninstall:          bash ~/.local/share/cloud-ai/install-ubuntu.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/determined-bardeen-vvrlm3"
DEST="$HOME/.local/share/cloud-ai"
MENU_FILE="$HOME/.local/share/applications/cloud-ai.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_FILE="$DESKTOP_DIR/cloud-ai.desktop"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# Adds or removes Cloud AI in the Ubuntu Dock (GNOME's favourite apps).
dock() {
  command -v gsettings >/dev/null 2>&1 || return 0
  local favs new
  favs="$(gsettings get org.gnome.shell favorite-apps 2>/dev/null)" || return 0
  if [[ "$1" == add ]]; then
    [[ "$favs" == *"'cloud-ai.desktop'"* ]] && return 0
    if [[ "$favs" == "@as []" || "$favs" == "[]" ]]; then new="['cloud-ai.desktop']"; else new="${favs%]}, 'cloud-ai.desktop']"; fi
  else
    [[ "$favs" == *"'cloud-ai.desktop'"* ]] || return 0
    new="$(printf '%s' "$favs" | sed -e "s/, 'cloud-ai.desktop'//" -e "s/'cloud-ai.desktop', //" -e "s/'cloud-ai.desktop'//")"
    [[ "$new" == "[]" ]] && new="@as []"
  fi
  gsettings set org.gnome.shell favorite-apps "$new" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
  pkill -f "^python3 $DEST/serve.py" 2>/dev/null || true
  dock remove
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
pkill -f "^python3 $DEST/serve.py" 2>/dev/null || true # restarted on next launch, serving the new files
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
Categories=Network;Chat;
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

dock add

echo
say "Done! Cloud AI is installed."
echo "You can open it any of these ways:"
echo "  • Click the blue cloud icon in the dock (the bar on the left of your screen)."
echo "  • Press the Super (Windows) key, type “Cloud AI” and press Enter."
if $on_desktop; then
  echo "  • Double-click “Cloud AI” on your desktop (press Super+D to hide windows and see it)."
  echo "    If it says it isn't allowed to launch, right-click it and choose “Allow Launching”."
fi
echo "  • Or run: $DEST/cloud-ai"
echo
echo "To uninstall later: bash $DEST/install-ubuntu.sh --uninstall"

# Open it now so there's nothing to hunt for.
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" && -z "${CLOUD_AI_NO_LAUNCH:-}" ]]; then
  echo
  say "Opening Cloud AI…"
  nohup "$DEST/cloud-ai" >/dev/null 2>&1 &
  disown || true
fi
