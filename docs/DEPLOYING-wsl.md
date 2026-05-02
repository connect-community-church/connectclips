# Deploying ConnectClips on Windows + WSL2

End-to-end install guide for running ConnectClips on a Windows PC using WSL2 and an NVIDIA GPU. This is the setup we run in production at Connect Community Church.

If you have a pure-Linux box, every command here that starts `sudo apt …` works the same — skip Step 1 and Step 9, and you're done.

## What you'll have at the end

- ConnectClips backend listening on `localhost:8765`
- Frontend served from the same port (no separate dev server in production)
- Sermon files stored on whichever drive you point the data dirs at
- Auto-starts on Windows boot (no logged-in user required)
- Reachable from your laptop / phone over Tailscale

Plan on **45–90 minutes** end-to-end, mostly waiting for `pip install` to compile the bigger packages.

---

## Prerequisites

- A Windows 10 (build 19041+) or Windows 11 PC
- NVIDIA GPU with **8 GB+ VRAM** (RTX 3060 Ti or better recommended)
- Latest [NVIDIA Game Ready / Studio driver](https://www.nvidia.com/Download/index.aspx) installed on the **Windows side** — CUDA passes through to WSL via the Windows driver, you do not install a separate CUDA toolkit
- ~30 GB free on whichever drive you put the venv + node_modules + model cache on (we recommend the WSL ext4 filesystem, not `/mnt/c/`)
- ~100 GB free on the drive you'll store sermon files on (`/mnt/c/` is fine for v1)
- An [Anthropic API key](anthropic-api-key.md) — billing account with a small credit (a few dollars goes a long way). If it's your first time, the [step-by-step walkthrough](anthropic-api-key.md) covers account setup → billing → key generation → pasting into ConnectClips.
- (Optional but recommended) a [Tailscale](https://tailscale.com/) tailnet for remote access

---

## 1. Install WSL2 with Ubuntu 24.04

In **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Reboot when prompted. After reboot, an Ubuntu shell opens — pick a username and password (the username we'll use below is `connectadmin`; substitute your own throughout).

Confirm WSL2 is the default version and Ubuntu is running on it:

```powershell
wsl --status
wsl -l -v
```

Both should report version 2 and a `Running` distribution.

### 1a. Enable systemd inside WSL

Inside the Ubuntu shell:

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[boot]
systemd=true

[network]
hostname=streaming-pc

[interop]
appendWindowsPath=true
EOF
```

Then from **PowerShell**:

```powershell
wsl --shutdown
```

Reopen the Ubuntu shell. Confirm systemd is up:

```bash
systemctl is-system-running   # should return "running" or "degraded"
```

`degraded` is fine — it just means one of Ubuntu's default services failed (often a snap-related service that doesn't apply to WSL).

### 1b. Disable the WSL idle timeout (load-bearing)

In the **Windows** filesystem, edit `C:\Users\<your-windows-username>\.wslconfig` (create it if missing):

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
vmIdleTimeout=-1
```

`vmIdleTimeout=-1` is critical for the autostart flow in Step 9 — without it, WSL shuts down ~60 seconds after the boot trigger fires and the systemd services die with it.

Apply the change:

```powershell
wsl --shutdown
```

Reopen Ubuntu.

---

## Quick install (recommended)

Once Step 1 is done — WSL2 + systemd up, `vmIdleTimeout=-1` set, NVIDIA
driver current on the Windows side — sections 2 through 9 are automated
by `scripts/install-wsl.sh`. Inside the Ubuntu shell:

```bash
cd ~
git clone https://github.com/connect-community-church/connectclips.git ConnectClips
cd ConnectClips
./scripts/install-wsl.sh
```

The script is idempotent (re-runnable if a step fails), prompts once for
your Anthropic API key and an admin password, and finishes by enabling
the `connectclips.service` systemd unit. Plan on **45–90 minutes**, mostly
waiting on `pip install` to compile a few hundred MB of CUDA wheels.

It does **not** touch the Windows side — Step 9d (Task Scheduler boot
trigger), Step 9f (firewall rule), and Step 10 (Tailscale) still need to
be done manually after the script finishes.

To run the script non-interactively (e.g. in CI or scripted provisioning):

```bash
export CONNECTCLIPS_API_KEY=sk-ant-...
export CONNECTCLIPS_ADMIN_PASSWORD='your-admin-password'
./scripts/install-wsl.sh
```

If you want to understand each step, or you're debugging a failure, the
manual walkthrough below is exactly what the script does.

---

## 2. System packages

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  curl git \
  python3.12 python3.12-venv python3-pip \
  ffmpeg \
  pkg-config libssl-dev libffi-dev \
  yt-dlp
```

Verify ffmpeg has NVENC:

```bash
ffmpeg -hide_banner -encoders 2>/dev/null | grep nvenc
```

You should see `h264_nvenc`, `hevc_nvenc`, and so on. If you don't, your ffmpeg build doesn't include NVENC — install a build that does:

```bash
sudo add-apt-repository ppa:ubuntuhandbook1/ffmpeg7
sudo apt update && sudo apt install -y ffmpeg
ffmpeg -hide_banner -encoders 2>/dev/null | grep nvenc
```

### Verify CUDA reaches WSL

```bash
nvidia-smi
```

You should see your GPU listed with the Windows-side driver version. If `nvidia-smi` reports "command not found" or "driver not loaded," your Windows driver is too old or the WSL CUDA passthrough isn't enabled — update the NVIDIA driver on the Windows side and retry.

---

## 3. Install Node.js (for the frontend build)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version   # v20.x.x
npm --version
```

---

## 4. Clone the repo

Put it in your home directory inside WSL — **not** under `/mnt/c/`. DrvFs (the Windows-mount filesystem) is too slow for venv operations and `node_modules`.

```bash
cd ~
git clone https://github.com/connect-community-church/connectclips.git ConnectClips
cd ConnectClips
```

---

## 5. Backend setup

```bash
cd ~/ConnectClips/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

This pulls a few hundred MB of CUDA libraries (`nvidia-cudnn-cu12`, `nvidia-cublas-cu12`, etc.) for `faster-whisper` and `onnxruntime-gpu`. Expect 5–15 minutes.

### 5a. Pre-fetch the YuNet face-detection model

```bash
mkdir -p ~/.cache/connectclips
curl -L -o ~/.cache/connectclips/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
```

(228 KB. Download once; the path is referenced from `backend/app/services/reframe.py`.)

### 5b. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in:

```ini
# Where sermon files / intermediate artifacts / exported clips live.
# Use a path on a drive with at least 100 GB free.
DATA_SOURCES_DIR=/mnt/c/ConnectClips-data/sources
DATA_WORK_DIR=/mnt/c/ConnectClips-data/work
DATA_CLIPS_DIR=/mnt/c/ConnectClips-data/clips

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-…
CLAUDE_MODEL=claude-sonnet-4-6

# Whisper
WHISPER_MODEL=large-v3
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=cuda

# Admin mode
ADMIN_PASSWORD=<choose a password>
SESSION_SECRET=<run the command below>

# (Optional) Tailscale logins that auto-promote to admin without password.
# Comma-separated emails. Requires Tailscale Serve in Step 10.
ADMIN_TAILSCALE_LOGINS=
```

Generate a strong session secret:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Paste its output into `SESSION_SECRET=`.

Create the data directories now so the backend doesn't have to:

```bash
mkdir -p /mnt/c/ConnectClips-data/{sources,work,clips}
```

---

## 6. Frontend build

```bash
cd ~/ConnectClips/frontend
npm install
npm run build
```

Drops the static SPA bundle in `frontend/dist/`, which the backend serves at `/`.

---

## 7. First-run smoke test

Manual launch (we'll wire up systemd in Step 9):

```bash
cd ~/ConnectClips/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

You should see uvicorn report `Application startup complete`. From a second terminal:

```bash
curl http://localhost:8765/api/health
```

Returns:

```json
{"status":"ok","sources_dir":"/mnt/c/ConnectClips-data/sources","work_dir":"/mnt/c/ConnectClips-data/work","clips_dir":"/mnt/c/ConnectClips-data/clips","whisper_model":"large-v3","claude_model":"claude-sonnet-4-6","spa_built":true}
```

`spa_built: true` confirms the frontend was built in Step 6.

Open <http://localhost:8765> in any browser. You should see the ConnectClips banner and an empty sermon list.

Ctrl-C to stop uvicorn — we'll launch it under systemd next.

---

## 8. Drop a sample sermon to verify the pipeline

The fastest end-to-end verification is to upload a short YouTube video:

1. Open <http://localhost:8765>.
2. Paste a short YouTube URL into the **From YouTube** field, click **Download**.
3. Watch the activity row: `youtube_download` → `transcribe` (5–15 min for a 50-min sermon) → `select_clips` (~30 s) → `prescan_faces` (~10–25 min, runs in parallel with select_clips).
4. Click into the sermon, pick a clip, hit **Export vertical clip**. ~30–60 s later you have an MP4 in `/mnt/c/ConnectClips-data/clips/`.

If any step fails, look at uvicorn's stdout — every error has a stack trace.

---

## 9. Auto-start on Windows boot

The architecture: systemd inside WSL runs the backend; a Task Scheduler entry on Windows boots WSL on startup; `vmIdleTimeout=-1` (set in Step 1b) keeps the VM alive so systemd survives.

### 9a. Install the systemd unit

```bash
sudo tee /etc/systemd/system/connectclips.service >/dev/null <<EOF
[Unit]
Description=ConnectClips backend (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$HOME/ConnectClips/backend
ExecStart=$HOME/ConnectClips/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765 --log-level warning
Restart=on-failure
RestartSec=5
Environment=HOME=$HOME
Environment=PATH=$HOME/ConnectClips/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
```

### 9b. Install the WSL anchor unit (defense in depth)

```bash
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
```

### 9c. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now connectclips.service wsl-anchor.service
sudo systemctl status connectclips.service
```

The status output should show `active (running)`.

### 9d. Create the Windows boot trigger

Open **Task Scheduler** → *Create Task…* (not "Basic Task").

| Tab | Setting |
|---|---|
| **General** | Name: `ConnectClips-StartWSL`. Run whether user is logged on or not. Configure for: Windows 10 / 11. |
| **Triggers** → New | Begin the task: **At startup**. |
| **Actions** → New | Action: **Start a program**. Program/script: `C:\Windows\System32\wsl.exe`. Arguments: `-d Ubuntu-24.04 --exec /bin/true` (replace `Ubuntu-24.04` with your distro name from `wsl -l -v`). |
| **Conditions** | Uncheck *Start the task only if the computer is on AC power*. |
| **Settings** | Check *Allow task to be run on demand*. |

Save the task.

### 9e. Test without rebooting

In **PowerShell**:

```powershell
wsl --shutdown
Start-Sleep 5
Start-ScheduledTask -TaskName 'ConnectClips-StartWSL'
Start-Sleep 15
curl http://localhost:8765/api/health
```

Returns `{"status":"ok",...}`. Wait two more minutes; `wsl -l -v` should still show the distro `Running` — that proves `vmIdleTimeout=-1` is in effect.

### 9f. Open the Windows firewall

Only needed if you'll access ConnectClips from another machine on the LAN (without Tailscale):

```powershell
New-NetFirewallRule -DisplayName "ConnectClips (8765)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765
```

---

## 10. Tailscale Serve for remote access (recommended)

This is what lets volunteers reach the app from their laptops or phones without exposing port 8765 to the public internet, and what lets ConnectClips identify volunteers by Tailscale login.

### 10a. Install Tailscale on the Windows side

Download from <https://tailscale.com/download/windows> and sign in with the church's Tailscale account.

### 10b. Serve port 8765 over HTTPS

In **PowerShell**:

```powershell
tailscale serve --bg --https=443 http://localhost:8765
```

Confirm:

```powershell
tailscale serve status
```

Volunteers can now reach the app at `https://<your-machine-name>.<your-tailnet>.ts.net/` from any device on the tailnet.

### 10c. (Optional) Auto-promote specific Tailscale logins to admin

In `backend/.env`, fill in:

```ini
ADMIN_TAILSCALE_LOGINS=pastor@example.com,media-lead@example.com
```

Restart the backend:

```bash
sudo systemctl restart connectclips.service
```

Those users now skip the password prompt — the app reads their identity from the headers Tailscale Serve forwards.

---

## Updating the app later

```bash
cd ~/ConnectClips
git pull
cd frontend && npm run build
sudo systemctl restart connectclips.service
```

The hashed-asset cache headers mean a normal browser refresh (F5) picks up the new bundle — no need to ask volunteers to hard-refresh.

---

## Troubleshooting

**`/api/health` returns 404 or 500** — the backend started but the SPA build is missing or the API failed to import. Check the journal:
```bash
sudo journalctl -u connectclips.service -n 100 --no-pager
```

**Page loads but admin login 503s** — `ADMIN_PASSWORD` is empty in `backend/.env`. Set it and `sudo systemctl restart connectclips.service`.

**`nvidia-smi` works but `WHISPER_DEVICE=cuda` fails on first transcribe** — the cuDNN/cuBLAS libraries from the pip-installed `nvidia-*-cu12` packages aren't on the loader path. The fix is in `backend/app/cuda_preload.py`, which `app.main` imports first; if you've moved imports around and broken that order, `faster-whisper` will silently fall back to CPU. Ensure `from app import cuda_preload  # noqa: F401` runs BEFORE any `faster_whisper` or `onnxruntime` import.

**Backend runs for ~2 minutes after boot then everything dies** — classic missing-`vmIdleTimeout` symptom. Check `C:\Users\<you>\.wslconfig` includes `vmIdleTimeout=-1` under `[wsl2]`, then `wsl --shutdown` to apply. Look for back-to-back short boots in `journalctl --list-boots`.

**Page loads on streaming PC but not over Tailscale** — confirm `tailscale serve status` shows the rule, and that the Windows firewall isn't blocking 8765 (Step 9f).

**Slow uploads / transcribe takes hours** — venv probably ended up under `/mnt/c/` instead of WSL ext4. Move it: `rm -rf backend/.venv && python3.12 -m venv ~/ConnectClips/backend/.venv && pip install -r backend/requirements.txt`. Same for `node_modules`.

**Pipeline says transcribe is "running" indefinitely** — Whisper occasionally hangs on weird audio. Restart: `sudo systemctl restart connectclips.service`. The job row stays as `running` in the DB; you can mark it failed in SQLite directly if it bothers you.

**Stale frontend after `npm run build`** — F5 in the browser. The hashed bundle filenames + `Cache-Control: no-cache, must-revalidate` on `index.html` should make hard-refreshes unnecessary; if a user complains, it's almost always a misconfigured proxy stripping the cache headers.

---

## What we're NOT doing in this guide

- Putting the app on the public internet without Tailscale (it has admin-mode but no rate-limiting; treat the network as untrusted at your peril)
- Multi-user concurrent uploads at high volume (the jobs queue is in-process asyncio; fine for ≤10 volunteers, not for a public service)
- HTTPS termination on the Windows host directly (Tailscale Serve handles that)

If your church needs any of those, ConnectClips is a good base but you'll be writing a few hundred lines of ops code. Open an issue if you want to discuss.
