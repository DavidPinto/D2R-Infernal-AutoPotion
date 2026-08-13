"""D2R Infernal Auto Potion - entry point.

Launches the desktop UI.  Only dependency is customtkinter (pip install -r
requirements.txt).  No AutoHotkey, no other third-party packages.

Usage:
    python main.py            # launch the desktop UI
    python main.py --version  # print the version and exit
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv or "-v" in argv:
        from d2r import __version__

        print(f"D2R Infernal Auto Potion v{__version__}")
        return 0
    try:
        from ui.app import run
    except ImportError as exc:
        print(f"Error: could not import the UI module: {exc}", file=sys.stderr)
        return 1
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
