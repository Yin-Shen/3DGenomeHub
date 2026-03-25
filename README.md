# 3D Genome & Deep Learning Literature Hub

> A curated, auto-updating collection of research papers at the intersection of **3D genome biology** and **deep learning / machine learning**.

![Last Updated](https://img.shields.io/badge/Last_Updated-2026--03--25-blue)
![Auto Update](https://img.shields.io/badge/Auto_Update-Weekly-brightgreen)

---

## Overview

This repository automatically tracks the latest research combining **three-dimensional genome organization** (Hi-C, chromatin conformation capture, TADs, loops, compartments) with **deep learning approaches** (CNNs, transformers, GNNs, generative models, foundation models).

**Features:**
- Automatic weekly paper fetching from **PubMed**, **bioRxiv**, and **arXiv**
- Intelligent categorization into 10 research topics
- Auto-generated README with organized paper listings
- Email digest notifications for new papers
- Full metadata including abstracts, DOIs, and direct links

## Research Categories

| Category | Description |
|----------|-------------|
| Hi-C Enhancement & Super-Resolution | Deep learning methods to enhance Hi-C contact map resolution |
| 3D Structure Prediction | Predicting 3D chromatin/chromosome structure from sequence or contact maps |
| TAD & Compartment Detection | Identifying topologically associating domains and A/B compartments |
| Chromatin Loop & Interaction Prediction | Predicting chromatin loops, enhancer-promoter interactions |
| Epigenomics & Sequence-based Prediction | Predicting epigenomic signals from DNA sequence (Akita, Enformer, etc.) |
| Single-cell 3D Genomics | Deep learning for single-cell Hi-C and 3D genome analysis |
| Multi-omics Integration | Integrating 3D genome data with other omics |
| Generative & Foundation Models | GANs, diffusion models, LLMs for genomics |
| Graph Neural Networks for Genomics | GNNs for chromatin interaction networks |
| Benchmark & Review | Benchmarks, reviews, and surveys |

## How It Works

```
PubMed API ─────┐
                 │     ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
bioRxiv API ─────┼────▶│   Fetcher    │───▶│ Categorizer │───▶│   Storage    │
                 │     └──────────────┘    └─────────────┘    └──────┬───────┘
arXiv API  ──────┘                                                   │
                                                                     ▼
                   ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
                   │ Email Digest │◀───│   Summarizer    │◀───│  README Gen  │
                   └──────────────┘    └─────────────────┘    └──────────────┘
```

### Automated Pipeline (GitHub Actions)

The workflow runs **every Monday** automatically:
1. Fetches new papers from PubMed, bioRxiv, and arXiv
2. Categorizes papers using keyword-based classification
3. Merges with existing database (deduplicating by DOI)
4. Regenerates this README with updated tables and statistics
5. Sends email digest to subscribers
6. Auto-commits and pushes changes

## Quick Start

### Option 1: Windows EXE (Easiest)

```
1. Install Python 3.9+ from https://python.org (check "Add to PATH")
2. Download this repository (Code → Download ZIP → unzip)
3. Double-click build_exe.bat
4. After build, double-click dist/3DGenomeHub.exe
5. Browser opens automatically — click buttons to use!
```

### Option 2: Run directly with Python

```bash
# Clone the repository
git clone https://github.com/Yin-Shen/3DGenomeHub.git
cd 3DGenomeHub

# Install dependencies
pip install -r requirements.txt

# Fetch papers and generate README
PYTHONPATH=src python -m genome_literature.cli fetch
PYTHONPATH=src python -m genome_literature.cli update-readme

# Or run the full pipeline (fetch + categorize + README + email)
PYTHONPATH=src python -m genome_literature.cli run-pipeline

# Search local database
PYTHONPATH=src python -m genome_literature.cli search "Hi-C deep learning"

# View statistics
PYTHONPATH=src python -m genome_literature.cli stats

# Export to CSV
PYTHONPATH=src python -m genome_literature.cli export --format csv
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `fetch` | Fetch papers from PubMed, bioRxiv, arXiv |
| `update-readme` | Regenerate README.md from paper database |
| `run-pipeline` | Run the full pipeline (fetch → README → email) |
| `stats` | Show paper database statistics |
| `search <query>` | Search papers by keyword |
| `export` | Export database to JSON or CSV |
| `send-email` | Send email digest manually |

## Email Notifications

Configure email via `.env` file (see `.env.example`):

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com
EMAIL_RECIPIENTS=user1@example.com,user2@example.com
```

## Project Structure

```
3DGenomeHub/
├── src/genome_literature/
│   ├── __init__.py          # Package init
│   ├── __main__.py          # python -m entry point
│   ├── cli.py               # Typer CLI with all commands
│   ├── config.py            # Search queries, categories, settings
│   ├── fetcher.py           # PubMed/bioRxiv/arXiv API clients
│   ├── categorizer.py       # Keyword-based paper categorization
│   ├── summarizer.py        # Digest and summary generation
│   ├── readme_generator.py  # Auto-generate README.md
│   ├── email_notifier.py    # SMTP email digest sender
│   ├── storage.py           # JSON-based paper storage
│   └── pipeline.py          # Full pipeline orchestrator
├── papers/
│   └── papers.json          # Paper database (auto-generated)
├── templates/
│   └── email_digest.html    # Jinja2 email template
├── .github/workflows/
│   └── update.yml           # Weekly auto-update workflow
├── .env.example             # Email configuration template
├── requirements.txt
└── pyproject.toml
```

## Contributing

Contributions welcome! You can help by:
- Adding new search queries to `config.py` to cover more research areas
- Improving the categorization keywords
- Suggesting new features or paper sources

## License

MIT License

---

*Auto-generated by [3DGenomeHub](https://github.com/Yin-Shen/3DGenomeHub) — this README will be automatically replaced with paper listings once the pipeline runs.*
