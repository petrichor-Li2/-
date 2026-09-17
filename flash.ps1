param(
    [ValidateSet('Debug', 'Release', 'SelfTest')]
    [string]$Config = 'Debug',

    [string]$File,      # explicitly flash this .hex / .elf / .bin
    [switch]$NoReset,   # do not reset the target after programming
    [switch]$Verify     # read the flash back and compare with the .hex
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

# ---------------------------------------------------------------- readback verify
if ($Verify) {
    if ([System.IO.Path]::GetExtension($File).ToLower() -ne '.hex') {
        Write-Host "-Verify needs the .hex (it is what the programmer writes). Skipped." -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host "Readback verification ..." -ForegroundColor Cyan

        # 1) work out how much flash to read back, from the HEX records
        #    (HEX 第一行通常是 type 0x04 的扩展线性地址记录, 必须跟踪,
        #     否则地址只算到低 16 位; 见 tools/verify_flash.py 里同样的逻辑)
        $maxAddr = 0
        $upper   = 0
        foreach ($line in [System.IO.File]::ReadLines($File)) {
            $t = $line.Trim()
            if ($t.Length -lt 11 -or $t[0] -ne ':') { continue }
            $b = New-Object byte[] ([int](($t.Length - 1) / 2))
            for ($i = 0; $i -lt $b.Length; $i++) { $b[$i] = [Convert]::ToByte($t.Substring(1 + 2 * $i, 2), 16) }
            $recType = $b[3]
            if ($recType -eq 0x01) { break }                      # EOF
            if ($recType -eq 0x04) {                              # 扩展线性地址
                # NOTE: PowerShell 的 -shl 作用在 byte 上会按 byte 截断(8 -shl 8 = 0),
                #       所以这里必须用显式乘法而不是移位。
                $upper = ([int]$b[4] * 256 + [int]$b[5]) * 65536
                continue
            }
            if ($recType -eq 0x00) {                              # 数据
                # NOTE: Intel HEX 的地址字段是大端 (b[1] = 高字节, b[2] = 低字节),
                #       写反了会把 0x47FC 算成 0xFC4B。
                $end = $upper + ([int]$b[1] * 256 + [int]$b[2] + [int]$b[0])
                if ($end -gt $maxAddr) { $maxAddr = $end }
            }
        }
        if ($maxAddr -le 0) { $maxAddr = 0x8000000 + 0x10000 }
        $bytes = $maxAddr - 0x08000000
        $size  = [int]([Math]::Ceiling(($bytes + 512) / 1024.0) * 1024)   # round up to 1 KB

        $dump = Join-Path $env:TEMP 'antiterror_readback.bin'
        Remove-Item $dump -Force -ErrorAction SilentlyContinue
        & $cli -c port=SWD -u 0x08000000 ("0x{0:X}" -f $size) $dump | Out-Null

        if (-not (Test-Path $dump)) {
            Write-Host "Readback failed (no dump file). Check the probe connection." -ForegroundColor Red
        } else {
            $py = Join-Path $root 'tools\verify_flash.py'
            & python $py $File $dump
            if ($LASTEXITCODE -ne 0) {
                Write-Host "VERIFY FAILED - flash content does not match the .hex" -ForegroundColor Red
                exit 1
            }
        }
    }
}

Write-Host ""
Write-Host "Debug log: USB-TTL on PA9(TX)+GND, 115200 8N1 (set your terminal to UTF-8)" -ForegroundColor Yellow
