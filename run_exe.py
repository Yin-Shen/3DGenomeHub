#!/usr/bin/env python3
"""
3D Genome & Deep Learning Literature Hub
=========================================
Standalone entry point for PyInstaller exe build.
Double-click the generated exe to launch the web GUI.
"""

import os
import sys


def get_base_path():
    """Get the base path — works for both script and PyInstaller exe."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def main():
    base = get_base_path()

    # Add source to path
    src_dir = os.path.join(base, "src") if os.path.exists(os.path.join(base, "src")) else base
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    # Also add base itself (for frozen exe where genome_literature is at top level)
    if base not in sys.path:
        sys.path.insert(0, base)

    # Set working directory to exe location for papers/templates
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(exe_dir)

        # Override config paths to use exe directory
        import genome_literature.config as cfg
        from pathlib import Path
        cfg.PROJECT_ROOT = Path(exe_dir)
        cfg.PAPERS_DIR = Path(exe_dir) / "papers"
        cfg.PAPERS_JSON = cfg.PAPERS_DIR / "papers.json"
        cfg.NEW_PAPERS_JSON = cfg.PAPERS_DIR / "new_papers.json"
        cfg.TEMPLATE_DIR = Path(exe_dir) / "templates"
        cfg.README_PATH = Path(exe_dir) / "README.md"

        # Ensure papers directory exists
        cfg.PAPERS_DIR.mkdir(exist_ok=True)

    from genome_literature.web_app import start_server

    print()
    print("=" * 60)
    print("  3D Genome & Deep Learning Literature Hub")
    print("  Starting web interface...")
    print("  Browser will open automatically.")
    print("=" * 60)
    print()

    start_server(port=8686, open_browser=True)


if __name__ == "__main__":
    main()
