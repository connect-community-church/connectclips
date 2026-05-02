#!/usr/bin/env bash
# install-mac.sh — automate ConnectClips install on macOS / Apple Silicon.
#
# Idempotent: safe to re-run after a partial failure. Each step detects
# existing state and skips work that's already done.
#
# Run from inside a ConnectClips checkout (you must `git clone` first).
# Will prompt twice: once for your Anthropic API key, once for an admin
# password. To run non-interactively, set CONNECTCLIPS_API_KEY and
# CONNECTCLIPS_ADMIN_PASSWORD in the environment.
#
# Optional env overrides:
#   CONNECTCLIPS_DATA_ROOT   default $HOME/ConnectClips-data
#   CONNECTCLIPS_PORT        default 8765
#
# This script does NOT install Tailscale, configure remote access, or sign
# you in to anything. See step 10 of docs/DEPLOYING-mac.md for that.

set -euo pipefail

# ----- Globals ---------------------------------------------------------------

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_ROOT="${CONNECTCLIPS_DATA_ROOT:-$HOME/ConnectClips-data}"
PORT="${CONNECTCLIPS_PORT:-8765}"

# Brew-managed paths we'll use throughout. /opt/homebrew is the canonical
# arm64 prefix; we install Homebrew there if it's missing.
BREW_PREFIX="/opt/homebrew"
BREW="$BREW_PREFIX/bin/brew"

# ----- Logging ---------------------------------------------------------------

