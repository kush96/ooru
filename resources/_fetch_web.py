"""Shared HTML-to-text helper. Individual resource folders choose their sources."""

import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


def extract_text(html, url):
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("main .hentry") or soup.find("main") or soup.find("body")
    if content is None:
        raise ValueError(f"No readable page body: {url}")
    for tag in content.select(
        "script, style, nav, footer, aside, form, select, button, input, "
        ".share-this, .social-icons, .breadcrumbs, .serviceMainContainer"
    ):
        tag.decompose()
    # Resolve links before flattening tables so links inside cells survive too.
    for link in content.find_all("a", href=True):
        href = urljoin(url, link["href"])
        if "facebook.com/sharer/" in href or "x.com/share" in href or "twitter.com/share" in href:
            link.decompose()
            continue
        label = link.get_text(" ", strip=True)
        if label and href.startswith(("https://", "http://")):
            link.replace_with(label if label == href else f"{label} ({href})")
    # Keep table headers attached to values, including empty contact fields.
    for table in content.find_all("table"):
        rows = table.find_all("tr")
        headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all("th")] if rows else []
        caption = table.find("caption")
        lines = [caption.get_text(" ", strip=True)] if caption else []
        for row in rows:
            cells = row.find_all("td", recursive=False)
            if cells:
                values = [cell.get_text(" ", strip=True) for cell in cells]
                lines.append(" | ".join(
                    f"{headers[i]}: {value or '(not listed)'}" if i < len(headers) else value
                    for i, value in enumerate(values)
                ))
        table.replace_with("\n" + "\n".join(lines) + "\n")
    return "\n".join(line.strip() for line in content.get_text("\n").splitlines() if line.strip())


def fetch_pages(folder, title, sources):
    """Read public pages only. Save no HTML and leave handwritten context untouched."""
    sections = []
    for label, url, expected in sources:
        response = subprocess.run(
            ["curl", "--fail", "--location", "--silent", "--show-error",
             "--connect-timeout", "8", "--max-time", "25", url],
            stdout=subprocess.PIPE, check=True, timeout=30,
        )
        text = extract_text(response.stdout, url)
        if len(text) < 80 or not all(term.lower() in text.lower() for term in expected):
            raise ValueError(f"Unexpected or incomplete content: {url}; saved text unchanged.")
        now = datetime.now(ZoneInfo("Asia/Dubai")).isoformat()
        sections.append(f"{label}\nSource: {url}\nFetched: {now}\n\n{text}")
    output = (
        f"{title}\n\nRead resource_context.md first for scope and limitations.\n"
        "Scraped official-page text; download time is NOT the date the underlying information was updated.\n\n"
        + "\n\n---\n\n".join(sections) + "\n"
    )
    (Path(folder) / "txt_source.txt").write_text(output, encoding="utf-8")
    print(f"Saved {len(sources)} source(s): {Path(folder) / 'txt_source.txt'}", flush=True)
