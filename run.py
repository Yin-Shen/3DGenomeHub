#!/usr/bin/env python3
"""
3D Genome & Deep Learning Literature Hub
=========================================
One-click launcher — double-click this file or run: python run.py

Features:
  - Auto-fetch papers from PubMed, bioRxiv, arXiv
  - Categorize papers into research topics
  - Auto-update README.md
  - Send email digests
  - Beautiful web GUI at http://localhost:8686
"""

import os
import subprocess
import sys


def check_dependencies():
    """Install dependencies if missing."""
    try:
        import httpx
        import typer
        import rich
        import jinja2
        import dotenv
    except ImportError:
        print("Installing dependencies...")
        req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        print("Dependencies installed!\n")


def main():
    # Ensure src is in path
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    check_dependencies()

    from genome_literature.web_app import start_server
    start_server(port=8686, open_browser=True)


if __name__ == "__main__":
    main()
