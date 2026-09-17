param(
    [ValidateSet('Debug', 'Release')]
    [string]$Config = 'Debug',

    [switch]$SelfTest,     # build the power-on self-test firmware (PASS/FAIL over UART)
    [switch]$Clean
)

# NOTE: keep this file ASCII-only so it runs in any Windows PowerShell encoding.

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$fw   = Join-Path $root 'firmware'
$clt  = 'D:\STM32CubeCLT_1.18.0'

# Add STM32CubeCLT tools to this session's PATH (works even if not in system PATH)
$extraPaths = @(
    "$clt\GNU-tools-for-STM32\bin",
    "$clt\CMake\bin",
    "$clt\Ninja\bin",
    "$clt\STM32CubeProgrammer\bin"
)
foreach ($p in $extraPaths) {
    if ((Test-Path $p) -and ($env:PATH -notlike "*$p*")) {
        $env:PATH = "$p;$env:PATH"
    }
}

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "cmake not found. Install STM32CubeCLT or add its CMake\bin to PATH."
}

$buildDir = Join-Path $fw "build\$(if ($SelfTest) { 'SelfTest' } else { $Config })"
$tag = if ($SelfTest) { 'SelfTest' } else { 'Normal' }

Write-Host "=== Configure [$Config / $tag] ===" -ForegroundColor Cyan
$cfgArgs = @('-S', $fw, '-B', $buildDir, '-G', 'Ninja', "-DCMAKE_BUILD_TYPE=$Config")
if ($SelfTest) { $cfgArgs += '-DSELFTEST=ON' } else { $cfgArgs += '-DSELFTEST=OFF' }
& cmake @cfgArgs
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }

Write-Host "=== Build ===" -ForegroundColor Cyan
if ($Clean) {
    & cmake --build $buildDir --clean-first
} else {
    & cmake --build $buildDir
}
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

Write-Host ""
Write-Host "Build OK:" -ForegroundColor Green
Get-ChildItem (Join-Path $buildDir 'AntiTerrorRobot.*') |
    Where-Object { $_.Extension -in '.elf', '.hex', '.bin' } |
    ForEach-Object { Write-Host ("  {0,-28} {1,10:N0} bytes" -f $_.Name, $_.Length) }
Write-Host ""
Write-Host "Flash with:  .\flash.ps1 -Config $(if ($SelfTest) { 'SelfTest' } else { $Config })" -ForegroundColor Yellow
