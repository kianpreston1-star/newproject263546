#!/usr/bin/env bash
# Installs Trend Clips on Ubuntu (or any Linux desktop). No sudo needed, unless FFmpeg is missing, in which case it
# tells you the one command to run. It sets up its own Python 3.12 (your system Python is left alone), downloads
# the free AI models, walks you through the free keys, turns on the daily run and the Telegram bot, and adds a
# "Trend Clips" icon that makes a video on demand.
#
#   Install or update:
#     python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/refs/heads/claude/trendclips/trendclips/install.sh', '$HOME/install-trendclips.sh')" && bash ~/install-trendclips.sh
#   Run it as yourself, not as root or with sudo.
#   Uninstall (keeps your settings in ~/.trendclips and your videos in ~/Videos/TrendClips):
#     bash ~/.local/share/trendclips/install.sh --uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
BRANCH="claude/trendclips"
DEST="$HOME/.local/share/trendclips"
BIN="$HOME/.local/bin/trendclips"
MENU_FILE="$HOME/.local/share/applications/trendclips.desktop"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_FILE="$DESKTOP_DIR/trendclips.desktop"
UNITS="$HOME/.config/systemd/user"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✘\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now trendclips-run.timer trendclips-bot.service >/dev/null 2>&1 || true
    rm -f "$UNITS/trendclips-run.timer" "$UNITS/trendclips-run.service" "$UNITS/trendclips-bot.service"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
  rm -rf "$DEST"
  rm -f "$BIN" "$MENU_FILE" "$DESKTOP_FILE"
  say "Trend Clips has been removed."
  echo "Your settings and keys are still in ~/.trendclips and your videos in ~/Videos/TrendClips."
  exit 0
fi

if [[ $EUID -eq 0 && -z "${TRENDCLIPS_ALLOW_ROOT:-}" ]]; then
  bad "Please don't run this as root or with sudo."
  echo "    Running as root installs Trend Clips for the administrator account, where you can't see or use it."
  echo "    Type exit (or open a new terminal) so the prompt ends with \$ instead of #, then run the command again."
  exit 1
fi

trap 'bad "The install stopped unexpectedly (line $LINENO: $BASH_COMMAND). Please copy everything above and ask for help."' ERR

say "Installing Trend Clips"

if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is missing. Install it with: sudo apt install python3"
  exit 1
fi
ok "Found $(python3 --version 2>&1)"

if ! command -v ffmpeg >/dev/null 2>&1; then
  bad "FFmpeg (the video engine) is missing. Install it with this command, then run the installer again:"
  echo "      sudo apt install -y ffmpeg"
  exit 1
fi
# Read the whole list first: piping into `grep -q` would cut FFmpeg off mid-write and look like a failure.
FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
if [[ "$FILTERS" != *" ass "* ]]; then
  bad "Your FFmpeg can't draw captions (it was built without libass). Install Ubuntu's version, then run this again:"
  echo "      sudo apt install -y ffmpeg"
  exit 1
fi
ok "Found $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)"

# Use the files next to this script when run from a copy of the repository; otherwise download them.
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$(dirname "$SELF")/pyproject.toml" && -d "$(dirname "$SELF")/trendclips" ]]; then
  SRC="$(cd "$(dirname "$SELF")" && pwd)"
  ok "Using the files in $SRC"
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
  if ! python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$URL" "$TMP/src.tgz"; then
    bad "Couldn't download Trend Clips from GitHub. Check your internet connection and try again."
    exit 1
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/src.tgz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src/trendclips"
  ok "Downloaded Trend Clips"
fi

mkdir -p "$DEST/bin"
# uv is a small, fast Python installer. It brings its own Python 3.12, because the AI libraries don't all support
# the very newest Python yet, and it never touches the system's Python.
if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
elif [[ -x "$DEST/bin/uv" ]]; then
  UV="$DEST/bin/uv"
else
  case "$(uname -m)" in
    x86_64) UV_ARCH="x86_64-unknown-linux-gnu" ;;
    aarch64|arm64) UV_ARCH="aarch64-unknown-linux-gnu" ;;
    *) bad "Unsupported processor: $(uname -m)"; exit 1 ;;
  esac
  python3 - "$UV_ARCH" "$DEST/bin" <<'PY'
