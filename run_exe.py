#!/usr/bin/env python3
"""
3D Genome & Deep Learning Literature Hub
=========================================
Entry point for the PyInstaller build (see build_exe.bat).
Double-click the generated exe to launch the web GUI.
"""

import os
import shutil
import sys
from pathlib import Path


def get_base_path() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    base = get_base_path()
    src_dir = os.path.join(base, "src") if os.path.exists(os.path.join(base, "src")) else base
    for path in (src_dir, base):
        if path not in sys.path:
            sys.path.insert(0, path)

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        os.chdir(exe_dir)

        import genome_literature.config as cfg

        cfg.PROJECT_ROOT = exe_dir
        cfg.PAPERS_DIR = exe_dir / "papers"
        cfg.PAPERS_JSON = cfg.PAPERS_DIR / "papers.json"
        cfg.NEW_PAPERS_JSON = cfg.PAPERS_DIR / "new_papers.json"
        cfg.STATE_JSON = cfg.PAPERS_DIR / "state.json"
        cfg.CURATED_DOIS_FILE = cfg.PAPERS_DIR / "curated_dois.txt"
        cfg.TRANSLATIONS_JSON = cfg.PAPERS_DIR / "translations.json"
        cfg.AI_NOTES_DIR = exe_dir / "ai_notes"
        cfg.CACHE_DIR = exe_dir / ".cache"
        cfg.FULLTEXT_CACHE_DIR = cfg.CACHE_DIR / "fulltext"
        cfg.ENV_FILE = exe_dir / ".env"
        if cfg.ENV_FILE.exists():
            from dotenv import load_dotenv

            load_dotenv(cfg.ENV_FILE)
            cfg.reload_llm_settings()
        cfg.TEMPLATE_DIR = exe_dir / "templates"
        cfg.README_PATH = exe_dir / "README.md"
        cfg.CATEGORY_PAGES_DIR = exe_dir / "docs" / "papers"
        cfg.PAPERS_DIR.mkdir(exist_ok=True)

        bundled = Path(base)
        for rel in ("papers/curated_dois.txt", "papers/papers.json", "papers/state.json", "papers/translations.json",
                    "templates/email_digest.html"):
            target = exe_dir / rel
            if not target.exists() and (bundled / rel).exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bundled / rel, target)

    from genome_literature.web_app import start_server

    print("\n" + "=" * 60)
    print("  3D Genome & Deep Learning Literature Hub")
    print("  Starting web interface - your browser will open automatically.")
    print("=" * 60 + "\n")
    start_server(open_browser=True)


if __name__ == "__main__":
    main()
