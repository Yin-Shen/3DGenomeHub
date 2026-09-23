from __future__ import annotations

import pytest

from genome_literature.categorizer import categorize_paper
from genome_literature.records import new_record
from genome_literature.relevance import filter_relevant, is_relevant, score_paper, annotate


def paper(title: str, abstract: str = "", **kw):
    return new_record("pubmed", title=title, abstract=abstract, **kw)


RELEVANT = [
    ("Predicting 3D genome folding from DNA sequence with a convolutional neural network",
     "We train a CNN on Hi-C contact maps to predict chromatin contacts from sequence alone.", "ml",
     "Epigenomics & Sequence-based Prediction"),
    ("Enhancing Hi-C data resolution with deep convolutional neural networks",
     "Low-resolution Hi-C contact matrices are enhanced by a deep neural network.", "ml",
     "Hi-C Enhancement & Super-Resolution"),
    ("A generative adversarial network for enhancing Hi-C contact map resolution",
     "Our GAN produces high-resolution chromatin contact maps from downsampled data.", "ml",
     "Hi-C Enhancement & Super-Resolution"),
    ("Multiscale single-cell Hi-C analysis with hypergraph representation learning",
     "We impute sparse scHi-C contact maps and embed single cells with a hypergraph neural network.", "ml",
     "Single-cell 3D Genomics"),
    ("A supervised learning framework for chromatin loop detection in genome-wide contact maps",
     "A random forest classifier trained on CTCF ChIA-PET loops detects chromatin loops in Hi-C data.", "ml",
     "Chromatin Loop & Interaction Prediction"),
    ("Graph neural networks predict enhancer–promoter interactions from Hi-C",
     "Enhancer–promoter interactions are predicted by a graph attention network over chromatin contacts.", "ml",
     "Chromatin Loop & Interaction Prediction"),
    ("Identifying topologically associating domains with a novel algorithm",
     "We describe a statistical algorithm for calling TAD boundaries from Hi-C maps; software is open source.",
     "computational", "TAD & Compartment Detection"),
    ("Polymer simulations of loop extrusion reproduce TAD patterns",
     "Coarse-grained polymer models with cohesin-mediated loop extrusion and CTCF barriers reproduce Hi-C maps.",
     "computational", "Polymer Modeling & Simulation"),
    ("Micro-C reveals nucleosome-resolution chromatin folding in mammalian cells",
     "We describe the Micro-C protocol using MNase digestion and proximity ligation to map chromatin folding.",
     "experimental", "Experimental Methods & Technologies"),
]

IRRELEVANT = [
    ("Chromosome-level genome assembly of the giant panda using Hi-C scaffolding",
     "We generated a chromosome-level genome assembly using Hi-C data for scaffolding."),
    ("Deep learning for protein contact map prediction",
     "Residue contact maps are predicted for protein structure prediction with a residual network."),
    ("Metadata standards for clinical data status reporting",
     "We investigate organization-wide metadata, activity logs and status reporting."),
    ("The p53 transactivation domain (TAD) binds MDM2",
     "The TAD of p53 mediates transactivation and binds MDM2 with high affinity."),
    ("Hydrophobic interaction chromatography (HIC) of monoclonal antibodies",
     "HIC separates antibody variants by hydrophobicity."),
    ("Deep learning predicts chromatin accessibility from DNA sequence",
     "A convolutional neural network predicts ATAC-seq peaks and chromatin accessibility."),
    ("Correction: Predicting 3D genome folding from DNA sequence",
     "This corrects the article on Hi-C contact map prediction with chromatin loops."),
    ("SARS-CoV-2 3C-like protease inhibitors discovered by virtual screening",
     "We screen inhibitors of the 3CLpro main protease."),
    ("Left anterior descending (LAD) artery stenosis outcomes",
     "Patients with LAD stenosis and coronary disease were followed."),
    ("Metagenomic Hi-C binning of microbial communities",
     "Proximity ligation (Hi-C) links contigs in metagenomes to reconstruct genomes."),
    ("Tadpole organ development and gut organization",
     "Organogenesis in tadpoles; organization of the gut; vitamin activity."),
]


@pytest.mark.parametrize("title,abstract,track,category", RELEVANT)
def test_relevant_papers_are_kept_with_track_and_category(title, abstract, track, category):
    p = paper(title, abstract)
    assert is_relevant(annotate(p)), score_paper(p)
    assert p["track"] == track
    assert category in categorize_paper(p)


@pytest.mark.parametrize("title,abstract", IRRELEVANT)
def test_noise_is_rejected(title, abstract):
    p = paper(title, abstract)
    assert not is_relevant(annotate(p)), score_paper(p)


def test_filter_relevant_strips_private_fields():
    kept, rejected = filter_relevant([paper(*RELEVANT[0][:2]), paper(*IRRELEVANT[0])])
    assert len(kept) == 1 and len(rejected) == 1
    assert not any(k.startswith("_") for k in kept[0])
    assert kept[0]["relevance"] > 50
    assert "CNN" in kept[0]["dl_methods"]


def test_word_boundaries_prevent_substring_matches():
    p = paper("Organization of nuclear speckles and investigation of activity in 3D genome architecture",
              "We investigate how the organization of speckles relates to Hi-C compartments and metadata.")
    annotate(p)
    assert p["dl_methods"] == []
    cats = categorize_paper(p)
    assert "Generative & Foundation Models" not in cats
    assert "Graph Neural Networks for Genomics" not in cats
    assert "TAD & Compartment Detection" not in cats or "compartment" in p["abstract"].lower()


def test_benchmark_category_uses_title_and_publication_type():
    review = paper("Deep learning for 3D genome organization: a review", "Hi-C models are compared.")
    assert "Benchmark & Review" in categorize_paper(review)
    not_review = paper("Predicting chromatin loops with transformers",
                       "We review prior work on Hi-C and propose a transformer.")
    assert "Benchmark & Review" not in categorize_paper(not_review)
    typed = paper("Chromatin loops in development", "Hi-C chromatin loops.", publication_types=["Review"])
    assert "Benchmark & Review" in categorize_paper(typed)


def test_curated_paper_needs_only_a_core_term():
    p = paper("Comprehensive mapping of long-range interactions reveals folding principles of the human genome",
              "We describe Hi-C, a method that probes the three-dimensional architecture of whole genomes.")
    p["curated"] = True
    assert is_relevant(annotate(p))
    assert p["relevance"] >= 90
    q = paper("An unrelated paper about photosynthesis", "Light harvesting in plants.")
    q["curated"] = True
    assert not is_relevant(annotate(q))
