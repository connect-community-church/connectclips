# Deploying ConnectClips on Windows 11 (native, no WSL)

End-to-end install guide for running ConnectClips directly on Windows 11,
without WSL2. Targets boxes with an AMD GPU (discrete or iGPU) or an
Intel iGPU, where the Windows-native `h264_amf` / `h264_qsv` ffmpeg
encoders + a Vulkan-built `whisper.cpp` give us hardware acceleration
without needing CUDA / WSL2.

> **Status: experimental.** The Linux/WSL2 path is the production-tested
> deployment for boxes with an NVIDIA GPU. The Windows-native path was
> added in v0.4 and validated on a Bosgame EffiZen mini PC (Ryzen 9
> 6900HX + Radeon 680M iGPU, 32 GB RAM). On that hardware:
>
> - Whisper transcription via the bundled `whisper-cli` (Vulkan): RTR
>   ~6.5x with `medium.en`, ~3.3x with `large-v3` -- a 60-min sermon
>   transcribes in 9-18 min depending on the model you pick.
> - h264 export via `h264_amf`: ~90-120 s per clip.
> - End-to-end pipeline for a 60-min sermon: ~25-30 min.
>
> If your box has an NVIDIA GPU, install WSL2 + Ubuntu and use
> [DEPLOYING-wsl.md](DEPLOYING-wsl.md) instead -- the CUDA path is
> mature and slightly faster end-to-end. If you're on a Mac, see
> [DEPLOYING-mac.md](DEPLOYING-mac.md).

## What you'll have at the end

