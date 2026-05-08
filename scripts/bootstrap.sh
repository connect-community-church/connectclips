#!/usr/bin/env bash
# bootstrap.sh -- one-liner ConnectClips installer for Linux/WSL + macOS.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/connect-community-church/connectclips/main/scripts/bootstrap.sh | bash
#
# What this does:
#   1. Detects Linux/WSL vs macOS Apple Silicon
#   2. Installs git if not already present (apt on Linux/WSL, expects
#      Xcode CLT on macOS -- prompts you to run xcode-select --install
#      if it isn't there)
#   3. Clones (or pulls) the repo into ~/ConnectClips
#   4. Hands off to scripts/install-wsl.sh on Linux/WSL or
#      scripts/install-mac.sh on macOS
#
# Override the install dir by setting CONNECTCLIPS_DIR before running:
#   curl -fsSL ... | CONNECTCLIPS_DIR=/opt/connectclips bash

set -euo pipefail

REPO_URL="https://github.com/connect-community-church/connectclips.git"
DIR="${CONNECTCLIPS_DIR:-$HOME/ConnectClips}"

step()  { printf '\033[1;36m[bootstrap]\033[0m %s\n' "$*" >&2; }
fail()  { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

# ----- Detect platform ------------------------------------------------------

OS="$(uname -s)"
case "$OS" in
    Linux)
        PLATFORM=linux
        if grep -qi microsoft /proc/version 2>/dev/null; then
            step "detected: Linux (WSL2)"
        else
            step "detected: Linux"
        fi
        INSTALL_SCRIPT=scripts/install-wsl.sh
        ;;
    Darwin)
        PLATFORM=mac
        if [[ "$(uname -m)" != "arm64" ]]; then
            fail "Apple Silicon (arm64) only. Intel Macs aren't supported by install-mac.sh."
        fi
        step "detected: macOS Apple Silicon"
        INSTALL_SCRIPT=scripts/install-mac.sh
        ;;
    *)
        fail "Unsupported OS '$OS'. For Windows native use bootstrap.ps1."
        ;;
esac

# ----- Step 1: git ----------------------------------------------------------

if ! command -v git >/dev/null 2>&1; then
    if [[ "$PLATFORM" == "linux" ]]; then
        step "installing git via apt..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq git
    else
        # macOS ships a git stub that prompts to install the Xcode Command
        # Line Tools on first invocation. We can't suppress that prompt
        # from inside this script -- if the user hasn't accepted it yet,
        # tell them what to do and bail.
        fail "git not found. On macOS, run: xcode-select --install
       Click through the Apple installer prompt that pops up, then re-run this bootstrap."
    fi
fi
step "using git: $(command -v git)"

# ----- Step 2: clone or pull ------------------------------------------------

if [[ -d "$DIR/.git" ]]; then
    step "$DIR already exists -- pulling latest"
    git -C "$DIR" pull --ff-only
elif [[ -e "$DIR" ]]; then
    fail "$DIR exists but isn't a git repo. Move or rename it, then re-run."
else
    step "cloning into $DIR"
    git clone "$REPO_URL" "$DIR"
fi

# ----- Step 3: hand off to install script -----------------------------------

if [[ ! -f "$DIR/$INSTALL_SCRIPT" ]]; then
    fail "expected $DIR/$INSTALL_SCRIPT after clone, but it's missing."
fi

step "starting $INSTALL_SCRIPT (this is the long part)"
echo
cd "$DIR"
exec bash "$INSTALL_SCRIPT"
