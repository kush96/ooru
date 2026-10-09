"""Fetch the district health department's official public overview."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from _fetch_web import fetch_pages

SOURCES = [("Bengaluru Urban: Health department",
            "https://bengaluruurban.nic.in/en/healthdept/", ("Health",))]

if __name__ == "__main__":
    fetch_pages(ROOT, "Bengaluru district health department", SOURCES)
