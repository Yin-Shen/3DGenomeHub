"""Send email digest notifications about new papers."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from . import config

logger = logging.getLogger(__name__)


def send_digest_email(
    new_papers: list[dict[str, Any]],
    digest: dict[str, Any],
) -> bool:
    """Send an HTML email digest about new papers to all configured recipients.

    Returns True if email was sent successfully, False otherwise.
    """
    if not config.EMAIL_RECIPIENTS:
        logger.warning("No email recipients configured — skipping email notification")
        return False

    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — skipping email notification")
        return False

    if not new_papers:
        logger.info("No new papers — skipping email notification")
        return False

    html_body = _render_email_html(new_papers, digest)
    plain_body = digest.get("summary_text", "New papers available.")

    subject = (
        f"[3DGenomeHub] {len(new_papers)} new paper(s) — "
        f"3D Genome & Deep Learning Update"
    )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.EMAIL_FROM or config.SMTP_USER
        msg["To"] = ", ".join(config.EMAIL_RECIPIENTS)

        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(
                config.EMAIL_FROM or config.SMTP_USER,
                config.EMAIL_RECIPIENTS,
                msg.as_string(),
            )

        logger.info("Email digest sent to %d recipient(s)", len(config.EMAIL_RECIPIENTS))
        return True

    except Exception:
        logger.exception("Failed to send email digest")
        return False


def _render_email_html(
    new_papers: list[dict[str, Any]],
    digest: dict[str, Any],
) -> str:
    """Render the email HTML using Jinja2 template."""
    template_dir = config.TEMPLATE_DIR
    if template_dir.exists() and (template_dir / "email_digest.html").exists():
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("email_digest.html")
        return template.render(
            new_papers=new_papers,
            digest=digest,
            new_by_category=digest.get("new_papers_by_category", {}),
            stats=digest.get("statistics", {}),
            new_stats=digest.get("new_statistics", {}),
        )

    # Fallback: inline HTML if template file is missing
    return _build_inline_html(new_papers, digest)


def _build_inline_html(
    new_papers: list[dict[str, Any]],
    digest: dict[str, Any],
) -> str:
    """Build email HTML inline (fallback when template not found)."""
    stats = digest.get("statistics", {})
    new_stats = digest.get("new_statistics", {})
    new_by_cat = digest.get("new_papers_by_category", {})

    paper_rows = []
    for p in sorted(new_papers, key=lambda x: x.get("date", ""), reverse=True):
        authors = p["authors"][0] + " et al." if len(p["authors"]) > 1 else (p["authors"][0] if p["authors"] else "Unknown")
        cats = ", ".join(p.get("categories", []))
        paper_rows.append(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;">
            <a href="{p.get('url', '#')}" style="color:#1a73e8;text-decoration:none;font-weight:600;">
              {p['title']}
            </a><br>
            <span style="color:#666;font-size:13px;">{authors} | {p.get('journal','')} ({p.get('year','')})</span><br>
            <span style="color:#888;font-size:12px;">{cats}</span>
          </td>
        </tr>""")

    cat_summary = ""
    for cat, papers in new_by_cat.items():
        cat_summary += f"<li><strong>{cat}</strong>: {len(papers)} paper(s)</li>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#333;">

<div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:30px;border-radius:12px;margin-bottom:20px;">
  <h1 style="margin:0;font-size:24px;">3D Genome & Deep Learning</h1>
  <p style="margin:8px 0 0;opacity:0.9;">Literature Update — {digest.get('generated_at', '')[:10]}</p>
</div>

<div style="background:#f8f9fa;padding:20px;border-radius:8px;margin-bottom:20px;">
  <h2 style="margin:0 0 10px;font-size:18px;">Summary</h2>
  <p>Total papers tracked: <strong>{stats.get('total_papers', 0)}</strong></p>
  <p>New papers this update: <strong>{new_stats.get('total_papers', 0)}</strong></p>
  <ul>{cat_summary}</ul>
</div>

<h2 style="font-size:18px;">New Papers</h2>
<table style="width:100%;border-collapse:collapse;">
  {''.join(paper_rows)}
</table>

<hr style="margin:30px 0;border:none;border-top:1px solid #eee;">
<p style="color:#999;font-size:12px;text-align:center;">
  Sent by <a href="https://github.com/Yin-Shen/3DGenomeHub">3DGenomeHub</a> —
  auto-updating 3D genome & deep learning literature tracker.
</p>

</body>
</html>"""
