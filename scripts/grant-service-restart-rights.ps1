# grant-service-restart-rights.ps1 -- one-time setup.
#
# Adds an ACE to the ConnectClips service's DACL granting the install
# user (the account that owns this Claude Code session) Start, Stop,
# QueryStatus, and a few related rights -- enough that
# `Restart-Service ConnectClips` works from a non-elevated PowerShell.
#
# Default user is whoever is running THIS script; pass -User <name> to
# grant a different account. Idempotent -- skips if the ACE is already
# present.
#
# Needs elevated PowerShell (sc.exe sdset is an SCM admin op).

[CmdletBinding()]
param(
    [string]$Service = 'ConnectClips',
    [string]$User    = $env:USERNAME
)

$ErrorActionPreference = 'Stop'

# Resolve user -> SID
try {
    $sid = (New-Object System.Security.Principal.NTAccount($User)).Translate([System.Security.Principal.SecurityIdentifier]).Value
} catch {
    Write-Host "Could not resolve user '$User' to a SID: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host "User:    $User" -ForegroundColor Cyan
Write-Host "SID:     $sid" -ForegroundColor Cyan

# Standard "manage this service" rights -- well-known pattern that matches
# what SYSTEM (SY) gets by default (sans WRITE_DAC / WRITE_OWNER / DELETE).
# For SERVICE objects the SDDL letter codes are:
#  CC = QUERY_CONFIG     DC = CHANGE_CONFIG    LC = QUERY_STATUS
#  SW = ENUMERATE_DEPS   RP = START            WP = STOP
#  DT = PAUSE_CONTINUE   LO = INTERROGATE      CR = USER_DEFINED_CONTROL
#  RC = READ_CONTROL (standard)
# NOT to be confused with the AD object SDDL where these letters mean
# different things -- this script earlier had CR for STOP, which silently
# granted USER_DEFINED_CONTROL instead.
$ace = "(A;;CCLCSWRPWPDTLOCRRC;;;$sid)"

# If a previous (broken) run left a wrong ACE for this SID, strip it first.
$current = (& sc.exe sdshow $Service) -join '' -replace '\s',''
$wrongAce = "(A;;CCLCSWRPLOCRRC;;;$sid)"
if ($current -match [regex]::Escape($wrongAce)) {
    Write-Host "Removing stale ACE from earlier run: $wrongAce" -ForegroundColor Yellow
    $current = $current -replace [regex]::Escape($wrongAce), ''
    & sc.exe sdset $Service $current | Out-Null
}

# Read current DACL
$current = (& sc.exe sdshow $Service) -join '' -replace '\s',''
if (-not $current) {
    Write-Host "sdshow returned empty for $Service -- service exists?" -ForegroundColor Red
    exit 1
}
Write-Host "Before:  $current"

if ($current -match [regex]::Escape($ace)) {
    Write-Host "ACE already present -- nothing to do" -ForegroundColor Green
    exit 0
}

# Prepend our ACE inside the D: section so it's evaluated before any
# DENY entries. SDDL format is roughly D:(ace1)(ace2)...S:(...)
if ($current -notmatch '^D:') {
    Write-Host "Unexpected SDDL format (no D: section): $current" -ForegroundColor Red
    exit 1
}
# Insert just after 'D:' and any flags before the first '('.
$newDacl = [regex]::Replace($current, '^(D:[^(]*)', "`$1$ace", 1)
Write-Host "After:   $newDacl"

# Apply
& sc.exe sdset $Service $newDacl
if ($LASTEXITCODE -ne 0) {
    Write-Host "sc.exe sdset failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Done. From a non-elevated PowerShell, '$User' should now be able to:" -ForegroundColor Green
Write-Host "  Restart-Service $Service"
Write-Host "  Stop-Service $Service"
Write-Host "  Start-Service $Service"
