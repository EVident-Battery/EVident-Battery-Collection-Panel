# Run this yourself (not through an assistant). It copies the customer Supabase
# URL and service-role key from the existing token-authorizer function into
# license-check, generates a random HMAC secret for activation tokens, and saves
# that secret to activation_hmac_secret.txt next to this script for embedding
# in Device Hub Pro. Nothing sensitive is printed.
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:AWS_PROFILE = 'battery-evidence'
$env:AWS_DEFAULT_REGION = 'us-east-1'

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretFile = Join-Path $Here 'activation_hmac_secret.txt'

$src = aws lambda get-function-configuration --function-name token-authorizer --output json | ConvertFrom-Json
$url = $src.Environment.Variables.SUPABASE_URL_CUSTOMER
$key = $src.Environment.Variables.SUPABASE_SERVICE_KEY_CUSTOMER
if (-not $url -or -not $key) { throw 'token-authorizer is missing SUPABASE_URL_CUSTOMER / SUPABASE_SERVICE_KEY_CUSTOMER' }

if (Test-Path $secretFile) {
  $hmac = (Get-Content $secretFile -Raw).Trim()
} else {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  $hmac = [Convert]::ToHexString($bytes).ToLower()
  Set-Content -Path $secretFile -Value $hmac -NoNewline
}

$envJson = @{ Variables = @{
  SUPABASE_URL_CUSTOMER         = $url
  SUPABASE_SERVICE_KEY_CUSTOMER = $key
  ACTIVATION_HMAC_SECRET        = $hmac
  SUBSCRIPTION_ENV              = 'production'
} } | ConvertTo-Json -Compress
$tmp = Join-Path $env:TEMP ("lc-env-{0}.json" -f [guid]::NewGuid())
Set-Content -Path $tmp -Value $envJson -NoNewline
try {
  aws lambda update-function-configuration --function-name license-check --environment "file://$tmp" --output json | Out-Null
} finally { Remove-Item $tmp -Force }
aws lambda wait function-updated --function-name license-check
Write-Output "license-check environment set (4 variables). HMAC secret saved to: $secretFile"
