# Gives license-check its own execution role so it can write to its own
# CloudWatch log group. deploy.ps1 initially reused token-authorizer's role,
# whose log policy is scoped to /aws/lambda/token-authorizer only.
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:AWS_PROFILE = 'battery-evidence'
$env:AWS_DEFAULT_REGION = 'us-east-1'

$Account = '011528284396'
$RoleName = 'license-check-role'
$FnName = 'license-check'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

$trust = Join-Path $Here 'trust.json'
@'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}
'@ | Set-Content -Path $trust -NoNewline

$policy = Join-Path $Here 'logs-policy.json'
@"
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"logs:CreateLogGroup","Resource":"arn:aws:logs:us-east-1:${Account}:*"},
 {"Effect":"Allow","Action":["logs:CreateLogStream","logs:PutLogEvents"],
  "Resource":"arn:aws:logs:us-east-1:${Account}:log-group:/aws/lambda/${FnName}:*"}
]}
"@ | Set-Content -Path $policy -NoNewline

$exists = $true
try { aws iam get-role --role-name $RoleName --output json | Out-Null } catch { $exists = $false }
if ($LASTEXITCODE -ne 0) { $exists = $false }
if (-not $exists) {
  aws iam create-role --role-name $RoleName --path /service-role/ --assume-role-policy-document "file://$trust" `
    --description 'Execution role for license-check Lambda (logs only)' --output json | Out-Null
  Write-Output "created role $RoleName"
} else { Write-Output "role $RoleName exists" }
aws iam put-role-policy --role-name $RoleName --policy-name license-check-logs --policy-document "file://$policy"
Write-Output "log policy attached"
Remove-Item $trust, $policy -Force

$roleArn = aws iam get-role --role-name $RoleName --query Role.Arn --output text
# IAM is eventually consistent; retry the role swap briefly
$ok = $false
for ($i = 0; $i -lt 6 -and -not $ok; $i++) {
  try {
    aws lambda update-function-configuration --function-name $FnName --role $roleArn --output json 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok = $true } else { Start-Sleep -Seconds 5 }
  } catch { Start-Sleep -Seconds 5 }
}
if (-not $ok) { throw 'could not attach role to function (IAM propagation); re-run in a minute' }
aws lambda wait function-updated --function-name $FnName
Write-Output "$FnName now uses $roleArn"