- ConnectClips backend listening on `localhost:8765`
- Frontend served from the same port (no separate dev server)
- Sermon files stored under `C:\ConnectClips-data\` by default
- Auto-starts at boot via an NSSM-managed Windows Service
- Reachable from your laptop / phone over Tailscale

Plan on **30-60 minutes** end-to-end, mostly waiting on `pip install` and
`npm install`.

---

## Prerequisites

- Windows 11 (build 22000+; tested on 26200/24H2). Windows 10 should
  work but isn't tested.
- 16 GB+ RAM recommended (Whisper int8 `small` peaks at ~3 GB)
- ~10 GB free for venv + node_modules + Whisper model cache
- ~100 GB free wherever you'll keep sermon files (default `C:\`)
- An [Anthropic API key](anthropic-api-key.md) with a small billing
  credit
- (Optional but recommended) a [Tailscale](https://tailscale.com/)
  tailnet for remote access
- An AMD GPU (iGPU is fine), an Intel iGPU with QuickSync, or any GPU
  -- without one, ffmpeg will fall back to libx264 software encode
  which is ~3x slower but still produces correct output

---

## Quick install (recommended)

If you're standing up a new Windows box and just want this working, the
sequence below is automated by `scripts\install-windows.ps1`. After
cloning the repo:

```powershell
cd C:\ConnectClips
.\scripts\install-windows.ps1
```

The script is idempotent (re-runnable if a step fails), prompts once
for your Anthropic API key and an admin password, and finishes by
installing an NSSM autostart service. The NSSM step needs Administrator;
the rest does not. If you launch the script as a regular user it will
do everything except the service install and tell you to re-launch
elevated for that one step.

To run non-interactively (e.g. provisioning):

```powershell
$env:CONNECTCLIPS_API_KEY = 'sk-ant-...'
$env:CONNECTCLIPS_ADMIN_PASSWORD = 'your-admin-password'
.\scripts\install-windows.ps1
```

The manual walkthrough below covers exactly what the script does.

---

## 1. winget tooling

Open PowerShell. Verify `winget` is on PATH (it ships with Windows 11):

```powershell
winget --version
```

If missing, install **App Installer** from the Microsoft Store, then
re-open PowerShell.

Install Python 3.12, Node.js LTS, ffmpeg (Gyan's build, includes
`h264_amf` + `h264_qsv`), Git, and NSSM:

```powershell
winget install --id Python.Python.3.12 --silent
winget install --id OpenJS.NodeJS.LTS  --silent
winget install --id Gyan.FFmpeg        --silent
winget install --id Git.Git            --silent
winget install --id NSSM.NSSM          --silent
```

Each accepts `--accept-source-agreements --accept-package-agreements`
if it's your first winget run.

**Open a new PowerShell window** so PATH refreshes with the new tools.
Verify:

```powershell
py -3.12 -V          # Python 3.12.x
node --version       # v20.x or v22.x
ffmpeg -version      # ffmpeg N-... gyan
git --version        # git version 2.x
nssm --version       # NSSM 2.24
```

---

## 2. Confirm the hardware encoder

```powershell
ffmpeg -hide_banner -encoders | Select-String 'h264_(amf|qsv|nvenc)'
```

You should see at least one of:

- `h264_amf` -- AMD GPU (any Radeon RX, including the 680M / 780M iGPUs)
- `h264_qsv` -- Intel iGPU with QuickSync
- `h264_nvenc` -- NVIDIA GPU (rare on this deployment path; if present,
  consider WSL2 for the bigger Whisper speedup)

If none are listed, ffmpeg will use `libx264` software encode -- still
correct output, just slower (~3x).

You can also verify the AMD AMF runtime is loaded by checking for
`amfrt64.dll`:

```powershell
Test-Path "$env:windir\System32\amfrt64.dll"
```

This DLL ships with the AMD graphics driver. If you see `False`, update
the AMD driver from amd.com.

---

## 3. Clone the repo

```powershell
cd C:\
git clone https://github.com/connect-community-church/connectclips.git ConnectClips
cd ConnectClips
```

The repo lives directly on `C:\`, not under your user profile -- avoids
OneDrive sync churn and keeps the venv path short (Windows MAX_PATH
nightmare).

---

## 4. Backend setup

### 4a. Create the venv and install Python dependencies

```powershell
cd C:\ConnectClips\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
```

`requirements.txt` is the cross-platform CPU base. The CUDA wheels in
`requirements-cuda.txt` are skipped on Windows. Expect 2-5 minutes.

Whisper itself runs through one of two backends on Windows:

- **`whispercli`** (preferred): a pre-built Vulkan-enabled `whisper-cli.exe`
  that ConnectClips ships as a release asset. Used whenever the binary
  is on disk. ~3x faster than `ctranslate2` on this hardware even before
  Vulkan kicks in, then another ~2.5x with the GPU. Section 4d below
  installs it.
- **`ctranslate2`** (fallback): faster-whisper, CPU int8. No extra
  install -- the wheel comes with `requirements.txt`. Slow on big
  models but works on any box.

If `Activate.ps1` fails with an execution-policy error:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 4b. Pre-fetch the YuNet face-detection model

```powershell
$dst = "$env:USERPROFILE\.cache\connectclips\face_detection_yunet_2023mar.onnx"
New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
Invoke-WebRequest `
  -Uri 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx' `
  -OutFile $dst -UseBasicParsing
```

228 KB. The backend resolves `~/.cache/connectclips/...` via `os.path.expanduser`,
so on Windows that lands under your user profile. Same model file as the
Linux and macOS deployments.

### 4c. (Optional but recommended) install the whisper-cli Vulkan bundle

Skip this section if you set `$env:CONNECTCLIPS_SKIP_WHISPERCLI = '1'`
or your box has no GPU and you're fine with the CPU `ctranslate2`
fallback (~3x slower for `medium`, won't keep up at all for `large-v3`).

Download the pre-built Windows binary from the latest ConnectClips
release that has whispercli assets:

```powershell
$tag    = 'whispercli-v1.8.4'      # bump when a newer release exists
$ref    = $tag -replace '^whispercli-', ''
$asset  = "whispercli-windows-x64-vulkan-$ref.zip"
$binDir = 'C:\ConnectClips\bin'

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Invoke-WebRequest `
  -Uri "https://github.com/connect-community-church/connectclips/releases/download/$tag/$asset" `
  -OutFile "$env:TEMP\$asset" -UseBasicParsing
Expand-Archive -Path "$env:TEMP\$asset" -DestinationPath $binDir -Force
```

Then download the ggml model (the format `whisper-cli` reads). Pick
based on hardware:

- **`large-v3`** (~3.1 GB) -- best accuracy. Practical only with Vulkan.
- **`medium.en`** (~1.5 GB) -- good accuracy, the recommended default.
  Works on Vulkan and tolerable on CPU.
- **`small.en`** (~470 MB) -- the floor. Use only if disk / bandwidth
  is tight.

```powershell
$model    = 'medium.en'
$modelDir = "$env:USERPROFILE\.cache\whisper.cpp"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
Invoke-WebRequest `
  -Uri "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$model.bin" `
  -OutFile "$modelDir\ggml-$model.bin" -UseBasicParsing
