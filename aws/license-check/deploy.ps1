# Deploys the license-check Lambda and wires POST /activate on the existing
# REST API (smv4232qo6, stage prod). Safe to re-run: updates code in place and
# skips API pieces that already exist. Does NOT touch /uploads.
#
# Environment variables (Supabase URL/key, HMAC secret) are set separately by
# set-env.ps1, which the account owner runs so credentials never pass through
# an assistant session.
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

# --- 1. package ---
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Here 'lambda_function.py') -DestinationPath $Zip
Write-Output "packaged $Zip"

# --- 2. create or update function ---
$exists = $true
try { aws lambda get-function --function-name $FnName --output json | Out-Null } catch { $exists = $false }
if ($LASTEXITCODE -ne 0) { $exists = $false }
if (-not $exists) {
  aws lambda create-function --function-name $FnName --runtime python3.12 --architectures x86_64 `
    --role $Role --handler lambda_function.lambda_handler --timeout 15 --memory-size 256 `
    --layers $Layer --zip-file "fileb://$Zip" --description 'Device Hub Pro license yes/no (annual subscription)' --output json | Out-Null
  Write-Output "created function $FnName"
} else {
  aws lambda update-function-code --function-name $FnName --zip-file "fileb://$Zip" --output json | Out-Null
  Write-Output "updated code for $FnName"
}
aws lambda wait function-updated --function-name $FnName
aws lambda wait function-active --function-name $FnName
$FnArn = aws lambda get-function-configuration --function-name $FnName --query FunctionArn --output text

# --- 3. API resource /activate ---
$res = aws apigateway get-resources --rest-api-id $ApiId --output json | ConvertFrom-Json
$act = $res.items | Where-Object { $_.path -eq '/activate' }
if (-not $act) {
  $act = aws apigateway create-resource --rest-api-id $ApiId --parent-id $RootId --path-part activate --output json | ConvertFrom-Json
  Write-Output "created resource /activate ($($act.id))"
} else { Write-Output "resource /activate exists ($($act.id))" }

# --- 4. POST method, no authorizer, Lambda proxy ---
$m = $null
try { $m = aws apigateway get-method --rest-api-id $ApiId --resource-id $act.id --http-method POST --output json 2>$null | ConvertFrom-Json } catch {}
if (-not $m) {
  aws apigateway put-method --rest-api-id $ApiId --resource-id $act.id --http-method POST --authorization-type NONE --output json | Out-Null
  $uri = "arn:aws:apigateway:${Region}:lambda:path/2015-03-31/functions/${FnArn}/invocations"
  aws apigateway put-integration --rest-api-id $ApiId --resource-id $act.id --http-method POST `
    --type AWS_PROXY --integration-http-method POST --uri $uri --output json | Out-Null
  Write-Output "created POST /activate -> $FnName"
} else { Write-Output "POST /activate already configured" }

# --- 5. allow API Gateway to invoke ---
$srcArn = "arn:aws:execute-api:${Region}:${Account}:${ApiId}/*/POST/activate"
aws lambda add-permission --function-name $FnName --statement-id apigw-activate-post `
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn $srcArn --output json 2>$null | Out-Null
Write-Output "invoke permission ensured"

# --- 6. deploy stage ---
aws apigateway create-deployment --rest-api-id $ApiId --stage-name $Stage --description 'add POST /activate (license-check)' --output json | Out-Null
Write-Output "deployed: https://${ApiId}.execute-api.${Region}.amazonaws.com/${Stage}/activate"
