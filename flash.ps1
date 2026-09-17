param(
    [ValidateSet('Debug', 'Release', 'SelfTest')]
    [string]$Config = 'Debug',

    [string]$File,      # explicitly flash this .hex / .elf / .bin
    [switch]$NoReset    # do not reset the target after programming
)

# NOTE: keep this file ASCII-only so it runs in any Windows PowerShell encoding.

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$clt  = 'D:\STM32CubeCLT_1.18.0'
$cli  = "$clt\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"

if (-not (Test-Path $cli)) {
    throw "STM32_Programmer_CLI.exe not found under $clt"
}

if (-not $File) {
    # Build output can live in several places depending on how you built:
    #   .\build.ps1          -> firmware\build\<Config>\
    #   CLion (own profile)  -> firmware\cmake-build-debug\  /  cmake-build-release\
    $fw = Join-Path $root 'firmware'
    $candidates = @(
        (Join-Path $fw "build\$Config\AntiTerrorRobot.hex"),
        (Join-Path $fw "build\$(if ($Config -eq 'SelfTest') { 'SelfTest' } else { $Config })\AntiTerrorRobot.hex"),
        (Join-Path $fw "cmake-build-$($Config.ToLower())\AntiTerrorRobot.hex"),
        (Join-Path $fw 'cmake-build-debug\AntiTerrorRobot.hex'),
        (Join-Path $fw 'cmake-build-release\AntiTerrorRobot.hex')
    ) | Select-Object -Unique

    $File = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $File) {
        # fall back to the newest .hex anywhere under firmware\
        $newest = Get-ChildItem $fw -Recurse -Filter 'AntiTerrorRobot.hex' -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($newest) { $File = $newest.FullName }
    }

    if (-not $File) {
        throw "No firmware found. Build it first:  .\build.ps1 -Config $Config"
    }
    Write-Host "Using: $File" -ForegroundColor DarkGray
}

if (-not (Test-Path $File)) {
    throw "Firmware not found: $File`nBuild it first:  .\build.ps1 -Config $Config"
}

Write-Host "Flashing $File ..." -ForegroundColor Cyan

$cliArgs = @('-c', 'port=SWD', 'mode=UR', '-w', $File, '-v')
if (-not $NoReset) { $cliArgs += '-rst' }

& $cli @cliArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Flash FAILED. Check:" -ForegroundColor Red
    Write-Host "  1) ST-Link plugged in and driver installed (STM32 STLink in Device Manager)"
    Write-Host "  2) Board powered, SWCLK / SWDIO / GND wired correctly"
    Write-Host "  3) No other tool holding the probe (CLion debug session / STM32CubeIDE)"
    exit 1
}

Write-Host ""
Write-Host "Flash OK, target reset and running." -ForegroundColor Green
Write-Host "Debug log: USB-TTL on PA9(TX)+GND, 115200 8N1 (set your terminal to UTF-8)" -ForegroundColor Yellow
