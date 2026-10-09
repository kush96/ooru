"""Fetch an official explanation and link for Karnataka's grievance portal."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from _fetch_web import fetch_pages

SOURCES = [("Government district guide to the statewide grievance system",
            "https://koppal.nic.in/en/service/ipgrs/", ("Janaspandana", "ipgrs"))]

if __name__ == "__main__":
    fetch_pages(ROOT, "Karnataka Janaspandana grievance guide", SOURCES)
