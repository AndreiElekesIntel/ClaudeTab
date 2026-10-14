"""Renders docs/installer-*.png from the real setup window, with fake install steps.

    python tools/make_installer_shots.py

Nothing is installed: install_steps/installed are swapped for dummies. Needs Pillow.
"""
import ctypes
import importlib.machinery
import importlib.util
import os
import time

from PIL import ImageGrab

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "docs")
loader = importlib.machinery.SourceFileLoader("setup_ui", os.path.join(ROOT, "installer", "setup.py"))
spec = importlib.util.spec_from_loader("setup_ui", loader)
setup_ui = importlib.util.module_from_spec(spec)
loader.exec_module(setup_ui)


def grab(win, name):
    win.root.update()
    time.sleep(0.15)
    win.root.update()
    x, y = win.root.winfo_rootx(), win.root.winfo_rooty()
    img = ImageGrab.grab(bbox=(x, y, x + win.W, y + win.H))
    for attempt in range(5):  # OneDrive can briefly lock a freshly written file
        try:
            img.save(os.path.join(OUT, name))
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(1)
    print("wrote", name)


def pump(win, seconds):
    end = time.time() + seconds
    while time.time() < end:
        win.root.update()
        time.sleep(0.01)


def session(prefix, current, uninstalling=False, steps=6):
    setup_ui.installed = lambda: current
    setup_ui.install_steps = lambda *a: [(f"Step {n}", lambda: time.sleep(0.9)) for n in range(steps)]
    setup_ui.install_steps = lambda *a, _l=("Closing the running copy", "Copying files", "Adding the uninstaller",
                                             "Creating shortcuts", "Registering in Installed apps",
                                             "Starting ClaudeTab"): [(l, lambda: time.sleep(0.8)) for l in _l]
    win = setup_ui.Window(r"C:\Users\you\AppData\Local\ClaudeTab", uninstalling)
    win.root.attributes("-topmost", True)
    grab(win, f"installer-{prefix}-options.png")
    win.begin()
    pump(win, 2.6)
    grab(win, f"installer-{prefix}-progress.png")
    pump(win, 6.0)
    grab(win, f"installer-{prefix}-done.png")
    win.root.destroy()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    session("upgrade", ("0.3.0", r"C:\Users\you\AppData\Local\ClaudeTab"))
    session("install", None)
