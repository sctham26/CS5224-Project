# Upload -> job -> result acceptance check against the deployed gateway.
# Usage:
#   .\scripts\e2e_upload.ps1 -Token "<access token>" [-File <csv path>] [-EntityId SG_228218_LATEST_6] [-Year 2024]
# The token is passed in memory and never written to disk; S3 receives the signed URL only.

param(
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$File = "data/cleaned/public_esg_baseline.csv",
    [string]$EntityId = "SG_228218_LATEST_6",
    [int]$Year = 2024,
    [string]$Base = "https://d10rc41o4pb0h.cloudfront.net/api",
    [int]$PollSeconds = 20
)

$ErrorActionPreference = "Stop"

# A JWT has no whitespace; anything else (pasted prompt, headers, newlines) makes
# CloudFront answer 400 before the gateway ever sees it.
$Token = ($Token -replace '\s', '')
if ($Token -notmatch '^eyJ[\w-]+\.[\w-]+\.[\w-]+$') {
    throw "token is not a bare JWT (length=$($Token.Length)). Pass only the access_token value, one line, without 'Bearer ' or quotes."
}

$auth = @{ Authorization = "Bearer $Token" }
$json = @{ "Content-Type" = "application/json" }

function Show($label, $code, $body) {
    "{0,-26} {1}  {2}" -f $label, $code, ($body -replace '\s+', ' ')
}

# 1. Presigned PUT for this tenant's own upload prefix.
$r = curl.exe -s -w "`n%{http_code}" -X POST "$Base/uploads" -H "Authorization: Bearer $Token"
$lines = $r -split "`n"; $code = $lines[-1]; $body = $lines[0..($lines.Length - 2)] -join "`n"
Show "POST /uploads" $code $body
if ($code -ne "201") { throw "presign failed" }
$presign = $body | ConvertFrom-Json

# 2. Upload bytes straight to S3 with the signed URL (no bearer token: the URL authorises it).
$putRaw = curl.exe -s -o NUL -w "%{http_code}" --upload-file "$File" -H "Content-Type: text/csv" $presign.upload_url
$put = ($putRaw | Select-Object -Last 1).Trim()
Show "PUT  presigned S3" $put ""
if ($put -ne "200") { throw "S3 upload failed" }

# 3. Submit the job with an idempotency key; re-running this script with the same key replays.
# The JSON goes through a temp file: PowerShell strips quotes when passing a JSON string
# straight to a native exe, which makes the server reject the body.
$payload = @{ upload_key = $presign.key; entity_id = $EntityId; reporting_year = $Year; scope = "asset" } | ConvertTo-Json -Compress
$key = "e2e-$EntityId-$Year-" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$tmpJson = [IO.Path]::GetTempFileName()
Set-Content -Path $tmpJson -Value $payload -Encoding ascii
$r = curl.exe -s -w "`n%{http_code}" -X POST "$Base/jobs" -H "Authorization: Bearer $Token" -H "Content-Type: application/json" -H "Idempotency-Key: $key" -d "@$tmpJson"
Remove-Item $tmpJson -ErrorAction SilentlyContinue
$lines = $r -split "`n"; $code = $lines[-1]; $body = $lines[0..($lines.Length - 2)] -join "`n"
Show "POST /jobs" $code $body
if ($code -ne "202") { throw "job submission failed" }
$job = $body | ConvertFrom-Json

# 4. Poll until the worker reaches a terminal state.
$jobId = $job.job_id
for ($i = 1; $i -le $PollSeconds; $i++) {
    Start-Sleep -Seconds 3
    $r = curl.exe -s -w "`n%{http_code}" "$Base/jobs/$jobId" -H "Authorization: Bearer $Token"
    $lines = $r -split "`n"; $code = $lines[-1]; $body = $lines[0..($lines.Length - 2)] -join "`n"
    $state = ($body | ConvertFrom-Json).status
    Show "GET  /jobs/$jobId" $code $body
    if ($state -in @("SUCCEEDED", "FAILED")) { break }
}

"job_id=$jobId  final_state=$state"
