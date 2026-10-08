$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "template"
$target = Join-Path $PSScriptRoot "fusionpilot-dataset-template.zip"
Compress-Archive -Path (Join-Path $source "*") -DestinationPath $target -Force
Write-Host "Created $target"