```

The model download is the long pole on first install (5-30 min depending
on connection + model size). `scripts\install-windows.ps1` does both
downloads automatically and lets you override the model via
`$env:CONNECTCLIPS_WHISPER_MODEL`.

### 4d. Configure environment

Create `backend\.env`:

```ini
# Where sermon files / intermediate artifacts / exported clips live.
DATA_SOURCES_DIR=C:\ConnectClips-data\sources
DATA_WORK_DIR=C:\ConnectClips-data\work
DATA_CLIPS_DIR=C:\ConnectClips-data\clips

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6

# Whisper. With the whispercli bundle installed (4c), use:
#   WHISPER_BACKEND=whispercli
#   WHISPER_MODEL=medium.en   # or large-v3 if you have Vulkan and the disk
#   WHISPER_CLI_PATH=C:\ConnectClips\bin\whisper-cli.exe
# Without the bundle, use:
#   WHISPER_BACKEND=ctranslate2
#   WHISPER_MODEL=small       # CPU floor; medium is unusably slow on int8
WHISPER_MODEL=medium.en
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=auto
WHISPER_BACKEND=whispercli
WHISPER_CLI_PATH=C:\ConnectClips\bin\whisper-cli.exe

# Admin mode
ADMIN_PASSWORD=<choose a password>
SESSION_SECRET=<run the command below>

# (Optional) Tailscale logins that auto-promote to admin without password
ADMIN_TAILSCALE_LOGINS=
```

Generate a strong session secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the output into `SESSION_SECRET=`.

Create the data directories:

```powershell
foreach ($d in 'sources','work','clips','logs') {
  New-Item -ItemType Directory -Force -Path "C:\ConnectClips-data\$d" | Out-Null
}
```

---

## 5. Frontend build

```powershell
cd C:\ConnectClips\frontend
npm install
npm run build
```

Drops the SPA bundle in `frontend\dist\`, served by the backend at `/`.

---

## 6. First-run smoke test

Manual launch:

```powershell
cd C:\ConnectClips\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Wait for `Application startup complete`. **First-time cold start can take
30-90 seconds** while the import chain (`faster_whisper` + `onnxruntime`
+ `opencv`) populates the filesystem cache. Subsequent starts are under
5 seconds.

From a second PowerShell window:

```powershell
Invoke-WebRequest http://localhost:8765/api/health -UseBasicParsing | Select-Object -ExpandProperty Content
```

Should return JSON including:

```json
"platform": {
    "platform": "Windows",
    "h264_encoder": "h264_amf",
    "ort_providers": ["CPUExecutionProvider"],
    "cuda_available": false,
    "initialized": true
}
```

`platform: "Windows"` + `h264_amf` (or `h264_qsv` on an Intel box)
confirms the hardware encoder is engaged. `CPUExecutionProvider` is
expected on this deployment path -- ConnectClips on Windows-native does
not install `onnxruntime-directml`, so YuNet face detection runs on CPU.
That's load-bearing for face detection but not the bottleneck (Whisper
+ ffmpeg encode dominate).

To confirm the whispercli backend picked up Vulkan, run a quick
transcribe and tail the backend log -- you should see lines from
whisper.cpp like:

```
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = AMD Radeon(TM) Graphics ...
whisper_backend_init_gpu: using Vulkan0 backend
```

If you instead see `whisper_init_with_params_no_state: use gpu = 0`,
the binary was built without Vulkan support -- re-download from a
release that has the `*-vulkan-*.zip` asset.

Open <http://localhost:8765/> in any browser. You should see the
ConnectClips banner and an empty sermon list.

Ctrl-C to stop. We'll wire up the autostart service next.

---

## 7. Drop a sample sermon to verify the pipeline

The fastest end-to-end check:

