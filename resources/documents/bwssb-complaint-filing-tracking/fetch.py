"""Scrape supporting details for the links in resource_context.md. Save text only."""

import subprocess
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
PAGES = [
    ("Submit a complaint", "https://cms.bwssb.gov.in/module/complain/new_complaint",
     ("Consumer Name", "Describe Your Complaint", "Sewerage")),
    ("Track an existing complaint", "https://cms.bwssb.gov.in/module/complain/view/search_new_complaint",
     ("Complaint Number", "Enter the characters shown in the image")),
]


class PageText(HTMLParser):
    """Read the public form only, without navigation, scripts or styles."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored_tag = None
        self.in_form = False

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.in_form = True
        if not self.in_form:
            return
        if tag in ("script", "style", "a"):
            self.ignored_tag = tag
        if tag == "br" and self.ignored_tag is None:
            self.parts.append("\n")
        if tag == "input" and self.ignored_tag is None:
            attributes = dict(attrs)
            hint = attributes.get("placeholder")
            if hint and attributes.get("type") != "hidden":
                self.parts.append(f"\n[Input hint: {hint}]\n")

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False
        if not self.in_form:
            return
        if tag == self.ignored_tag:
            self.ignored_tag = None
        if self.ignored_tag is None and tag in (
            "title", "h1", "h2", "h3", "h4", "p", "div", "label", "option", "button", "a", "li",
        ):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_form and self.ignored_tag is None:
            self.parts.append(data)

    def text(self):
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def main():
    scraped_at = datetime.now(ZoneInfo("Asia/Dubai")).isoformat()
    sections = []
    # Fetch public blank forms only. Keep HTML in memory, never save it.
    for title, url, expected_labels in PAGES:
        response = subprocess.run(
            ["curl", "--fail", "--location", "--silent", "--show-error",
             "--connect-timeout", "10", "--max-time", "45", url],
            stdout=subprocess.PIPE, check=True,
        )
        html = response.stdout.decode("utf-8")
        parser = PageText()
        parser.feed(html)
        parser.close()
        text = parser.text()
        if "<form" not in html.lower() or "BWSSB" not in html or not all(
            label in text for label in expected_labels
        ):
            raise ValueError(f"Unexpected page at {url}; existing files were not changed.")
        sections.append(f"{title.upper()}\nSource: {url}\n\nForm fields and choices:\n{text}")

    # Update text only after both pages pass checks. Leave the context untouched.
    introduction = (
        "BWSSB complaint links: scraped supporting details\n"
        f"Scraped: {scraped_at}\n\n"
        "Read resource_context.md first for which link to use and why.\n"
        "Below are labels and choices from blank public forms, not complaint records.\n"
        "An asterisk (*) marks a field the page labels as required.\n"
        "Interactive subcategory choices are not captured. No form was submitted.\n\n"
    )
    (ROOT / "txt_source.txt").write_text(
        introduction + "\n\n---\n\n".join(sections) + "\n", encoding="utf-8",
    )
    print(f"Refreshed txt_source.txt in {ROOT}; no HTML files saved.")


if __name__ == "__main__":
    main()
