# install-windows.ps1 -- automate ConnectClips install on Windows 11 native.
#
# Idempotent: safe to re-run after a partial failure. Each step detects
# existing state and skips work that's already done.
#
# Run from inside a ConnectClips checkout (you must `git clone` first).
# Will prompt twice: once for your Anthropic API key, once for an admin
# password. To run non-interactively, set $env:CONNECTCLIPS_API_KEY and
# $env:CONNECTCLIPS_ADMIN_PASSWORD.
#
# The NSSM Windows-service step at the end requires Administrator. The
# rest does not. The script detects the elevation level and skips the
# service step with a hint if you're running as a regular user -- finish
# the build/test phase first, then re-launch the script elevated to
# install the service.
#
# Optional env overrides:
#   CONNECTCLIPS_DATA_ROOT  default C:\ConnectClips-data
#   CONNECTCLIPS_PORT       default 8765
#
# This script does NOT install Tailscale or open the Windows firewall.
# See docs/DEPLOYING-windows.md for those steps.

[CmdletBinding()]
param(
    [string]$DataRoot = $env:CONNECTCLIPS_DATA_ROOT,
    [int]$Port = $(if ($env:CONNECTCLIPS_PORT) { [int]$env:CONNECTCLIPS_PORT } else { 8765 })
)

$ErrorActionPreference = 'Stop'

# ----- Globals --------------------------------------------------------------

