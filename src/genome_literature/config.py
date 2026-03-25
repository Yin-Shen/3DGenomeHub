"""Configuration for 3D Genome & Deep Learning Literature Hub."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PAPERS_DIR = PROJECT_ROOT / "papers"
PAPERS_JSON = PAPERS_DIR / "papers.json"
NEW_PAPERS_JSON = PAPERS_DIR / "new_papers.json"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
README_PATH = PROJECT_ROOT / "README.md"

# ---------------------------------------------------------------------------
# Search queries — 3D genome × deep learning / machine learning
# ---------------------------------------------------------------------------
SEARCH_QUERIES: list[dict[str, str]] = [
    # PubMed queries
    {"source": "pubmed", "query": "(3D genome OR three-dimensional genome OR chromatin architecture) AND (deep learning OR neural network)"},
    {"source": "pubmed", "query": "(Hi-C OR HiC) AND (deep learning OR convolutional neural network OR transformer)"},
    {"source": "pubmed", "query": "(chromatin loop OR TAD OR topologically associating domain) AND (deep learning OR machine learning OR graph neural network)"},
    {"source": "pubmed", "query": "(chromatin conformation OR chromosome conformation) AND (deep learning OR generative model OR diffusion model)"},
    {"source": "pubmed", "query": "(3D genome structure prediction) AND (deep learning OR neural network)"},
    {"source": "pubmed", "query": "(single-cell Hi-C OR scHi-C) AND (deep learning OR machine learning)"},
    # bioRxiv queries
    {"source": "biorxiv", "query": "3D genome deep learning"},
    {"source": "biorxiv", "query": "Hi-C deep learning"},
    {"source": "biorxiv", "query": "chromatin conformation neural network"},
    {"source": "biorxiv", "query": "TAD prediction deep learning"},
    # arXiv queries
    {"source": "arxiv", "query": "3D genome deep learning"},
    {"source": "arxiv", "query": "Hi-C neural network"},
    {"source": "arxiv", "query": "chromatin structure prediction deep learning"},
]

# Maximum results per query
MAX_RESULTS_PER_QUERY = 50

# ---------------------------------------------------------------------------
# Paper categories — for organizing the literature
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, dict] = {
    "Hi-C Enhancement & Super-Resolution": {
        "description": "Methods using deep learning to enhance Hi-C contact map resolution",
        "keywords": ["super-resolution", "enhance", "hicsr", "deephic", "hicplus", "hicnn",
                      "resolution enhancement", "upscale", "upsampling", "imputation"],
    },
    "3D Structure Prediction": {
        "description": "Predicting 3D chromatin/chromosome structure from sequence or contact maps",
        "keywords": ["3d structure", "structure prediction", "3d reconstruction",
                      "chromosome structure", "polymer model", "3d fold", "3d organization",
                      "spatial structure", "chromatin structure prediction"],
    },
    "TAD & Compartment Detection": {
        "description": "Identifying topologically associating domains and A/B compartments",
        "keywords": ["tad", "topologically associating domain", "compartment", "boundary",
                      "domain detection", "insulation", "tadpole", "deeptad", "domain boundary"],
    },
    "Chromatin Loop & Interaction Prediction": {
        "description": "Predicting chromatin loops, enhancer-promoter interactions, and contacts",
        "keywords": ["loop", "interaction prediction", "contact prediction", "enhancer-promoter",
                      "chromatin interaction", "ctcf", "cohesin", "loop extrusion",
                      "deeploop", "peakachu", "chromosight"],
    },
    "Epigenomics & Sequence-based Prediction": {
        "description": "Predicting epigenomic signals and chromatin features from DNA sequence",
        "keywords": ["sequence-based", "epigenome", "epigenomic", "dna sequence",
                      "akita", "orca", "sei", "enformer", "basenji", "sequence model",
                      "nucleotide", "variant effect"],
    },
    "Single-cell 3D Genomics": {
        "description": "Deep learning methods for single-cell Hi-C and 3D genome analysis",
        "keywords": ["single-cell", "single cell", "schic", "sc-hi-c", "scool",
                      "cell-type specific", "cell type", "imputation single cell"],
    },
    "Multi-omics Integration": {
        "description": "Integrating 3D genome data with other omics using deep learning",
        "keywords": ["multi-omics", "multiomics", "integration", "gene expression",
                      "transcription", "chip-seq", "atac-seq", "methylation",
                      "multi-modal", "multimodal"],
    },
    "Generative & Foundation Models": {
        "description": "Generative AI, foundation models, and large language models for genomics",
        "keywords": ["generative", "diffusion", "vae", "variational autoencoder", "gan",
                      "generative adversarial", "foundation model", "large language model",
                      "llm", "transformer", "gpt", "bert", "pre-trained", "pretrained"],
    },
    "Graph Neural Networks for Genomics": {
        "description": "Using GNNs to model chromatin interaction networks and 3D genome graphs",
        "keywords": ["graph neural network", "gnn", "graph convolutional", "gcn",
                      "graph attention", "gat", "network embedding", "graph-based",
                      "interaction network"],
    },
    "Benchmark & Review": {
        "description": "Benchmarks, reviews, and surveys of computational methods",
        "keywords": ["benchmark", "review", "survey", "comparison", "evaluation",
                      "comprehensive analysis", "systematic review", "meta-analysis",
                      "perspective", "overview"],
    },
}

# ---------------------------------------------------------------------------
# Email configuration (via environment variables)
# ---------------------------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS", "").split(",")
    if addr.strip()
]

# ---------------------------------------------------------------------------
# GitHub configuration (for auto-commit)
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Yin-Shen/3DGenomeHub")
