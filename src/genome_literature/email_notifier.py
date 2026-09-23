"""Send email digest notifications about new papers."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config
from .relevance import track_label
from .summarizer import short_authors

logger = logging.getLogger(__name__)

_FALLBACK_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:16px;color:#1f2937">
<h2 style="margin:0 0 4px">3D Genome &amp; Deep Learning — literature update</h2>
<p style="color:#6b7280;margin:0 0 16px">{{ digest.generated_at[:10] }} · {{ new_stats.total_papers }} new
({{ new_stats.ml_papers }} AI/ML) · {{ stats.total_papers }} in database</p>
{% for p in papers %}
<div style="margin:0 0 14px;padding-left:10px;border-left:3px solid {{ '#7c3aed' if p.track == 'ml' else '#cbd5e1' }}">
<a href="{{ p.url }}" style="color:#1d4ed8;font-weight:600;text-decoration:none">{{ p.title }}</a>
<div style="font-size:12px;color:#6b7280">{{ authors(p) }} · {{ p.journal }} ({{ p.date or p.year }}) · {{ label(p.track) }}</div>
</div>
{% endfor %}
{% if truncated %}<p style="color:#6b7280">… and {{ truncated }} more in the repository.</p>{% endif %}
<p style="font-size:12px;color:#9ca3af">Sent by <a href="{{ repo_url }}">3DGenomeHub</a>.</p>
</body></html>"""


def send_digest_email(new_papers: list[dict[str, Any]], digest: dict[str, Any]) -> bool:
    """Send an HTML digest to all configured recipients; returns True on success."""
    if not config.EMAIL_RECIPIENTS:
        logger.warning("No email recipients configured — skipping email notification")
        return False
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — skipping email notification")
        return False
    if not new_papers:
        logger.info("No new papers — skipping email notification")
        return False

    ml_count = sum(1 for p in new_papers if p.get("track") == "ml")
    subject = f"[3DGenomeHub] {len(new_papers)} new paper(s), {ml_count} AI/ML — 3D genome literature update"
    sender = config.EMAIL_FROM or config.SMTP_USER
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(config.EMAIL_RECIPIENTS)
        msg.attach(MIMEText(digest.get("summary_text", "New papers available."), "plain", "utf-8"))
        msg.attach(MIMEText(render_email_html(new_papers, digest), "html", "utf-8"))

        context = ssl.create_default_context()
        if config.SMTP_PORT == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=60, context=context)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=60)
        with server:
            if config.SMTP_PORT != 465:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(sender, config.EMAIL_RECIPIENTS, msg.as_string())
        logger.info("Email digest sent to %d recipient(s)", len(config.EMAIL_RECIPIENTS))
        return True
    except Exception:
        logger.exception("Failed to send email digest")
        return False


def render_email_html(new_papers: list[dict[str, Any]], digest: dict[str, Any]) -> str:
    """Render the HTML digest (templates/email_digest.html, or a built-in fallback)."""
    ranked = digest.get("new_papers") or new_papers
    shown = ranked[: config.EMAIL_MAX_PAPERS]
    shown_ids = {p.get("id") for p in shown}
    by_category = {
        cat: [p for p in items if p.get("id") in shown_ids]
        for cat, items in (digest.get("new_papers_by_category") or {}).items()
    }
    context = dict(
        papers=shown,
        new_papers=shown,
        new_by_category={k: v for k, v in by_category.items() if v},
        digest=digest,
        stats=digest.get("statistics", {}),
        new_stats=digest.get("new_statistics", {}),
        truncated=max(0, len(ranked) - len(shown)),
        repo_url=config.REPO_URL,
        authors=lambda p: short_authors(p.get("authors") or []),
        label=track_label,
    )
    template_dir = config.TEMPLATE_DIR
    env_kwargs = dict(autoescape=select_autoescape(["html", "xml"], default_for_string=True))
    if (template_dir / "email_digest.html").exists():
        env = Environment(loader=FileSystemLoader(str(template_dir)), **env_kwargs)
        return env.get_template("email_digest.html").render(**context)
    return Environment(**env_kwargs).from_string(_FALLBACK_TEMPLATE).render(**context)