1. Open <http://localhost:8765/>.
2. Paste a short YouTube URL into the **From YouTube** field.
3. Watch activity: `youtube_download` -> `transcribe` (CPU int8 small,
   roughly real time -- a 30-min sermon transcribes in ~30 min) ->
   `select_clips` (~30 s) -> `prescan_faces` (~10-15 min on iGPU CPU
   fallback, parallel with select_clips).
4. Click into the sermon, pick a clip, hit **Export vertical clip**.
   ~60-180 s later you have an MP4 in `C:\ConnectClips-data\clips\`.

**Expected performance on a Ryzen 9 6900HX + Radeon 680M (production
target hardware), with the whispercli Vulkan bundle installed:**

| Stage | 30-min sermon | 60-min sermon |
|---|---|---|
| Transcribe (whispercli Vulkan, `medium.en`) | ~5 min | ~9 min |
| Transcribe (whispercli Vulkan, `large-v3`) | ~9 min | ~18 min |
| Transcribe (ctranslate2 CPU, `small`, fallback) | ~17 min | ~35 min |
| Clip selection (Claude API) | ~30 s | ~60 s |
| Face prescan (CPU YuNet) | ~5-10 min | ~10-15 min |
| Vertical export (1 clip, h264_amf) | ~90-120 s | ~90-120 s |

For comparison, the Linux RTX 3060 Ti deployment does the same
60-minute workload in 5-15 min transcribe + 30-60 s export.

---

## 8. NSSM autostart service

Windows doesn't have a per-user service manager equivalent to systemd
or launchd. The conventional answer is [NSSM](https://nssm.cc/), the
"Non-Sucking Service Manager", which wraps a regular Windows Service
around any executable. We installed it via winget in step 1.

**Open an elevated PowerShell** (right-click PowerShell -> Run as
Administrator) for the rest of this section. NSSM's
install-as-Service step needs admin.

### 8a. Install the service

```powershell
$svc = 'ConnectClips'
$venvUvicorn = 'C:\ConnectClips\backend\.venv\Scripts\uvicorn.exe'
$logPath = 'C:\ConnectClips-data\logs\connectclips.log'

nssm install $svc $venvUvicorn 'app.main:app' '--host' '0.0.0.0' '--port' '8765' '--log-level' 'warning'
nssm set $svc AppDirectory   'C:\ConnectClips\backend'
nssm set $svc AppStdout      $logPath
nssm set $svc AppStderr      $logPath
nssm set $svc AppRotateFiles 1
nssm set $svc AppRotateBytes 10485760   # 10 MB rotation
nssm set $svc Start          SERVICE_AUTO_START
nssm set $svc Description    'ConnectClips backend (FastAPI/uvicorn)'

nssm start $svc
```

### 8b. Confirm it's running

```powershell
Get-Service ConnectClips
Invoke-WebRequest http://localhost:8765/api/health -UseBasicParsing | Select-Object -ExpandProperty Content
```

`Status` should be `Running`, and `/api/health` should return JSON.

To stop / restart / remove:

```powershell
nssm stop ConnectClips
nssm start ConnectClips
nssm restart ConnectClips
nssm remove ConnectClips confirm
```

Logs at `C:\ConnectClips-data\logs\connectclips.log` (rotated at 10 MB).

---

## 9. Tailscale Serve for remote access (recommended)

This lets volunteers reach the app from their laptops or phones without
exposing port 8765 to the public internet, and lets ConnectClips
identify volunteers by Tailscale login.

### 9a. Install Tailscale

```powershell
winget install --id tailscale.tailscale --silent
```

Open the Tailscale tray app, sign in with the church's Tailscale
account.

### 9b. Serve port 8765 over HTTPS

```powershell
tailscale serve --bg --https=443 http://localhost:8765
tailscale serve status
```

Volunteers can now reach the app at
`https://<machine-name>.<tailnet>.ts.net/` from any device on the
tailnet.

### 9c. (Optional) auto-promote specific Tailscale logins to admin

In `backend\.env`:

```ini
ADMIN_TAILSCALE_LOGINS=pastor@example.com,media-lead@example.com
```

Restart the service:

```powershell
nssm restart ConnectClips
```

### 9d. (Optional) open the Windows firewall for LAN access

If you also want plain HTTP from the LAN (no Tailscale), open port 8765
inbound:

