# Puts a "ClaudeTab" shortcut in the Startup folder, pointing at the
# claude_tab.pyw next to this script, and starts it now.
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'claude_tab.pyw'
$pyw = (Get-Command pythonw).Source
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'ClaudeTab.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = '"' + $src + '"'
$s.WorkingDirectory = $PSScriptRoot
$s.WindowStyle = 7
$s.Description = 'ClaudeTab - Claude Code session menu'
$s.Save()
"Startup shortcut: $lnk -> $src"

# Restart so the running copy is this one.
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -like 'pythonw*' -and $_.CommandLine -match 'claude_tab.pyw|perch.pyw|claude_menu.pyw' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 500
Start-Process -FilePath $pyw -ArgumentList ('"' + $src + '"') -WorkingDirectory $PSScriptRoot
"Started."
