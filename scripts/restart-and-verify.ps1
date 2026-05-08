# Stop + start the ConnectClips NSSM service, then read /api/health
# back so we can SEE whether the new code took effect. Needs elevated
# PowerShell.

Write-Host 'Stopping ConnectClips...' -ForegroundColor Cyan
nssm stop ConnectClips

# Make sure the python process really died -- NSSM sometimes reports
# success while the worker is still winding down.
Start-Sleep -Seconds 2
$stillRunning = Get-Process uvicorn -ErrorAction SilentlyContinue
if ($stillRunning) {
    Write-Host "uvicorn still alive (pid $($stillRunning.Id)) -- killing forcibly" -ForegroundColor Yellow
    Stop-Process -Id $stillRunning.Id -Force
    Start-Sleep -Seconds 2
}

Write-Host 'Starting ConnectClips...' -ForegroundColor Cyan
nssm start ConnectClips

# Wait for /api/health to come up (cold start can take 30-60s).
Write-Host 'Waiting for /api/health...' -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $j = Invoke-RestMethod 'http://localhost:8765/api/health' -TimeoutSec 2
        $ok = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ok) { Write-Host '/api/health never answered -- check service status' -ForegroundColor Red; exit 1 }

Write-Host ''
Write-Host '=== /api/health platform ===' -ForegroundColor Green
$j.platform | ConvertTo-Json
Write-Host ''
if ($j.platform.h264_encoder -eq 'h264_amf') {
    Write-Host 'h264_amf -- ready to retry export' -ForegroundColor Green
} elseif ($j.platform.h264_encoder -eq 'h264_nvenc') {
    Write-Host 'still h264_nvenc -- the new code did not take. Something else is wrong.' -ForegroundColor Red
} else {
    Write-Host "encoder = $($j.platform.h264_encoder) -- unexpected, check logs" -ForegroundColor Yellow
}
