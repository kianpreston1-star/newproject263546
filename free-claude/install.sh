#!/usr/bin/env bash
# Installs free-claude: Claude Code running on free AI models, with automatic switching.
#
# It checks what your computer already has, installs Claude Code if it's missing, adds a small
# local router (~/.local/share/free-claude/router.py, Python standard library only), asks for free
# API keys, and creates two commands:
#   claude-free          Claude Code on free models (starts in bypass-permissions mode)
#   claude-free-router   status, logs, keys, restart, update, uninstall
#
#   Install or update (uses python3, since newer Ubuntu releases no longer include wget by default):
#     python3 -c "import urllib.request as u; u.urlretrieve('https://raw.githubusercontent.com/kianpreston1-star/newproject263546/claude/keen-dirac-yp8pmx/free-claude/install.sh', '/tmp/free-claude-install.sh')" && bash /tmp/free-claude-install.sh
#   Run it as yourself, not as root or with sudo.
#   Uninstall:
#     claude-free-router uninstall
set -euo pipefail

REPO="kianpreston1-star/newproject263546"
REFS=("HEAD" "claude/keen-dirac-yp8pmx")  # the default branch first, then the branch this was built on
DEST="$HOME/.local/share/free-claude"
BIN="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
MIN_CLAUDE="2.1.273"  # first version that tells the router what each request is for

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✔\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✘\033[0m %s\n' "$*"; }
note() { printf '  \033[33m!\033[0m %s\n' "$*"; }
ask() { local a; read -r -p "  $1 " a </dev/tty || a=""; [[ "${a:-$2}" =~ ^[Yy] ]]; }

if [[ "${1:-}" == "--uninstall" ]]; then
  if [[ -f "$DEST/router.py" ]]; then exec python3 "$DEST/router.py" uninstall; fi
  echo "free-claude isn't installed."
  exit 0
fi

# Claude Code refuses bypass-permissions mode as root, and a root install lands in the wrong home folder.
if [[ $EUID -eq 0 ]]; then
  bad "Please don't run this as root or with sudo."
  echo "    Type exit (or open a new terminal) so the prompt ends with \$ instead of #, then run the command again."
  exit 1
fi

trap 'bad "The install stopped unexpectedly (line $LINENO: $BASH_COMMAND). Please copy everything above and ask for help."' ERR

say "Checking your computer"
if [[ -r /etc/os-release ]]; then ok "$(. /etc/os-release; echo "${PRETTY_NAME:-Linux}") on $(uname -m)"; fi

if ! command -v python3 >/dev/null 2>&1; then
  bad "python3 is missing. Install it with: sudo apt install python3"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))'; then
  bad "$(python3 --version 2>&1) is too old; free-claude needs Python 3.8 or newer."
  exit 1
fi
ok "Found $(python3 --version 2>&1)"

fetch() {  # fetch URL FILE, with Python so neither curl nor wget is needed
  python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2" 2>/dev/null
}

if python3 -c 'import urllib.request as u; u.urlopen("https://integrate.api.nvidia.com/v1/models", timeout=15)' 2>/dev/null; then
  ok "Internet connection works"
else
  bad "Couldn't reach the internet (integrate.api.nvidia.com). Check your connection and try again."
  exit 1
fi

say "Claude Code"
export PATH="$BIN:$PATH"
if ! command -v claude >/dev/null 2>&1; then
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    note "Claude Code's installer needs curl, which isn't installed."
    if ask "Install curl now with sudo (asks for your password)? [Y/n]" y; then
      sudo apt-get install -y curl
    else
      bad "Install curl with: sudo apt install curl   then run this again."
      exit 1
    fi
  fi
  echo "  Installing Claude Code with its official installer…"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://claude.ai/install.sh | bash
  else
    wget -qO- https://claude.ai/install.sh | bash
  fi
  hash -r
  if ! command -v claude >/dev/null 2>&1; then
    bad "Claude Code didn't install. Copy everything above and ask for help."
    exit 1
  fi
fi
version="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
if [[ -n "$version" && "$(printf '%s\n%s\n' "$MIN_CLAUDE" "$version" | sort -V | head -1)" != "$MIN_CLAUDE" ]]; then
  echo "  Claude Code $version is older than $MIN_CLAUDE; updating it…"
  claude update || note "Couldn't update Claude Code. It still works, but routing works best on $MIN_CLAUDE or newer."
  version="$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
fi
ok "Claude Code ${version:-installed} ($(command -v claude))"

say "Installing the router"
mkdir -p "$DEST" "$BIN"
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$(dirname "$SELF")/router.py" ]]; then
  cp "$(dirname "$SELF")/router.py" "$DEST/router.py.new"
  ok "Using router.py next to this script"
