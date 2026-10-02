# Copy the settings the hosted HUD needs from .env to the linked Vercel project,
# then redeploy production so they take effect. Windows version of vercel-env.sh.
#
#   powershell -ExecutionPolicy Bypass -File scripts\vercel-env.ps1           upload and redeploy
#   powershell -ExecutionPolicy Bypass -File scripts\vercel-env.ps1 -DryRun   show what would happen
#
# Uploads only the three LiveKit values and the HUD access code. The Gemini and
# Sarvam keys stay on your machine: only the voice agent uses them.
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .env)) { throw "No .env file here. Copy .env.example to .env first." }
if (-not (Get-Command vercel -ErrorAction SilentlyContinue)) {
    throw "Vercel CLI not found. Install it with: npm i -g vercel"
}

# Read one value from .env (strips surrounding quotes).
function Get-EnvValue([string]$Name) {
    $line = Get-Content .env | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    $value = $line.Substring($Name.Length + 1).Trim()
    if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") { $value = $Matches[1] }
    return $value
}

# Send a value to `vercel env add` on stdin, byte for byte. A PowerShell pipe would
# append a line ending, which would corrupt a secret.
function Send-ToVercel([string]$Name, [string]$Value) {
    $file = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($file, $Value)
        cmd /c "vercel env add $Name production --force --sensitive < `"$file`" > nul 2>&1"
        if ($LASTEXITCODE -ne 0) { throw "vercel env add $Name failed (exit code $LASTEXITCODE)." }
    }
    finally {
        Remove-Item $file -Force
    }
}

if (-not (Get-EnvValue "FRIDAY_ACCESS_CODE")) {
    if ($DryRun) {
        Write-Host "Would generate an access code and save it to .env as FRIDAY_ACCESS_CODE."
    }
    else {
        $bytes = New-Object byte[] 12
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $code = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
        $entry = "`n# Typed into the hosted HUD to unlock it.`nFRIDAY_ACCESS_CODE=$code`n"
        [IO.File]::AppendAllText((Resolve-Path .env), $entry)
        Write-Host "Generated an access code and saved it to .env as FRIDAY_ACCESS_CODE."
    }
}

foreach ($name in "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "FRIDAY_ACCESS_CODE") {
    $value = Get-EnvValue $name
    if (-not $value) {
        if ($DryRun -and $name -eq "FRIDAY_ACCESS_CODE") { Write-Host "Would upload $name"; continue }
        throw "$name is empty in .env; fill it in and run this again."
    }
    if ($DryRun) {
        Write-Host "Would upload $name ($($value.Length) characters)"
    }
    else {
        Send-ToVercel $name $value
        Write-Host "Uploaded $name"
    }
}

if ($DryRun) {
    Write-Host "Would redeploy production."
    exit 0
}

cmd /c "vercel deploy --prod --yes"
if ($LASTEXITCODE -ne 0) { throw "vercel deploy failed (exit code $LASTEXITCODE)." }
Write-Host ""
Write-Host "Done. Open https://tonystark-voiceagent.vercel.app and enter the access code"
Write-Host "(FRIDAY_ACCESS_CODE in .env)."
