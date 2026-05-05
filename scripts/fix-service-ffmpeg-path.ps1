# One-shot: tell the ConnectClips NSSM service where ffmpeg lives.
#
# winget installs Gyan.FFmpeg into the user profile and only puts a shim
# on PATH. The NSSM-managed service runs as LocalSystem and can't follow
# that shim, so yt-dlp inside the running backend reports "ffmpeg not
# installed". This script auto-detects the real ffmpeg dir under WinGet
# packages and writes it into the service's AppEnvironmentExtra PATH.
#
# install-windows.ps1 does the same thing automatically -- this script is
# the recovery path for an existing install (e.g., after winget upgrades
# ffmpeg and changes the version in the directory name).
#
# Needs elevated PowerShell (NSSM service-config writes need admin).

$wingetPkgs = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
$hit = Get-ChildItem $wingetPkgs -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
         Where-Object { $_.FullName -match 'Gyan\.FFmpeg' } |
         Select-Object -First 1

if (-not $hit) {
    Write-Host "Could not find ffmpeg.exe under $wingetPkgs" -ForegroundColor Red
    Write-Host "Try: winget install Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements"
    exit 1
}

$ffdir = $hit.DirectoryName
Write-Host "ffmpeg dir: $ffdir" -ForegroundColor Cyan

nssm set ConnectClips AppEnvironmentExtra "PATH=$ffdir"
Write-Host "Restarting service..." -ForegroundColor Cyan
nssm restart ConnectClips

Start-Sleep -Seconds 5
Get-Service ConnectClips
Write-Host ""
Write-Host "Tail the log to confirm h264_amf shows up at startup:"
Write-Host "  Get-Content -Tail 30 C:\ConnectClips-data\logs\connectclips.log"
