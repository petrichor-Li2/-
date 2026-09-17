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

Write-Host "=== 1/3 protocol reference tests ===" -ForegroundColor Cyan
$r1 = Invoke-Py (Join-Path $tools 'test_maix_protocol.py')

Write-Host ""
Write-Host "=== 2/3 MaixCAM vision + device protocol tests ===" -ForegroundColor Cyan
$r2 = Invoke-Py (Join-Path $tools 'test_maixcam_vision.py')

Write-Host ""
Write-Host "=== 3/3 simulator selfcheck ===" -ForegroundColor Cyan
$r3 = Invoke-Py ((Join-Path $tools 'maix_sim.py') + ' --selfcheck')

Write-Host ""
if (($r1 -eq 0) -and ($r2 -eq 0) -and ($r3 -eq 0)) {
    Write-Host "ALL PC TESTS PASSED" -ForegroundColor Green
    exit 0
}
Write-Host "SOME TESTS FAILED (r1=$r1 r2=$r2 r3=$r3)" -ForegroundColor Red
exit 1