is_tty=0; [[ -t 2 ]] && is_tty=1
clr() { [[ $is_tty -eq 1 ]] && printf '\033[%sm' "$1"; }
log()  { printf '%b[install]%b %s\n' "$(clr '1;34')" "$(clr 0)" "$*" >&2; }
warn() { printf '%b[install:warn]%b %s\n' "$(clr '1;33')" "$(clr 0)" "$*" >&2; }
fail() { printf '%b[install:fail]%b %s\n' "$(clr '1;31')" "$(clr 0)" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ----- Preflight -------------------------------------------------------------

[[ "$(uname -s)" == "Darwin" ]] || fail "macOS only — for WSL/Linux use scripts/install-wsl.sh"
[[ "$(uname -m)" == "arm64" ]]  || fail "Apple Silicon only (Intel Macs are out of scope for v0.2)"
[[ -f "$REPO_DIR/backend/requirements.txt" ]] \
    || fail "Couldn't find backend/requirements.txt — run this from inside a ConnectClips clone."

# ----- Steps -----------------------------------------------------------------

step_xcode_clt() {
    log "[1/11] Xcode toolchain"
    if xcode-select -p >/dev/null 2>&1; then
        log "  using $(xcode-select -p)"
        return
    fi
    warn "  Xcode tools not found — triggering Apple's GUI installer"
    xcode-select --install || true
    fail "Click through the CLT installer dialog, wait for it to finish, then re-run this script."
}

prime_sudo() {
    # The Homebrew installer needs sudo to chown /opt/homebrew. With
    # NONINTERACTIVE=1 it can't prompt for a password — it just bails with
    # the misleading "Need sudo access on macOS" error if there's no cached
    # credential. So we prime the cache here, prompting once if needed.
    if sudo -n true 2>/dev/null; then
        return
    fi
    log "Sudo needed for Homebrew install. You'll be prompted once."
    sudo -v
    # Keep the cache warm in the background so a slow brew install doesn't
    # let the credential expire mid-install.
    ( while true; do sudo -n true 2>/dev/null || exit; sleep 60; done ) &
    SUDO_REFRESH_PID=$!
    # shellcheck disable=SC2064
    trap "kill $SUDO_REFRESH_PID 2>/dev/null || true" EXIT
}

step_homebrew() {
    log "[2/11] arm64 Homebrew"
    if [[ -x "$BREW" ]]; then
        log "  $BREW already installed"
    else
        prime_sudo
        warn "  installing Homebrew"
        NONINTERACTIVE=1 /bin/bash -c \
            "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    eval "$("$BREW" shellenv)"
    [[ "$(brew --prefix)" == "$BREW_PREFIX" ]] \
        || fail "brew --prefix is not $BREW_PREFIX after install — something went sideways."
}

step_system_packages() {
    log "[3/11] System packages"

    # ffmpeg-full pulls libass + libfreetype + fontconfig (load-bearing for
    # caption burn-in). The default 'ffmpeg' bottle on Tahoe ships without
    # libass and exports die with BrokenPipeError when the subtitles= filter
    # isn't present. expat is needed for the python@3.12 pyexpat fix in [4/11].
    local pkgs=(python@3.12 node ffmpeg-full yt-dlp git expat)
    for p in "${pkgs[@]}"; do
        if brew list --versions "$p" >/dev/null 2>&1; then
            log "  $p already installed"
        else
            log "  installing $p..."
            brew install "$p"
        fi
    done

    # ffmpeg-full is keg-only by design; force-link so 'ffmpeg' resolves to it.
    brew link --overwrite --force ffmpeg-full >/dev/null 2>&1 || true

    # Verify the two capabilities the export pipeline needs.
    have ffmpeg || fail "ffmpeg not on PATH after install"
    ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_videotoolbox \
        || fail "ffmpeg lacks h264_videotoolbox — wrong build linked?"
    ffmpeg -hide_banner -h filter=subtitles 2>/dev/null | grep -q "Render text" \
        || fail "ffmpeg subtitles filter missing — ffmpeg-full not linked correctly. \
Try: brew remove ffmpeg && brew link --overwrite --force ffmpeg-full"
}

step_pyexpat_patch() {
    log "[4/11] Tahoe pyexpat ABI patch (only if needed)"

    # Brew's python@3.12 bottle on Tahoe is built against newer libexpat than
    # what ships in the OS dyld shared cache, so 'pip' / 'ensurepip' can fail
    # with `Symbol not found: _XML_SetAllocTrackerActivationThreshold`.
    # We detect the failure by trying ensurepip; only patch on the known
    # symbol error so we don't mask unrelated breakage.
    local err
    if err=$("$BREW_PREFIX/bin/python3.12" -m ensurepip --version 2>&1); then
        log "  pyexpat works — no patch needed"
        return
    fi

    if ! grep -q "_XML_Set" <<< "$err"; then
        printf '%s\n' "$err" >&2
        fail "ensurepip fails for an unexpected reason (not the libexpat symbol). \
See above output."
    fi

    local py_prefix pyexpat
    py_prefix="$(brew --prefix python@3.12)"
    pyexpat="$py_prefix/Frameworks/Python.framework/Versions/3.12/lib/python3.12/lib-dynload/pyexpat.cpython-312-darwin.so"
    [[ -f "$pyexpat" ]] || fail "pyexpat.so not found at $pyexpat"

    log "  patching pyexpat to use brew expat (instead of system libexpat)"
    install_name_tool -change \
        /usr/lib/libexpat.1.dylib \
        "$BREW_PREFIX/opt/expat/lib/libexpat.1.dylib" \
        "$pyexpat"
    codesign --force --sign - "$pyexpat" 2>/dev/null

    "$BREW_PREFIX/bin/python3.12" -m ensurepip --version >/dev/null 2>&1 \
        || fail "patch applied but ensurepip still fails — see project_macos_brew_pyexpat memory"

    log "  patched"
    warn "  this patch is reverted by 'brew upgrade python@3.12' — re-run this script if that happens"
}

step_venv_pip() {
    log "[5/11] Backend venv + pip install"
    cd "$REPO_DIR/backend"

    # If a non-arm64 venv exists from a previous (Intel-brew) attempt, blow
    # it away and rebuild — its python binary won't dlopen Metal correctly.
    if [[ -d .venv ]]; then
        local arch
        arch=$(file .venv/bin/python 2>/dev/null | grep -oE 'arm64|x86_64' | head -1)
        if [[ "$arch" != "arm64" ]]; then
            warn "  existing .venv is $arch — recreating as arm64"
            rm -rf .venv
        fi
    fi

    if [[ ! -d .venv ]]; then
        "$BREW_PREFIX/bin/python3.12" -m venv .venv
    fi

    .venv/bin/pip install --upgrade --quiet pip wheel
    log "  installing requirements (pywhispercpp compiles whisper.cpp from source — ~5-10 min)"
    .venv/bin/pip install --quiet -r requirements.txt
}

step_yunet_model() {
    log "[6/11] YuNet face detector"
    local target="$HOME/.cache/connectclips/face_detection_yunet_2023mar.onnx"
    if [[ -f "$target" ]] && (( $(stat -f%z "$target") > 200000 )); then
        log "  already downloaded ($(($(stat -f%z "$target") / 1024)) KB)"
        return
    fi
    mkdir -p "$(dirname "$target")"
    curl -fsSL -o "$target" \
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
}

step_data_dirs() {
    log "[7/11] Data directories"
    mkdir -p "$DATA_ROOT"/sources "$DATA_ROOT"/work "$DATA_ROOT"/clips
    log "  $DATA_ROOT/{sources,work,clips}"
}

step_env_file() {
    log "[8/11] backend/.env"
    cd "$REPO_DIR/backend"

    if [[ -f .env ]]; then
        log "  existing .env preserved (delete it if you want to redo this step)"
        return
    fi

    local api_key admin_pw session_secret

    if [[ -n "${CONNECTCLIPS_API_KEY:-}" ]]; then
        api_key="$CONNECTCLIPS_API_KEY"
    else
        [[ $is_tty -eq 1 ]] || fail "Need an API key. Either run interactively or set CONNECTCLIPS_API_KEY."
        printf '\nEnter your Anthropic API key (sk-ant-...): ' >&2
        IFS= read -rs api_key
        echo >&2
    fi
    [[ -n "$api_key" ]] || fail "API key cannot be empty"
    [[ "$api_key" == sk-ant-* ]] \
        || warn "  API key doesn't start with 'sk-ant-' — make sure that's intended"

    if [[ -n "${CONNECTCLIPS_ADMIN_PASSWORD:-}" ]]; then
        admin_pw="$CONNECTCLIPS_ADMIN_PASSWORD"
    else
        [[ $is_tty -eq 1 ]] || fail "Need an admin password. Either run interactively or set CONNECTCLIPS_ADMIN_PASSWORD."
        printf 'Choose an admin password: ' >&2
        IFS= read -rs admin_pw
        echo >&2
    fi
    [[ -n "$admin_pw" ]] || fail "admin password cannot be empty"

    session_secret="$("$BREW_PREFIX/bin/python3.12" -c 'import secrets; print(secrets.token_urlsafe(32))')"

    umask 077
    cat > .env <<EOF
# ConnectClips backend config — generated by scripts/install-mac.sh
DATA_SOURCES_DIR=$DATA_ROOT/sources
DATA_WORK_DIR=$DATA_ROOT/work
DATA_CLIPS_DIR=$DATA_ROOT/clips

ANTHROPIC_API_KEY=$api_key
CLAUDE_MODEL=claude-sonnet-4-6

WHISPER_MODEL=large-v3
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=auto
WHISPER_BACKEND=auto

ADMIN_PASSWORD=$admin_pw
SESSION_SECRET=$session_secret
ADMIN_TAILSCALE_LOGINS=
EOF
    chmod 600 .env
    log "  written (mode 600)"
}

step_frontend_build() {
    log "[9/11] Frontend build"
    cd "$REPO_DIR/frontend"
    if [[ ! -d node_modules ]]; then
        log "  npm install..."
        npm install --silent
    fi
    log "  npm run build..."
    npm run build --silent
    [[ -f dist/index.html ]] || fail "Frontend build didn't produce dist/index.html"
}

step_smoke_test() {
    log "[10/11] Smoke test (start uvicorn briefly + curl /api/health)"
    cd "$REPO_DIR/backend"

    # If something's already on the port (e.g. a launchd-managed instance),
    # don't fight with it — just verify it answers /api/health.
    if lsof -nP -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        log "  port $PORT already bound — testing existing instance"
        curl -fsS "http://127.0.0.1:$PORT/api/health" > /tmp/connectclips-install-health.json \
            || fail "Existing process on port $PORT but /api/health didn't answer."
    else
        local logfile="/tmp/connectclips-install-smoke.log"
        .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
            > "$logfile" 2>&1 &
        local pid=$!
        # Make sure we tear down on any exit path from here on. We want $pid
        # to expand NOW (it's local to this function and out of scope at fire
        # time), not at trap-fire time — hence the explicit shellcheck silence.
        # shellcheck disable=SC2064
        trap "kill $pid 2>/dev/null || true" RETURN

        # 120 s gives the smaller-RAM Macs (M1/M2 8-16 GB) enough time for
        # a cold-start import of faster_whisper + pywhispercpp + onnxruntime
        # + opencv. On a warm machine this loop exits in <5 s.
        local ok=0
        for _ in {1..120}; do
            if curl -fsS "http://127.0.0.1:$PORT/api/health" \
                > /tmp/connectclips-install-health.json 2>/dev/null
            then
                ok=1; break
            fi
            sleep 1
        done

        if [[ $ok -eq 0 ]]; then
            cat "$logfile" >&2 || true
            fail "Smoke test failed after 120 s — uvicorn didn't respond. Log: $logfile"
        fi

        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        trap - RETURN
    fi

    grep -q '"h264_encoder": "h264_videotoolbox"' /tmp/connectclips-install-health.json \
        || warn "  /api/health didn't report h264_videotoolbox — encoder may be wrong"
    grep -q '"CoreMLExecutionProvider"' /tmp/connectclips-install-health.json \
        || warn "  /api/health didn't report CoreMLExecutionProvider — face detection on CPU"
    log "  /api/health 200 OK"
}

step_launchd() {
    log "[11/11] launchd autostart"
    local plist="$HOME/Library/LaunchAgents/com.connectclips.plist"

    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

    if [[ -f "$plist" ]]; then
        log "  $plist exists — unloading old version before rewriting"
        launchctl unload "$plist" 2>/dev/null || true
    fi

    cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.connectclips</string>

  <key>ProgramArguments</key>
  <array>
    <string>$REPO_DIR/backend/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string><string>0.0.0.0</string>
    <string>--port</string><string>$PORT</string>
    <string>--log-level</string><string>warning</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$REPO_DIR/backend</string>

  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>

  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/connectclips.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/connectclips.log</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key>
    <string>$REPO_DIR/backend/.venv/bin:$BREW_PREFIX/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF

    launchctl load "$plist"
    sleep 2

    if launchctl list 2>/dev/null | grep -q com.connectclips; then
        log "  loaded — backend now running under launchd"
    else
        warn "  launchctl list didn't show com.connectclips. Check ~/Library/Logs/connectclips.log"
    fi
}

main() {
    log "ConnectClips macOS install — repo at $REPO_DIR"
    log "Data dirs: $DATA_ROOT (set CONNECTCLIPS_DATA_ROOT to override)"
    log "Port: $PORT"

    step_xcode_clt
    step_homebrew
    step_system_packages
    step_pyexpat_patch
    step_venv_pip
    step_yunet_model
    step_data_dirs
    step_env_file
    step_frontend_build
    step_smoke_test
    step_launchd

    log ""
    log "Install complete. Open http://localhost:$PORT/"
    log "Backend logs: tail -f ~/Library/Logs/connectclips.log"
    log "For Tailscale remote access, see step 10 of docs/DEPLOYING-mac.md"
}

main "$@"
