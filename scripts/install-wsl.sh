#!/usr/bin/env bash
# install-wsl.sh — automate ConnectClips install on WSL2/Ubuntu (or any
# pure Ubuntu 24.04 box, with or without an NVIDIA GPU).
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
#   CONNECTCLIPS_DATA_ROOT  default /mnt/c/ConnectClips-data on WSL,
#                                   $HOME/ConnectClips-data elsewhere
#   CONNECTCLIPS_PORT       default 8765
#
# This script does NOT configure the Windows-side autostart trigger
# (Task Scheduler entry) or open the Windows firewall. See steps 9d / 9f
# of docs/DEPLOYING-wsl.md for those.
#
# Preconditions you must satisfy BEFORE running this on WSL:
#   - WSL2 + Ubuntu 24.04 installed and running (deploy doc step 1)
#   - systemd enabled in /etc/wsl.conf
#   - vmIdleTimeout=-1 in C:\Users\<you>\.wslconfig
#   - NVIDIA driver up-to-date on the Windows side; nvidia-smi works in WSL
#     (only required if you want CUDA acceleration)

set -euo pipefail

# ----- Globals ---------------------------------------------------------------

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CONNECTCLIPS_PORT:-8765}"

is_wsl=0
if grep -qi microsoft /proc/version 2>/dev/null; then
    is_wsl=1
fi

if [[ -n "${CONNECTCLIPS_DATA_ROOT:-}" ]]; then
    DATA_ROOT="$CONNECTCLIPS_DATA_ROOT"
elif [[ $is_wsl -eq 1 ]]; then
    DATA_ROOT="/mnt/c/ConnectClips-data"
else
    DATA_ROOT="$HOME/ConnectClips-data"
fi

# ----- Logging ---------------------------------------------------------------

