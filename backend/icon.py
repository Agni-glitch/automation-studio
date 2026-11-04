"""The app icon, drawn in code so the tray (runtime) and the build (app.ico) share one design."""

from __future__ import annotations

from PIL import Image, ImageDraw

_BASE = 1024
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def draw(size: int = 256, *, badge: tuple[int, int, int] | None = None) -> Image.Image:
    """Rounded coral tile with a three-node workflow graph. ``badge`` adds a status dot."""
    img = Image.new("RGBA", (_BASE, _BASE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tile = Image.new("RGBA", (_BASE, _BASE))
    td = ImageDraw.Draw(tile)
    top, bottom = (255, 128, 102), (232, 76, 61)
    for y in range(_BASE):
        t = y / (_BASE - 1)
        td.line([(0, y), (_BASE, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (_BASE, _BASE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, _BASE - 40, _BASE - 40], radius=210, fill=255)
    img.paste(tile, (0, 0), mask)

    white, soft = (255, 255, 255, 255), (255, 255, 255, 170)
    src, dst1, dst2 = (300, 512), (720, 330), (720, 694)
    for end in (dst1, dst2):
        mid_x = (src[0] + end[0]) // 2
        d.line([src, (mid_x, src[1]), (mid_x, end[1]), end], fill=soft, width=46, joint="curve")
    for (x, y), r in ((src, 118), (dst1, 96), (dst2, 96)):
        d.ellipse([x - r, y - r, x + r, y + r], fill=white)
    d.ellipse([src[0] - 46, src[1] - 46, src[0] + 46, src[1] + 46], fill=(232, 76, 61, 255))
    if badge is not None:
        d.ellipse([640, 640, 1010, 1010], fill=(28, 31, 38, 255))
        d.ellipse([690, 690, 960, 960], fill=badge + (255,))
    return img.resize((size, size), Image.LANCZOS)
