# Builds dist\ClaudeTabSetup.exe: one double-click installer that carries ClaudeTab.exe
# (Python + tkinter bundled), so end users need no Python and download nothing.
# Only this build step needs the network (PyInstaller from PyPI), and it goes through
# the Intel proxy.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Corporate proxy for pip; Intel-internal hosts bypass it.
if (-not $env:HTTPS_PROXY) { $env:HTTPS_PROXY = 'http://proxy-ir.intel.com:912' }
if (-not $env:HTTP_PROXY)  { $env:HTTP_PROXY  = $env:HTTPS_PROXY }
if (-not $env:NO_PROXY)    { $env:NO_PROXY    = 'intel.com,127.0.0.1,localhost' }
"Proxy: $env:HTTPS_PROXY"

$py = (Get-Command python -ErrorAction Stop).Source
& $py -c "import tkinter" 2>$null
if ($LASTEXITCODE) { throw 'This Python has no tkinter; install Python from python.org with tcl/tk.' }

& $py -m pip install --quiet --upgrade pyinstaller pillow
if ($LASTEXITCODE) { throw 'pip install failed (check the proxy).' }

& $py tools\make_icon.py
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# 1. the app
& $py -m PyInstaller --noconfirm --onefile --noconsole --name ClaudeTab `
    --icon assets\claudetab.ico claude_tab.pyw
if ($LASTEXITCODE) { throw 'building ClaudeTab.exe failed' }

# 2. the installer, with the app inside
& $py -m PyInstaller --noconfirm --onefile --noconsole --name ClaudeTabSetup `
    --icon assets\claudetab.ico --add-data "dist\ClaudeTab.exe;." installer\setup.py
if ($LASTEXITCODE) { throw 'building ClaudeTabSetup.exe failed' }

Get-Item dist\ClaudeTabSetup.exe | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
