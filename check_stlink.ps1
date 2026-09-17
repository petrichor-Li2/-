param(
    [int]$FreqKHz = 4000,
    [switch]$Quiet
)

# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 + GBK).
#
# check_stlink.ps1 -- ST-Link / SWD wiring self-check.
#
#   .\check_stlink.ps1                 normal check (4 MHz SWD)
#   .\check_stlink.ps1 -FreqKHz 500    slow SWD (long jumper wires / clone probe)
#
# It verifies, in order:
#   1. Is the ST-Link visible on USB (driver OK)?
#   2. Can it reach the target over SWD (SWCLK / SWDIO / GND wired right)?
#   3. Is the target powered (VTref voltage)?
#   4. Does it identify the chip (expects STM32F405/407/415/417, 1 MB flash)?
# Then it prints the wiring table and what each failure means.

$ErrorActionPreference = 'Continue'
$cli = 'D:\STM32CubeCLT_1.18.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe'

function Section($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }

Write-Host "ST-Link / SWD wiring self-check" -ForegroundColor Green
Write-Host ("Probe path: {0}" -f $cli) -ForegroundColor DarkGray
if (-not (Test-Path $cli)) { Write-Host "STM32_Programmer_CLI.exe not found!" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- 1. USB / driver
Section "1. USB - is the ST-Link present and its driver healthy?"
$pnp = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
       Where-Object { $_.FriendlyName -match 'ST-?Link|STM32|STMicro' }
if ($pnp) {
    $pnp | ForEach-Object { Write-Host ("   [{0}] {1}" -f $_.Status, $_.FriendlyName) -ForegroundColor Green }
} else {
    Write-Host "   Nothing found on USB." -ForegroundColor Red
    Write-Host "   -> Plug the ST-Link into the PC, install the ST-Link driver (STM32 STLink"
    Write-Host "      should appear in Device Manager). A clone with old firmware can also"
    Write-Host "      be the cause: run D:\STM32CubeCLT_1.18.0\STLinkUpgrade.bat"
}

# ---------------------------------------------------------------- 1b. probe already busy?
$busy = Get-Process -Name 'ST-LINK_gdbserver' -ErrorAction SilentlyContinue
$clion = Get-Process -Name 'clion64','clion' -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host ("   NOTE: a GDB server is already running (PID " + (($busy | ForEach-Object { $_.Id }) -join ',') + ").") -ForegroundColor Yellow
    Write-Host "         Only ONE program can use the ST-Link at a time." -ForegroundColor Yellow
    Write-Host "         Stop it first:  .\debug.ps1 -Stop" -ForegroundColor Yellow
} elseif ($clion) {
    Write-Host "   NOTE: CLion is running - if it is in a debug session it also holds the probe." -ForegroundColor Yellow
    Write-Host "         Stop the CLion debug session first (or use CLion's own ST-LINK config)." -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 2/3/4. SWD connect
Section "2. SWD connect (this is what tests SWCLK / SWDIO / GND / target power)"
$out = & $cli -c port=SWD freq=$FreqKHz 2>&1 | Out-String
$ok = $false

foreach ($line in ($out -split "`r?`n")) {
    $l = $line.Trim()
    if ($l -match '^(ST-LINK SN|ST-LINK FW|Voltage|Device ID|Device name|Flash size|Device CPU|SWD freq|Connect mode|Reset mode)') {
        Write-Host "   $l"
        if ($l -match '^Device ID') { $ok = $true }
    }
}

$volt = $null
if ($out -match 'Voltage\s*:\s*([0-9\.]+)V') { $volt = [double]$Matches[1] }

Section "3. Result"
if ($ok) {
    Write-Host "   OK - probe found the chip. SWD wiring is correct." -ForegroundColor Green
    if ($volt -ne $null) {
        if ($volt -lt 2.5) {
            Write-Host ("   WARNING: VTref = {0}V is low. The board may be running on a" -f $volt) -ForegroundColor Yellow
            Write-Host "            weak supply - use the board's own power while debugging." -ForegroundColor Yellow
        } else {
            Write-Host ("   VTref = {0}V (target powered, 3.3V reference OK)" -f $volt) -ForegroundColor Green
        }
    }
} else {
    Write-Host "   FAILED - could not identify the chip." -ForegroundColor Red
    Write-Host ""
    if ($out -match 'No debug probe detected') {
        Write-Host "   Cause: the PC does not see the ST-Link itself (step 1 failed)."
        Write-Host "   Check: USB cable / port, driver, STLinkUpgrade.bat for clones."
    } elseif ($out -match 'DEV_CONNECT_ERR|No STM32 target found|Cannot connect|Error occured|Unable to connect') {
        Write-Host "   Cause: probe is fine but the SWD link to the chip failed."
        Write-Host "   Check (in this order):"
        Write-Host "     0) Is another program holding the probe? (gdbserver / CLion debug session)"
        Write-Host "        -> .\debug.ps1 -Stop     and stop any CLion debug session"
        Write-Host "     1) GND between ST-Link and board (most common mistake)"
        Write-Host "     2) SWDIO -> PA13, SWCLK -> PA14 (not swapped)"
        Write-Host "     3) board is powered (3.3V on the board's own pins)"
        Write-Host "     4) BOOT0 = 0, then press reset once"
        Write-Host "     5) wires too long / noisy -> retry:  .\check_stlink.ps1 -FreqKHz 500"
        Write-Host "     6) wire NRST and use connect-under-reset (this firmware never"
        Write-Host "        disables SWD or sleeps, so this is rarely needed)"
    } else {
        Write-Host "   Raw output:"
        Write-Host $out
    }
}

if (-not $Quiet) {
    Section "Wiring reference: ST-Link V2  <->  STM32F407VGT6"
    Write-Host "   ST-Link side (function)     board side (pin)"
    Write-Host "   ----------------------      ----------------"
    Write-Host "   3.3V   (VTref)          -> 3V3      (only for level reference)"
    Write-Host "   SWDIO                   -> PA13"
    Write-Host "   SWCLK                   -> PA14"
    Write-Host "   GND                     -> GND      (must be connected)"
    Write-Host "   RST / NRST (optional)   -> NRST     (helps connect-under-reset)"
    Write-Host ""
    Write-Host "   Notes:"
    Write-Host "     - On the common blue 'ST-Link V2' USB stick the header is silk-screened"
    Write-Host "       with the function names above - match them, not the pin numbers."
    Write-Host "     - GND is mandatory: without it SWD often half-works then fails."
    Write-Host "     - Do not power the board from the probe's 3.3V if the board has its own"
    Write-Host "       supply; connecting both can back-feed."
    Write-Host "     - This project uses PA13/PA14 for SWD only - it never disables the"
    Write-Host "       debug port and never enters low-power mode, so plain SWD always works."
}

exit $(if ($ok) { 0 } else { 1 })
