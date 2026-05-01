# Deploying ConnectClips on macOS (Apple Silicon)

End-to-end install guide for running ConnectClips on a Mac with an
Apple Silicon chip (M1, M2, M3, M4 — any of them). Uses `whisper.cpp`
+ Metal for transcription and Apple's VideoToolbox for h264 encoding,
so transcribe + export are GPU-accelerated even though there's no
NVIDIA card.

> **Status: experimental.** The Linux/WSL2 path is the production-tested
> deployment. The macOS path was added in v0.2 and validated on a
> MacBook Air M4 / 24 GB. Smaller M-series chips (M1 8 GB) will work
> but transcribes will run slower; minimum recommended is 16 GB unified
> memory.

If you have a pure-Linux box, see [DEPLOYING-wsl.md](DEPLOYING-wsl.md)
instead — the install is simpler.

## What you'll have at the end

- ConnectClips backend listening on `localhost:8765`
- Frontend served from the same port (no separate dev server)
- Sermon files stored on the Mac's internal SSD (or external if you point
  the data dirs there)
- Auto-starts on login via launchd
- Reachable from your laptop / phone over Tailscale

Plan on **30-60 minutes** end-to-end.

---

## Prerequisites

- Apple Silicon Mac (M1 or later) running macOS 14 (Sonoma) or later
- **16 GB+ unified memory recommended** (8 GB will work but
  transcription thrashes; 24 GB+ is comfortable)
