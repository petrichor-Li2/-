# Run every PC-side test.  ASCII-only file (works in any PowerShell encoding).
# NOTE: unittest writes to stderr, so we must not use ErrorActionPreference = 'Stop'.
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$tools = Join-Path $root 'tools'

function Invoke-Py([string]$argline) {
    $out = & python $argline.Split(' ') 2>&1
    $out | ForEach-Object { Write-Host $_ }
    return $LASTEXITCODE
}

Write-Host "=== 1/4 protocol reference tests ===" -ForegroundColor Cyan
$r1 = Invoke-Py (Join-Path $tools 'test_maix_protocol.py')

Write-Host ""
Write-Host "=== 2/4 MaixCAM vision (v1) + device protocol tests ===" -ForegroundColor Cyan
$r2 = Invoke-Py (Join-Path $tools 'test_maixcam_vision.py')

Write-Host ""
Write-Host "=== 3/4 MaixCAM v2 ball-test logic tests ===" -ForegroundColor Cyan
$r3 = Invoke-Py (Join-Path $tools 'test_ball_test.py')

Write-Host ""
Write-Host "=== 4/4 simulator selfcheck ===" -ForegroundColor Cyan
$r4 = Invoke-Py ((Join-Path $tools 'maix_sim.py') + ' --selfcheck')

Write-Host ""
if (($r1 -eq 0) -and ($r2 -eq 0) -and ($r3 -eq 0) -and ($r4 -eq 0)) {
    Write-Host "ALL PC TESTS PASSED" -ForegroundColor Green
    exit 0
}
Write-Host "SOME TESTS FAILED (r1=$r1 r2=$r2 r3=$r3 r4=$r4)" -ForegroundColor Red
exit 1