else
  got=""
  for ref in "${REFS[@]}"; do
    if fetch "https://raw.githubusercontent.com/$REPO/$ref/free-claude/router.py" "$DEST/router.py.new"; then got="$ref"; break; fi
  done
  if [[ -z "$got" ]]; then
    bad "Couldn't download the router from GitHub. Check your connection and try again."
    exit 1
  fi
  ok "Downloaded the router"
fi
if ! python3 -m py_compile "$DEST/router.py.new"; then
  bad "The downloaded router is damaged. Please run the command again."
  exit 1
fi
mv "$DEST/router.py.new" "$DEST/router.py"
chmod +x "$DEST/router.py"
rm -rf "$DEST/__pycache__"
ok "Router $(python3 "$DEST/router.py" version) in $DEST"

cat > "$BIN/claude-free" <<'LAUNCHER'
#!/usr/bin/env bash
# claude-free: Claude Code on free models through the local free-claude router.
# Made by the free-claude installer. Remove with: claude-free-router uninstall
ROUTER="$HOME/.local/share/free-claude/router.py"
export PATH="$HOME/.local/bin:$PATH"
if [[ ! -f "$ROUTER" ]]; then
  echo "free-claude isn't installed (missing $ROUTER). Run the installer again." >&2
  exit 1
fi
python3 "$ROUTER" ensure || exit 1
eval "$(python3 "$ROUTER" env)" || exit 1
args=()
case " $* " in
  *" --permission-mode"* | *" --dangerously-skip-permissions "*) ;;  # you chose a mode yourself
  *) if [[ -n "$FREE_CLAUDE_PERMISSION_MODE" && "$FREE_CLAUDE_PERMISSION_MODE" != default ]]; then
       args+=(--permission-mode "$FREE_CLAUDE_PERMISSION_MODE")
     fi ;;
esac
if [[ "${FREE_CLAUDE_STATUSLINE:-1}" != 0 ]]; then args+=(--settings "$FREE_CLAUDE_SETTINGS"); fi
exec claude "${args[@]}" "$@"
LAUNCHER
cat > "$BIN/claude-free-router" <<'MANAGER'
#!/usr/bin/env bash
# claude-free-router: status, logs, keys, restart, update and uninstall for free-claude.
# Made by the free-claude installer.
exec python3 "$HOME/.local/share/free-claude/router.py" "$@"
MANAGER
chmod +x "$BIN/claude-free" "$BIN/claude-free-router"
ok "Added the commands claude-free and claude-free-router"

# The earlier one-provider setup added a claude-free alias, which would hide the new command.
if [[ -f "$HOME/.bashrc" ]] && grep -q 'claude-openrouter.env' "$HOME/.bashrc"; then
  cp "$HOME/.bashrc" "$HOME/.bashrc.before-free-claude"
  sed -i '/claude-openrouter\.env/d' "$HOME/.bashrc"
  ok "Removed the old claude-free alias from ~/.bashrc (backup: ~/.bashrc.before-free-claude)"
fi
if ! grep -qs '\.local/bin' "$HOME/.bashrc"; then
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
  ok "Added ~/.local/bin to your PATH in ~/.bashrc"
fi

# A user service restarts the router if it ever crashes. claude-free starts it when needed, so
# nothing runs at login.
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/free-claude-router.service" <<UNIT
[Unit]
Description=free-claude router (lets Claude Code use free models)

[Service]
ExecStart=$(command -v python3) %h/.local/share/free-claude/router.py serve
Restart=on-failure
RestartSec=3
UNIT
  systemctl --user daemon-reload
  ok "Set up the background service"
fi

say "Free API keys"
if ! python3 "$DEST/router.py" keys; then
  bad "free-claude needs at least one key. Add one any time with: claude-free-router keys"
  exit 1
fi

say "Testing"
python3 "$DEST/router.py" restart >/dev/null 2>&1 || true
if python3 "$DEST/router.py" selftest; then
  ok "The router answers through your free providers"
else
  note "The test request didn't go through. Your keys are saved; see claude-free-router status for details."
fi

trap - ERR
say "Done!"
echo "  Open a new terminal (so the new commands are found), go to a project folder and run:"
printf '\n      \033[1mclaude-free\033[0m\n\n'
echo "  • It starts in bypass-permissions mode: Claude acts without asking first, so work inside a"
echo "    git repository you can roll back. Claude Code shows a one-time warning to accept."
echo "  • Pick a model with /model: Free · Auto (default, picks per task), Free · Smart, Free · Fast."
echo "  • The status line at the bottom shows which free model answered and when it swapped."
echo "  • claude-free-router status   which providers are working or resting, and why"
echo "    claude-free-router logs -f  every request: the tier, the model, and any swaps"
echo "    claude-free-router keys     add more free keys (more keys = more free requests a day)"
echo "    claude-free-router uninstall"