- ~30 GB free for venv + node_modules + Whisper model cache
- ~100 GB free wherever you'll keep sermon files
- An [Anthropic API key](https://console.anthropic.com/) with a small
  billing credit (a few dollars goes a long way)
- (Optional but recommended) a [Tailscale](https://tailscale.com/)
  tailnet for remote access

---

## 1. Xcode Command Line Tools

`pywhispercpp` and a few other packages compile from source. They need
the Apple toolchain:

```bash
xcode-select --install
```

Click through the prompt that pops up. Takes a few minutes.

---

## 2. Homebrew

Install [Homebrew](https://brew.sh/) if you don't have it:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the post-install instructions to add brew to your PATH (the
installer prints them).

---

## 3. System packages

```bash
brew install python@3.12 node ffmpeg-full yt-dlp git expat
brew link --overwrite --force ffmpeg-full
```

Two non-obvious things in that line, both load-bearing:

- **`ffmpeg-full`, not plain `ffmpeg`.** The default `ffmpeg` formula on
  Tahoe ships without `libass`, so the `subtitles=…` filter the export
  pipeline relies on for caption burn-in is missing entirely. Exports
  fail with `BrokenPipeError` and no helpful hint. `ffmpeg-full`
  pulls in libass, libfreetype, fontconfig, and ~40 other deps. It's
  keg-only by default, hence the explicit `brew link --force`.
- **`expat`** is needed because brew's `python@3.12` bottle on Tahoe is
  compiled against a newer libexpat than the OS ships, and we patch
  `pyexpat` to load brew's expat instead in step 5. Without `expat`
  installed first, that patch has nothing to point at.

Verify ffmpeg has both VideoToolbox (Apple's hardware encoder) and the
subtitles filter (libass):

```bash
ffmpeg -hide_banner -encoders | grep videotoolbox
ffmpeg -hide_banner -h filter=subtitles | head -3
```

You should see `h264_videotoolbox`, and the subtitles help text instead
of `Unknown filter 'subtitles'`.

---

## 4. Clone the repo

```bash
cd ~
git clone https://github.com/connect-community-church/connectclips.git ConnectClips
cd ConnectClips
```

---

## 5. Backend setup

### 5a. Patch brew's `python@3.12` for Tahoe's libexpat ABI

Skip this if `python3.12 -m ensurepip --version` runs cleanly. On
Tahoe 26.x with brew bottle `python@3.12 3.12.13_2`, it errors with

```
ImportError: dlopen(.../pyexpat.cpython-312-darwin.so):
Symbol not found: _XML_SetAllocTrackerActivationThreshold
```

The brew bottle was built against expat 2.7+, but the libexpat that
ships in Tahoe's dyld shared cache is older. Repoint pyexpat at brew's
expat (which we installed in step 3):

```bash
PYEXPAT="$(brew --prefix python@3.12)/Frameworks/Python.framework/Versions/3.12/lib/python3.12/lib-dynload/pyexpat.cpython-312-darwin.so"
install_name_tool -change /usr/lib/libexpat.1.dylib /opt/homebrew/opt/expat/lib/libexpat.1.dylib "$PYEXPAT"
codesign --force --sign - "$PYEXPAT"
```

Verify: `python3.12 -c 'from pyexpat import *; print("ok")'` should
print `ok`. **This patch is reverted by `brew upgrade python@3.12`** —
re-run it after any python upgrade until brew ships a fixed bottle.

### 5b. Create the venv and install Python dependencies

```bash
cd ~/ConnectClips/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

`requirements.txt` uses environment markers so the NVIDIA / CUDA wheels
that exist for Linux are silently skipped on macOS, and `pywhispercpp`
+ the standard `onnxruntime` (with CoreML support) are installed in
their place. Expect 5-10 minutes — `pywhispercpp` compiles whisper.cpp
from source on first install.

### 5c. Pre-fetch the YuNet face-detection model

```bash
mkdir -p ~/.cache/connectclips
curl -L -o ~/.cache/connectclips/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
```

228 KB. Same model as the Linux deployment.

### 5d. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in:

```ini
# Where sermon files / intermediate artifacts / exported clips live.
DATA_SOURCES_DIR=/Users/<your-username>/ConnectClips-data/sources
DATA_WORK_DIR=/Users/<your-username>/ConnectClips-data/work
DATA_CLIPS_DIR=/Users/<your-username>/ConnectClips-data/clips

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-…
CLAUDE_MODEL=claude-sonnet-4-6

# Whisper. On macOS the auto-detected backend is whispercpp (Metal),
# so leave WHISPER_BACKEND=auto. WHISPER_DEVICE / WHISPER_COMPUTE_TYPE
# are only honored by the ctranslate2 backend, ignored on macOS.
WHISPER_MODEL=large-v3
WHISPER_BACKEND=auto

# Admin mode
ADMIN_PASSWORD=<choose a password>
SESSION_SECRET=<run the command below>

# (Optional) Tailscale logins that auto-promote to admin without password
ADMIN_TAILSCALE_LOGINS=
```

Generate a strong session secret:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Paste the output into `SESSION_SECRET=`.

Create the data directories:

```bash
mkdir -p ~/ConnectClips-data/{sources,work,clips}
```

---

## 6. Frontend build

```bash
cd ~/ConnectClips/frontend
npm install
npm run build
```

Drops the SPA bundle in `frontend/dist/`, served by the backend at `/`.

---

## 7. First-run smoke test

Manual launch:

```bash
cd ~/ConnectClips/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

You should see `Application startup complete`. From a second terminal:

```bash
curl http://localhost:8765/api/health
```

Should return JSON including:

```json
"platform": {
    "platform": "Darwin",
    "h264_encoder": "h264_videotoolbox",
    "ort_providers": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "cuda_available": false,
    "initialized": true
}
```

`platform: "Darwin"` + `h264_videotoolbox` + `CoreMLExecutionProvider`
confirms hardware acceleration is active. If you see `libx264` or only
`CPUExecutionProvider`, something's off — check ffmpeg / onnxruntime
install.

Open <http://localhost:8765/> in any browser. You should see the
ConnectClips banner and an empty sermon list.

Ctrl-C to stop. We'll wire up launchd next.

---

## 8. Drop a sample sermon to verify the pipeline

The fastest end-to-end check:

1. Open <http://localhost:8765/>.
2. Paste a short YouTube URL into the **From YouTube** field.
3. Watch activity: `youtube_download` → `transcribe` (whisper.cpp + Metal,
    expect ~25-40 % realtime — a 50-min sermon transcribes in 12-20 min)
    → `select_clips` (~30 s) → `prescan_faces` (~10-15 min, parallel
    with select_clips).
4. Click into the sermon, pick a clip, hit **Export vertical clip**.
   ~60-120 s later you have an MP4 in
   `~/ConnectClips-data/clips/`.

**Expected performance on M-series:**

| Mac | Transcribe (50-min sermon) | Export (60-s clip) |
|---|---|---|
| M1 8 GB | 30-50 min | 90-180 s |
| M1 16 GB / M2 | 20-35 min | 75-150 s |
| M3 / M4 16+ GB | 12-20 min | 60-120 s |

For comparison, the Linux RTX 3060 Ti deployment does the same workload
in 5-15 min transcribe + 30-60 s export.

---

## 9. Auto-start on login (launchd)

Unlike Linux/systemd, macOS doesn't have a system-level service manager
that's friendly for non-root single-user setups. The conventional
approach is a **LaunchAgent** that starts the backend when you log in.

### 9a. Install the launchd plist

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.connectclips.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.connectclips</string>

  <key>ProgramArguments</key>
  <array>
    <string>$HOME/ConnectClips/backend/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8765</string>
    <string>--log-level</string>
    <string>warning</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$HOME/ConnectClips/backend</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/connectclips.log</string>

  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/connectclips.log</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>$HOME/ConnectClips/backend/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF
```

### 9b. Load the agent

```bash
launchctl load ~/Library/LaunchAgents/com.connectclips.plist
```

Confirm it's running:

```bash
launchctl list | grep connectclips
```

Should show a PID (third column).

```bash
curl http://localhost:8765/api/health
```

Should return `{"status":"ok",...}`.

To stop it:

```bash
launchctl unload ~/Library/LaunchAgents/com.connectclips.plist
```

Logs at `~/Library/Logs/connectclips.log`.

---

## 10. Tailscale Serve for remote access (recommended)

This lets volunteers reach the app from their laptops or phones without
exposing port 8765 to the public internet, and lets ConnectClips
identify volunteers by Tailscale login.

### 10a. Install Tailscale

```bash
brew install --cask tailscale
```

Open the Tailscale app from Applications, sign in with the church's
Tailscale account.

### 10b. Serve port 8765 over HTTPS

```bash
tailscale serve --bg --https=443 http://localhost:8765
```

Confirm:

```bash
tailscale serve status
```

Volunteers can now reach the app at
`https://<your-machine-name>.<your-tailnet>.ts.net/` from any device
on the tailnet.

### 10c. (Optional) auto-promote specific Tailscale logins to admin

In `backend/.env`:

```ini
ADMIN_TAILSCALE_LOGINS=pastor@example.com,media-lead@example.com
```

Reload the service:

```bash
launchctl unload ~/Library/LaunchAgents/com.connectclips.plist
launchctl load ~/Library/LaunchAgents/com.connectclips.plist
```

---

## Updating the app later

```bash
cd ~/ConnectClips
git pull
cd frontend && npm run build
launchctl unload ~/Library/LaunchAgents/com.connectclips.plist
launchctl load ~/Library/LaunchAgents/com.connectclips.plist
```

---

## Troubleshooting

**`pywhispercpp` fails to install** — usually means Xcode Command Line
Tools aren't installed. Run `xcode-select --install`. If that's already
done, try `pip install --no-cache-dir pywhispercpp` to force a clean
rebuild.

**`/api/health` reports `h264_encoder: "libx264"` instead of
`h264_videotoolbox`** — your ffmpeg build doesn't include VideoToolbox.
Reinstall via Homebrew: `brew reinstall ffmpeg-full`.

**Export fails with `BrokenPipeError: [Errno 32] Broken pipe`** —
almost certainly your `ffmpeg` is the regular brew formula instead of
`ffmpeg-full`, so the `subtitles=…` filter (which needs libass) doesn't
exist. Confirm with `ffmpeg -h filter=subtitles`; if you see "Unknown
filter", run `brew remove ffmpeg && brew install ffmpeg-full && brew
link --overwrite --force ffmpeg-full` and restart the service.

**`cuda_available: true` on macOS** — shouldn't happen; the platform
helper short-circuits CUDA detection on Darwin. If it does, it's
harmless: `ctranslate2` would still fall back to CPU since there's no
driver. File an issue.

**Transcribe takes much longer than 20 min on an M3 / M4** — most
likely cause is that `whispercpp` failed to enable Metal and is running
on CPU. Check `~/Library/Logs/connectclips.log` for "Metal" or
"backend" lines on first transcribe. If you see "ggml_metal_init:
allocating" the GPU is engaged.

**Page loads on the Mac but not over Tailscale** — confirm
`tailscale serve status` shows the rule. If it does, restart the
Tailscale app (sometimes the serve process needs a kick after a
sleep/wake cycle).

**Slow uploads / transcribe / general sluggishness** — check Activity
Monitor → Memory tab for "Memory Pressure". If it's yellow or red,
your machine is swapping. 8 GB Macs feel this with `large-v3`; the
fix is either upgrade to a 16 GB+ machine or set
`WHISPER_MODEL=medium` in `.env` (smaller / faster / slightly less
accurate).

---

## What we're NOT doing in this guide

- Putting the app on the public internet without Tailscale
- Multi-user concurrent uploads at high volume
- HTTPS termination on the Mac directly (Tailscale Serve handles that)

If your church needs any of those, ConnectClips is a good base but
you'll be writing some ops code. Open an issue if you want to discuss.
