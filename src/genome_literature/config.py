"""Configuration for 3D Genome & Deep Learning Literature Hub.

Everything that controls *what* is fetched and *how* papers are judged lives
here: search topics, relevance vocabularies, research categories, per-source
limits and credentials.  Term dictionaries map a term to a weight; see
``matching.compile_term`` for the matching rules (word boundaries, acronyms
are case-sensitive, ``re:`` prefix for raw regular expressions).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PAPERS_DIR = PROJECT_ROOT / "papers"
PAPERS_JSON = PAPERS_DIR / "papers.json"
NEW_PAPERS_JSON = PAPERS_DIR / "new_papers.json"
STATE_JSON = PAPERS_DIR / "state.json"
TRANSLATIONS_JSON = PAPERS_DIR / "translations.json"
AI_NOTES_DIR = PROJECT_ROOT / "ai_notes"
CACHE_DIR = PROJECT_ROOT / ".cache"
FULLTEXT_CACHE_DIR = CACHE_DIR / "fulltext"
ENV_FILE = PROJECT_ROOT / ".env"
CURATED_DOIS_FILE = PAPERS_DIR / "curated_dois.txt"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
README_PATH = PROJECT_ROOT / "README.md"
CATEGORY_PAGES_DIR = PROJECT_ROOT / "docs" / "papers"

REPO_URL = "https://github.com/Yin-Shen/3DGenomeHub"

# ---------------------------------------------------------------------------
# Credentials / politeness settings (all optional)
# ---------------------------------------------------------------------------
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", NCBI_EMAIL)

ALL_SOURCES = ["pubmed", "europepmc", "biorxiv", "arxiv", "semantic_scholar", "crossref"]
ENABLED_SOURCES = [
    s.strip() for s in os.getenv("GENOME_HUB_SOURCES", ",".join(ALL_SOURCES)).split(",") if s.strip()
]

# ---------------------------------------------------------------------------
# Fetch limits
# ---------------------------------------------------------------------------
MAX_RESULTS_PER_QUERY: dict[str, int] = {
    "pubmed": 200,
    "europepmc": 200,
    "arxiv": 100,
    "semantic_scholar": 100,
    "crossref": 40,
}
BACKFILL_MAX_RESULTS_PER_QUERY: dict[str, int] = {
    "pubmed": 1000,
    "europepmc": 1000,
    "arxiv": 200,
    "semantic_scholar": 100,
    "crossref": 60,
}
INCREMENTAL_OVERLAP_DAYS = 7
DEFAULT_LOOKBACK_DAYS = 30
MAX_INCREMENTAL_LOOKBACK_DAYS = 120
BIORXIV_BACKFILL_DAYS = 90
BIORXIV_MAX_RECORDS = 20000
BIORXIV_CATEGORIES = {
    "bioinformatics", "genomics", "genetics", "molecular biology", "cell biology",
    "biophysics", "systems biology", "synthetic biology", "developmental biology",
    "cancer biology", "evolutionary biology", "biochemistry",
}

SOURCE_FAILURE_LIMIT = 2

HTTP_TIMEOUT = 45.0
HTTP_MAX_RETRIES = 4
HOST_MIN_INTERVAL: dict[str, float] = {
    "eutils.ncbi.nlm.nih.gov": 0.12 if NCBI_API_KEY else 0.4,
    "www.ebi.ac.uk": 0.2,
    "export.arxiv.org": 3.1,
    "api.biorxiv.org": 0.5,
    "api.semanticscholar.org": 1.1 if SEMANTIC_SCHOLAR_API_KEY else 3.0,
    "api.crossref.org": 0.3,
}

# ---------------------------------------------------------------------------
# Search topics.  Each topic is a list of term groups: terms inside a group
# are OR-ed, groups are AND-ed.  The fetcher translates the groups into each
# database's own syntax (PubMed [tiab], Europe PMC TITLE/ABSTRACT, arXiv
# ti/abs).  ``plain`` holds free-text queries for relevance-ranked engines
# (Semantic Scholar, CrossRef) that have no boolean field search.
# ---------------------------------------------------------------------------
G_CORE = [
    "3D genome", "three-dimensional genome", "3D chromatin", "chromatin conformation",
    "chromosome conformation capture", "Hi-C", "Micro-C", "HiChIP", "chromatin loop",
    "topologically associating domain", "chromatin architecture", "genome folding",
    "chromatin interaction", "chromatin contact", "enhancer-promoter interaction",
]
M_DL = [
    "deep learning", "neural network", "machine learning", "transformer", "convolutional",
    "graph neural network", "generative model", "diffusion model", "language model",
    "foundation model", "autoencoder", "artificial intelligence", "attention mechanism",
]
M_COMP = [
    "computational", "algorithm", "software", "tool", "toolkit", "pipeline", "framework",
    "statistical", "bioinformatics", "package", "web server",
]

SEARCH_TOPICS: list[dict] = [
    {
        "name": "3D genome x deep learning",
        "groups": [G_CORE, M_DL],
        "plain": [
            "3D genome deep learning", "Hi-C deep learning", "chromatin conformation neural network",
            "Hi-C transformer model", "chromatin interaction prediction deep learning",
        ],
    },
    {
        "name": "Hi-C enhancement & imputation",
        "groups": [
            ["Hi-C", "Micro-C", "contact map", "contact matrix", "single-cell Hi-C", "scHi-C"],
            ["super-resolution", "resolution enhancement", "imputation", "denoising", "enhancing",
             "upsampling", "low-resolution"],
        ],
        "plain": ["Hi-C super-resolution deep learning", "Hi-C contact map enhancement", "single-cell Hi-C imputation"],
    },
    {
        "name": "Sequence-to-3D prediction",
        "groups": [
            ["genome folding", "3D genome", "chromatin contact", "contact map", "Hi-C",
             "chromatin interaction", "chromatin organization", "chromatin conformation"],
            ["DNA sequence", "sequence-based", "from sequence", "in silico mutagenesis",
             "variant effect", "sequence model"],
        ],
        "plain": ["predicting 3D genome folding from DNA sequence", "sequence-based prediction of chromatin contacts"],
    },
    {
        "name": "TAD & compartment calling",
        "groups": [
            ["topologically associating domain", "topologically associated domain", "topological domain",
             "TAD boundary", "TAD calling", "A/B compartment", "chromatin compartment", "domain boundary"],
            M_COMP + M_DL + ["prediction", "detection", "identification", "calling"],
        ],
        "plain": ["TAD boundary prediction machine learning", "TAD calling algorithm Hi-C"],
    },
    {
        "name": "Loops & chromatin interactions",
        "groups": [
            ["chromatin loop", "chromatin looping", "looping chromatin", "loop calling", "loop detection",
             "chromatin interaction", "enhancer-promoter interaction", "enhancer-promoter contact",
             "promoter-enhancer interaction"],
            M_COMP + M_DL + ["prediction", "detection"],
        ],
        "plain": ["chromatin loop detection deep learning", "enhancer-promoter interaction prediction deep learning"],
    },
    {
        "name": "Single-cell 3D genome",
        "groups": [
            ["single-cell Hi-C", "scHi-C", "single-nucleus Hi-C", "Dip-C", "sn-m3C-seq",
             "single-cell 3D genome", "single-cell chromatin conformation"],
        ],
        "plain": ["single-cell Hi-C computational analysis", "single-cell 3D genome embedding"],
    },
    {
        "name": "3D structure modeling",
        "groups": [
            ["3D genome structure", "chromosome structure", "3D chromatin structure", "genome structure",
             "chromatin structure", "3D chromosome"],
            ["reconstruction", "polymer model", "polymer simulation", "molecular dynamics",
             "structure modeling", "3D modeling", "structure inference"],
        ],
        "plain": ["3D chromosome structure reconstruction Hi-C", "chromatin polymer model simulation Hi-C"],
    },
    {
        "name": "Loop extrusion modeling",
        "groups": [
            ["loop extrusion", "CTCF", "cohesin"],
            ["model", "simulation", "prediction", "deep learning", "machine learning", "computational"],
            ["chromatin", "genome", "Hi-C", "TAD"],
        ],
        "plain": ["loop extrusion model simulation Hi-C"],
    },
    {
        "name": "Graph & multi-omics methods",
        "groups": [
            G_CORE,
            ["graph", "hypergraph", "multi-omics", "multiomics", "integrative", "multimodal", "embedding"],
        ],
        "plain": ["graph neural network Hi-C", "multi-omics integration 3D genome"],
    },
    {
        "name": "Imaging-based 3D genome",
        "groups": [
            ["chromatin tracing", "chromosome tracing", "ORCA", "multiplexed DNA FISH", "DNA seqFISH",
             "Hi-M", "MERFISH chromatin"],
        ],
        "plain": ["chromatin tracing imaging 3D genome"],
    },
    {
        "name": "Tools & resources",
        "groups": [
            ["Hi-C", "Micro-C", "HiChIP", "3D genome", "chromatin conformation capture"],
            ["software", "toolkit", "pipeline", "database", "genome browser", "visualization",
             "normalization", "web server", "package", "benchmark"],
        ],
        "plain": ["Hi-C data analysis software", "Hi-C normalization benchmark"],
    },
    {
        "name": "3D genome in disease",
        "groups": [
            G_CORE,
            ["disease", "cancer", "structural variant", "enhancer hijacking", "GWAS", "non-coding variant"],
            M_COMP + M_DL + ["prediction"],
        ],
        "plain": ["3D genome structural variants cancer computational"],
    },
]

# ---------------------------------------------------------------------------
# Relevance vocabularies
# ---------------------------------------------------------------------------
# A paper enters the database only if it mentions at least one *core* 3D
# genome term and (core + context - negative) reaches MIN_GENOME_SCORE.
# Title hits count double.
MIN_GENOME_SCORE = 6.0

GENOME_CORE_TERMS: dict[str, float] = {
    "3D genome": 3, "3D genomic": 3, "three-dimensional genome": 3, "three-dimensional genomic": 3,
    "3D chromatin": 3, "three-dimensional chromatin": 3, "3D chromosome": 3,
    "chromatin conformation": 3, "chromosome conformation": 3,
    "re:(?<![A-Za-z0-9])(?:Hi-?C|HI-C|hi-c)s?(?![A-Za-z0-9])": 3,
    "Micro-C": 3, "HiChIP": 3, "PLAC-seq": 3, "ChIA-PET": 3, "ChIA-Drop": 3,
    "Capture-C": 3, "4C-seq": 3, "Pore-C": 3, "SPRITE": 2, "genome architecture mapping": 3,
    "Dip-C": 3, "re:(?<![A-Za-z0-9])sc-?Hi-?C": 3, "sn-m3C-seq": 3, "snm3C-seq": 3,
    "topologically associating domain": 3, "topologically associated domain": 3, "topological domain": 3,
    "TAD": 2, "looping chromatin": 3,
    "chromatin loop": 3, "chromatin looping": 3, "CTCF loop": 3, "loop extrusion": 3,
    "A/B compartment": 3, "chromatin compartment": 3,
    "genome folding": 3, "chromatin folding": 3, "chromosome folding": 3,
    "chromatin architecture": 3, "chromatin contact": 3, "contact map": 2, "contact matrix": 2,
    "contact matrices": 2, "chromatin interaction": 3,
    "enhancer-promoter interaction": 3, "enhancer-promoter contact": 3, "enhancer-promoter loop": 3,
    "promoter-enhancer interaction": 3, "E-P interaction": 3,
    "chromatin tracing": 3, "chromosome tracing": 3, "chromosome territory": 3, "chromosome territories": 3,
    "lamina-associated domain": 3, "insulation score": 3, "4D nucleome": 3, "nucleome": 3,
    "spatial genome organization": 3,
    "re:(?i)(?:3D|three-dimensional|spatial|higher-order)\\s+(?:organi[sz]ation|architecture|structure|folding)\\s+of\\s+(?:the\\s+)?(?:genome|chromatin|chromosomes?)": 3,
}

GENOME_CONTEXT_TERMS: dict[str, float] = {
    "genome organization": 2, "genome organisation": 2, "chromatin organization": 2,
    "chromatin organisation": 2, "nuclear organization": 1.5, "nuclear architecture": 1.5,
    "genome architecture": 1.5, "chromatin structure": 1.5, "chromosome structure": 1.5,
    "long-range interaction": 1.5, "long-range regulation": 1, "long-range regulatory": 1.5,
    "DNA loop": 1, "DNA looping": 1, "higher-order chromatin": 2, "higher-order structure": 1,
    "chromatin domain": 1.5, "chromatin nanodomain": 2, "3D regulatory": 2, "enhancer-gene": 1,
    "CTCF": 2, "cohesin": 1.5, "condensin": 1, "insulator": 1, "domain boundary": 1.5,
    "compartmentalization": 1, "LAD": 1, "nuclear lamina": 1.5, "nuclear speckle": 1,
    "phase separation": 0.5, "polymer model": 1.5, "polymer simulation": 1.5,
    "spatial proximity": 1, "3C": 1, "5C": 1, "GAM": 0.5, "ORCA": 1,
    "chromatin": 0.5, "chromosome": 0.5, "enhancer": 0.5, "nucleosome": 0.5,
}

NEGATIVE_TERMS: dict[str, float] = {
    "genome assembly": 4, "chromosome-level": 4, "chromosome-scale": 4, "chromosome level genome": 4,
    "haplotype-resolved": 3, "scaffolding": 3, "de novo assembly": 3, "reference genome": 1.5,
    "re:(?i)metagenom\\w*": 3, "re:(?i)\\bviromes?\\b": 2,
    "transactivation domain": 4, "transactivation": 2, "trans-activation domain": 4,
    "protein structure prediction": 4, "protein folding": 3, "protein contact": 4,
    "residue contact": 3, "amino acid": 1.5, "hydrophobic interaction chromatography": 5,
    "re:3C-?like|3CL(?:pro)?": 3, "left anterior descending": 5, "coronary": 3,
    "RNA-chromatin interaction": 4, "RNA-chromatin interactome": 4, "virus-host": 4, "host-virus": 4,
    "synthetic community": 3, "microbial community": 3,
}

EXCLUDE_TITLE_PATTERN = (
    "re:(?i)^\\s*(?:correction|erratum|corrigendum|retraction|retracted|author correction|"
    "publisher correction|expression of concern|reply to|response to|comment on)\\b"
)

DL_TERMS: dict[str, float] = {
    "deep learning": 3, "deep-learning": 3, "deep neural network": 3, "neural network": 3,
    "convolutional": 3, "CNN": 3, "transformer": 3, "self-attention": 3, "attention mechanism": 3,
    "attention-based": 2, "graph neural network": 3, "GNN": 3, "graph convolutional": 3,
    "graph attention": 3, "generative adversarial": 3, "GAN": 3, "diffusion model": 3,
    "denoising diffusion": 3, "autoencoder": 3, "auto-encoder": 3, "VAE": 3, "U-Net": 3,
    "ResNet": 3, "LSTM": 3, "long short-term memory": 3, "recurrent neural": 3, "RNN": 3,
    "language model": 3, "large language model": 3, "LLM": 3, "foundation model": 3,
    "contrastive learning": 3, "self-supervised": 3, "transfer learning": 3, "representation learning": 2,
    "pre-trained": 2, "pretrained": 2, "pre-training": 2, "pretraining": 2, "BERT": 2, "GPT": 2,
    "multilayer perceptron": 2, "MLP": 1, "few-shot": 2, "zero-shot": 2,
}

ML_TERMS: dict[str, float] = {
    "machine learning": 2, "machine-learning": 2, "random forest": 2, "gradient boosting": 2,
    "XGBoost": 2, "LightGBM": 2, "support vector machine": 2, "SVM": 2, "supervised learning": 2,
    "unsupervised learning": 2, "reinforcement learning": 2, "artificial intelligence": 2,
    "AI": 1, "logistic regression": 1, "classifier": 1, "embedding": 1, "latent space": 1,
}

COMPUTATIONAL_TERMS: dict[str, float] = {
    "algorithm": 2, "computational": 2, "software": 2, "toolkit": 2, "tool": 1, "pipeline": 1,
    "package": 1, "web server": 2, "database": 1, "framework": 1, "statistical": 1,
    "probabilistic": 1, "Bayesian": 1, "simulation": 1, "polymer model": 2, "in silico": 1,
    "benchmark": 1, "open-source": 2, "open source": 2, "re:(?i)github\\.com|bitbucket|zenodo|pypi|bioconductor": 2,
    "re:(?i)\\bwe (?:develop|present|introduce|propose|describe)\\w*": 1, "method": 0.5,
}

TRACKS: dict[str, str] = {
    "ml": "AI / ML",
    "computational": "Computational",
    "experimental": "Experimental & Biology",
}

# Deep-learning architecture families: label -> terms
DL_METHODS: dict[str, list[str]] = {
    "CNN": ["CNN", "convolutional neural network", "convolutional network", "convolutional layer",
            "ResNet", "U-Net", "dilated convolution"],
    "Transformer / Attention": ["transformer", "self-attention", "multi-head attention",
                                "attention mechanism", "attention-based", "vision transformer", "ViT"],
    "GNN": ["graph neural network", "GNN", "graph convolutional", "GCN", "graph attention", "GAT",
            "message passing", "graph transformer", "hypergraph neural network"],
    "GAN": ["generative adversarial", "GAN", "WGAN", "CycleGAN", "adversarial training"],
    "Autoencoder / VAE": ["autoencoder", "auto-encoder", "VAE", "variational autoencoder",
                          "encoder-decoder"],
    "Diffusion Model": ["diffusion model", "denoising diffusion", "DDPM", "score-based generative",
                        "latent diffusion"],
    "RNN / LSTM": ["recurrent neural network", "RNN", "LSTM", "long short-term memory", "GRU",
                   "BiLSTM", "Bi-LSTM"],
    "Language / Foundation Model": ["foundation model", "large language model", "LLM", "language model",
                                    "BERT", "GPT", "DNABERT", "nucleotide transformer", "HyenaDNA"],
    "Contrastive / Self-supervised": ["contrastive learning", "self-supervised", "siamese network",
                                      "triplet loss", "masked modeling"],
    "Transfer Learning": ["transfer learning", "domain adaptation", "fine-tuning", "fine-tuned",
                          "pre-trained", "pretrained"],
    "Tree Ensembles": ["random forest", "XGBoost", "gradient boosting", "LightGBM", "decision tree"],
    "Classical ML": ["support vector machine", "SVM", "logistic regression", "naive Bayes",
                     "k-nearest neighbor", "hidden Markov model", "HMM"],
    "Reinforcement Learning": ["reinforcement learning", "policy gradient", "Q-learning"],
}

# Named 3D-genome tools / models: label -> terms
GENOME_TOOLS: dict[str, list[str]] = {
    "Akita": ["Akita"],
    "Orca": ["re:\\bOrca\\b"],
    "C.Origami": ["re:C\\.\\s?Origami"],
    "DeepC": ["re:\\bDeepC\\b"],
    "ChromaFold": ["ChromaFold"],
    "EPCOT": ["EPCOT"],
    "Enformer": ["Enformer"],
    "Borzoi": ["Borzoi"],
    "Basenji": ["Basenji"],
    "HiCPlus": ["HiCPlus", "HiC-Plus"],
    "HiCNN": ["HiCNN"],
    "DeepHiC": ["DeepHiC"],
    "hicGAN": ["hicGAN"],
    "HiCSR": ["HiCSR"],
    "HiCARN": ["HiCARN"],
    "HiCDiff": ["HiCDiff", "HiCDiffusion"],
    "Higashi": ["Higashi"],
    "scHiCluster": ["scHiCluster"],
    "Peakachu": ["Peakachu"],
    "DeepLoop": ["DeepLoop"],
    "Mustache": ["re:\\bMustache\\b"],
    "Chromosight": ["Chromosight"],
    "HiCCUPS": ["re:\\bHiCCUPS\\b"],
    "Fit-Hi-C": ["re:\\bFit-?Hi-?C\\d?\\b"],
    "Juicer": ["re:\\bJuicer(?:box)?\\b"],
    "HiC-Pro": ["HiC-Pro"],
    "cooler": ["re:\\bcooler\\b"],
    "HiCExplorer": ["HiCExplorer"],
    "HiGlass": ["HiGlass"],
    "HiCRep": ["HiCRep"],
    "Dip-C": ["Dip-C"],
}

# ---------------------------------------------------------------------------
# Research categories.  A paper gets up to MAX_CATEGORIES_PER_PAPER labels:
# those whose score reaches MIN_CATEGORY_SCORE and at least
# CATEGORY_RELATIVE_CUTOFF x the best category's score.
# ---------------------------------------------------------------------------
MAX_CATEGORIES_PER_PAPER = 3
MIN_CATEGORY_SCORE = 2.0
CATEGORY_RELATIVE_CUTOFF = 0.34
FALLBACK_CATEGORY = "Other 3D Genome"

CATEGORIES: dict[str, dict] = {
    "Hi-C Enhancement & Super-Resolution": {
        "description": "Enhancing, denoising and imputing sparse or low-resolution Hi-C / Micro-C contact maps",
        "terms": {
            "re:(?i)super-?resolution(?!\\s+(?:imaging|microscop\\w*|fluorescence|optical|STORM|PALM|chromatin imaging))": 3,
            "resolution enhancement": 3, "Hi-C enhancement": 3, "fine-resolution": 2, "high-resolution Hi-C": 2,
            "re:(?i)(?:denois\\w*|imput\\w*|enhanc\\w*|upsampl\\w*|super-?resolution|refin\\w*)\\s+(?:[\\w-]+\\s+){0,5}?(?:Hi-?C|contact\\s+(?:maps?|matri\\w+))": 3,
            "re:(?i)(?:Hi-?C|contact\\s+(?:maps?|matri\\w+))\\s+(?:[\\w-]+\\s+){0,2}(?:denois\\w*|imput\\w*|enhancement|upsampl\\w*|super-?resolution)": 3,
            "re:(?i)enhanc\\w*\\s+(?:the\\s+)?(?:(?:spatial\\s+)?resolution|(?:sparse\\s+|low[\\s-]resolution\\s+)?Hi-?C|contact\\s+maps?)": 3,
            "low-resolution": 1, "imputation": 1.5, "impute": 1.5, "imputing": 1.5, "denoising": 1.5, "denoise": 1.5,
            "upsampling": 2, "downsampled": 1, "sequencing depth": 1, "low-coverage": 1, "sparsity": 1,
            "HiCPlus": 4, "HiCNN": 4, "DeepHiC": 4, "hicGAN": 4, "HiCSR": 4, "HiCARN": 4,
            "re:VEHiCLE": 4, "HiCDiff": 4, "HiCDiffusion": 4, "SRHiC": 4, "Higashi": 1,
        },
    },
    "3D Structure Prediction": {
        "description": "Reconstructing 3D chromosome / genome structures and structural ensembles",
        "terms": {
            "3D structure": 1, "3D structures": 1, "3D reconstruction": 3, "structure reconstruction": 3,
            "re:(?i)reconstruct\\w*\\s+(?:the\\s+)?(?:3D|three-dimensional)": 3,
            "3D genome structure": 3, "3D chromosome structure": 3, "3D chromatin structure": 3,
            "3D model": 1.5, "3D modeling": 1.5, "3D modelling": 1.5, "structural ensemble": 3,
            "ensemble of structures": 3, "structure inference": 3, "spatial coordinates": 2,
            "multidimensional scaling": 2, "chromosome structure": 1, "genome structure": 1,
            "Pastis": 3, "ShRec3D": 3, "Chromosome3D": 3, "3DMax": 3, "LorDG": 3,
        },
    },
    "TAD & Compartment Detection": {
        "description": "Calling and predicting TADs, sub-TADs, domain boundaries and A/B (sub)compartments",
        "terms": {
            "TAD": 1.5, "topologically associating domain": 1.5, "topologically associated domain": 1.5,
            "topological domain": 1.5,
            "TAD boundary": 3, "TAD boundaries": 3, "sub-TAD": 3, "domain boundary": 2, "domain boundaries": 2,
            "domain calling": 3, "domain caller": 3, "TAD calling": 3, "TAD caller": 3, "domain detection": 3,
            "hierarchical domain": 2, "insulation score": 2, "insulation": 1,
            "A/B compartment": 3, "subcompartment": 3, "sub-compartment": 3, "compartmentalization": 2,
            "compartment": 0.75, "chromosome interaction domain": 3, "chromosomal interaction domain": 3,
            "re:Arrowhead": 3, "TopDom": 3, "Armatus": 3, "deDoc": 3, "SpectralTAD": 3,
            "OnTAD": 3, "TADbit": 3, "deepTAD": 3, "re:TADpole": 3,
        },
    },
    "Chromatin Loop & Interaction Prediction": {
        "description": "Detecting and predicting chromatin loops, enhancer-promoter and other long-range contacts",
        "terms": {
            "chromatin loop": 2, "loop calling": 3, "loop caller": 3, "loop detection": 3,
            "loop prediction": 3, "chromatin interaction": 2, "interaction prediction": 3,
            "enhancer-promoter": 2, "promoter-enhancer": 2, "E-P interaction": 2,
            "long-range interaction": 1, "significant interaction": 2, "target gene": 1,
            "re:(?i)predict\\w*\\s+(?:\\w+\\s+){0,3}(?:loops|interactions|contacts)": 2,
            "re:\\bHiCCUPS\\b": 3, "Peakachu": 3, "re:\\bMustache\\b": 3, "Chromosight": 3, "DeepLoop": 3,
            "re:\\bFit-?Hi-?C\\d?\\b": 3, "HiC-DC": 3, "RefHiC": 3, "LoopNet": 3,
        },
    },
    "CTCF, Cohesin & Loop Extrusion": {
        "description": "CTCF binding, cohesin / condensin dynamics and the loop-extrusion mechanism",
        "terms": {
            "CTCF": 2, "cohesin": 2, "loop extrusion": 3, "SMC complex": 2, "WAPL": 2, "NIPBL": 2,
            "RAD21": 2, "condensin": 2, "STAG2": 1, "convergent": 1, "CTCF motif": 2, "extrusion": 1,
            "insulator": 1, "YY1": 1,
        },
    },
    "Epigenomics & Sequence-based Prediction": {
        "description": "Predicting 3D contacts from DNA sequence and epigenomic features (Akita, Orca, C.Origami, ...)",
        "terms": {
            "DNA sequence": 1, "sequence-based": 1.5, "sequence alone": 3, "from sequence": 2,
            "from DNA sequence": 3, "genomic sequence": 1, "epigenomic features": 2, "histone marks": 1,
            "histone modification": 1, "sequence features": 1, "in silico mutagenesis": 3, "in silico perturbation": 3,
            "in silico screen": 3, "variant effect": 2, "genetic variant": 1, "epigenomic": 1,
            "epigenetic features": 1, "histone": 1, "chromatin accessibility": 1,
            "re:(?i)predict\\w*\\s+(?:\\w+\\s+){0,4}(?:contact\\s+maps?|Hi-?C|3D\\s+genome|genome\\s+folding|chromatin\\s+(?:structure|organi[sz]ation|contacts|folding))": 3,
            "Akita": 3, "re:\\bOrca\\b": 3, "re:C\\.\\s?Origami": 3, "re:\\bDeepC\\b": 3, "ChromaFold": 3,
            "EPCOT": 3, "Enformer": 2, "Borzoi": 2, "Basenji": 2, "re:\\bSei\\b": 1,
            "re:(?i)(?:3D genome|genome folding|chromatin (?:structure|contacts?|organi[sz]ation|architecture|interactions?)|contact maps?|Hi-?C)\\w*\\s+(?:\\w+\\s+){0,3}prediction": 3,
        },
    },
    "Single-cell 3D Genomics": {
        "description": "Single-cell and single-nucleus 3D genome assays and their computational analysis",
        "terms": {
            "single-cell": 0.75, "single cell": 0.75, "single-nucleus": 0.75, "re:sc-?Hi-?C": 3, "Dip-C": 3,
            "single-cell Hi-C": 4, "single-nucleus Hi-C": 4, "single-cell 3D": 4, "single-cell chromatin conformation": 4,
            "single-cell chromatin structure": 3, "single-cell chromatin tracing": 3, "single-cell resolution": 1,
            "sn-m3C-seq": 3, "snm3C": 3, "HiRES": 2, "cell-to-cell variability": 2, "cell type": 0.5,
            "cell-type": 0.5, "Higashi": 3, "scHiCluster": 3, "Fast-Higashi": 3, "BandNorm": 3, "scGAD": 3,
        },
    },
    "Multi-omics Integration": {
        "description": "Integrating 3D genome data with transcriptomic, epigenomic and other modalities",
        "terms": {
            "multi-omics": 3, "multiomics": 3, "multi-omic": 3, "multi-modal": 2, "multimodal": 2,
            "integrative analysis": 2, "data integration": 2, "integrating": 1, "ChIP-seq": 0.7,
            "ATAC-seq": 0.7, "RNA-seq": 0.7, "DNA methylation": 0.7, "histone modification": 0.7,
            "gene expression": 0.5, "transcriptome": 0.7, "epigenome": 0.7, "epigenomic": 0.5,
        },
    },
    "Generative & Foundation Models": {
        "description": "Generative models (GANs, VAEs, diffusion) and pre-trained foundation / language models",
        "terms": {
            "generative": 2, "diffusion model": 3, "denoising diffusion": 3, "VAE": 3,
            "variational autoencoder": 3, "GAN": 3, "generative adversarial": 3, "foundation model": 3,
            "large language model": 3, "LLM": 3, "language model": 3, "pre-trained": 2, "pretrained": 2,
            "pre-training": 2, "pretraining": 2, "GPT": 2, "BERT": 2, "DNABERT": 3,
            "nucleotide transformer": 3, "HyenaDNA": 3, "transformer": 1,
        },
    },
    "Graph Neural Networks for Genomics": {
        "description": "Graph and hypergraph representations of chromatin contacts and GNN models",
        "terms": {
            "graph neural network": 3, "GNN": 3, "graph convolutional": 3, "GCN": 3, "graph attention": 3,
            "GAT": 2, "graph transformer": 3, "graph embedding": 2, "node embedding": 2,
            "network embedding": 2, "hypergraph": 3, "message passing": 2, "link prediction": 2,
            "graph-based": 1, "graph representation": 2,
        },
    },
    "Experimental Methods & Technologies": {
        "description": "3C-derived, ligation-free and imaging technologies and protocols for mapping genome structure",
        "terms": {
            "protocol": 2, "technique": 1, "assay": 1, "proximity ligation": 2, "ligation-free": 3,
            "crosslinking": 1, "cross-linking": 1, "restriction enzyme": 2, "MNase": 1, "library preparation": 2,
            "in situ Hi-C": 2, "Micro-C": 1, "HiChIP": 1, "PLAC-seq": 1, "Capture-C": 2, "Capture Hi-C": 2,
            "4C-seq": 2, "5C": 1, "ChIA-PET": 1, "ChIA-Drop": 2, "SPRITE": 2, "genome architecture mapping": 3,
            "Pore-C": 2, "concatemer": 2, "multi-way contact": 2, "multiway": 1, "DamID": 2, "TSA-seq": 2,
            "DNA-FISH": 2, "DNA FISH": 2, "chromatin tracing": 2, "long-read": 1,
            "super-resolution microscopy": 2, "super-resolution imaging": 2,
            "re:(?i)\\bwe (?:performed|generated|conducted|produced|applied)\\s+(?:\\w+\\s+){0,3}(?:in situ\\s+)?(?:Hi-?C|Micro-C|HiChIP|ChIA-PET|Capture Hi-C|4C-seq)": 2,
        },
    },
    "Nuclear Organization & Architecture": {
        "description": "Nuclear bodies, lamina, speckles, chromosome territories and radial genome positioning",
        "terms": {
            "nuclear organization": 2, "nuclear organisation": 2, "nuclear architecture": 2,
            "nuclear body": 2, "nuclear bodies": 2, "nuclear speckle": 3, "nucleolus": 2, "nucleolar": 2,
            "nuclear lamina": 3, "lamina-associated domain": 3, "LAD": 2, "nuclear envelope": 2,
            "nuclear periphery": 2, "chromosome territory": 3, "chromosome territories": 3,
            "nuclear pore": 2, "radial position": 2, "heterochromatin": 1, "lamin": 1, "lamina": 1.5,
            "radial": 1, "interchromosomal": 1.5, "inter-chromosomal": 1.5, "nuclear position": 2, "nucleoid": 2,
        },
    },
    "Phase Separation & Chromatin": {
        "description": "Biomolecular condensates and phase separation in chromatin organization",
        "terms": {
            "phase separation": 3, "liquid-liquid phase": 3, "LLPS": 3, "condensate": 2,
            "biomolecular condensate": 3, "phase-separated": 3, "intrinsically disordered": 1,
            "membraneless": 2, "droplet": 1, "microphase": 2,
        },
    },
    "Polymer Modeling & Simulation": {
        "description": "Polymer physics models and molecular / Brownian dynamics simulations of chromatin",
        "terms": {
            "polymer model": 3, "polymer simulation": 3, "polymer physics": 3, "molecular dynamics": 2,
            "coarse-grained": 2, "bead-spring": 3, "Monte Carlo": 1, "Brownian dynamics": 2,
            "chromatin fiber": 1, "block copolymer": 3, "strings and binders": 3, "loop extrusion model": 3,
            "energy landscape": 2, "MiChroM": 3, "simulation": 1, "simulations": 1, "polymer": 1,
        },
    },
    "Data Processing & Normalization": {
        "description": "Hi-C processing pipelines, normalization, reproducibility and differential analysis",
        "terms": {
            "normalization": 2, "normalisation": 2, "bias correction": 3, "iterative correction": 3,
            "Knight-Ruiz": 3, "matrix balancing": 3, "quality control": 1, "reproducibility": 1,
            "differential analysis": 2, "differential interaction": 2, "differential chromatin": 2,
            "file format": 2, "scalable": 1, "HiC-Pro": 3, "re:\\bJuicer\\b": 3, "re:\\bcooler\\b": 3,
            "distiller": 2, "pairtools": 3, "HiCExplorer": 3, "FAN-C": 3, "HiCRep": 3, "GenomeDISCO": 3,
            "diffHic": 3, "multiHiCcompare": 3, "CHESS": 2, "pipeline": 1, "data processing": 2,
            "analysis pipeline": 2, "Python package": 2, "R package": 2, "toolkit": 1.5, "software": 1,
        },
    },
    "Visualization & Browsers": {
        "description": "Genome browsers, visualization tools, portals and databases for 3D genome data",
        "terms": {
            "visualization": 2, "visualisation": 2, "genome browser": 3, "HiGlass": 3, "Juicebox": 3,
            "WashU": 3, "3D Genome Browser": 3, "interactive": 1, "heatmap": 1, "arc plot": 2,
            "virtual 4C": 3, "web server": 2, "web portal": 2, "data portal": 2, "database": 1, "resource": 1,
        },
    },
    "Disease & Clinical Applications": {
        "description": "3D genome alterations in cancer, developmental disorders and complex-trait genetics",
        "terms": {
            "disease": 0.5, "cancer": 2, "tumor": 2, "tumour": 2, "leukemia": 2, "leukaemia": 2, "lymphoma": 2,
            "re:(?i)oncogen\\w*": 2, "clinical": 0.5, "patient": 0.5, "pathogenic": 2, "structural variant": 2,
            "structural variation": 2, "translocation": 1, "enhancer hijacking": 3, "TAD disruption": 3,
            "ectopic contact": 3, "congenital": 2, "developmental disorder": 2, "GWAS": 2,
            "risk variant": 2, "non-coding variant": 2, "noncoding variant": 2, "SNP": 0.5,
        },
    },
    "Evolution & Conservation": {
        "description": "Evolutionary conservation and divergence of 3D genome organization across species",
        "terms": {
            "evolution": 2, "evolutionary": 2, "conservation": 1, "conserved": 0.5, "divergence": 1,
            "comparative": 1, "synteny": 3, "syntenic": 3, "ortholog": 2, "orthologous": 2,
            "phylogenetic": 2, "cross-species": 3, "across species": 2, "species": 0.5,
        },
    },
    "Benchmark & Review": {
        "description": "Reviews, benchmarks, comparisons and perspectives on 3D genome methods",
        "title_only": True,
        "facet": True,
        "pub_types": ["review", "review-article", "systematic review", "meta-analysis"],
        "abstract_terms": {
            "re:(?i)\\b(?:in this|this) (?:review|mini-review|minireview|perspective|survey)\\b": 3,
            "re:(?i)\\bwe (?:review|survey|summari[sz]e) (?:the |recent |current |existing |state-of-the-art )*(?:advances|progress|developments|methods|approaches|tools|literature|state|field|computational)": 3,
            "re:(?i)\\bwe (?:benchmark(?:ed)?|systematically (?:compare|evaluate)d?)\\b": 3,
            "re:(?i)\\bhere,? we (?:summari[sz]e|discuss|highlight) (?:recent|current)\\b": 3,
        },
        "terms": {
            "review": 3, "survey": 3, "benchmark": 3, "benchmarking": 3, "comparison": 2,
            "comparative analysis": 2, "systematic evaluation": 3, "evaluation": 1, "perspective": 2,
            "overview": 2, "primer": 2, "tutorial": 2, "guide": 1, "best practice": 2, "challenges": 1,
            "opportunities": 1, "recent advances": 2, "advances in": 1, "roadmap": 1,
        },
    },
}

# ---------------------------------------------------------------------------
# Email configuration (via environment variables)
# ---------------------------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv("EMAIL_RECIPIENTS", "").split(",")
    if addr.strip()
]
EMAIL_MAX_PAPERS = 60

# ---------------------------------------------------------------------------
# Large language model (AI reading assistant and Chinese translation)
# Any OpenAI-compatible chat-completions API works:
#   DeepSeek  https://api.deepseek.com                            deepseek-chat / deepseek-reasoner
#   Qwen      https://dashscope.aliyuncs.com/compatible-mode/v1   qwen-max
#   Moonshot  https://api.moonshot.cn/v1                          (model name from the provider)
# The web app can edit these settings; they are saved to ENV_FILE.
# ---------------------------------------------------------------------------
DEFAULT_LLM_BASE = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_LLM_REASONING_MODEL = "deepseek-reasoner"
LLM_SETTING_KEYS = ("LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL", "LLM_REASONING_MODEL")

LLM_API_KEY = ""
LLM_API_BASE = DEFAULT_LLM_BASE
LLM_MODEL = DEFAULT_LLM_MODEL
LLM_REASONING_MODEL = DEFAULT_LLM_REASONING_MODEL


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def reload_llm_settings() -> None:
    """(Re)read the model settings from the environment (DEEPSEEK_* and TRANSLATE_* are accepted aliases)."""
    global LLM_API_KEY, LLM_API_BASE, LLM_MODEL, LLM_REASONING_MODEL
    LLM_API_KEY = _env("LLM_API_KEY", "DEEPSEEK_API_KEY", "TRANSLATE_API_KEY")
    LLM_API_BASE = _env("LLM_API_BASE", "TRANSLATE_API_BASE", default=DEFAULT_LLM_BASE)
    LLM_MODEL = _env("LLM_MODEL", "TRANSLATE_MODEL", default=DEFAULT_LLM_MODEL)
    LLM_REASONING_MODEL = _env("LLM_REASONING_MODEL", default=DEFAULT_LLM_REASONING_MODEL)


reload_llm_settings()

LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180") or 180)
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192") or 8192)
LLM_REASONING_MAX_TOKENS = int(os.getenv("LLM_REASONING_MAX_TOKENS", "32768") or 32768)

# AI reading assistant
AI_CONTEXT_CHARS = int(os.getenv("AI_CONTEXT_CHARS", "120000") or 120000)
AI_FULLTEXT_CHARS = int(os.getenv("AI_FULLTEXT_CHARS", "60000") or 60000)
AI_FULLTEXT_MAX_PAPERS = 5
AI_MAX_PAPERS = 200
AI_BATCH_CHARS = 45000
AI_LIBRARY_TOP_K = 15
AI_CHAT_CONTEXT_MAX = 40
FULLTEXT_CACHE_DAYS_MISSING = 14

# Chinese academic translation
TRANSLATE_NEW_PAPERS = os.getenv("TRANSLATE_NEW_PAPERS", "1").strip().lower() not in ("0", "false", "no", "off")
TRANSLATE_MAX_PER_RUN = int(os.getenv("TRANSLATE_MAX_PER_RUN", "100") or 100)
TRANSLATE_MIN_LENGTH_RATIO = 0.2
TRANSLATE_MAX_LENGTH_RATIO = 1.1

# ---------------------------------------------------------------------------
# Web GUI
# ---------------------------------------------------------------------------
WEB_HOST = os.getenv("GENOME_HUB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("GENOME_HUB_PORT", "8686") or 8686)

# ---------------------------------------------------------------------------
# GitHub configuration (optional)
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Yin-Shen/3DGenomeHub")
