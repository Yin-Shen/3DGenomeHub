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
# Search queries — comprehensive 3D genome + deep learning / computational
# ---------------------------------------------------------------------------
SEARCH_QUERIES: list[dict[str, str]] = [
    # ===== PubMed: Core 3D genome + deep learning =====
    {"source": "pubmed", "query": "(3D genome OR three-dimensional genome OR chromatin architecture) AND (deep learning OR neural network)"},
    {"source": "pubmed", "query": "(Hi-C OR HiC) AND (deep learning OR convolutional neural network OR transformer)"},
    {"source": "pubmed", "query": "(chromatin loop OR TAD OR topologically associating domain) AND (deep learning OR machine learning OR graph neural network)"},
    {"source": "pubmed", "query": "(chromatin conformation OR chromosome conformation) AND (deep learning OR generative model OR diffusion model)"},
    {"source": "pubmed", "query": "(3D genome structure prediction) AND (deep learning OR neural network)"},
    {"source": "pubmed", "query": "(single-cell Hi-C OR scHi-C) AND (deep learning OR machine learning)"},

    # ===== PubMed: 3D genome experimental methods =====
    {"source": "pubmed", "query": "(Hi-C OR Micro-C OR HiChIP OR PLAC-seq) AND (computational OR algorithm OR method)"},
    {"source": "pubmed", "query": "(Capture-C OR Capture Hi-C OR promoter capture) AND (genome organization OR chromatin)"},
    {"source": "pubmed", "query": "(4C-seq OR 5C OR chromosome conformation capture) AND (computational OR analysis pipeline)"},
    {"source": "pubmed", "query": "(SPRITE OR GAM OR genome architecture mapping) AND (3D genome OR chromatin)"},
    {"source": "pubmed", "query": "(ChIA-PET OR ChIA-Drop) AND (chromatin interaction OR 3D genome)"},
    {"source": "pubmed", "query": "(DNA-FISH OR chromatin tracing OR ORCA imaging) AND (3D genome OR chromosome)"},
    {"source": "pubmed", "query": "(DamID OR TRIP OR TSA-seq OR nuclear speckle) AND (genome organization)"},
    {"source": "pubmed", "query": "(Pore-C OR concatemer) AND (chromatin OR genome structure)"},
    {"source": "pubmed", "query": "(CUT&RUN OR CUT&Tag) AND (3D genome OR chromatin architecture)"},

    # ===== PubMed: Nuclear organization & structure =====
    {"source": "pubmed", "query": "(nuclear organization OR nuclear architecture) AND (deep learning OR computational)"},
    {"source": "pubmed", "query": "(lamina-associated domain OR LAD) AND (genome organization OR computational)"},
    {"source": "pubmed", "query": "(nuclear speckle OR nuclear body OR nucleolus) AND (genome organization)"},
    {"source": "pubmed", "query": "(phase separation OR liquid-liquid phase) AND (chromatin OR 3D genome)"},
    {"source": "pubmed", "query": "(CTCF OR cohesin OR loop extrusion) AND (computational OR modeling OR deep learning)"},
    {"source": "pubmed", "query": "(polymer model OR polymer simulation) AND (chromatin OR chromosome OR 3D genome)"},

    # ===== PubMed: Broader computational genomics =====
    {"source": "pubmed", "query": "(enhancer-promoter interaction) AND (prediction OR deep learning OR machine learning)"},
    {"source": "pubmed", "query": "(chromatin accessibility OR ATAC-seq) AND (3D genome OR Hi-C) AND computational"},
    {"source": "pubmed", "query": "(genome folding OR chromosome folding) AND (prediction OR deep learning)"},
    {"source": "pubmed", "query": "(contact map OR contact matrix) AND (deep learning OR neural network)"},
    {"source": "pubmed", "query": "(topological domain OR chromatin domain) AND (prediction OR classification OR deep learning)"},
    {"source": "pubmed", "query": "(Hi-C normalization OR Hi-C bias) AND (method OR algorithm OR computational)"},
    {"source": "pubmed", "query": "(3D genome browser OR genome visualization) AND (Hi-C OR chromatin)"},

    # ===== PubMed: Disease & evolution =====
    {"source": "pubmed", "query": "(3D genome OR chromatin architecture) AND (disease OR cancer OR disorder) AND computational"},
    {"source": "pubmed", "query": "(structural variant OR translocation) AND (3D genome OR Hi-C OR TAD)"},
    {"source": "pubmed", "query": "(3D genome OR chromatin conformation) AND (evolution OR conservation OR comparative)"},

    # ===== bioRxiv queries =====
    {"source": "biorxiv", "query": "3D genome deep learning"},
    {"source": "biorxiv", "query": "Hi-C deep learning"},
    {"source": "biorxiv", "query": "chromatin conformation neural network"},
    {"source": "biorxiv", "query": "TAD prediction deep learning"},
    {"source": "biorxiv", "query": "Hi-C computational method"},
    {"source": "biorxiv", "query": "chromatin loop prediction"},
    {"source": "biorxiv", "query": "genome structure prediction"},
    {"source": "biorxiv", "query": "single-cell Hi-C analysis"},
    {"source": "biorxiv", "query": "Micro-C chromatin"},
    {"source": "biorxiv", "query": "nuclear organization computational"},

    # ===== arXiv queries =====
    {"source": "arxiv", "query": "3D genome deep learning"},
    {"source": "arxiv", "query": "Hi-C neural network"},
    {"source": "arxiv", "query": "chromatin structure prediction deep learning"},
    {"source": "arxiv", "query": "genome folding convolutional network"},
    {"source": "arxiv", "query": "chromatin contact map prediction"},
    {"source": "arxiv", "query": "graph neural network genomics chromatin"},

    # ===== Semantic Scholar queries =====
    {"source": "semantic_scholar", "query": "3D genome deep learning"},
    {"source": "semantic_scholar", "query": "Hi-C super resolution deep learning"},
    {"source": "semantic_scholar", "query": "chromatin loop prediction neural network"},
    {"source": "semantic_scholar", "query": "TAD boundary prediction machine learning"},
    {"source": "semantic_scholar", "query": "single cell Hi-C computational"},
    {"source": "semantic_scholar", "query": "Akita Enformer genome folding"},
    {"source": "semantic_scholar", "query": "chromatin conformation capture computational methods"},
    {"source": "semantic_scholar", "query": "3D genome structure prediction polymer model"},
    {"source": "semantic_scholar", "query": "nuclear organization imaging computational"},
    {"source": "semantic_scholar", "query": "CTCF cohesin loop extrusion modeling"},

    # ===== Europe PMC queries =====
    {"source": "europepmc", "query": "(3D genome OR three-dimensional genome) AND (deep learning OR neural network)"},
    {"source": "europepmc", "query": "(Hi-C OR HiChIP OR Micro-C) AND (deep learning OR computational method)"},
    {"source": "europepmc", "query": "(chromatin architecture OR nuclear organization) AND (machine learning OR algorithm)"},
    {"source": "europepmc", "query": "(TAD OR chromatin loop OR compartment) AND (prediction OR detection) AND computational"},
    {"source": "europepmc", "query": "(chromosome conformation capture) AND (tool OR software OR pipeline)"},

    # ===== CrossRef queries =====
    {"source": "crossref", "query": "3D genome deep learning"},
    {"source": "crossref", "query": "Hi-C computational method"},
    {"source": "crossref", "query": "chromatin architecture machine learning"},
    {"source": "crossref", "query": "chromosome conformation capture tools"},
]

