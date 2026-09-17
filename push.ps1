param(
    [int]$Retries = 3,
    [switch]$UseToken,
    [string]$Branch = 'main',
    [string]$User = 'petrichor-Li2'
)

# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads .ps1 with the ANSI
# code page; UTF-8 Chinese comments can corrupt parsing, see docs/).
#
# Push this project to GitHub, with retries for flaky connections.
#
#   .\push.ps1                     -> push; a GitHub login window may pop up
#   .\push.ps1 -UseToken           -> paste a Personal Access Token instead (hidden input)
#   .\push.ps1 -Retries 5          -> retry more times when the network resets
#
# If the login window never appears, force the device-code flow first:
#   git config --global credential.gitHubAuthModes device
# then run this script again and open https://github.com/login/device

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot

Set-Location $root

Write-Host "=== Repository ===" -ForegroundColor Cyan
git remote -v
git status -sb | Select-Object -First 3

# ---------------------------------------------------------------- token mode
if ($UseToken) {
    Write-Host ""
    Write-Host "Paste a GitHub Personal Access Token (classic, scope: repo)." -ForegroundColor Yellow
    Write-Host "Input is hidden. It is stored in Windows Credential Manager via Git Credential Manager." -ForegroundColor Yellow
    Write-Host "Revoke it on GitHub when you are done." -ForegroundColor Yellow
    $sec = Read-Host "Token" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
        $tok = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    if ([string]::IsNullOrWhiteSpace($tok)) {
        Write-Host "Empty token, aborting." -ForegroundColor Red
        exit 1
    }
    "protocol=https`nhost=github.com`nusername=$User`npassword=$tok`n" |
        git credential approve
    Write-Host "Token stored." -ForegroundColor Green
    $tok = $null
}

# ---------------------------------------------------------------- push with retries
for ($i = 1; $i -le $Retries; $i++) {
    Write-Host ""
    Write-Host "=== Push attempt $i / $Retries ===" -ForegroundColor Cyan

    git push -u origin $Branch
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host ""
        Write-Host "PUSH OK" -ForegroundColor Green
        git log --oneline -3
        Write-Host ""
        Write-Host "Repo: https://github.com/$User/-" -ForegroundColor Green
        exit 0
    }

    Write-Host "push failed (exit $code)" -ForegroundColor Red
    if ($i -lt $Retries) {
        Write-Host "Retrying in 5s ... (network to github.com is often intermittent)" -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
}

Write-Host ""
Write-Host "Push FAILED after $Retries attempts." -ForegroundColor Red
Write-Host "Things to try:"
Write-Host "  1) Login did not happen -> git config --global credential.gitHubAuthModes device, run again, open https://github.com/login/device"
Write-Host "  2) Use a token        -> .\push.ps1 -UseToken"
Write-Host "  3) Network reset      -> retry, or use a proxy:"
Write-Host "        git config --global http.proxy http://127.0.0.1:7890    (your proxy port)"
Write-Host "        git config --global --unset http.proxy                  (when done)"
Write-Host "  4) Also try SSH over 443:"
Write-Host "        git remote set-url origin git@github.com:$User/-.git"
exit 1
