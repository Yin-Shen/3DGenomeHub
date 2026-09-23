#!/usr/bin/env python3
"""
3D Genome & Deep Learning Literature Hub
=========================================
One-click launcher: double-click this file or run ``python run.py``.

Installs missing dependencies on first run, then opens the web GUI at
http://localhost:8686 (search, filters, landscape analysis, one-click updates).
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def check_dependencies() -> None:
    try:
        import dotenv  # noqa: F401
        import httpx  # noqa: F401
        import jinja2  # noqa: F401
        import rich  # noqa: F401
        import typer  # noqa: F401
    except ImportError:
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", os.path.join(ROOT, "requirements.txt")])
        print("Dependencies installed!\n")


def main() -> None:
    src_dir = os.path.join(ROOT, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    check_dependencies()

    from genome_literature.web_app import start_server

    start_server(open_browser=True)


if __name__ == "__main__":
    main()