is_tty=0; [[ -t 2 ]] && is_tty=1
clr() { [[ $is_tty -eq 1 ]] && printf '\033[%sm' "$1"; }
log()  { printf '%b[install]%b %s\n' "$(clr '1;34')" "$(clr 0)" "$*" >&2; }
warn() { printf '%b[install:warn]%b %s\n' "$(clr '1;33')" "$(clr 0)" "$*" >&2; }
fail() { printf '%b[install:fail]%b %s\n' "$(clr '1;31')" "$(clr 0)" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ----- Preflight -------------------------------------------------------------

[[ "$(uname -s)" == "Linux" ]] || fail "Linux/WSL only — for macOS use scripts/install-mac.sh"
[[ -f "$REPO_DIR/backend/requirements.txt" ]] \
    || fail "Couldn't find backend/requirements.txt — run this from inside a ConnectClips clone."

if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
        warn "Tested on Ubuntu 24.04 only. You're on ${PRETTY_NAME:-$ID-$VERSION_ID} — proceeding anyway."
    fi
fi

# WSL2 ext4 vs DrvFs sanity: if the repo is under /mnt/, venv ops will be
# painfully slow. Surface this loud, before sudo creds are cached.
if [[ $is_wsl -eq 1 && "$REPO_DIR" == /mnt/* ]]; then
    fail "Repo is on a Windows mount ($REPO_DIR). DrvFs is too slow for venv + node_modules. \
Move the clone to your WSL home (e.g. ~/ConnectClips) and re-run."
fi

# ----- Helpers ---------------------------------------------------------------

prime_sudo() {
    if sudo -n true 2>/dev/null; then
        return
    fi
    log "Sudo needed for apt install + systemd unit. You'll be prompted once."
    sudo -v
    # Refresh the cache in the background while the install runs (cheap).
    ( while true; do sudo -n true; sleep 60; done ) 2>/dev/null &
    SUDO_REFRESH_PID=$!
    trap 'kill $SUDO_REFRESH_PID 2>/dev/null || true' EXIT
}

apt_ensure() {
    # apt_ensure pkg1 pkg2 ... — install only what's missing.
    local missing=()
    local p
    for p in "$@"; do
        if dpkg -s "$p" >/dev/null 2>&1; then continue; fi
        missing+=("$p")
    done
    if (( ${#missing[@]} == 0 )); then return; fi
    log "  installing: ${missing[*]}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}" >/dev/null
}

# ----- Steps -----------------------------------------------------------------

step_apt_packages() {
    log "[1/11] APT packages"
    log "  refreshing package index..."
    sudo apt-get update -qq >/dev/null

    apt_ensure \
        build-essential \
        curl git ca-certificates \
        python3.12 python3.12-venv python3-pip \
        ffmpeg \
        pkg-config libssl-dev libffi-dev \
        yt-dlp lsof
}

step_nvenc_check() {
    log "[2/11] ffmpeg NVENC encoder"
    if ! have ffmpeg; then
        fail "ffmpeg missing despite apt install — bail out and check apt logs."
    fi

    if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q nvenc; then
        log "  h264_nvenc present — hardware encode available"
        return
    fi

    warn "  ffmpeg lacks NVENC — installing the ffmpeg7 PPA and replacing"
    if ! have add-apt-repository; then
        apt_ensure software-properties-common
    fi
    sudo add-apt-repository -y ppa:ubuntuhandbook1/ffmpeg7 >/dev/null
    sudo apt-get update -qq >/dev/null
    sudo apt-get install -y -qq ffmpeg >/dev/null

    if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q nvenc; then
        log "  h264_nvenc now present"
    else
        warn "  ffmpeg still lacks NVENC after PPA install. Encoding will fall back to libx264 (CPU)."
    fi
}

step_cuda_check() {
    log "[3/11] CUDA passthrough (nvidia-smi)"
    if ! have nvidia-smi; then
        warn "  nvidia-smi not on PATH — Whisper will run on CPU (no GPU acceleration)"
        return
    fi
    if nvidia-smi -L >/dev/null 2>&1; then
        log "  $(nvidia-smi -L | head -1)"
    else
        warn "  nvidia-smi present but didn't list a GPU — Windows driver too old, or WSL CUDA passthrough not enabled"
    fi
}

step_node() {
    log "[4/11] Node.js"
    if have node && [[ "$(node --version 2>/dev/null)" == v2[02468]* ]]; then
        log "  node $(node --version) already installed"
        return
    fi
    log "  adding NodeSource 20.x repo + installing nodejs..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
    have node || fail "node still not on PATH after nodesource install"
    log "  node $(node --version)"
}

step_venv_pip() {
    log "[5/11] Backend venv + pip install"
    cd "$REPO_DIR/backend"

    if [[ ! -d .venv ]]; then
        python3.12 -m venv .venv
    fi

    .venv/bin/pip install --upgrade --quiet pip wheel
    log "  installing requirements (CUDA wheels are a few hundred MB — ~5-15 min)"
    .venv/bin/pip install --quiet -r requirements.txt
}

step_yunet_model() {
    log "[6/11] YuNet face detector"
    local target="$HOME/.cache/connectclips/face_detection_yunet_2023mar.onnx"
    if [[ -f "$target" ]] && (( $(stat -c%s "$target") > 200000 )); then
        log "  already downloaded ($(($(stat -c%s "$target") / 1024)) KB)"
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

    local api_key admin_pw session_secret whisper_device

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

    session_secret="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"

    # auto picks ctranslate2+CUDA on Linux when nvidia-smi works, else CPU.
    whisper_device=auto

    umask 077
    cat > .env <<EOF
# ConnectClips backend config — generated by scripts/install-wsl.sh
DATA_SOURCES_DIR=$DATA_ROOT/sources
DATA_WORK_DIR=$DATA_ROOT/work
DATA_CLIPS_DIR=$DATA_ROOT/clips

ANTHROPIC_API_KEY=$api_key
CLAUDE_MODEL=claude-sonnet-4-6

WHISPER_MODEL=large-v3
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=$whisper_device
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

    if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
        log "  port $PORT already bound — testing existing instance"
        curl -fsS "http://127.0.0.1:$PORT/api/health" > /tmp/connectclips-install-health.json \
            || fail "Existing process on port $PORT but /api/health didn't answer."
    else
        local logfile="/tmp/connectclips-install-smoke.log"
        .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
            > "$logfile" 2>&1 &
        local pid=$!
        # We want $pid to expand NOW (local var, out of scope at fire time).
        # shellcheck disable=SC2064
        trap "kill $pid 2>/dev/null || true" RETURN

        local ok=0
        for _ in {1..30}; do
            if curl -fsS "http://127.0.0.1:$PORT/api/health" \
                > /tmp/connectclips-install-health.json 2>/dev/null
            then
                ok=1; break
            fi
            sleep 1
        done

        if [[ $ok -eq 0 ]]; then
            cat "$logfile" >&2 || true
            fail "Smoke test failed — uvicorn didn't respond. Log: $logfile"
        fi

        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        trap - RETURN
    fi

    grep -q '"spa_built": true' /tmp/connectclips-install-health.json \
        || warn "  /api/health reported spa_built: false — frontend build may not have landed in dist/"
    log "  /api/health 200 OK"
}

step_systemd() {
    log "[11/11] systemd autostart"

    local user="${SUDO_USER:-$USER}"
    local home_dir
    home_dir="$(getent passwd "$user" | cut -d: -f6)"

    sudo tee /etc/systemd/system/connectclips.service >/dev/null <<EOF
[Unit]
Description=ConnectClips backend (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$user
Group=$user
WorkingDirectory=$REPO_DIR/backend
ExecStart=$REPO_DIR/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PORT --log-level warning
Restart=on-failure
RestartSec=5
Environment=HOME=$home_dir
Environment=PATH=$REPO_DIR/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # WSL anchor: keeps the VM alive long enough for systemd to actually
    # serve the backend after a Task-Scheduler-driven boot. Pure Linux
    # boxes don't need this; only install on WSL.
    if [[ $is_wsl -eq 1 ]]; then
        sudo tee /etc/systemd/system/wsl-anchor.service >/dev/null <<'EOF'
[Unit]
Description=Anchor to keep WSL running
After=multi-user.target

[Service]
Type=simple
ExecStart=/bin/sleep infinity
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    fi

    sudo systemctl daemon-reload
    sudo systemctl enable connectclips.service >/dev/null
    if [[ $is_wsl -eq 1 ]]; then
        sudo systemctl enable wsl-anchor.service >/dev/null
    fi

    sudo systemctl restart connectclips.service
    if [[ $is_wsl -eq 1 ]]; then
        sudo systemctl restart wsl-anchor.service
    fi

    sleep 2
    if systemctl is-active --quiet connectclips.service; then
        log "  connectclips.service: active"
    else
        warn "  connectclips.service didn't come up. Tail with: sudo journalctl -u connectclips.service -n 100 --no-pager"
    fi
}

main() {
    log "ConnectClips Linux/WSL install — repo at $REPO_DIR"
    log "Data dirs: $DATA_ROOT (set CONNECTCLIPS_DATA_ROOT to override)"
    log "Port: $PORT"
    [[ $is_wsl -eq 1 ]] && log "WSL2 detected"

    prime_sudo

    step_apt_packages
    step_nvenc_check
    step_cuda_check
    step_node
    step_venv_pip
    step_yunet_model
    step_data_dirs
    step_env_file
    step_frontend_build
    step_smoke_test
    step_systemd

    log ""
    log "Install complete. Open http://localhost:$PORT/"
    log "Backend logs: sudo journalctl -u connectclips.service -f"
    if [[ $is_wsl -eq 1 ]]; then
        log ""
        log "Windows side still TODO:"
        log "  - Task Scheduler trigger so WSL boots with Windows (deploy doc step 9d)"
        log "  - Optional firewall rule for LAN access (deploy doc step 9f)"
        log "  - Tailscale install + Tailscale Serve on the Windows side (deploy doc step 10)"
    else
        log "For Tailscale remote access, see step 10 of docs/DEPLOYING-wsl.md"
    fi
}

main "$@"
