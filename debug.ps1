param(
    [ValidateSet('Debug', 'Release', 'SelfTest')]
    [string]$Config = 'Debug',

    [int]$Port = 61234,
    [int]$FreqKHz = 0,
    [switch]$Gdb,
    [switch]$Stop,
    [switch]$KeepAlive
)

# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files using the
# system ANSI code page (GBK on a Chinese Windows), so UTF-8 Chinese comments can
# silently corrupt parsing (the param block stops binding). All Chinese docs live in
# README.md / docs/ instead.
#
# Why: CLion's default Run cannot execute an ARM firmware image on Windows
# (CreateProcess error=193, "not a valid Win32 application"). Correct flow:
#   1) Build the project (Ctrl+F9)
#   2) .\flash.ps1                     flash it  (or CLion run config "Flash to board")
#   3) .\debug.ps1 -Gdb                debug it   (breakpoints / stepping / variables)
#
# Two-step route, for CLion's "GDB Remote Debug" run configuration:
#   terminal A :  .\debug.ps1          start the GDB server only
#   CLion      :  run the GDB Remote Debug config (target remote tcp:localhost:61234)

$ErrorActionPreference = 'Stop'

$root      = $PSScriptRoot
$clt       = 'D:\STM32CubeCLT_1.18.0'
$gdbserver = "$clt\STLink-gdb-server\bin\ST-LINK_gdbserver.exe"
$gdbExe    = "$clt\GNU-tools-for-STM32\bin\arm-none-eabi-gdb.exe"
$cpPath    = "$clt\STM32CubeProgrammer\bin"
$pidFile   = Join-Path $env:TEMP 'antiterror_gdbserver.pid'

if (-not (Test-Path $gdbserver)) { throw "ST-LINK_gdbserver.exe not found: $gdbserver" }
if (-not (Test-Path $gdbExe))    { throw "arm-none-eabi-gdb.exe not found: $gdbExe" }

# ---------------------------------------------------------------- stop mode
if ($Stop) {
    $stopped = $false

    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile | Select-Object -First 1
        $p = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
        if ($p) {
            Stop-Process -Id $oldPid -Force
            Write-Host "Stopped GDB server PID $oldPid." -ForegroundColor Green
            $stopped = $true
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    $left = Get-Process -Name 'ST-LINK_gdbserver' -ErrorAction SilentlyContinue
    if ($left) {
        $left | ForEach-Object { Stop-Process -Id $_.Id -Force }
        Write-Host ("Stopped leftover GDB server(s): " + (($left | ForEach-Object { $_.Id }) -join ',')) -ForegroundColor Green
        $stopped = $true
    }

    if (-not $stopped) { Write-Host "No GDB server was running." -ForegroundColor Yellow }
    exit 0
}

# ---------------------------------------------------------------- locate the ELF
$fw = Join-Path $root 'firmware'
$elfCandidates = @(
    (Join-Path $fw "build\$Config\AntiTerrorRobot.elf"),
    (Join-Path $fw "cmake-build-$($Config.ToLower())\AntiTerrorRobot.elf"),
    (Join-Path $fw 'cmake-build-debug\AntiTerrorRobot.elf'),
    (Join-Path $fw 'build\Debug\AntiTerrorRobot.elf')
) | Select-Object -Unique

$elf = $elfCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $elf) {
    $newest = Get-ChildItem $fw -Recurse -Filter 'AntiTerrorRobot.elf' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest) { $elf = $newest.FullName }
}
if (-not $elf) { throw "No AntiTerrorRobot.elf found. Build it first:  .\build.ps1" }

# ---------------------------------------------------------------- start server
Write-Host "Starting ST-LINK GDB server on port $Port ..." -ForegroundColor Cyan
Write-Host "ELF: $elf" -ForegroundColor DarkGray

$serverArgs = @('-p', $Port, '-d', '-s', '-m', '0', '-e', '-cp', $cpPath)
if ($FreqKHz -gt 0) {
    # ST-Link V2 (especially clones) can fail to handshake over long jumper wires;
    # lowering SWD to 1000 or 500 kHz usually fixes it.
    $serverArgs += @('--frequency', $FreqKHz)
    Write-Host "SWD frequency limited to $FreqKHz kHz" -ForegroundColor DarkGray
}
$proc = Start-Process -FilePath $gdbserver -ArgumentList $serverArgs -PassThru
$proc.Id | Set-Content -Path $pidFile -Encoding ASCII

Start-Sleep -Seconds 3

if ($proc.HasExited) {
    Write-Host ""
    Write-Host "GDB server exited -> most likely no ST-Link / board detected." -ForegroundColor Red
    Write-Host "  - ST-Link plugged in, driver installed?"
    Write-Host "  - Board powered, SWCLK / SWDIO / GND connected?"
    Write-Host "  - Port $Port already used by another gdbserver?  try: .\debug.ps1 -Stop"
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "GDB server running (PID $($proc.Id))." -ForegroundColor Green

# ---------------------------------------------------------------- gdb or hints
if ($Gdb) {
    $gdbScript = Join-Path $env:TEMP 'antiterror.gdb'
    @"
set confirm off
set pagination off
target extended-remote localhost:$Port
monitor reset halt
load
monitor reset halt
break main
continue
"@ | Set-Content -Path $gdbScript -Encoding ASCII

    Write-Host "Connecting arm-none-eabi-gdb (type 'quit' to leave)..." -ForegroundColor Cyan
    & $gdbExe -x $gdbScript $elf

    if (-not $KeepAlive) {
        Get-Process -Id $proc.Id -ErrorAction SilentlyContinue | Stop-Process -Force
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "GDB server stopped." -ForegroundColor Green
    }
    exit 0
}

Write-Host ""
Write-Host "CLion -> Run -> Edit Configurations -> + -> GDB Remote Debug:" -ForegroundColor Yellow
Write-Host "  target remote :  tcp:localhost:$Port"
Write-Host "  symbol file   :  $elf"
Write-Host "  GDB           :  $gdbExe"
Write-Host ""
Write-Host "One-shot terminal debugging :  .\debug.ps1 -Gdb" -ForegroundColor Yellow
Write-Host "Slow SWD for ST-Link V2 clone:  .\debug.ps1 -Gdb -FreqKHz 500" -ForegroundColor Yellow
Write-Host "Stop the server             :  .\debug.ps1 -Stop" -ForegroundColor Yellow
