"""Fetch the district government's introduction to Sakala."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from _fetch_web import fetch_pages

SOURCES = [("Bengaluru Urban: Sakala services",
            "https://bengaluruurban.nic.in/en/service/sakala-services/",
            ("Sakala", "Guarantee of Services"))]

if __name__ == "__main__":
    fetch_pages(ROOT, "Karnataka Sakala service guarantees: introduction", SOURCES)
