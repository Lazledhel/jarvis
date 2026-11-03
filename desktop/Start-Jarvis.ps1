param([string]$Server = $env:JARVIS_SERVER_URL)
$ErrorActionPreference = 'Stop'
if (!$Server) { throw 'Set JARVIS_SERVER_URL or pass -Server' }
$env:JARVIS_SERVER_URL = $Server
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (!$edge) { throw 'Microsoft Edge is required' }
$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
& $python (Join-Path $PSScriptRoot 'launcher.py') $edge --server $Server
