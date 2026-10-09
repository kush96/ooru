"""Fetch the district animal-husbandry department overview."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from _fetch_web import fetch_pages

SOURCES = [("Bengaluru Urban: Animal Husbandry",
            "https://bengaluruurban.nic.in/en/animal-husbandry/", ("Animal Husbandry",))]

if __name__ == "__main__":
    fetch_pages(ROOT, "Bengaluru district veterinary services", SOURCES)
