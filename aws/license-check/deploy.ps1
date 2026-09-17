# Deploys the license-check Lambda and wires POST /activate on the existing
# REST API (smv4232qo6, stage prod). Safe to re-run: updates code in place and
# skips API pieces that already exist. Does NOT touch /uploads.
#
# Environment variables (Supabase URL/key, HMAC secret) are set separately by
# set-env.ps1, which the account owner runs so credentials never pass through
# an assistant session.
#
# 2026-09-17: every aws call now goes through Invoke-Aws, which throws on a
# non-zero exit. PowerShell does not stop on a failed native command, so with
# an expired login the first version printed "created function" and "deployed"
# over a wall of auth errors, having done nothing. A preflight now names the
# expired login up front and tells you the command that fixes it.
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:AWS_PROFILE = 'battery-evidence'
$env:AWS_DEFAULT_REGION = 'us-east-1'

$Account  = '011528284396'
$Region   = 'us-east-1'
$ApiId    = 'smv4232qo6'
$RootId   = 'l92jt7arbi'
$Stage    = 'prod'
$FnName   = 'license-check'
$Role     = "arn:aws:iam::${Account}:role/service-role/token-authorizer-role-pjcl6dqn"
$Layer    = "arn:aws:lambda:${Region}:${Account}:layer:supabase-layer:1"
$Here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Zip      = Join-Path $Here 'license-check.zip'

# Run aws, return stdout, throw on failure with what aws said.
function Invoke-Aws {
  $out = & aws @args 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "aws $($args[0]) $($args[1]) failed (exit $LASTEXITCODE):`n$($out | Out-String)"
  }
  return $out
}

# For "does it exist" probes, where a non-zero exit is an answer, not an error.
function Test-Aws {
  & aws @args 2>&1 | Out-Null
  return ($LASTEXITCODE -eq 0)
}

# --- 0. preflight: is the login alive, and is it the right account ---
$who = & aws sts get-caller-identity --query Account --output text 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host "Not logged in to AWS (profile $env:AWS_PROFILE). Nothing was changed." -ForegroundColor Red
  Write-Host "Run:  aws login --profile $env:AWS_PROFILE   then run this script again." -ForegroundColor Yellow
  exit 1
}
if ("$who".Trim() -ne $Account) {
  Write-Host "Logged in to account $who, expected $Account. Nothing was changed." -ForegroundColor Red
  exit 1
}

# --- 1. package ---
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Here 'lambda_function.py') -DestinationPath $Zip
Write-Output "packaged $Zip"

# --- 2. create or update function ---
if (Test-Aws lambda get-function --function-name $FnName) {
  Invoke-Aws lambda update-function-code --function-name $FnName --zip-file "fileb://$Zip" --output json | Out-Null
  Write-Output "updated code for $FnName"
} else {
  Invoke-Aws lambda create-function --function-name $FnName --runtime python3.12 --architectures x86_64 `
    --role $Role --handler lambda_function.lambda_handler --timeout 15 --memory-size 256 `
    --layers $Layer --zip-file "fileb://$Zip" --description 'Device Hub Pro license yes/no (annual subscription)' --output json | Out-Null
  Write-Output "created function $FnName"
}
Invoke-Aws lambda wait function-updated --function-name $FnName | Out-Null
Invoke-Aws lambda wait function-active --function-name $FnName | Out-Null
$FnArn = (Invoke-Aws lambda get-function-configuration --function-name $FnName --query FunctionArn --output text | Out-String).Trim()
$sha = (Invoke-Aws lambda get-function-configuration --function-name $FnName --query CodeSha256 --output text | Out-String).Trim()
Write-Output "live code sha256: $sha"

# --- 3. API resource /activate ---
$res = Invoke-Aws apigateway get-resources --rest-api-id $ApiId --output json | Out-String | ConvertFrom-Json
$act = $res.items | Where-Object { $_.path -eq '/activate' }
if (-not $act) {
  $act = Invoke-Aws apigateway create-resource --rest-api-id $ApiId --parent-id $RootId --path-part activate --output json | Out-String | ConvertFrom-Json
  Write-Output "created resource /activate ($($act.id))"
} else { Write-Output "resource /activate exists ($($act.id))" }
if (-not $act.id) { throw 'could not resolve the /activate resource id' }

# --- 4. POST method, no authorizer, Lambda proxy ---
if (Test-Aws apigateway get-method --rest-api-id $ApiId --resource-id $act.id --http-method POST) {
  Write-Output "POST /activate already configured"
} else {
  Invoke-Aws apigateway put-method --rest-api-id $ApiId --resource-id $act.id --http-method POST --authorization-type NONE --output json | Out-Null
  $uri = "arn:aws:apigateway:${Region}:lambda:path/2015-03-31/functions/${FnArn}/invocations"
  Invoke-Aws apigateway put-integration --rest-api-id $ApiId --resource-id $act.id --http-method POST `
    --type AWS_PROXY --integration-http-method POST --uri $uri --output json | Out-Null
  Write-Output "created POST /activate -> $FnName"
}

# --- 5. allow API Gateway to invoke (a second add is a conflict, which is fine) ---
$srcArn = "arn:aws:execute-api:${Region}:${Account}:${ApiId}/*/POST/activate"
if (Test-Aws lambda add-permission --function-name $FnName --statement-id apigw-activate-post `
      --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn $srcArn) {
  Write-Output "invoke permission added"
} else {
  Write-Output "invoke permission already present"
}

# --- 6. deploy stage ---
Invoke-Aws apigateway create-deployment --rest-api-id $ApiId --stage-name $Stage --description 'license-check deploy' --output json | Out-Null
Write-Output "deployed: https://${ApiId}.execute-api.${Region}.amazonaws.com/${Stage}/activate"
