# Install / remove / status for the Free TTS Studio auto-start Task Scheduler entry.
#
# Usage:
#   .\install-autostart.ps1 install     # create the task
#   .\install-autostart.ps1 remove      # delete the task
#   .\install-autostart.ps1 status      # show what exists
#   .\install-autostart.ps1 run-now     # trigger the task immediately (test)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startAll = Join-Path $root 'start-all.bat'

$taskName = 'FreeTTSStudio-Autostart'
$taskDescription = 'Start Kokoro TTS engine, bridge, and Cloudflare tunnel at user logon.'

function Assert-StartAll {
  if (-not (Test-Path -LiteralPath $script:startAll)) {
    throw "start-all.bat not found at: $script:startAll"
  }
}

switch ($args[0]) {

  'install' {
    Write-Host "Installing Task Scheduler entry: $taskName" -ForegroundColor Cyan
    Assert-StartAll

    # Remove any pre-existing task with the same name.
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction -Execute $startAll `
                                       -WorkingDirectory $root `
                                       -Argument ''

    $trigger = New-ScheduledTaskTrigger -AtLogOn

    # Run as the current user (not SYSTEM) so the venv and OneDrive paths are accessible.
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
                                             -LogonType Interactive `
                                             -RunLevel Limited

    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                                             -DontStopIfGoingOnBatteries `
                                             -StartWhenAvailable `
                                             -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
                                             -RestartCount 3 `
                                             -RestartInterval (New-TimeSpan -Minutes 1)

    Register-ScheduledTask -TaskName $taskName `
                           -Action $action `
                           -Trigger $trigger `
                           -Principal $principal `
                           -Settings $settings `
                           -Description $taskDescription | Out-Null

    Write-Host ""
    Write-Host "  Installed.  Will fire at next logon." -ForegroundColor Green
    Write-Host "  Test now with:  .\install-autostart.ps1 run-now"
    Write-Host "  Inspect with:    Get-ScheduledTask -TaskName '$taskName'  (PowerShell)"
    Write-Host "                    taskschd.msc                              (GUI)"
    Write-Host ""
    Write-Host "  Customize engine path:  setx TTS_ENGINE_DIR 'C:\path\to\kokoro-tts'"
    Write-Host "  Customize tunnel name:  setx TTS_TUNNEL_NAME 'tts-bridge'"
  }

  'remove' {
    Write-Host "Removing Task Scheduler entry: $taskName" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "  Removed." -ForegroundColor Green
  }

  'status' {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
      Write-Host "TASK EXISTS: $taskName" -ForegroundColor Green
      $task | Format-List TaskName, State, Author, Description
      $info = (Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue)
      if ($info) {
        Write-Host "Last run:    $($info.LastRunTime)"
        Write-Host "Last result: $($info.LastTaskResult)"
        Write-Host "Next run:    $($info.NextRunTime)"
      }
    } else {
      Write-Host "TASK NOT FOUND: $taskName" -ForegroundColor Red
      Write-Host "Run 'install' to create it."
    }
  }

  'run-now' {
    Write-Host "Triggering task: $taskName" -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $taskName
    Write-Host "Started.  Check start-all.log / bridge.out.log for output." -ForegroundColor Green
  }

  default {
    Write-Host "Usage: install-autostart.ps1 {install | remove | status | run-now}"
  }
}
