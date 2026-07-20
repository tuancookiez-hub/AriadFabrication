[CmdletBinding()]
param(
    [ValidateSet("showcase", "fixture", "runs")]
    [string]$Evidence = "showcase",
    [string]$HostAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$WebPort = 5173,
    [System.IO.FileInfo]$CodexBin
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root ".venv\Scripts\ariad-interface-api.exe"
$web = Join-Path $root "web"
$runsRoot = switch ($Evidence) {
    "fixture" { Join-Path $root "benchmarks\interface" }
    "runs" { Join-Path $root "runs" }
    default { Join-Path $root "runs\showcase" }
}
$projectsRoot = Join-Path $root "runs\projects"

if (-not (Test-Path -LiteralPath $api -PathType Leaf)) {
    throw "Ariad API is not installed. Run: uv sync --extra test --extra cad"
}
if ($Evidence -eq "showcase") {
    & (Join-Path $root ".venv\Scripts\python.exe") -m ariad_fabrication.api.showcase `
        --runtime-root (Join-Path $root "runs") `
        --fixture-root (Join-Path $root "benchmarks\interface") `
        --output-root $runsRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Ariad could not prepare the curated showcase workspace."
    }
}
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm is required. Install the repository's pinned package manager first."
}
if (-not (Test-Path -LiteralPath (Join-Path $web "node_modules") -PathType Container)) {
    throw "Frontend dependencies are missing. Run: pnpm --dir web install --frozen-lockfile"
}

$apiArguments = @(
    "--runs-root", $runsRoot,
    "--projects-root", $projectsRoot,
    "--host", $HostAddress,
    "--port", [string]$ApiPort
)
if ($null -ne $CodexBin) {
    if (-not $CodexBin.Exists -or $CodexBin.Extension -ne ".exe") {
        throw "CodexBin must be an existing native codex.exe path."
    }
    $codexWorkspace = Join-Path $root "runs\codex-chat"
    if (-not (Test-Path -LiteralPath $codexWorkspace)) {
        New-Item -ItemType Directory -Path $codexWorkspace | Out-Null
    }
    if (@(Get-ChildItem -LiteralPath $codexWorkspace -Force).Count -ne 0) {
        throw "The isolated Codex conversation workspace must be empty: $codexWorkspace"
    }
    $apiArguments += @(
        "--codex-bin", $CodexBin.FullName,
        "--codex-workspace", $codexWorkspace
    )
}
$apiProcess = Start-Process -FilePath $api -ArgumentList $apiArguments -WorkingDirectory $root -PassThru -WindowStyle Hidden

try {
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        if ($apiProcess.HasExited) {
            throw "Ariad API exited before becoming ready."
        }
        try {
            $health = Invoke-RestMethod -Uri "http://${HostAddress}:${ApiPort}/api/v1/health" -TimeoutSec 1
            if ($health.status -eq "ok" -and $health.capabilities.hardware_actions -eq $false) {
                break
            }
        } catch {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Ariad API did not become ready within 15 seconds."
            }
            Start-Sleep -Milliseconds 200
        }
    } while ([DateTime]::UtcNow -lt $deadline)

    Write-Host "Ariad demo: http://${HostAddress}:${WebPort}"
    Write-Host "Evidence root: $runsRoot"
    Write-Host "Hardware actions: disabled"
    Write-Host "Codex conversation: $(if ($null -eq $CodexBin) { 'not configured' } else { 'configured (read-only)' })"
    $env:ARIAD_API_PROXY = "http://${HostAddress}:${ApiPort}"
    & pnpm --dir $web dev --host $HostAddress --port $WebPort
} finally {
    if (-not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id
        $apiProcess.WaitForExit()
    }
}
