"""Generate build/assets/app.ico (+ app.png) from backend/icon.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.icon import ICO_SIZES, draw  # noqa: E402


def main(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    draw(1024).save(out, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    draw(256).save(out.with_suffix(".png"))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "assets" / "app.ico")
