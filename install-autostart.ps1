# Install / remove / status for the Free TTS Studio auto-start Task Scheduler entry.
#
# Usage:
#   .\install-autostart.ps1 install     # create the task
#   .\install-autostart.ps1 remove      # delete the task
#   .\install-autostart.ps1 status      # show what exists
#   .\install-autostart.ps1 run-now     # trigger the task immediately (test)
#
# Run from any PowerShell window. If not elevated, the script auto-relaunches
# itself as Administrator (you'll see a UAC prompt the first time only).

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startAll = Join-Path $root 'start-all.bat'

$taskName = 'FreeTTSStudio-Autostart'
$taskDescription = 'Start Kokoro TTS engine, bridge, and Cloudflare tunnel at user logon.'

# --- self-elevate if needed ----------------------------------------------
$currentId = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentId)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "Not running as Administrator; relaunching elevated..." -ForegroundColor Yellow
  $argString = ($args | ForEach-Object { "`"$_`"" }) -join ' '
  Start-Process -FilePath 'powershell.exe' `
                -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $argString" `
                -Verb RunAs | Out-Null
  exit
}

# Full username in DOMAIN\User (or User@Domain) form -- Register-ScheduledTask
# rejects bare "$env:USERNAME" on most systems.
$userFullName = $currentId.Name

# --- helpers -------------------------------------------------------------
function Remove-TaskSilently {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
}

function Register-ViaPowerShell {
  param([string]$UserFullName)
  $schedPrincipal = New-ScheduledTaskPrincipal -UserId $UserFullName `
                                               -LogonType Interactive `
                                               -RunLevel Limited
  $action = New-ScheduledTaskAction -Execute $startAll `
                                    -WorkingDirectory $root
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                                           -DontStopIfGoingOnBatteries `
                                           -StartWhenAvailable `
                                           -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
                                           -RestartCount 3 `
                                           -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName $taskName `
                         -Action $action `
                         -Trigger $trigger `
                         -Principal $schedPrincipal `
                         -Settings $settings `
                         -Description $taskDescription | Out-Null
}

function Register-ViaSchtasks {
  param([string]$UserFullName)
  # schtasks is more forgiving about principal formats and works around some
  # CIM-layer "Access is denied" errors that hit Register-ScheduledTask.
  $schtasksArgs = @(
    '/Create',
    '/TN',  $taskName,
    '/TR',  "`"$startAll`"",
    '/SC',  'ONLOGON',
    '/RU',  $UserFullName,
    '/RL',  'LIMITED',
    '/IT',
    '/F'
  )
  $proc = Start-Process -FilePath 'schtasks.exe' `
                        -ArgumentList $schtasksArgs `
                        -NoNewWindow -PassThru -Wait `
                        -RedirectStandardOutput "$env:TEMP\schtasks_out.txt" `
                        -RedirectStandardError  "$env:TEMP\schtasks_err.txt"
  $out = if (Test-Path "$env:TEMP\schtasks_out.txt") { (Get-Content "$env:TEMP\schtasks_out.txt" -Raw).Trim() } else { '' }
  $err = if (Test-Path "$env:TEMP\schtasks_err.txt")  { (Get-Content "$env:TEMP\schtasks_err.txt"  -Raw).Trim() } else { '' }
  Remove-Item "$env:TEMP\schtasks_out.txt","$env:TEMP\schtasks_err.txt" -Force -ErrorAction SilentlyContinue
  if ($proc.ExitCode -ne 0) {
    throw "schtasks exit $($proc.ExitCode): stdout=`"$out`" stderr=`"$err`""
  }
}

# --- subcommands ---------------------------------------------------------
switch ($args[0]) {

  'install' {
    Write-Host "Installing Task Scheduler entry: $taskName" -ForegroundColor Cyan
    Write-Host "  principal: $userFullName" -ForegroundColor DarkGray

    if (-not (Test-Path -LiteralPath $startAll)) {
      throw "start-all.bat not found at: $startAll"
    }

    Remove-TaskSilently

    try {
      Register-ViaPowerShell -UserFullName $userFullName
      Write-Host "  registered via Register-ScheduledTask." -ForegroundColor Green
    } catch {
      Write-Host "  Register-ScheduledTask failed ($($_.Exception.Message));" -ForegroundColor Yellow
      Write-Host "  falling back to schtasks.exe..." -ForegroundColor Yellow
      Register-ViaSchtasks -UserFullName $userFullName
      Write-Host "  registered via schtasks.exe." -ForegroundColor Green
    }

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
    Remove-TaskSilently
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
    Write-Host "Started.  Check start-all output for log lines." -ForegroundColor Green
  }

  default {
    Write-Host "Usage: install-autostart.ps1 {install | remove | status | run-now}"
  }
}
