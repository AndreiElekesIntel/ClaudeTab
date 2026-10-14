"""Renders the README screenshots from the real menu code, with fake sessions.

    python tools/make_screenshots.py

Draws a mock terminal window, puts the handle on it and opens the real dropdown
(App.session_block) for made-up sessions, then grabs the screen region. Nothing
from your own terminals or sessions ends up in the images. Needs Pillow.
"""
import ctypes
import importlib.machinery
import importlib.util
import os
import time
import tkinter as tk

from PIL import ImageGrab

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "docs")
loader = importlib.machinery.SourceFileLoader("claude_tab", os.path.join(ROOT, "claude_tab.pyw"))
spec = importlib.util.spec_from_loader("claude_tab", loader)
claude_tab = importlib.util.module_from_spec(spec)
loader.exec_module(claude_tab)

TERM_BG, TERM_FG, TERM_DIM = "#0c0c0c", "#cccccc", "#767676"
W = 920
LINES = [
    ("> refactor the retry logic in sync.py so it backs off exponentially", TERM_FG),
    ("", TERM_FG),
    ("● I'll read sync.py first, then update the retry loop.", "#e8eaf2"),
    ("  ⎿  Read sync.py (212 lines)", TERM_DIM),
    ("● Update(sync.py)", "#e8eaf2"),
    ("  ⎿  Updated sync.py with 14 additions and 6 removals", TERM_DIM),
    ("", TERM_FG),
    ("● Backoff is now 1s, 2s, 4s ... capped at 30s, with jitter. Tests pass.", "#e8eaf2"),
    ("", TERM_FG),
    ("> ", TERM_FG),
]


def shot(name, sessions, H=470):
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{W}x{H}+80+80")
    root.configure(bg=TERM_BG)
    bar = tk.Frame(root, bg="#1f1f1f", height=36)
    bar.pack(fill="x")
    tk.Label(bar, text="  >_  PowerShell", bg="#1f1f1f", fg=TERM_FG, font=("Segoe UI", 9)).pack(side="left", pady=8)
    for c in ("—", "☐", "✕"):
        tk.Label(bar, text=c, bg="#1f1f1f", fg=TERM_FG, width=6, font=("Segoe UI", 9)).pack(side="right", pady=8)
    body = tk.Frame(root, bg=TERM_BG, padx=16, pady=14)
    body.pack(fill="both", expand=True)
    for text, color in LINES:
        tk.Label(body, text=text, bg=TERM_BG, fg=color, font=("Cascadia Mono", 11), anchor="w").pack(fill="x")
    root.update()

    app = claude_tab.App.__new__(claude_tab.App)
    app.pick = lambda *a, **k: None

    # handle, positioned exactly like App.tick does
    x0, y0 = root.winfo_rootx(), root.winfo_rooty()
    hx, hy = x0 + W - claude_tab.OFFSET_RIGHT - claude_tab.HANDLE_W, y0 + claude_tab.OFFSET_TOP
    handle = tk.Toplevel(root, bg="#5b5bd6")
    handle.overrideredirect(True)
    handle.geometry(f"{claude_tab.HANDLE_W}x{claude_tab.HANDLE_H}+{hx}+{hy}")
    tk.Button(handle, text="Claude  ▴", relief="flat", bg="#5b5bd6", fg="white", bd=0, padx=6,
              font=("Segoe UI", 9, "bold")).pack(fill="both", expand=True)

    # dropdown, built like App.on_click
    panel = tk.Toplevel(root, bg=claude_tab.BORDER)
    panel.overrideredirect(True)
    inner = tk.Frame(panel, bg=claude_tab.BG, padx=6, pady=6)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    for n, sess in enumerate(sessions):
        if n:
            tk.Frame(inner, bg=claude_tab.BORDER, height=1).pack(fill="x", pady=6)
        app.session_block(inner, sess)
    panel.update_idletasks()
    px = hx + claude_tab.HANDLE_W - panel.winfo_reqwidth()
    py = hy + claude_tab.HANDLE_H + 4
    panel.geometry(f"+{px}+{py}")
    for w in (root, handle, panel):
        w.attributes("-topmost", True)
        w.update()
    root.after(400, lambda: None)
    root.update()
    time.sleep(0.6)
    root.update()
    ph = panel.winfo_reqheight()
    img = ImageGrab.grab(bbox=(x0, y0, x0 + W, y0 + H))
    for attempt in range(5):  # OneDrive can briefly lock a freshly written file
        try:
            img.save(os.path.join(OUT, name))
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(1)
    print("wrote", name, img.size)
    root.destroy()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    shot("menu-idle.png", [{"pid": 1, "name": "sync-backoff", "status": "idle"}])
    shot("menu-busy.png", [{"pid": 1, "name": "sync-backoff", "status": "busy"}])
    shot("menu-multi.png", [{"pid": 1, "name": "sync-backoff", "status": "idle"},
                            {"pid": 2, "name": "docs-cleanup", "status": "busy"}], H=700)