```powershell
New-NetFirewallRule -DisplayName 'ConnectClips' -Direction Inbound `
  -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private
```

The `Private` profile restricts this to networks marked Private (your
home / office LAN), not Public networks (coffee shops, hotels).

---

## Updating the app later

```powershell
cd C:\ConnectClips
git pull
cd frontend
npm run build
nssm restart ConnectClips
```

If `requirements.txt` or `package.json` changed:

```powershell
cd C:\ConnectClips\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install
npm run build
nssm restart ConnectClips
```

---

## Troubleshooting

**`/api/health` reports `h264_encoder: "libx264"`** -- ffmpeg's
`h264_amf` (or `h264_qsv`) didn't link. Update the GPU driver from
amd.com / intel.com and re-check `ffmpeg -encoders`.

**Service starts but transcribe never finishes** -- `WHISPER_MODEL` is
probably `large-v3` left over from a copied `.env`, and `WHISPER_BACKEND`
is `ctranslate2` (no Vulkan). Either install the whispercli bundle
(section 4c) and set `WHISPER_BACKEND=whispercli`, or switch to
`WHISPER_MODEL=small` to stay on the CPU fallback.

**`/api/health` shows `ort_providers: ["CPUExecutionProvider"]` and
the backend log says `whisper-cli not found` even though the binary
is at `C:\ConnectClips\bin\whisper-cli.exe`** -- check `WHISPER_CLI_PATH`
in `.env` and confirm there are no smart quotes (some editors auto-
substitute the regular `\` path separator with U+201C `"`). NSSM
service needs a restart after `.env` changes (`nssm restart ConnectClips`).

**YouTube job fails with `ffmpeg is not installed`** -- the NSSM
service runs as LocalSystem and can't follow the per-user winget shim
that `Gyan.FFmpeg` puts on PATH. `install-windows.ps1` writes the real
ffmpeg directory into the service's PATH at install time, but if
winget later upgrades ffmpeg the directory name changes (the version
is baked in) and the service config goes stale. Recover with:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ConnectClips\scripts\fix-service-ffmpeg-path.ps1
```

That script re-resolves the current ffmpeg location and rewrites the
service's `AppEnvironmentExtra`. Needs elevated PowerShell.

**`Activate.ps1 cannot be loaded because running scripts is disabled`**
-- run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy
RemoteSigned` once, in an unelevated PowerShell.

**`pip install` hangs at `Building wheel for X`** -- some wheels need
a C++ compiler. Install Visual Studio Build Tools (winget id
`Microsoft.VisualStudio.2022.BuildTools` with the C++ workload) and
re-run.

**NSSM service won't start, log file is empty** -- the venv path is
probably wrong. `nssm dump ConnectClips` shows the configured command
line. Common cause: cloning the repo somewhere other than
`C:\ConnectClips\`. Fix with `nssm set ConnectClips Application
<correct-path>` then `nssm restart ConnectClips`.

**`select_clips` fails with `401 invalid x-api-key`** -- usually means
the `.env` file has Windows line endings (CRLF) inside the API key.
Re-paste the key in a clean editor (Notepad++, VS Code) with LF endings
and restart.

**Whisper transcribes correctly but the captions look wrong** -- check
that `WHISPER_MODEL` is at least `small`. `tiny` and `base` mistranscribe
proper names and Bible references frequently enough that volunteers
will notice; `small` is the floor.

**Service runs but `/api/health` returns 502 from outside the box** --
firewall. See step 9d above, or rely on Tailscale.

**Page loads on the box but not over Tailscale** -- check
`tailscale serve status`. If the rule is missing, re-run the `tailscale
serve` command from step 9b.

---

## What we're NOT doing in this guide

- Putting the app on the public internet without Tailscale
- Multi-user concurrent uploads at high volume
- HTTPS termination on the Windows box directly (Tailscale Serve
  handles that)
- Running ConnectClips during a service while the box is also driving
  WorshipTools Presenter -- ConnectClips is CPU-heavy and will fight
  Presenter for cycles. Schedule jobs around the service window manually
  for now; the admin-configurable service-window gate is on the
  Phase 3 roadmap.

If your church needs any of those, ConnectClips is a good base but
you'll be writing some ops code. Open an issue if you want to discuss.
