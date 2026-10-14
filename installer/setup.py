"""
ClaudeTab setup — double-click to install or upgrade, no Python or downloads needed.

Built by build.ps1 into one ClaudeTabSetup.exe that carries ClaudeTab.exe inside.
Installs per user (no admin): copies the app to %LOCALAPPDATA%\\ClaudeTab, adds Start
Menu / Startup / optional Desktop shortcuts, registers an entry in "Installed apps",
and starts it. Run a newer ClaudeTabSetup.exe over an existing install to upgrade it.
Run it with --uninstall (or use Installed apps) to remove it.

    ClaudeTabSetup.exe [--silent] [--uninstall] [--dir PATH]
                       [--no-startup] [--desktop] [--no-start]

The window is one page at a time (options -> progress -> done), all in the same frame.
"""
import argparse
import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg

APP = "ClaudeTab"
EXE = "ClaudeTab.exe"
SETUP = "ClaudeTabSetup.exe"
VERSION = "0.4.0"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClaudeTab"
LEGACY_SHORTCUTS = ("Claude Session Menu.lnk", "Perch.lnk")  # names from earlier builds
NO_WINDOW = 0x08000000
DETACHED = 0x00000008

# Same palette as the menu itself.
BG, PANEL, BORDER, TROUGH = "#171a26", "#1f2336", "#2a2f45", "#262b42"
FG, MUTED, DIM = "#e9ebf5", "#9097b3", "#5a6080"
ACCENT, ACCENT_HOVER, ON_ACCENT = "#8b8bf5", "#a3a3fa", "#10122a"
GOOD, DANGER = "#6fdca0", "#f27d83"
FONT, FONT_B, FONT_S = ("Segoe UI", 10), ("Segoe UI Semibold", 10), ("Segoe UI", 9)


# ---------------------------------------------------------------- system work
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


