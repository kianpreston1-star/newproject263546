#!/usr/bin/env bash
# Installs Date Night Picker on Ubuntu (any desktop: XFCE, GNOME, ...). It adds the app to your menu
# and puts a launcher icon on the desktop, checks that it opens, and opens it.
#
#   Install or update:
#     python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/determined-bardeen-vvrlm3/datenight/install.sh', '$HOME/install-datenight.sh')" && bash ~/install-datenight.sh
#   Run it as yourself, not as root or with sudo.
#   Uninstall:
#     bash ~/.local/share/datenight/install.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/determined-bardeen-vvrlm3"
DEST="$HOME/.local/share/datenight"
MENU_FILE="$HOME/.local/share/applications/datenight.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_FILE="$DESKTOP_DIR/datenight.desktop"
FILES=(datenight.py ideas.json icon.svg install.sh)

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✘\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$DEST" "$HOME/.config/datenight"
  rm -f "$MENU_FILE" "$DESKTOP_FILE"
  say "Date Night Picker has been removed."
  exit 0
fi

if [[ $EUID -eq 0 ]]; then
  bad "Please don't run this as root or with sudo."
  echo "    Type exit (or open a new terminal) so the prompt ends with \$ instead of #, then run the command again."
  exit 1
fi

trap 'bad "The install stopped unexpectedly (line $LINENO: $BASH_COMMAND). Please copy everything above and ask for help."' ERR

say "Installing Date Night Picker"

if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is missing. Install it with: sudo apt install python3"
  exit 1
fi
ok "Found $(python3 --version 2>&1)"

# Ubuntu doesn't always include Tkinter, the window toolkit the app uses.
if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  echo "  Tkinter (the window toolkit) isn't installed. Installing it needs your password:"
  if [[ -t 0 ]] && command -v sudo >/dev/null 2>&1 && sudo apt-get install -y python3-tk; then
    :
  else
    bad "Couldn't install Tkinter. Run this, then run the installer again:"
    echo "      sudo apt install python3-tk"
    exit 1
  fi
fi
ok "Tkinter is available"

# Use the files next to this script when run from a copy of the repository; otherwise download them.
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$(dirname "$SELF")/datenight.py" && -f "$(dirname "$SELF")/ideas.json" ]]; then
  SRC="$(cd "$(dirname "$SELF")" && pwd)"
  ok "Using the files in $SRC"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  if ! python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$URL" "$TMP/src.tgz"; then
    bad "Couldn't download Date Night Picker from GitHub. Check your internet connection and try again."
    exit 1
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/src.tgz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src/datenight"
  ok "Downloaded Date Night Picker"
fi

mkdir -p "$DEST"
# Keep a copy of ideas you've added yourself before an update replaces the list.
if [[ -f "$DEST/ideas.json" ]] && ! cmp -s "$DEST/ideas.json" "$SRC/ideas.json"; then
  cp "$DEST/ideas.json" "$DEST/ideas.json.bak"
  ok "Saved your old ideas list as $DEST/ideas.json.bak"
fi
for f in "${FILES[@]}"; do cp "$SRC/$f" "$DEST/$f"; done
chmod +x "$DEST/datenight.py" "$DEST/install.sh"
ok "Copied the app to $DEST"

mkdir -p "$(dirname "$MENU_FILE")"
cat > "$MENU_FILE" <<ENTRY
[Desktop Entry]
Type=Application
Name=Date Night Picker
Comment=Pick a date night idea near Fleckney
Exec=python3 "$DEST/datenight.py"
Icon=$DEST/icon.svg
Terminal=false
Categories=Utility;
Keywords=date;night;ideas;girlfriend;random;
StartupNotify=true
StartupWMClass=Datenight
ENTRY
chmod +x "$MENU_FILE"
update-desktop-database "$(dirname "$MENU_FILE")" >/dev/null 2>&1 || true
ok "Added Date Night Picker to your app menu"

if [[ -d "$DESKTOP_DIR" ]]; then
  cp "$MENU_FILE" "$DESKTOP_FILE"
  chmod +x "$DESKTOP_FILE"
  # XFCE only runs desktop launchers whose checksum it has been told to trust; GNOME uses a trusted flag.
  gio set "$DESKTOP_FILE" metadata::xfce-exe-checksum "$(sha256sum "$DESKTOP_FILE" | cut -d' ' -f1)" >/dev/null 2>&1 || true
  gio set "$DESKTOP_FILE" metadata::trusted true >/dev/null 2>&1 || true
  ok "Added a Date Night Picker icon to your desktop"
fi

if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  if check="$(python3 "$DEST/datenight.py" --check 2>&1)"; then
    ok "$check"
  else
    printf '%s\n' "$check" | sed 's/^/  /'
    bad "The app is installed, but its window won't open. Please copy everything above and ask for help."
    exit 1
  fi
fi

echo
say "Done! To open Date Night Picker later:"
echo "  • Double-click the pink heart icon on your desktop. If it asks whether to trust or launch it,"
echo "    choose Launch Anyway / Mark Executable, or"
echo "  • Open the app menu and look under Accessories (or search for “Date Night”)."
echo "To uninstall: bash $DEST/install.sh --uninstall"

if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" && -z "${DATENIGHT_NO_LAUNCH:-}" ]]; then
  echo
  say "Opening Date Night Picker now…"
  nohup python3 "$DEST/datenight.py" >/dev/null 2>&1 &
  disown || true
fi
