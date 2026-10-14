"""
ClaudeTab — a small menu on every Claude Code terminal window.

Runs in the background (double-click, or `pythonw claude_tab.pyw`). Whenever the
window you are in hosts a live Claude Code session, a little "Claude" handle
appears at its top-right. Click it for: Rename, Compact, Clear, Opus, Sonnet.
Stdlib only (tkinter + ctypes), Windows only.

How it works
  * Sessions: ~/.claude/sessions/<pid>.json (written by Claude Code itself).
  * Which window: each session's console has a window; the terminal that hosts it
    owns that window (the ConPTY pseudo-window in Windows Terminal, the console
    window itself in classic conhost). Process ancestry cannot answer this: with
    Windows Terminal as the default terminal, claude's parents lead to explorer.
    Several tabs in one window -> the one whose name is in the window title, else
    the menu lists each session.
  * Acting: attach to the session's console by pid and write the slash command
    plus Enter into its input buffer. No focus needed, nothing is "typed" into the
    wrong window. Only done while the session is idle.

Limit: a half-typed draft in the session's prompt box gets the command appended
to it.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import time
import tkinter as tk

POLL_MS = 150          # foreground check
REFRESH_S = 2.0        # session list + process tree
HANDLE_W, HANDLE_H = 74, 22
OFFSET_RIGHT = 150     # keeps the handle clear of min/max/close
OFFSET_TOP = 6
MODELS = {"Opus": "opus", "Sonnet": "sonnet"}
# label -> /effort argument. "max" lasts for the session only (Claude Code's rule).
EFFORTS = {"Low": "low", "Med": "medium", "High": "high", "XHigh": "xhigh", "Max": "max"}
# Argument-less commands. /rename with no name lets Claude Code pick one.
SIMPLE = {"rename": "/rename", "compact": "/compact", "clear": "/clear"}
# Commands Claude Code runs immediately even mid-turn, so they are offered while busy.
ANYTIME = {"/rename"} | {f"/effort {a}" for a in EFFORTS.values()}
# Commands that may stop at an "are you sure?" prompt: the model switches always do,
# /effort does when it has to warn about the prompt cache.
CONFIRMED = {"/model opus", "/model sonnet"} | {f"/effort {a}" for a in EFFORTS.values()}
# Enter is pressed at each of these delays. The prompt takes a variable time to
# draw, so one fixed delay is either slow or early; an Enter that lands before
# the prompt (or after it is answered) hits an empty input box and does nothing.
CONFIRM_DELAYS_MS = (350, 700, 1100)

# Dropdown look. Dark, like the terminal it sits on.
BG, BORDER, HOVER = "#1e2130", "#363b52", "#2c3248"
FG, MUTED, DIM, DANGER, ACCENT = "#e8eaf2", "#8b91a8", "#565c75", "#f2777a", "#8b8bf0"
FONT, FONT_B, FONT_S = ("Segoe UI", 10), ("Segoe UI Semibold", 10), ("Segoe UI", 8)
MENU_W = 230

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------- win32 types
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.AttachConsole.argtypes = [wt.DWORD]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.c_void_p]
k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.c_void_p]
k32.WriteConsoleInputW.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
u32.GetForegroundWindow.restype = wt.HWND
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.IsIconic.argtypes = [wt.HWND]
u32.GetAsyncKeyState.restype = ctypes.c_short
u32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
u32.GetAncestor.restype = wt.HWND
u32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
k32.GetConsoleWindow.restype = wt.HWND

PROCESS_QUERY_LIMITED = 0x1000
STILL_ACTIVE = 259
INVALID_HANDLE = ctypes.c_void_p(-1).value
TH32CS_SNAPPROCESS = 0x2


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


class KEY_EVENT(ctypes.Structure):
    _fields_ = [("bKeyDown", wt.BOOL), ("wRepeatCount", wt.WORD), ("wVirtualKeyCode", wt.WORD),
                ("wVirtualScanCode", wt.WORD), ("UnicodeChar", wt.WCHAR), ("dwControlKeyState", wt.DWORD)]


class INPUT_RECORD(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT)]
    _anonymous_ = ("u",)
    _fields_ = [("EventType", wt.WORD), ("u", _U)]


def log(msg):
    """pythonw has no stderr, so errors go to a file next to the temp dir."""
    try:
        with open(os.path.join(os.environ.get("TEMP", "."), "claude_tab.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- sessions
def sessions_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "sessions")


def pid_alive(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return False
    try:
        code = wt.DWORD()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


_owner_cache = {}


def console_owner(pid):
    """Top-level window hosting `pid`'s console, or 0. Cached: it never moves."""
    if pid in _owner_cache:
        return _owner_cache[pid]
    owner = 0
    k32.FreeConsole()
    try:
        if k32.AttachConsole(pid):
            hw = k32.GetConsoleWindow()
            if hw:
                owner = u32.GetAncestor(hw, 3) or hw  # GA_ROOTOWNER
    finally:
        k32.FreeConsole()
    if owner:
        _owner_cache[pid] = owner
    return owner


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def load_sessions():
    out = []
    d = sessions_dir()
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                rec = json.load(f)
            pid = int(rec["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if pid_alive(pid):
            out.append({"pid": pid, "id": rec.get("sessionId"), "name": rec.get("name") or rec.get("kind") or "Claude Code",
                        "cwd": rec.get("cwd") or "", "status": rec.get("status") or "unknown"})
    return out


# ---------------------------------------------------------------- injection
def build_command(action, arg):
    """Allowlisted slash command, or None. Never a newline."""
    if action == "model" and arg in MODELS.values():
        return f"/model {arg}"
    if action == "effort" and arg in EFFORTS.values():
        return f"/effort {arg}"
    if action in SIMPLE:
        return SIMPLE[action]
    return None


def send_to_console(pid, text):
    """Write `text` + Enter into the console of `pid` (empty text = Enter alone).
    Returns (ok, reason)."""
    if "\r" in text or "\n" in text:
        return False, "refusing multi-line text"
    recs = []
    for c in text:
        recs += [_key(c, 1, 0, 0), _key(c, 0, 0, 0)]
    recs += [_key("\r", 1, 13, 28), _key("\r", 0, 13, 28)]
    arr = (INPUT_RECORD * len(recs))(*recs)
    k32.FreeConsole()
    try:
        if not k32.AttachConsole(pid):
            return False, f"could not attach to pid {pid} (error {ctypes.get_last_error()})"
        h = k32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        if h in (0, INVALID_HANDLE, None):
            return False, "could not open the session's input"
        try:
            written = wt.DWORD()
            ok = k32.WriteConsoleInputW(h, arr, len(recs), ctypes.byref(written))
        finally:
            k32.CloseHandle(h)
        if not ok or written.value != len(recs):
            return False, "the session did not accept the keystrokes"
        return True, ""
    finally:
        k32.FreeConsole()


def _key(ch, down, vk, scan):
    r = INPUT_RECORD()
    r.EventType = 1
    r.KeyEvent.bKeyDown = down
    r.KeyEvent.wRepeatCount = 1
    r.KeyEvent.wVirtualKeyCode = vk
    r.KeyEvent.wVirtualScanCode = scan
    r.KeyEvent.UnicodeChar = ch
    return r


# ---------------------------------------------------------------- the handle
class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.handle = tk.Toplevel(self.root)
        self.handle.overrideredirect(True)
        self.handle.attributes("-topmost", True)
        self.handle.withdraw()
        self.btn = tk.Button(self.handle, text="Claude  ▾", relief="flat", bg="#5b5bd6", fg="white",
                             activebackground="#7070e0", activeforeground="white", bd=0, padx=6,
                             font=("Segoe UI", 9, "bold"), cursor="hand2")
        self.btn.pack(fill="both", expand=True)
        self.btn.bind("<Button-1>", self.on_click)
        self.handle.update_idletasks()
        self.no_activate(self.handle)
        self.sessions, self.refreshed = [], 0.0
        self.matches, self.shown_hwnd, self.menu_open = [], None, False
        self.panel, self.menu_owner = None, None
        self.tick()

    @staticmethod
    def no_activate(win):
        """Clicking the handle must not pull focus off the terminal."""
        hwnd = u32.GetParent(win.winfo_id()) or win.winfo_id()
        style = u32.GetWindowLongW(hwnd, -20)
        u32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x80)  # NOACTIVATE | TOOLWINDOW

    def handle_hwnd(self):
        return u32.GetParent(self.handle.winfo_id()) or self.handle.winfo_id()

    def refresh(self):
        if time.time() - self.refreshed > REFRESH_S:
            self.sessions, self.refreshed = load_sessions(), time.time()
            for pid in [p for p in _owner_cache if p not in {x['pid'] for x in self.sessions}]:
                del _owner_cache[pid]

    def sessions_for(self, hwnd):
        hosted = [x for x in self.sessions if console_owner(x["pid"]) == hwnd]
        # Windows Terminal: one window, many tabs, and the title is the active tab's.
        title = window_title(hwnd)
        active = [x for x in hosted if x["name"] and x["name"] in title]
        return active or hosted

    def tick(self):
        try:
            hwnd = u32.GetForegroundWindow()
            if hwnd and hwnd != self.handle.winfo_id() and not self.menu_open:
                self.refresh()
                own = os.getpid()
                owner = wt.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                found = [] if owner.value == own or u32.IsIconic(hwnd) else self.sessions_for(hwnd)
                if found:
                    self.matches = found
                    r = wt.RECT()
                    u32.GetWindowRect(hwnd, ctypes.byref(r))
                    x, y = r.right - OFFSET_RIGHT - HANDLE_W, r.top + OFFSET_TOP
                    self.handle.geometry(f"{HANDLE_W}x{HANDLE_H}+{x}+{y}")
                    self.handle.deiconify()
                    self.handle.attributes("-topmost", True)
                else:
                    self.matches = []
                    self.handle.withdraw()
        except Exception as e:  # never die in the background
            log(f"tick error: {e!r}")
        self.root.after(POLL_MS, self.tick)

    # ------------------------------------------------------------ dropdown
    def on_click(self, _event):
        if self.panel:
            return self.close_menu()
        if not self.matches:
            return
        self.menu_owner = u32.GetForegroundWindow()
        panel = tk.Toplevel(self.root, bg=BORDER)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        body = tk.Frame(panel, bg=BG, padx=6, pady=6)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        for n, sess in enumerate(self.matches):
            if n:
                tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=6)
            self.session_block(body, sess)
        panel.update_idletasks()
        x = self.handle.winfo_rootx() + HANDLE_W - panel.winfo_reqwidth()
        y = self.handle.winfo_rooty() + HANDLE_H + 4
        x = max(4, min(x, panel.winfo_screenwidth() - panel.winfo_reqwidth() - 4))
        panel.geometry(f"+{x}+{y}")
        self.no_activate(panel)
        self.panel, self.menu_open = panel, True
        self.btn.configure(text="Claude  ▴")
        self.watch_menu()

    def session_block(self, body, sess):
        idle = sess["status"] == "idle"
        head = tk.Frame(body, bg=BG)
        head.pack(fill="x", padx=6, pady=(2, 4))
        tk.Label(head, text="●", bg=BG, fg="#5fd38d" if idle else "#f0b45a", font=FONT_S).pack(side="left")
        tk.Label(head, text=" " + sess["name"][:28], bg=BG, fg=FG, font=FONT_B, anchor="w").pack(side="left")
        tk.Label(head, text=sess["status"], bg=BG, fg=MUTED, font=FONT_S).pack(side="right")
        if not idle:
            tk.Label(body, text="Busy — only Rename and Effort work until it is idle", bg=BG, fg=MUTED,
                     font=FONT_S, anchor="w").pack(fill="x", padx=8, pady=(0, 2))
        self.section(body, "SESSION")
        self.item(body, "✎", "Rename", "/rename", True, lambda: self.pick(sess, "rename"))
        self.item(body, "⇲", "Compact", "/compact", idle, lambda: self.pick(sess, "compact"))
        self.item(body, "⌫", "Clear", "/clear", idle, lambda: self.pick(sess, "clear"), danger=True)
        self.section(body, "MODEL")
        for label, alias in MODELS.items():
            self.item(body, "◆", label, f"/model {alias}", idle, lambda a=alias: self.pick(sess, "model", a))
        self.section(body, "EFFORT")
        self.chips(body, [(label, lambda a=arg: self.pick(sess, "effort", a)) for label, arg in EFFORTS.items()])

    def section(self, body, text):
        tk.Label(body, text=text, bg=BG, fg=DIM, font=("Segoe UI Semibold", 7), anchor="w").pack(
            fill="x", padx=8, pady=(6, 1))

    def chips(self, body, buttons):
        """A row of small buttons, equal width, for short choices like effort levels."""
        row = tk.Frame(body, bg=BG, width=MENU_W)
        row.pack(fill="x", padx=6, pady=(2, 4))
        for n, (label, command) in enumerate(buttons):
            row.columnconfigure(n, weight=1, uniform="chip")
            b = tk.Label(row, text=label, bg=HOVER, fg=FG, font=FONT_S, pady=5, cursor="hand2")
            b.grid(row=0, column=n, sticky="ew", padx=2)
            b.bind("<Enter>", lambda _e, w=b: w.configure(bg=ACCENT, fg="#101322"))
            b.bind("<Leave>", lambda _e, w=b: w.configure(bg=HOVER, fg=FG))
            b.bind("<ButtonRelease-1>", lambda _e, c=command: c())

    def item(self, body, icon, label, hint, enabled, command, danger=False):
        fg = (DANGER if danger else FG) if enabled else DIM
        row = tk.Frame(body, bg=BG, width=MENU_W, height=28, cursor="hand2" if enabled else "arrow")
        row.pack(fill="x")
        row.pack_propagate(False)
        parts = [
            tk.Label(row, text=icon, bg=BG, fg=(DANGER if danger else ACCENT) if enabled else DIM, font=FONT, width=2),
            tk.Label(row, text=label, bg=BG, fg=fg, font=FONT, anchor="w"),
            tk.Label(row, text=hint, bg=BG, fg=DIM if enabled else BG, font=FONT_S),
        ]
        parts[0].pack(side="left", padx=(4, 2))
        parts[1].pack(side="left", fill="x", expand=True)
        parts[2].pack(side="right", padx=(0, 8))
        if not enabled:
            return
        widgets = [row] + parts

        def paint(color):
            for w in widgets:
                w.configure(bg=color)

        for w in widgets:
            w.bind("<Enter>", lambda _e: paint(HOVER))
            w.bind("<Leave>", lambda _e: paint(BG))
            w.bind("<ButtonRelease-1>", lambda _e: command())

    def pick(self, sess, action, arg=None):
        self.close_menu()
        self.send(sess, build_command(action, arg))

    def watch_menu(self):
        """Close on a click outside, Esc, or when the user switches windows.

        The panel is no-activate (it must not steal focus from the terminal), so
        it never receives focus-out; this polls the mouse and foreground instead.
        """
        if not self.panel:
            return
        try:
            pt = wt.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            inside = any(self.contains(w, pt) for w in (self.panel, self.handle))
            clicked = any(u32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))
            fg = u32.GetForegroundWindow()
            if (clicked and not inside) or u32.GetAsyncKeyState(0x1B) & 0x8000 or (fg and fg != self.menu_owner):
                return self.close_menu()
        except Exception as e:
            log(f"watch error: {e!r}")
        self.root.after(40, self.watch_menu)

    @staticmethod
    def contains(w, pt):
        x, y = w.winfo_rootx(), w.winfo_rooty()
        return x <= pt.x < x + w.winfo_width() and y <= pt.y < y + w.winfo_height()

    def close_menu(self):
        if self.panel:
            self.panel.destroy()
        self.panel, self.menu_open = None, False
        self.btn.configure(text="Claude  ▾")

    def send(self, s, text):
        if not text:
            return
        self.refreshed = 0  # re-read status before acting
        self.refresh()
        live = next((x for x in self.sessions if x["pid"] == s["pid"]), None)
        if not live:
            return self.toast("That session has exited.")
        if live["status"] != "idle" and text not in ANYTIME:
            return self.toast("Session is busy — try again when it is idle.")
        ok, why = send_to_console(s["pid"], text)
        if ok and text in CONFIRMED:
            # The TUI asks "are you sure?" for these; give it a moment to draw the
            # prompt, then press Enter to accept the default. A stray Enter on an
            # empty prompt box does nothing, so a missing prompt is harmless.
            for delay in CONFIRM_DELAYS_MS:
                self.root.after(delay, lambda pid=s["pid"]: send_to_console(pid, ""))
        self.toast(f"Sent {text}" if ok else f"Failed: {why}")

    def toast(self, msg):
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        tk.Label(t, text=msg, bg="#1b1f2c", fg="white", padx=12, pady=8, font=("Segoe UI", 9)).pack()
        t.update_idletasks()
        sw = self.root.winfo_screenwidth()
        t.geometry(f"+{sw - t.winfo_width() - 24}+24")
        self.no_activate(t)
        t.after(2500, t.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # One copy only: a second would stack a second handle on every window.
    mutex = k32.CreateMutexW(None, False, "Local\\perch")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    App().run()
