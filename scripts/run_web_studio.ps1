param(
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$hostName = "127.0.0.1"
$projectRoot = Split-Path -Parent $PSScriptRoot
$distIndex = Join-Path $projectRoot "web\dist\index.html"

if ($Port -lt 1 -or $Port -gt 65535) {
  throw "Port must be between 1 and 65535."
}

$occupied = Get-NetTCPConnection -LocalAddress $hostName -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
  throw "Port $Port is already in use. Stop the existing local server manually; the launcher will not kill it."
}

if (-not (Test-Path -LiteralPath $distIndex)) {
  Push-Location (Join-Path $projectRoot "web")
  try {
    npm run build
    if ($LASTEXITCODE -ne 0) {
      throw "Web Studio build failed with exit code $LASTEXITCODE."
    }
  } finally {
    Pop-Location
  }
}

Push-Location $projectRoot
try {
  python -m uvicorn ghost_protocol.api.main:app --host $hostName --port $Port
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}
