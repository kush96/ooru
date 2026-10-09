"""Download the Act and extract its text. Leave resource_context.md unchanged."""

import io
import subprocess
from pathlib import Path

from pypdf import PdfReader


SOURCE_URL = "https://www.indiacode.nic.in/bitstream/123456789/21664/1/36_of_2025_(e).pdf"
ROOT = Path(__file__).resolve().parent


def main():
    # Download into memory so a failed request does not overwrite saved files.
    result = subprocess.run(
        ["curl", "--http1.1", "--fail", "--location", "--silent",
         "--show-error", "--connect-timeout", "10", "--max-time", "60", SOURCE_URL],
        stdout=subprocess.PIPE, check=True,
    )
    pdf = result.stdout
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("The download is not a PDF; existing files were not changed.")

    # Extract every page, keeping page numbers for looking up the original.
    reader = PdfReader(io.BytesIO(pdf))
    pages = [page.extract_text() or "" for page in reader.pages]
    if not pages or "GREATER BENGALURU GOVERNANCE ACT" not in " ".join(pages[0].split()).upper():
        raise ValueError("Unexpected document; existing files were not changed.")
    if any(not page.strip() for page in pages):
        raise ValueError("A page has no readable text; OCR or manual review is needed.")
    text = "\n\n".join(
        f"=== PDF PAGE {number} ===\n{page}"
        for number, page in enumerate(pages, start=1)
    )

    # Refresh these two files only. The context is maintained by hand.
    (ROOT / "pdf_source.pdf").write_bytes(pdf)
    (ROOT / "txt_source.txt").write_text(text, encoding="utf-8")
    print(f"Saved pdf_source.pdf and txt_source.txt ({len(pages)} pages) in {ROOT}")


if __name__ == "__main__":
    main()
