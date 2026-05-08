# bootstrap.ps1 -- one-liner ConnectClips installer for Windows native.
#
# Usage (paste into an ELEVATED PowerShell):
#   irm https://raw.githubusercontent.com/connect-community-church/connectclips/main/scripts/bootstrap.ps1 | iex
#
# What this does:
#   1. Verifies Windows + winget + admin privileges
#   2. Installs git via winget if not already present
#   3. Clones (or pulls) the repo into C:\ConnectClips
#   4. Hands off to scripts\install-windows.ps1
#
# Override the install dir by setting $env:CONNECTCLIPS_DIR before running:
#   $env:CONNECTCLIPS_DIR = 'D:\Apps\ConnectClips'; irm ... | iex

$ErrorActionPreference = 'Stop'

# ----- Preflight ------------------------------------------------------------

if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    Write-Host '[bootstrap] Windows only. For Linux/WSL/macOS use bootstrap.sh.' -ForegroundColor Red
    exit 1
}

$isAdmin = ([Security.Principal.WindowsPrincipal]([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '[bootstrap] This script needs an elevated PowerShell.' -ForegroundColor Red
    Write-Host '[bootstrap] Right-click PowerShell, pick "Run as administrator", then paste the same command.' -ForegroundColor Red
    exit 1
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host '[bootstrap] winget not found. Install "App Installer" from the Microsoft Store, then re-run.' -ForegroundColor Red
    exit 1
}

$dir = if ($env:CONNECTCLIPS_DIR) { $env:CONNECTCLIPS_DIR } else { 'C:\ConnectClips' }
$repo = 'https://github.com/connect-community-church/connectclips.git'

function Write-Step { param($msg) Write-Host "[bootstrap] $msg" -ForegroundColor Cyan }

# ----- Step 1: git ----------------------------------------------------------

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Step 'installing git via winget...'
    winget install --id Git.Git --silent --accept-source-agreements --accept-package-agreements
    # Refresh PATH so this session sees the just-installed git.
    $env:PATH = ($env:PATH + ';' +
        [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path','User'))
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host '[bootstrap] git still not on PATH after install. Open a new PowerShell and re-run.' -ForegroundColor Red
        exit 1
    }
}
Write-Step "using git: $((Get-Command git).Source)"

# ----- Step 2: clone or pull ------------------------------------------------

if (Test-Path "$dir\.git") {
    Write-Step "$dir already exists -- pulling latest"
    git -C $dir pull --ff-only
} elseif (Test-Path $dir) {
    Write-Host "[bootstrap] $dir exists but isn't a git repo. Move or rename it, then re-run." -ForegroundColor Red
    exit 1
} else {
    Write-Step "cloning into $dir"
    git clone $repo $dir
}

# ----- Step 3: hand off to install-windows.ps1 ------------------------------

$installScript = "$dir\scripts\install-windows.ps1"
if (-not (Test-Path $installScript)) {
    Write-Host "[bootstrap] expected $installScript after clone, but it's missing." -ForegroundColor Red
    exit 1
}

Write-Step 'starting install-windows.ps1 (this is the long part -- ~20-30 min on a fresh box)'
Write-Host ''
& $installScript
