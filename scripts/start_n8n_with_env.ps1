$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $repoRoot ".env"

if (-not (Test-Path $envFile)) {
  throw "Cannot find .env at $envFile"
}

# Allow n8n file nodes to read/write repo data/logs
$allowedPaths = @(
  (Join-Path $repoRoot "data")
  (Join-Path $repoRoot "logs")
  "$env:USERPROFILE\.n8n-files"
) -join ";"
[Environment]::SetEnvironmentVariable("N8N_RESTRICT_FILE_ACCESS_TO", $allowedPaths, "Process")
# Allow env access inside expressions (comma-separated list)
[Environment]::SetEnvironmentVariable(
  "N8N_ENVIRONMENT_VARIABLES_ALLOWLIST",
  "GEMINI_API_KEY,N8N_API_KEY",
  "Process"
)

# Load key=value pairs from .env (ignore comments/blank)
$envMap = @{}
Get-Content -Path $envFile -ErrorAction Stop |
  Where-Object { $_ -and ($_ -notmatch '^\s*#') -and ($_ -match '=') } |
  ForEach-Object {
    $parts = $_ -split '=', 2
    $name = $parts[0].Trim()
    $value = $parts[1]
    $envMap[$name] = $value
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
  }

# CORS for browser form submissions (allow localhost/file origins by default)
$corsOrigin = if ($envMap.ContainsKey("N8N_CORS_ALLOW_ORIGIN")) { $envMap["N8N_CORS_ALLOW_ORIGIN"] } else { "http://localhost:5678,http://127.0.0.1:5678,file://" }
[Environment]::SetEnvironmentVariable("N8N_CORS_ALLOW_ORIGIN", $corsOrigin, "Process")
[Environment]::SetEnvironmentVariable("N8N_CORS_ALLOW_METHODS", "GET,POST,OPTIONS", "Process")
[Environment]::SetEnvironmentVariable("N8N_CORS_ALLOW_HEADERS", "Content-Type,Authorization,Accept", "Process")

# Auto-wire Gemini credential overwrite so the node sees the key
if ($envMap.ContainsKey("GEMINI_API_KEY")) {
  $cred = @{
    googlePalmApi = @(
      @{
        id = "gemini-auto"
        name = "gemini-auto"
        type = "googlePalmApi"
        data = @{ apiKey = $envMap["GEMINI_API_KEY"] }
        nodesAccess = @(
          @{
            nodeType = "@n8n/n8n-nodes-langchain.googleGemini"
            allowed = $true
          }
        )
      }
    )
  }
  $json = $cred | ConvertTo-Json -Compress
  [Environment]::SetEnvironmentVariable("N8N_CREDENTIALS_OVERWRITE_DATA", $json, "Process")
}

Write-Host "Loaded environment variables from .env"
Write-Host "Starting n8n..."

npx n8n
