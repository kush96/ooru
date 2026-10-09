"""Fetch the district government's public agency directory."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from _fetch_web import fetch_pages

SOURCES = [("Bengaluru Urban district agency directory",
            "https://bengaluruurban.nic.in/en/directory/",
            ("Bangalore Water Supply", "Pollution Control", "Development Authority"))]

if __name__ == "__main__":
    fetch_pages(ROOT, "Bengaluru public-agency directory", SOURCES)