# Maximum results per query
MAX_RESULTS_PER_QUERY = 50

# ---------------------------------------------------------------------------
# Paper categories — comprehensive 3D genome research topics
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, dict] = {
    "Hi-C Enhancement & Super-Resolution": {
        "description": "Methods using deep learning to enhance Hi-C contact map resolution",
        "keywords": ["super-resolution", "enhance", "hicsr", "deephic", "hicplus", "hicnn",
                      "resolution enhancement", "upscale", "upsampling", "imputation",
                      "hi-c enhancement", "contact map enhancement", "low-resolution"],
    },
    "3D Structure Prediction": {
        "description": "Predicting 3D chromatin/chromosome structure from sequence or contact maps",
        "keywords": ["3d structure", "structure prediction", "3d reconstruction",
                      "chromosome structure", "3d fold", "3d organization",
                      "spatial structure", "chromatin structure prediction",
                      "3d model", "chromosome model", "genome structure"],
    },
    "TAD & Compartment Detection": {
        "description": "Identifying topologically associating domains, sub-TADs, and A/B compartments",
        "keywords": ["tad", "topologically associating domain", "compartment", "boundary",
                      "domain detection", "insulation", "tadpole", "deeptad", "domain boundary",
                      "sub-tad", "a/b compartment", "compartmentalization", "insulation score",
                      "arrowhead", "topdom", "hicexplorer"],
    },
    "Chromatin Loop & Interaction Prediction": {
        "description": "Predicting chromatin loops, enhancer-promoter interactions, and contacts",
        "keywords": ["chromatin loop", "interaction prediction", "contact prediction", "enhancer-promoter",
                      "chromatin interaction", "loop extrusion", "loop detection",
                      "deeploop", "peakachu", "chromosight", "hiccups", "mustache",
                      "significant interaction", "peak calling"],
    },
    "CTCF, Cohesin & Loop Extrusion": {
        "description": "CTCF binding, cohesin dynamics, and loop extrusion mechanisms",
        "keywords": ["ctcf", "cohesin", "loop extrusion", "smc complex", "wapl", "nipbl",
                      "convergent ctcf", "ctcf binding", "ctcf motif", "extrusion barrier",
                      "cohesin loading", "cohesin release", "topological insulator"],
    },
    "Epigenomics & Sequence-based Prediction": {
        "description": "Predicting epigenomic signals and chromatin features from DNA sequence",
        "keywords": ["sequence-based", "epigenome", "epigenomic", "dna sequence",
                      "akita", "orca", "sei", "enformer", "basenji", "sequence model",
                      "nucleotide", "variant effect", "from sequence",
                      "sequence-to-function", "genomic sequence"],
    },
    "Single-cell 3D Genomics": {
        "description": "Deep learning methods for single-cell Hi-C and 3D genome analysis",
        "keywords": ["single-cell", "single cell", "schic", "sc-hi-c", "scool",
                      "cell-type specific", "cell type", "imputation single cell",
                      "single-cell hi-c", "dip-c", "single-cell 3d", "cell-to-cell variability",
                      "single cell chromatin"],
    },
    "Multi-omics Integration": {
        "description": "Integrating 3D genome data with other omics using deep learning",
        "keywords": ["multi-omics", "multiomics", "integration", "gene expression",
                      "transcription", "chip-seq", "atac-seq", "methylation",
                      "multi-modal", "multimodal", "joint analysis",
                      "epigenome integration", "transcriptome"],
    },
    "Generative & Foundation Models": {
        "description": "Generative AI, foundation models, and large language models for genomics",
        "keywords": ["generative", "diffusion", "vae", "variational autoencoder", "gan",
                      "generative adversarial", "foundation model", "large language model",
                      "llm", "transformer", "gpt", "bert", "pre-trained", "pretrained",
                      "genomic language model", "dna language model"],
    },
    "Graph Neural Networks for Genomics": {
        "description": "Using GNNs to model chromatin interaction networks and 3D genome graphs",
        "keywords": ["graph neural network", "gnn", "graph convolutional", "gcn",
                      "graph attention", "gat", "network embedding", "graph-based",
                      "interaction network", "chromatin graph", "genome graph"],
    },
    "Experimental Methods & Technologies": {
        "description": "3C/4C/5C/Hi-C/Micro-C/HiChIP and other chromosome conformation capture technologies",
        "keywords": ["hi-c", "micro-c", "hichip", "plac-seq", "capture-c", "capture hi-c",
                      "4c-seq", "5c", "3c", "chromosome conformation capture",
                      "chia-pet", "chia-drop", "sprite", "gam", "genome architecture mapping",
                      "pore-c", "concatemer", "dna-fish", "chromatin tracing",
                      "cut&run", "cut&tag", "damid", "tsa-seq"],
    },
    "Nuclear Organization & Architecture": {
        "description": "Nuclear structure, lamina-associated domains, nuclear bodies, and phase separation",
        "keywords": ["nuclear organization", "nuclear architecture", "nuclear body",
                      "nuclear speckle", "nucleolus", "nuclear lamina",
                      "lamina-associated domain", "lad", "nuclear envelope",
                      "chromosome territory", "nuclear compartment",
                      "nuclear pore", "radial position"],
    },
    "Phase Separation & Chromatin": {
        "description": "Liquid-liquid phase separation and its role in chromatin organization",
        "keywords": ["phase separation", "liquid-liquid phase", "condensate",
                      "biomolecular condensate", "intrinsically disordered",
                      "droplet", "phase-separated", "membraneless organelle"],
    },
    "Polymer Modeling & Simulation": {
        "description": "Polymer physics models and molecular dynamics simulations of chromatin",
        "keywords": ["polymer model", "polymer simulation", "molecular dynamics",
                      "coarse-grained", "bead-spring", "monte carlo",
                      "chromatin fiber", "chromosome simulation", "polymer physics",
                      "string and binders", "block copolymer", "energy landscape"],
    },
    "Data Processing & Normalization": {
        "description": "Tools for Hi-C data processing, normalization, and quality control",
        "keywords": ["normalization", "bias correction", "ice normalization",
                      "knight-ruiz", "matrix balancing", "data processing",
                      "quality control", "mapping", "alignment", "binning",
                      "juicer", "cooler", "hic-pro", "distiller", "pairtools",
                      "valid pairs", "contact matrix"],
    },
    "Visualization & Browsers": {
        "description": "Genome browsers and visualization tools for 3D genome data",
        "keywords": ["visualization", "genome browser", "3d genome browser",
                      "higlass", "juicebox", "washu", "3d-genome browser",
                      "contact map visualization", "heatmap", "arc plot",
                      "virtual 4c", "genome viewer"],
    },
    "Disease & Clinical Applications": {
        "description": "3D genome alterations in disease, cancer, and developmental disorders",
        "keywords": ["disease", "cancer", "disorder", "clinical", "pathogenic",
                      "oncogene", "tumor", "patient", "therapeutic",
                      "structural variant", "translocation", "deletion",
                      "tad disruption", "enhancer hijacking", "ectopic contact",
                      "congenital", "developmental disorder"],
    },
    "Evolution & Conservation": {
        "description": "Evolutionary conservation and divergence of 3D genome organization",
        "keywords": ["evolution", "conservation", "conserved", "divergence",
                      "comparative", "synteny", "ortholog", "phylogenetic",
                      "cross-species", "evolutionary constraint"],
    },
    "Benchmark & Review": {
        "description": "Benchmarks, reviews, and surveys of computational methods",
        "keywords": ["benchmark", "review", "survey", "comparison", "evaluation",
                      "comprehensive analysis", "systematic review", "meta-analysis",
                      "perspective", "overview", "tutorial", "guideline", "best practice",
                      "protocol"],
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