if (-not $DataRoot) { $DataRoot = 'C:\ConnectClips-data' }
$RepoDir = (Resolve-Path "$PSScriptRoot\..").Path
$IsElev  = ([Security.Principal.WindowsPrincipal]([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# ----- Logging --------------------------------------------------------------

function Write-Log    { param($msg) Write-Host "[install] $msg" -ForegroundColor Blue }
function Write-Warn   { param($msg) Write-Host "[install:warn] $msg" -ForegroundColor Yellow }
function Write-Fail   { param($msg) Write-Host "[install:fail] $msg" -ForegroundColor Red; exit 1 }
function Have-Cmd     { param($cmd) [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    # winget installs land in dirs that aren't on PATH for the running shell.
    # Pull machine + user PATH from the registry to pick up new tools.
    $machine = [Environment]::GetEnvironmentVariable('Path','Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path','User')
    $env:PATH = ($machine, $user -join ';')
}

# ----- Preflight ------------------------------------------------------------

if (-not (Test-Path "$RepoDir\backend\requirements.txt")) {
    Write-Fail "Couldn't find backend\requirements.txt under $RepoDir -- run this from inside a ConnectClips clone."
}
if (-not (Have-Cmd winget)) {
    Write-Fail "winget not on PATH. Install 'App Installer' from the Microsoft Store, then re-run."
}
if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    Write-Fail 'Windows only -- for macOS use scripts/install-mac.sh, for WSL/Linux use scripts/install-wsl.sh'
}

# ----- Steps ----------------------------------------------------------------

function Step-WingetPackages {
    Write-Log '[1/10] Tooling via winget (Python 3.12, Node LTS, ffmpeg, git, NSSM)'

    # Map: winget package id  ->  exe name we expect on PATH after refresh.
    # Order matters: python first so Step-VenvPip can use it; nssm last
    # because it's only needed by the elevated service step.
    $packages = @(
        @{ Id = 'Python.Python.3.12';  Probe = 'python.exe' },
        @{ Id = 'OpenJS.NodeJS.LTS';   Probe = 'node.exe'   },
        @{ Id = 'Gyan.FFmpeg';         Probe = 'ffmpeg.exe' },
        @{ Id = 'Git.Git';             Probe = 'git.exe'    },
        @{ Id = 'NSSM.NSSM';           Probe = 'nssm.exe'   }
    )

    foreach ($p in $packages) {
        if (Have-Cmd $p.Probe) {
            Write-Log "  $($p.Id) already present"
            continue
        }
        Write-Log "  installing $($p.Id)..."
        # Note: don't name this $args -- that's an automatic variable in PS.
        $wingetArgs = @(
            'install','--id', $p.Id,
            '--silent',
            '--accept-source-agreements',
            '--accept-package-agreements'
        )
        & winget @wingetArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "winget install $($p.Id) failed (exit $LASTEXITCODE)"
        }
    }

    Refresh-Path

    foreach ($p in $packages) {
        if (-not (Have-Cmd $p.Probe)) {
            Write-Warn "  $($p.Probe) still not on PATH after install -- open a new PowerShell and re-run."
            Write-Fail "tool $($p.Probe) missing"
        }
    }
}

function Step-AcceleratorCheck {
    Write-Log '[2/10] Hardware accelerator probe (informational only)'

    if (Test-Path "$env:windir\System32\amfrt64.dll") {
        Write-Log '  AMF runtime present (h264_amf encoder available on AMD GPUs)'
    } else {
        Write-Warn '  AMF runtime missing -- AMD hardware encode not available; libx264 software fallback'
    }
    if (Test-Path "$env:windir\System32\nvcuda.dll") {
        Write-Log '  NVIDIA driver present (h264_nvenc + CUDA Whisper would work -- but this script does NOT install CUDA wheels; use install-wsl.sh for NVIDIA)'
    }
    if (Test-Path "$env:windir\System32\vulkan-1.dll") {
        Write-Log '  Vulkan loader present (deviceID enumerable; not used by ConnectClips in v1)'
    }

    # Probe ffmpeg's actual encoder list -- winget's Gyan.FFmpeg ships with
    # h264_amf, h264_qsv, and libx264. Surface what's available.
    $encoders = & ffmpeg -hide_banner -encoders 2>$null | Out-String
    if     ($encoders -match 'h264_nvenc')      { Write-Log '  ffmpeg: h264_nvenc available' }
    elseif ($encoders -match 'h264_amf')        { Write-Log '  ffmpeg: h264_amf available (AMD HW encode)' }
    elseif ($encoders -match 'h264_qsv')        { Write-Log '  ffmpeg: h264_qsv available (Intel QuickSync)' }
    else                                        { Write-Warn '  ffmpeg has no hardware h264 encoder; export will use libx264 (slower but works)' }
}

function Step-VenvPip {
    Write-Log '[3/10] Backend venv + pip install'

    # Use py launcher to pin the venv to Python 3.12 specifically; on a box
    # with multiple Pythons `python` may resolve to the wrong one.
    $py312 = & py -3.12 -V 2>$null
    if (-not $py312) {
        Write-Fail "py -3.12 not callable -- Python 3.12 install didn't take. Open a new PowerShell and re-run."
    }

    Push-Location "$RepoDir\backend"
    try {
        if (-not (Test-Path .venv)) {
            & py -3.12 -m venv .venv
        }
        & ".\.venv\Scripts\python.exe" -m pip install --upgrade --quiet pip wheel
        Write-Log '  installing requirements.txt (CPU-only; CUDA wheels are skipped on Windows)'
        & ".\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
    } finally {
        Pop-Location
    }
}

function Step-YunetModel {
    Write-Log '[4/11] YuNet face detector'
    # Backend looks for the model at ~/.cache/connectclips/face_*.onnx
    # (see backend/app/services/reframe.py); match the Linux/macOS layout
    # so we don't have to special-case path resolution per platform.
    $target = "$env:USERPROFILE\.cache\connectclips\face_detection_yunet_2023mar.onnx"
    if (Test-Path $target) {
        $sz = (Get-Item $target).Length
        if ($sz -gt 200000) {
            Write-Log "  already downloaded ($([math]::Round($sz/1KB)) KB)"
            return
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Invoke-WebRequest `
        -Uri 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx' `
        -OutFile $target -UseBasicParsing
    Write-Log "  downloaded to $target"
}

# Module-level state set by Step-WhispercliBundle, read by Step-EnvFile so the
# generated .env points at whichever Whisper backend actually got installed.
$Script:WhispercliPath  = $null
$Script:WhispercliModel = $null

function Step-WhispercliBundle {
    Write-Log '[5/11] whisper-cli (Vulkan whisper.cpp) bundle'

    if ($env:CONNECTCLIPS_SKIP_WHISPERCLI -eq '1') {
        Write-Warn '  CONNECTCLIPS_SKIP_WHISPERCLI=1 -- using ctranslate2 CPU instead'
        return
    }

    # Tag of a ConnectClips release that has whispercli-windows-x64-vulkan-*.zip
    # attached. Built by .github/workflows/build-whispercli.yml and uploaded via
    # softprops/action-gh-release. Bumped when whisper.cpp upstream cuts a
    # release we want to follow.
    $tag = if ($env:CONNECTCLIPS_WHISPERCLI_TAG) { $env:CONNECTCLIPS_WHISPERCLI_TAG } else { 'whispercli-v1.8.4' }
    # Model name for the whisper-cli ggml file. medium.en is the default --
    # ~1.5 GB download, ~6.5x realtime on Vulkan / ~2.7x on CPU. Overridable
    # to small (~470 MB, CPU-friendly) or large-v3 (~3.1 GB, best quality;
    # only practical with Vulkan).
    $model = if ($env:CONNECTCLIPS_WHISPER_MODEL) { $env:CONNECTCLIPS_WHISPER_MODEL } else { 'medium.en' }

    $binDir   = "$RepoDir\bin"
    $cliPath  = "$binDir\whisper-cli.exe"
    $modelDir = "$env:USERPROFILE\.cache\whisper.cpp"
    $modelPath = "$modelDir\ggml-$model.bin"

    # ---- whisper-cli binary ----
    if (Test-Path $cliPath) {
        Write-Log "  whisper-cli.exe already at $cliPath"
    } else {
        # The release zip is built by .github/workflows/build-whispercli.yml;
        # the asset name pattern there is whispercli-<os-arch>-vulkan-<ref>.zip.
        $ref = $tag -replace '^whispercli-', ''
        $assetName = "whispercli-windows-x64-vulkan-$ref.zip"
        $url = "https://github.com/connect-community-church/connectclips/releases/download/$tag/$assetName"
        Write-Log "  downloading $assetName..."
        $tmpZip = "$env:TEMP\$assetName"
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmpZip -UseBasicParsing -ErrorAction Stop
        } catch {
            Write-Warn "  download failed ($($_.Exception.Message))"
            Write-Warn "  falling back to ctranslate2 CPU. To retry later: re-run this script after the release is published."
            Write-Warn "  Or build the binary locally: scripts\install-vulkan-buildtools.ps1 then build whisper.cpp from source."
            return
        }
        New-Item -ItemType Directory -Force -Path $binDir | Out-Null
        Expand-Archive -Path $tmpZip -DestinationPath $binDir -Force
        Remove-Item $tmpZip -ErrorAction SilentlyContinue
        if (-not (Test-Path $cliPath)) {
            Write-Warn "  zip extracted but $cliPath not found; falling back to ctranslate2 CPU"
            return
        }
        Write-Log "  installed to $cliPath"
    }

    # ---- ggml model ----
    if (Test-Path $modelPath) {
        $sz = (Get-Item $modelPath).Length
        Write-Log "  ggml-$model.bin already present ($([math]::Round($sz/1MB)) MB)"
    } else {
        # huggingface hosts the canonical ggml whisper weights.
        $modelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$model.bin"
        Write-Log "  downloading ggml-$model.bin (this is the long pole -- 470 MB / 1.5 GB / 3.1 GB depending on model)..."
        New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
        try {
            Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath -UseBasicParsing -ErrorAction Stop
        } catch {
            Write-Warn "  model download failed ($($_.Exception.Message))"
            Write-Warn "  whisper-cli will fail to start until a model is dropped at $modelPath"
            Write-Warn "  You can also download manually from $modelUrl"
            return
        }
        Write-Log "  installed to $modelPath ($([math]::Round((Get-Item $modelPath).Length/1MB)) MB)"
    }

    # Record paths so Step-EnvFile writes them to .env.
    $Script:WhispercliPath  = $cliPath
    $Script:WhispercliModel = $model
}

function Step-DataDirs {
    Write-Log '[6/11] Data directories'
    foreach ($sub in 'sources','work','clips','logs') {
        New-Item -ItemType Directory -Force -Path "$DataRoot\$sub" | Out-Null
    }
    Write-Log "  $DataRoot\{sources,work,clips,logs}"
}

function Read-Secret {
    param($Prompt)
    $secure = Read-Host -AsSecureString -Prompt $Prompt
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try   { [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Step-EnvFile {
    Write-Log '[7/11] backend\.env'
    Push-Location "$RepoDir\backend"
    try {
        if (Test-Path .env) {
            Write-Log '  existing .env preserved (delete it if you want to redo this step)'
            return
        }

        $apiKey = if ($env:CONNECTCLIPS_API_KEY) { $env:CONNECTCLIPS_API_KEY } else { Read-Secret 'Anthropic API key (sk-ant-...)' }
        if (-not $apiKey) { Write-Fail 'API key cannot be empty' }
        if (-not $apiKey.StartsWith('sk-ant-')) { Write-Warn '  API key does not start with sk-ant- -- make sure that is intended' }

        $adminPw = if ($env:CONNECTCLIPS_ADMIN_PASSWORD) { $env:CONNECTCLIPS_ADMIN_PASSWORD } else { Read-Secret 'Choose an admin password' }
        if (-not $adminPw) { Write-Fail 'admin password cannot be empty' }

        $sessionSecret = & ".\.venv\Scripts\python.exe" -c 'import secrets; print(secrets.token_urlsafe(32))'
        if ($LASTEXITCODE -ne 0) { Write-Fail 'failed to generate SESSION_SECRET via venv python' }

        # Whisper model + backend: pick whichever Step-WhispercliBundle
        # actually managed to install. If it landed (whisper-cli + ggml model
        # present), use the whispercli backend with the model that was pulled.
        # Otherwise fall back to ctranslate2 + 'small' on CPU -- the floor
        # that transcribes Bible references reliably.
        if ($Script:WhispercliPath -and $Script:WhispercliModel) {
            $whisperBackend = 'whispercli'
            $whisperModel   = $Script:WhispercliModel
            $whisperCliPath = $Script:WhispercliPath
            Write-Log "  using whispercli backend (model=$whisperModel)"
        } else {
            $whisperBackend = 'ctranslate2'
            $whisperModel   = 'small'
            $whisperCliPath = ''
            Write-Log "  using ctranslate2 CPU backend (model=$whisperModel)"
        }

        $envContent = @"
# ConnectClips backend config -- generated by scripts\install-windows.ps1
DATA_SOURCES_DIR=$DataRoot\sources
DATA_WORK_DIR=$DataRoot\work
DATA_CLIPS_DIR=$DataRoot\clips

ANTHROPIC_API_KEY=$apiKey
CLAUDE_MODEL=claude-sonnet-4-6

WHISPER_MODEL=$whisperModel
WHISPER_COMPUTE_TYPE=int8
WHISPER_DEVICE=auto
WHISPER_BACKEND=$whisperBackend
WHISPER_CLI_PATH=$whisperCliPath

ADMIN_PASSWORD=$adminPw
SESSION_SECRET=$sessionSecret
ADMIN_TAILSCALE_LOGINS=
"@
        # WriteAllText avoids the BOM that Set-Content -Encoding utf8 adds in
        # PowerShell 5.1 -- python-dotenv reads the file fine either way, but
        # a BOM-free file matches what install-mac.sh and install-wsl.sh produce.
        [System.IO.File]::WriteAllText("$pwd\.env", $envContent, [System.Text.UTF8Encoding]::new($false))
        Write-Log '  written'
    } finally {
        Pop-Location
    }
}

function Step-FrontendBuild {
    Write-Log '[8/11] Frontend build'
    Push-Location "$RepoDir\frontend"
    try {
        if (-not (Test-Path node_modules)) {
            Write-Log '  npm install...'
            & npm install --silent
            if ($LASTEXITCODE -ne 0) { Write-Fail 'npm install failed' }
        }
        Write-Log '  npm run build...'
        & npm run build --silent
        if ($LASTEXITCODE -ne 0) { Write-Fail 'npm run build failed' }
        if (-not (Test-Path 'dist\index.html')) { Write-Fail 'Frontend build did not produce dist\index.html' }
    } finally {
        Pop-Location
    }
}

function Step-SmokeTest {
    Write-Log '[9/11] Smoke test (start uvicorn briefly + GET /api/health)'
    Push-Location "$RepoDir\backend"
    try {
        # If something's already on the port (e.g. a previously-installed
        # NSSM service), don't fight with it -- verify it answers /api/health.
        $existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Log "  port $Port already bound -- testing existing instance"
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 5
            $resp.Content | Set-Content "$env:TEMP\connectclips-install-health.json"
            Write-Log '  /api/health 200 OK'
            return
        }

        $logfile = "$env:TEMP\connectclips-install-smoke.log"
        $errfile = "$env:TEMP\connectclips-install-smoke.err"
        # Start-Process refuses to redirect stdout and stderr to the same file
        # (sharing violation), so use two paths and merge if you need to read.
        $proc = Start-Process -FilePath ".\.venv\Scripts\uvicorn.exe" `
            -ArgumentList @('app.main:app','--host','127.0.0.1','--port',$Port,'--log-level','warning') `
            -PassThru -RedirectStandardOutput $logfile -RedirectStandardError $errfile -NoNewWindow

        try {
            # 120 s parity with install-mac.sh -- first-time imports of
            # faster_whisper + onnxruntime + opencv on a cold cache can be slow.
            $ok = $false
            for ($i = 0; $i -lt 120; $i++) {
                try {
                    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
                    $resp.Content | Set-Content "$env:TEMP\connectclips-install-health.json"
                    $ok = $true
                    break
                } catch {
                    Start-Sleep -Seconds 1
                }
            }
            if (-not $ok) {
                if (Test-Path $errfile) { Get-Content $errfile | Select-Object -Last 50 | Write-Host }
                if (Test-Path $logfile) { Get-Content $logfile | Select-Object -Last 50 | Write-Host }
                Write-Fail "Smoke test failed after 120 s -- uvicorn did not respond. Logs: $logfile / $errfile"
            }
            Write-Log '  /api/health 200 OK'
        } finally {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    } finally {
        Pop-Location
    }
}

function Step-NssmService {
    Write-Log '[10/11] NSSM Windows Service'

    if (-not $IsElev) {
        Write-Warn '  NOT running as Administrator -- skipping NSSM service install'
        Write-Log '  To install the autostart service, re-run this script from an elevated PowerShell:'
        Write-Log "    Start-Process powershell -Verb RunAs -ArgumentList '-File','$($MyInvocation.PSCommandPath)'"
        Write-Log '  (the rest of the install is already complete; the elevated re-run will only finish this step)'
        return
    }

    $svc = 'ConnectClips'
    $existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Log "  $svc service exists -- stopping + removing old config so the new one can install cleanly"
        try { & nssm stop $svc 2>&1 | Out-Null } catch {}
        & nssm remove $svc confirm 2>&1 | Out-Null
        Start-Sleep -Seconds 1
    }

    $venvUvicorn = "$RepoDir\backend\.venv\Scripts\uvicorn.exe"
    $logPath = "$DataRoot\logs\connectclips.log"
    if (-not (Test-Path $venvUvicorn)) {
        Write-Fail "uvicorn.exe not found at $venvUvicorn -- venv install must have failed"
    }

    # winget installs Gyan.FFmpeg into the user profile and adds a *shim*
    # exe to %LOCALAPPDATA%\Microsoft\WinGet\Links. Shims work fine for
    # interactive sessions but the NSSM service runs as LocalSystem and
    # can't traverse them reliably. Resolve the real ffmpeg directory
    # and bake it into the service's PATH so yt-dlp + ffmpeg find each
    # other at runtime.
    $ffmpegBin = $null
    $wingetPkgs = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
    if (Test-Path $wingetPkgs) {
        $hit = Get-ChildItem $wingetPkgs -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
                 Where-Object { $_.FullName -match 'Gyan\.FFmpeg' } |
                 Select-Object -First 1
        if ($hit) { $ffmpegBin = $hit.DirectoryName }
    }
    if (-not $ffmpegBin) {
        Write-Warn '  could not locate ffmpeg.exe under WinGet packages -- service may not see ffmpeg'
        Write-Warn '  if YouTube downloads fail with "ffmpeg not installed", run scripts\fix-service-ffmpeg-path.ps1'
    }

    & nssm install $svc $venvUvicorn 'app.main:app' '--host' '0.0.0.0' '--port' $Port '--log-level' 'warning'
    & nssm set $svc AppDirectory   "$RepoDir\backend"
    & nssm set $svc AppStdout      $logPath
    & nssm set $svc AppStderr      $logPath
    & nssm set $svc AppRotateFiles 1
    & nssm set $svc AppRotateBytes 10485760  # 10 MB rotation
    & nssm set $svc Start          SERVICE_AUTO_START
    & nssm set $svc Description    'ConnectClips backend (FastAPI/uvicorn)'
    if ($ffmpegBin) {
        & nssm set $svc AppEnvironmentExtra "PATH=$ffmpegBin"
        Write-Log "  service PATH now includes $ffmpegBin"
    }

    & nssm start $svc

    Start-Sleep -Seconds 3
    $svcStatus = (Get-Service -Name $svc).Status
    if ($svcStatus -eq 'Running') {
        Write-Log "  $svc service: Running"
    } else {
        Write-Warn "  $svc service status: $svcStatus. Tail the log: Get-Content -Tail 100 $logPath"
    }
}

function Step-Done {
    Write-Log '[11/11] All done'
    Write-Log ''
    Write-Log "Install complete. Open http://localhost:$Port/"
    Write-Log "Backend logs: Get-Content -Tail 100 -Wait $DataRoot\logs\connectclips.log"
    if (-not $IsElev) {
        Write-Log ''
        Write-Log 'NSSM autostart service was NOT installed (script not elevated).'
        Write-Log 'To install it now, run this in an elevated PowerShell:'
        Write-Log "  Start-Process powershell -Verb RunAs -ArgumentList '-File','$($MyInvocation.PSCommandPath)'"
    }
    Write-Log 'For Tailscale remote access, see step 9 of docs/DEPLOYING-windows.md'
}

# ----- Main -----------------------------------------------------------------

Write-Log "ConnectClips Windows install -- repo at $RepoDir"
Write-Log "Data dirs: $DataRoot (set CONNECTCLIPS_DATA_ROOT to override)"
Write-Log "Port: $Port"
if ($IsElev) { Write-Log 'Running as Administrator (NSSM step will install the service)' }

Step-WingetPackages
Step-AcceleratorCheck
Step-VenvPip
Step-YunetModel
Step-WhispercliBundle
Step-DataDirs
Step-EnvFile
Step-FrontendBuild
Step-SmokeTest
Step-NssmService
Step-Done
