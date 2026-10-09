"""Download the sewage law and extract text. Keep resource_context.md handwritten."""

import io
import subprocess
from pathlib import Path

from pypdf import PdfReader


SOURCE_URL = "https://indiacode.gov.in/server/api/core/bitstreams/7ffa7b67-a466-42a9-b892-825faad50d0e/content"
ROOT = Path(__file__).resolve().parent


def main():
    # Download first; failed requests must not overwrite the saved document.
    result = subprocess.run(
        ["curl", "--http1.1", "--fail", "--location", "--silent",
         "--show-error", "--connect-timeout", "10", "--max-time", "60", SOURCE_URL],
        stdout=subprocess.PIPE, check=True,
    )
    pdf = result.stdout
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("The download is not a PDF; existing files were not changed.")

    # Keep page numbers so extracted passages can be checked in the PDF.
    reader = PdfReader(io.BytesIO(pdf))
    pages = [page.extract_text() or "" for page in reader.pages]
    title = "BANGALORE WATER SUPPLY AND SEWERAGE ACT"
    if not pages or title not in " ".join(pages[0].split()).upper():
        raise ValueError("Unexpected document; existing files were not changed.")
    if any(not page.strip() for page in pages):
        raise ValueError("A page has no readable text; OCR or manual review is needed.")
    text = "\n\n".join(
        f"=== PDF PAGE {number} ===\n{page}"
        for number, page in enumerate(pages, start=1)
    )

    # Only these two files are generated. Never overwrite the context note.
    (ROOT / "pdf_source.pdf").write_bytes(pdf)
    (ROOT / "txt_source.txt").write_text(text, encoding="utf-8")
    print(f"Saved pdf_source.pdf and txt_source.txt ({len(pages)} pages) in {ROOT}")


if __name__ == "__main__":
    main()
