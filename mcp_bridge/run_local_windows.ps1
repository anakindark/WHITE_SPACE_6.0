$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$nodeVersion = (& node -p "process.versions.node").Trim()
if (-not $nodeVersion) {
    throw "Node.js 20+ is required."
}
$nodeMajor = [int]($nodeVersion.Split(".")[0])
if ($nodeMajor -lt 20) {
    throw "Node.js 20+ is required; found v$nodeVersion."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created mcp_bridge\.env. Edit WS_API_BASE and WS_ALLOWED_API_HOSTS to match the live WHITE_SPACE API, then rerun."
    exit 2
}

Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) {
            [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
        }
    }
}

npm install --ignore-scripts
npm run check
npm test
npm start
