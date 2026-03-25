"""Main pipeline: fetch → categorize → merge → summarize → update README → notify."""

from __future__ import annotations

import logging
from typing import Any

from . import config
from .categorizer import categorize_papers
from .email_notifier import send_digest_email
from .fetcher import fetch_all_papers
from .readme_generator import generate_readme
from .storage import load_papers, merge_papers, save_papers
from .summarizer import generate_digest

logger = logging.getLogger(__name__)


def run_pipeline(
    skip_fetch: bool = False,
    skip_email: bool = False,
    skip_readme: bool = False,
) -> dict[str, Any]:
    """Execute the full update pipeline.

    Steps:
    1. Load existing paper database
    2. Fetch new papers from all sources
    3. Categorize fetched papers
    4. Merge with existing (deduplicate)
    5. Save updated database
    6. Generate digest summary
    7. Update README.md
    8. Send email notification

    Returns a result dict with statistics and status.
    """
    result: dict[str, Any] = {"success": False}

    # 1. Load existing
    logger.info("Step 1: Loading existing paper database...")
    existing = load_papers()
    result["existing_count"] = len(existing)
    logger.info("Loaded %d existing papers", len(existing))

    # 2. Fetch new papers
    if skip_fetch:
        logger.info("Step 2: Skipping fetch (--skip-fetch)")
        fetched: list[dict[str, Any]] = []
    else:
        logger.info("Step 2: Fetching papers from PubMed, bioRxiv, arXiv...")
        fetched = fetch_all_papers()
    result["fetched_count"] = len(fetched)

    # 3. Categorize
    logger.info("Step 3: Categorizing papers...")
    if fetched:
        categorize_papers(fetched)

    # 4. Merge
    logger.info("Step 4: Merging with existing database...")
    all_papers, new_papers = merge_papers(existing, fetched)

    # Re-categorize all papers (in case categories were updated)
    categorize_papers(all_papers)

    result["total_count"] = len(all_papers)
    result["new_count"] = len(new_papers)

    # 5. Save
    logger.info("Step 5: Saving updated database...")
    save_papers(all_papers)
    if new_papers:
        save_papers(new_papers, config.NEW_PAPERS_JSON)

    # 6. Generate digest
    logger.info("Step 6: Generating digest...")
    digest = generate_digest(new_papers, all_papers)
    result["digest_summary"] = digest["summary_text"]

    # 7. Update README
    if skip_readme:
        logger.info("Step 7: Skipping README update (--skip-readme)")
    else:
        logger.info("Step 7: Updating README.md...")
        readme_content = generate_readme(all_papers)
        config.README_PATH.write_text(readme_content, encoding="utf-8")
        logger.info("README.md updated (%d chars)", len(readme_content))

    # 8. Send email
    if skip_email:
        logger.info("Step 8: Skipping email (--skip-email)")
    else:
        logger.info("Step 8: Sending email notification...")
        email_sent = send_digest_email(new_papers, digest)
        result["email_sent"] = email_sent

    result["success"] = True
    logger.info("Pipeline completed successfully!")
    logger.info(digest["summary_text"])

    return result
