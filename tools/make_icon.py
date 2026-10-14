"""Draws assets/claudetab.ico: the handle's purple tab with a down caret. Needs Pillow."""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "claudetab.ico")
S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((24, 120, S - 24, S - 120), radius=70, fill="#5b5bd6")
d.polygon([(S // 2 - 90, 215), (S // 2 + 90, 215), (S // 2, 320)], fill="white")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("wrote", os.path.normpath(OUT))
