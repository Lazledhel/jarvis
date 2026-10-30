param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][string]$PythonPath,[string]$TaskName='JarvisDesktopBridge')
$ErrorActionPreference='Stop'
$resolvedConfig=(Resolve-Path -LiteralPath $ConfigPath).Path
$resolvedPython=(Resolve-Path -LiteralPath $PythonPath).Path
$worker=Join-Path $PSScriptRoot 'worker.py'
$owner=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$arguments='-X utf8 "'+$worker+'" --config "'+$resolvedConfig+'"'
$action=New-ScheduledTaskAction -Execute $resolvedPython -Argument $arguments -WorkingDirectory (Split-Path -Parent $resolvedConfig)
$principal=New-ScheduledTaskPrincipal -UserId $owner -LogonType Interactive -RunLevel Limited
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $owner
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output 'Jarvis desktop bridge configured for the current Windows user.'
