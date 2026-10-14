"""Draws assets/claudetab.ico: a rounded purple tile with a white down-caret, like the menu handle.
Needs Pillow."""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "claudetab.ico")
S, SS = 256, 4  # draw 4x and downsample for smooth edges
N = S * SS

# vertical gradient tile, clipped to a rounded square
top, bottom = (124, 124, 245), (84, 84, 210)
grad = Image.new("RGBA", (N, N))
gd = ImageDraw.Draw(grad)
for y in range(N):
    t = y / (N - 1)
    gd.line([(0, y), (N, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((8 * SS, 8 * SS, N - 8 * SS, N - 8 * SS), radius=58 * SS, fill=255)
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
img.paste(grad, mask=mask)

d = ImageDraw.Draw(img)
w = 30 * SS  # chevron stroke
pts = [(68 * SS, 98 * SS), (128 * SS, 158 * SS), (188 * SS, 98 * SS)]
d.line(pts, fill="white", width=w, joint="curve")
for x, y in (pts[0], pts[2]):
    d.ellipse((x - w // 2, y - w // 2, x + w // 2, y + w // 2), fill="white")

img = img.resize((S, S), Image.LANCZOS)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
img.save(OUT.replace(".ico", ".png"))
print("wrote", os.path.normpath(OUT))
