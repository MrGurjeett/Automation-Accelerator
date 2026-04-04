[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $false)]
    [string]$Agent = "pipeline_agent",

    [Parameter(Mandatory = $false)]
    [string]$Connection = "direct",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$NeuroSanRoot = Join-Path (Split-Path -Parent $ProjectRoot) "neuro-san"

$ManifestPath = Join-Path $ProjectRoot "neuro_agents\manifest.hocon"
$ToolPath = Join-Path $ProjectRoot "neuro_agents\coded_tools"

if (-not (Test-Path $ManifestPath)) {
    throw "Manifest not found: $ManifestPath"
}
if (-not (Test-Path $ToolPath)) {
    throw "Coded tools path not found: $ToolPath"
}

$PythonExe = Join-Path $NeuroSanRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Neuro-SAN venv Python not found: $PythonExe"
}

$env:PYTHONNOUSERSITE = "1"
$env:AGENT_MANIFEST_FILE = $ManifestPath
$env:AGENT_TOOL_PATH = $ToolPath

# Force `.env` values to override any stale inherited environment variables.
# This keeps Neuro-SAN runs consistent with CLI/UI runs in this repo.
$env:DOTENV_OVERRIDE = "1"

# Neuro-SAN expects AGENT_TOOL_PATH to also be present in PYTHONPATH.
# Include both Neuro-SAN source and this project so imports resolve.
$env:PYTHONPATH = "$NeuroSanRoot;$ProjectRoot;$ToolPath"

Write-Host "Using manifest: $env:AGENT_MANIFEST_FILE"
Write-Host "Using tool path: $env:AGENT_TOOL_PATH"
Write-Host "Agent: $Agent"

# If the caller supplied --response_output_file, also export that path so our
# coded tools can reliably write structured JSON there (agent_cli may capture
# only tool calls or an empty response depending on filtering/mode).
for ($i = 0; $i -lt $Args.Count; $i++) {
    if ($Args[$i] -eq "--response_output_file" -and ($i + 1) -lt $Args.Count) {
        $env:NEURO_PIPELINE_OUTPUT_FILE = $Args[$i + 1]
        Write-Host "Will write pipeline output JSON to: $env:NEURO_PIPELINE_OUTPUT_FILE"
        break
    }
}

$connArgs = @()
switch ($Connection.ToLowerInvariant()) {
    "direct" { $connArgs = @("--direct") }
    "http"   { $connArgs = @("--http") }
    "https"  { $connArgs = @("--https") }
    default  { throw "Unsupported -Connection '$Connection'. Use: direct|http|https" }
}

& $PythonExe -m neuro_san.client.agent_cli --agent $Agent @connArgs @Args