def installed():
    """(version, location) of the current install, or None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return (winreg.QueryValueEx(k, "DisplayVersion")[0], winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def vtuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def install_steps(dest, startup, desktop, start):
    """[(label, fn)] — each step is one tick of the progress bar."""
    app_exe = os.path.join(dest, EXE)
    uninstaller = os.path.join(dest, SETUP)
    links = shortcut_paths()

    def copy_app():
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(bundled(EXE), app_exe)

    def copy_uninstaller():
        # Setup rerun from the installed copy cannot overwrite itself; it is already current enough
        # to uninstall, and the next upgrade comes from a fresh download anyway.
        if getattr(sys, "frozen", False) and not same_file(sys.executable, uninstaller):
            shutil.copy2(sys.executable, uninstaller)

    def shortcuts():
        make_shortcut(links["menu"], app_exe, dest)
        for key, want in (("startup", startup), ("desktop", desktop)):
            if want:
                make_shortcut(links[key], app_exe, dest)
            elif os.path.exists(links[key]):
                os.remove(links[key])
        for old in LEGACY_SHORTCUTS:
            for d in (folder("startup"), folder("programs")):
                p = os.path.join(d, old)
                if os.path.exists(p):
                    os.remove(p)

    def register():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            for name, val in {"DisplayName": APP, "DisplayVersion": VERSION, "Publisher": "Andrei Elekes",
                              "InstallLocation": dest, "DisplayIcon": app_exe,
                              "UninstallString": f'"{uninstaller}" --uninstall',
                              "URLInfoAbout": "https://github.com/AndreiElekesIntel/ClaudeTab"}.items():
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)

    def launch():
        if start:
            subprocess.Popen([app_exe], cwd=dest, creationflags=NO_WINDOW | DETACHED)

    return [("Closing the running copy", stop_running), ("Copying files", copy_app),
            ("Adding the uninstaller", copy_uninstaller), ("Creating shortcuts", shortcuts),
            ("Registering in Installed apps", register), ("Starting ClaudeTab", launch)]


def uninstall_steps():
    found = installed()
    dest = found[1] if found else default_dir()

    def shortcuts():
        for p in shortcut_paths().values():
            if os.path.exists(p):
                os.remove(p)

    def unregister():
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        except OSError:
            pass

    def files():
        if os.path.isdir(dest):
            # this very exe may live in dest: hand deletion to a detached shell that outlives us
            subprocess.Popen(["cmd", "/c", f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{dest}" 2>nul & '
                              f'ping 127.0.0.1 -n 5 >nul & rmdir /s /q "{dest}" 2>nul'],
                             creationflags=NO_WINDOW | DETACHED)

    return [("Closing the running copy", stop_running), ("Removing shortcuts", shortcuts),
            ("Unregistering", unregister), ("Removing files", files)]


# ---------------------------------------------------------------- window
class Button(tk.Label):
    """Flat button; the primary one is accent-filled."""

    def __init__(self, parent, text, command, primary=False):
        self.primary = primary
        super().__init__(parent, text=text, font=FONT_B, padx=22, pady=8, cursor="hand2",
                         bg=ACCENT if primary else PANEL, fg=ON_ACCENT if primary else FG)
        self.bind("<Enter>", lambda _e: self.configure(bg=ACCENT_HOVER if primary else BORDER))
        self.bind("<Leave>", lambda _e: self.configure(bg=ACCENT if primary else PANEL))
        self.bind("<ButtonRelease-1>", lambda _e: command())


class Bar(tk.Canvas):
    """Thin progress bar that eases toward its target instead of jumping."""

    def __init__(self, parent, width=420):
        super().__init__(parent, width=width, height=8, bg=BG, highlightthickness=0)
        self.w, self.shown, self.target = width, 0.0, 0.0
        self.create_rectangle(0, 0, width, 8, fill=TROUGH, width=0)
        self.fill = self.create_rectangle(0, 0, 0, 8, fill=ACCENT, width=0)
        self.step()

    def set(self, frac):
        self.target = frac

    def step(self):
        self.shown += (self.target - self.shown) * 0.18
        if abs(self.target - self.shown) < 0.002:
            self.shown = self.target
        self.coords(self.fill, 0, 0, self.w * self.shown, 8)
        self.after(16, self.step)


class Window:
    W, H = 500, 380

    def __init__(self, dest, uninstalling):
        self.dest, self.uninstalling = dest, uninstalling
        self.current = installed()
        self.busy = False
        try:  # own taskbar identity, so the taskbar shows our icon and not python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClaudeTab.Setup")
        except (AttributeError, OSError):
            pass
        self.root = tk.Tk()
        self.root.title(f"{APP} Setup")
        try:  # title-bar and taskbar icon
            self.root.iconbitmap(default=bundled("claudetab.ico"))
        except tk.TclError:
            pass
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 3}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=32, pady=(26, 0))
        tk.Label(head, text=" Claude ▾ ", bg=ACCENT, fg=ON_ACCENT, font=("Segoe UI", 9, "bold"),
                 padx=4, pady=2).pack(side="left")
        tk.Label(head, text=f"v{VERSION}", bg=BG, fg=DIM, font=FONT_S).pack(side="right")
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=32, pady=(18, 0))
        self.page = tk.Frame(self.root, bg=BG)
        self.page.pack(fill="both", expand=True, padx=32)
        self.startup = tk.BooleanVar(value=True)
        self.desktop = tk.BooleanVar(value=False)
        links = shortcut_paths()
        if self.current:  # an upgrade keeps whatever shortcuts the user chose before
            self.startup.set(os.path.exists(links["startup"]))
            self.desktop.set(os.path.exists(links["desktop"]))
        self.events = queue.Queue()
        self.show_options()

    # -- helpers
    def clear(self):
        for w in self.page.winfo_children():
            w.destroy()

    def title(self, text, sub=None, color=FG):
        tk.Label(self.page, text=text, bg=BG, fg=color, font=("Segoe UI Semibold", 17), anchor="w").pack(
            fill="x", pady=(20, 0))
        if sub:
            tk.Label(self.page, text=sub, bg=BG, fg=MUTED, font=FONT, anchor="w", justify="left",
                     wraplength=self.W - 64).pack(fill="x", pady=(4, 0))

    def buttons(self, *items):
        row = tk.Frame(self.page, bg=BG)
        row.pack(side="bottom", fill="x", pady=(0, 24))
        for text, command, primary in reversed(items):
            Button(row, text, command, primary).pack(side="right", padx=(10, 0))

    def check(self, text, var):
        tk.Checkbutton(self.page, text=text, variable=var, bg=BG, fg=FG, selectcolor=PANEL, font=FONT,
                       activebackground=BG, activeforeground=FG, bd=0, highlightthickness=0,
                       cursor="hand2").pack(anchor="w", pady=(8, 0))

    def close(self):
        if not self.busy:
            self.root.destroy()

    # -- pages
    def show_options(self):
        self.clear()
        if self.uninstalling:
            self.title(f"Remove {APP}?", "The app, its shortcuts and its Installed-apps entry will be removed.")
            self.buttons(("Cancel", self.close, False), ("Remove", self.begin, True))
            return
        if not self.current:
            self.title(f"Install {APP}", "A menu on every Claude Code terminal window.\n"
                       "No admin rights needed, nothing to download.")
            action = "Install"
        else:
            old, new = self.current[0], VERSION
            if vtuple(old) < vtuple(new):
                self.title(f"Upgrade {APP}", f"Installed {old}  →  new {new}", GOOD)
                action = "Upgrade"
            elif vtuple(old) == vtuple(new):
                self.title(f"{APP} is up to date", f"Version {old} is installed. You can reinstall it to repair.")
                action = "Reinstall"
            else:
                self.title("Older version", f"{old} is installed; this setup is {new}. Continuing downgrades it.", DANGER)
                action = "Downgrade"
            self.dest = self.current[1]  # upgrade in place, wherever it was installed
        tk.Frame(self.page, bg=BG, height=6).pack()
        self.check("Start when I sign in", self.startup)
        self.check("Add a Desktop shortcut", self.desktop)
        tk.Label(self.page, text=f"Location: {self.dest}", bg=BG, fg=DIM, font=FONT_S, anchor="w").pack(
            fill="x", pady=(16, 0))
        self.buttons(("Cancel", self.close, False), (action, self.begin, True))

    def begin(self):
        steps = uninstall_steps() if self.uninstalling else install_steps(
            self.dest, self.startup.get(), self.desktop.get(), True)
        verb = "Removing" if self.uninstalling else ("Upgrading" if self.current else "Installing")
        self.clear()
        self.busy = True
        self.title(f"{verb} {APP}…")
        self.status = tk.Label(self.page, text="", bg=BG, fg=MUTED, font=FONT, anchor="w")
        self.status.pack(fill="x", pady=(20, 10))
        self.bar = Bar(self.page, self.W - 64)
        self.bar.pack(anchor="w")
        self.percent = tk.Label(self.page, text="0%", bg=BG, fg=DIM, font=FONT_S, anchor="e")
        self.percent.pack(fill="x", pady=(6, 0))
        threading.Thread(target=self.work, args=(steps,), daemon=True).start()
        self.poll(len(steps))

    def work(self, steps):
        try:
            for n, (label, fn) in enumerate(steps):
                self.events.put(("step", n, label))
                fn()
                time.sleep(0.35)  # long enough to read, short enough not to drag
                self.events.put(("done", n + 1, label))
            self.events.put(("finished",))
        except Exception as e:
            self.events.put(("error", str(e)))

    def poll(self, total):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "step":
                    self.status.configure(text=ev[2] + "…")
                elif ev[0] == "done":
                    frac = ev[1] / total
                    self.bar.set(frac)
                    self.percent.configure(text=f"{round(frac * 100)}%")
                elif ev[0] == "finished":
                    self.busy = False
                    return self.root.after(450, self.show_done)
                elif ev[0] == "error":
                    self.busy = False
                    return self.show_error(ev[1])
        except queue.Empty:
            pass
        self.root.after(40, self.poll, total)

    def show_done(self):
        self.clear()
        if self.uninstalling:
            self.title(f"{APP} was removed", "Thanks for trying it.", GOOD)
        else:
            what = "upgraded to" if self.current and vtuple(self.current[0]) != vtuple(VERSION) else "ready"
            head = f"{APP} {what} {VERSION}" if what != "ready" else f"{APP} is ready"
            self.title(head, "It is running now. Open a Claude Code terminal and look for the "
                       "Claude ▾ tab at the top-right of its window.", GOOD)
        self.buttons(("Close", self.root.destroy, True))

    def show_error(self, msg):
        self.clear()
        self.title("Setup failed", msg, DANGER)
        self.buttons(("Close", self.root.destroy, True))

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- entry point
def main():
    ap = argparse.ArgumentParser(description=APP + " setup")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--silent", action="store_true", help="no window; defaults apply")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--no-startup", action="store_true")
    ap.add_argument("--desktop", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    a = ap.parse_args()
    found = installed()
    dest = a.dir or (found[1] if found else default_dir())
    if not a.silent:
        Window(dest, a.uninstall).run()
        return 0
    try:
        steps = uninstall_steps() if a.uninstall else install_steps(
            dest, not a.no_startup, a.desktop, not a.no_start)
        for _label, fn in steps:
            fn()
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
