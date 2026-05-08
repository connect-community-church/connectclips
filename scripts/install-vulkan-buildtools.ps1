# install-vulkan-buildtools.ps1 -- one-time dev tool.
#
# Installs the toolchain needed to build whisper.cpp from source with
# Vulkan support: cmake + Vulkan SDK + VS Build Tools 2022 (C++ workload).
#
# Self-elevates via UAC if not already running as Administrator, so you
# can launch it from any PowerShell or by right-clicking -> Run with
# PowerShell.
#
# This is a Phase 3 smoke-test dependency; delete this file before the
# Phase 3 PR if we don't end up using the Vulkan path.

# --- Self-elevate -----------------------------------------------------------

$IsAdmin = ([Security.Principal.WindowsPrincipal]([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host 'Re-launching elevated (you should see a UAC prompt)...' -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"")
    exit
}

$ErrorActionPreference = 'Continue'

# --- Steps ------------------------------------------------------------------

function Run-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ''
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        # -1978335189 = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE (already at latest)
        Write-Host "  winget exit code: $LASTEXITCODE" -ForegroundColor Yellow
    }
}

Run-Step 'cmake (small, ~1 min)' {
    winget install --id Kitware.CMake `
        --silent --accept-source-agreements --accept-package-agreements
}

Run-Step 'Vulkan SDK (~1 GB, ~3-5 min)' {
    winget install --id KhronosGroup.VulkanSDK `
        --silent --accept-source-agreements --accept-package-agreements
}

Run-Step 'VS Build Tools 2022 + C++ workload (~5-7 GB, ~10-20 min)' {
    winget install --id Microsoft.VisualStudio.2022.BuildTools `
        --silent --accept-source-agreements --accept-package-agreements `
        --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
}

# --- Verify -----------------------------------------------------------------

# Refresh PATH from registry so newly-installed tools resolve in this session.
$env:PATH = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

Write-Host ''
Write-Host '=== Verify ===' -ForegroundColor Cyan
$ok = $true

foreach ($cmd in 'cmake','glslc') {
    $c = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($c) {
        Write-Host ("  {0,-12} {1}" -f $cmd, $c.Source) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-12} MISSING" -f $cmd) -ForegroundColor Red
        $ok = $false
    }
}

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vs = & $vswhere -latest -property installationPath 2>$null
    if ($vs) {
        Write-Host ("  {0,-12} {1}" -f 'VS Build Tools', $vs) -ForegroundColor Green
    } else {
        Write-Host '  VS Build Tools: vswhere found no instance' -ForegroundColor Red
        $ok = $false
    }
} else {
    Write-Host '  VS Build Tools: vswhere.exe missing -- install failed' -ForegroundColor Red
    $ok = $false
}

if ($env:VULKAN_SDK) {
    Write-Host ("  {0,-12} {1}" -f 'VULKAN_SDK', $env:VULKAN_SDK) -ForegroundColor Green
} else {
    Write-Host '  VULKAN_SDK env var not yet visible -- normal in elevated PS, will appear in a fresh shell' -ForegroundColor Yellow
}

Write-Host ''
if ($ok) {
    Write-Host 'All three installed successfully. You can close this window.' -ForegroundColor Green
} else {
    Write-Host 'One or more tools missing. Check the output above; you may need to re-run.' -ForegroundColor Yellow
}

Write-Host ''
Read-Host 'Press Enter to close this window'
