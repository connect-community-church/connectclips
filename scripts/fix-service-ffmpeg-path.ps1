# One-shot: rewrite the ConnectClips NSSM service's environment so it can
# (a) find ffmpeg via PATH and (b) resolve ~/.cache/... paths to the user's
# profile instead of LocalSystem's empty systemprofile.
#
# install-windows.ps1 does the same thing automatically -- this script is
# the recovery path for an existing install (e.g., after winget upgrades
# ffmpeg and changes the version in the directory name, or if the service
# was registered before this fix landed).
#
# Needs elevated PowerShell (NSSM service-config writes need admin).

# --- ffmpeg dir under WinGet ----------------------------------------------

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
$home_  = $env:USERPROFILE   # avoid shadowing the auto var $HOME
Write-Host "ffmpeg dir:    $ffdir"   -ForegroundColor Cyan
Write-Host "service HOME:  $home_"   -ForegroundColor Cyan

# --- Apply ----------------------------------------------------------------
# nssm set ... AppEnvironmentExtra K1=V1 K2=V2 K3=V3 -- multiple args = multiple
# env entries. PATH is special-cased by NSSM to append to the system PATH
# rather than replace it.

nssm set ConnectClips AppEnvironmentExtra "PATH=$ffdir" "USERPROFILE=$home_" "HOME=$home_"
Write-Host "Restarting service..." -ForegroundColor Cyan
nssm restart ConnectClips

Start-Sleep -Seconds 5
Get-Service ConnectClips
Write-Host ""
Write-Host "Tail the log to confirm h264_amf at startup + no NoSuchFile errors:"
Write-Host "  Get-Content -Tail 50 C:\ConnectClips-data\logs\connectclips.log"
