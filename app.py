"""Entry point of the packaged app (both AutomationStudio.exe and studio.exe).

    AutomationStudio.exe                  -> open the desktop window (starting the service if needed)
    AutomationStudio.exe serve --background -> the background service (used by autostart)
    studio.exe <command> ...              -> the command-line interface (same as main.py)
"""

from __future__ import annotations

import multiprocessing
import sys


def run() -> int:
    multiprocessing.freeze_support()
    if len(sys.argv) <= 1:
        from desktop.app_window import main as open_window

        return open_window()
    from main import main as cli

    return cli()


if __name__ == "__main__":
    sys.exit(run())
