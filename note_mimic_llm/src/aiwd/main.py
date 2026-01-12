from __future__ import annotations
import os
import sys
from pathlib import Path

from .cli import main as cli_main
from .gui import run_gui


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Cases:
    #  - No args (double-click): show GUI
    #  - Arg is a directory (drag & drop / SendTo): run CLI on that folder
    if not argv:
        run_gui()
        return 0
    # If first arg is folder, run CLI path directly
    first = argv[0]
    if os.path.isdir(first):
        return cli_main([first] + argv[1:])
    # Otherwise, pass-through to CLI
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