import io, sys, tarfile, urllib.request
arch, dest = sys.argv[1], sys.argv[2]
url = f"https://github.com/astral-sh/uv/releases/latest/download/uv-{arch}.tar.gz"
data = urllib.request.urlopen(url, timeout=120).read()
with tarfile.open(fileobj=io.BytesIO(data)) as t:
    for m in t.getmembers():
        if m.name.endswith("/uv") or m.name == "uv":
            m.name = "uv"
            try:
                t.extract(m, dest, filter="data")
            except TypeError:  # Python older than 3.11.4
                t.extract(m, dest)
PY
  chmod +x "$DEST/bin/uv"
  UV="$DEST/bin/uv"
fi
ok "Python installer ready (uv $("$UV" --version 2>/dev/null | cut -d' ' -f2))"

# An update replaces the code the bot is running, so stop it first; the schedule step starts it again.
systemctl --user stop trendclips-bot.service >/dev/null 2>&1 || true

rm -rf "$DEST/src"
cp -r "$SRC" "$DEST/src"
rm -rf "$DEST/src/tests" "$DEST/src/.pytest_cache" "$DEST/src/"*.egg-info
cp "$SRC/install.sh" "$DEST/install.sh"
cp "$SRC/trendclips/icon.svg" "$DEST/trendclips.svg"
chmod +x "$DEST/install.sh"
ok "Copied Trend Clips to $DEST"

say "Installing Python 3.12 and the AI libraries (a few minutes the first time)…"
[[ -x "$DEST/venv/bin/python" ]] || "$UV" venv --quiet --python 3.12 "$DEST/venv"
"$UV" pip install --quiet --python "$DEST/venv/bin/python" --upgrade "$DEST/src"
ok "Installed Trend Clips and its libraries"

mkdir -p "$(dirname "$BIN")"
ln -sf "$DEST/venv/bin/trendclips" "$BIN"
ok "Added the trendclips command ($BIN)"

mkdir -p "$(dirname "$MENU_FILE")"
cat > "$MENU_FILE" <<ENTRY
[Desktop Entry]
Type=Application
Name=Trend Clips
Comment=Make a short video about what's trending right now
Exec=bash -c '"$DEST/venv/bin/trendclips" make --open; echo; read -rp "Press Enter to close this window… "'
Icon=$DEST/trendclips.svg
Terminal=true
Categories=AudioVideo;Video;
Keywords=video;shorts;tiktok;trending;AI;
ENTRY
chmod +x "$MENU_FILE"
update-desktop-database "$(dirname "$MENU_FILE")" >/dev/null 2>&1 || true
ok "Added Trend Clips to your app list"

if [[ -d "$DESKTOP_DIR" ]]; then
  cp "$MENU_FILE" "$DESKTOP_FILE"
  chmod +x "$DESKTOP_FILE"
  # Desktops only run launchers marked as trusted: GNOME checks a flag, XFCE a checksum of the file.
  gio set "$DESKTOP_FILE" metadata::trusted true >/dev/null 2>&1 || true
  gio set "$DESKTOP_FILE" metadata::xfce-exe-checksum "$(sha256sum "$DESKTOP_FILE" | cut -d' ' -f1)" >/dev/null 2>&1 || true
  ok "Added a Trend Clips icon to your desktop"
fi

echo
if [[ -t 0 && -z "${TRENDCLIPS_NO_SETUP:-}" ]]; then
  "$DEST/venv/bin/trendclips" setup
else
  "$DEST/venv/bin/trendclips" setup --downloads-only
  echo "  Run 'trendclips setup' to enter your free keys."
fi

echo
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  "$DEST/venv/bin/trendclips" schedule on | sed 's/^/  /'
else
  echo "  This computer has no systemd user session, so the daily run isn't scheduled. See the README for cron."
fi

echo
say "Done! What happens now:"
echo "  • Every day at the scheduled time, Trend Clips makes new videos and sends them to Telegram for you to approve."
echo "  • To make one right now: double-click Trend Clips on the desktop, send /make to your bot,"
echo "    or type: trendclips make"
echo "  • To check everything is working: trendclips check"
echo "  • Videos are saved in ~/Videos/TrendClips"
echo "If 'trendclips' isn't found in a terminal, log out and back in once (Ubuntu adds ~/.local/bin to your PATH then)."
echo "To uninstall: bash $DEST/install.sh --uninstall"
