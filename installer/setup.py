"""
ClaudeTab setup — double-click to install, no Python or downloads needed.

Built by build.ps1 into one ClaudeTabSetup.exe that carries ClaudeTab.exe inside.
Installs per user (no admin): copies the app to %LOCALAPPDATA%\\ClaudeTab, adds Start
Menu / Startup / optional Desktop shortcuts, registers an entry in "Installed apps",
and starts it. Run the same exe with --uninstall (or use Installed apps) to remove it.

    ClaudeTabSetup.exe [--silent] [--uninstall] [--dir PATH]
                       [--no-startup] [--desktop] [--no-start]
"""
import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tkinter as tk
import winreg
from tkinter import messagebox

APP = "ClaudeTab"
EXE = "ClaudeTab.exe"
SETUP = "ClaudeTabSetup.exe"
VERSION = "0.3.0"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClaudeTab"
LEGACY_SHORTCUTS = ("Claude Session Menu.lnk", "Perch.lnk")  # names from earlier builds
NO_WINDOW = 0x08000000
DETACHED = 0x00000008


def folder(name):
    """Shell folder path via the Windows API (works with redirected/OneDrive folders)."""
    ids = {"startup": 7, "programs": 2, "desktop": 0}
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, ids[name], None, 0, buf)
    return buf.value


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)


def make_shortcut(lnk, target, workdir):
    def q(s):
        return "'" + s.replace("'", "''") + "'"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({q(lnk)});"
          f"$s.TargetPath={q(target)};$s.WorkingDirectory={q(workdir)};"
          f"$s.Description='ClaudeTab - Claude Code session menu';$s.Save()")
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    if r.returncode:
        raise RuntimeError(f"could not create shortcut {lnk}: {r.stderr.strip()}")


def stop_running():
    run(["taskkill", "/F", "/IM", EXE])
    # earlier script-based builds ran under pythonw
    run(["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'pythonw*' -and "
         "$_.CommandLine -match 'claude_tab.pyw|perch.pyw|claude_menu.pyw' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"])


def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)


def bundled(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def shortcut_paths():
    return {
        "menu": os.path.join(folder("programs"), f"{APP}.lnk"),
        "startup": os.path.join(folder("startup"), f"{APP}.lnk"),
        "desktop": os.path.join(folder("desktop"), f"{APP}.lnk"),
    }


def install(dest, startup, desktop, start):
    stop_running()
    os.makedirs(dest, exist_ok=True)
    app_exe = os.path.join(dest, EXE)
    shutil.copy2(bundled(EXE), app_exe)
    uninstaller = os.path.join(dest, SETUP)
    if getattr(sys, "frozen", False):
        shutil.copy2(sys.executable, uninstaller)

    links = shortcut_paths()
    make_shortcut(links["menu"], app_exe, dest)
    if startup:
        make_shortcut(links["startup"], app_exe, dest)
    if desktop:
        make_shortcut(links["desktop"], app_exe, dest)
    for old in LEGACY_SHORTCUTS:
        for d in (folder("startup"), folder("programs")):
            p = os.path.join(d, old)
            if os.path.exists(p):
                os.remove(p)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in {"DisplayName": APP, "DisplayVersion": VERSION, "Publisher": "Andrei Elekes",
                          "InstallLocation": dest, "DisplayIcon": app_exe,
                          "UninstallString": f'"{uninstaller}" --uninstall',
                          "URLInfoAbout": "https://github.com/AndreiElekesIntel/ClaudeTab"}.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
    if start:
        subprocess.Popen([app_exe], cwd=dest, creationflags=NO_WINDOW | DETACHED)
    return app_exe


def uninstall():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            dest = winreg.QueryValueEx(k, "InstallLocation")[0]
    except OSError:
        dest = default_dir()
    stop_running()
    for p in shortcut_paths().values():
        if os.path.exists(p):
            os.remove(p)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if os.path.isdir(dest):
        # this very exe may live in dest: hand deletion to a detached shell that outlives us
        subprocess.Popen(["cmd", "/c", f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{dest}" 2>nul & ping 127.0.0.1 -n 5 >nul & rmdir /s /q "{dest}" 2>nul'],
                         creationflags=NO_WINDOW | DETACHED)


def ask_options(dest):
    """Tiny dialog: returns (startup, desktop) or None if cancelled."""
    root = tk.Tk()
    root.title(f"Install {APP}")
    root.resizable(False, False)
    startup, desktop, ok = tk.BooleanVar(value=True), tk.BooleanVar(value=False), tk.BooleanVar(value=False)
    tk.Label(root, text=f"{APP} {VERSION}", font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18, pady=(16, 0))
    tk.Label(root, text="A menu on every Claude Code terminal window.\nNo admin rights needed; nothing to download.",
             justify="left").pack(anchor="w", padx=18, pady=(2, 10))
    tk.Label(root, text=f"Install to: {dest}", fg="#555").pack(anchor="w", padx=18)
    tk.Checkbutton(root, text="Start when I sign in", variable=startup).pack(anchor="w", padx=14, pady=(8, 0))
    tk.Checkbutton(root, text="Add a Desktop shortcut", variable=desktop).pack(anchor="w", padx=14)
    row = tk.Frame(root)
    row.pack(anchor="e", padx=18, pady=14)
    tk.Button(row, text="Cancel", width=9, command=root.destroy).pack(side="right", padx=(8, 0))
    tk.Button(row, text="Install", width=9, default="active",
              command=lambda: (ok.set(True), root.destroy())).pack(side="right")
    root.mainloop()
    return (startup.get(), desktop.get()) if ok.get() else None


def main():
    ap = argparse.ArgumentParser(description=APP + " setup")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--silent", action="store_true", help="no dialogs; defaults apply")
    ap.add_argument("--dir", default=default_dir())
    ap.add_argument("--no-startup", action="store_true")
    ap.add_argument("--desktop", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    a = ap.parse_args()
    note = (lambda m: None) if a.silent else (lambda m: messagebox.showinfo(APP, m))
    try:
        if a.uninstall:
            if not a.silent and not messagebox.askyesno(APP, f"Remove {APP}?"):
                return 0
            uninstall()
            note(f"{APP} was removed.")
            return 0
        startup, desktop = not a.no_startup, a.desktop
        if not a.silent:
            picked = ask_options(a.dir)
            if picked is None:
                return 0
            startup, desktop = picked
        install(a.dir, startup, desktop, not a.no_start)
        note(f"{APP} is installed and running.\n\nOpen a Claude Code terminal and look for the "
             "Claude ▾ tab at the top-right of the window.")
        return 0
    except Exception as e:
        if a.silent:
            print(f"error: {e}", file=sys.stderr)
        else:
            messagebox.showerror(APP, f"Setup failed:\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
