"""Generate the Windows AURIX icon from the same simple geometric mark.

Only a build-time operation. Pillow is already a desktop packaging dependency.
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
size, scale = 256, 4
img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
a = lambda v: round(v * scale)
d.rounded_rectangle((a(4), a(4), a(252), a(252)), radius=a(65),
                    fill="#0B1928", outline="#345B74", width=a(3))
d.line([(a(58),a(185)),(a(119),a(56)),(a(135),a(56)),(a(198),a(185))],
       fill="#65DDE7", width=a(21), joint="curve")
d.line([(a(89),a(143)),(a(171),a(143))], fill="#BEF8FF", width=a(17))
d.arc((a(28),a(24),a(225),a(223)), 195, 255, fill="#928DFF", width=a(5))
d.arc((a(28),a(24),a(225),a(223)), 10, 69, fill="#58DDED", width=a(5))
image = img.resize((size,size), Image.Resampling.LANCZOS)
destination = ROOT / "frontend" / "src-tauri" / "icons" / "icon.ico"
destination.parent.mkdir(parents=True, exist_ok=True)
image.save(destination, format="ICO", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(f"Created {destination}")
