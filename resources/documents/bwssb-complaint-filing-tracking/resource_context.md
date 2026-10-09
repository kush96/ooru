# BWSSB complaint filing and tracking

**BWSSB** is the Bangalore Water Supply and Sewerage Board, Bengaluru's public water and sewage agency.

**Start here:** Use these links to tell users where to complain and how to track a complaint.
These are the board's general complaint pages, not sewage-only forms. They include water, sewerage, billing and other categories. `txt_source.txt` contains scraped form details, not complaint records or a complete escalation process.

## Which link to use

- [Submit a complaint](https://cms.bwssb.gov.in/module/complain/new_complaint): for reporting a problem. **Sewerage** means the wastewater pipe system. Prepare a name, phone number, address and description; the page also asks for a category and subcategory.
- [Track a complaint](https://cms.bwssb.gov.in/module/complain/view/search_new_complaint): asks for the complaint number and an image verification code, also called a CAPTCHA.

**Checked: 9 October 2026.** No submission or private complaint lookup was tested. Subcategories load interactively and are not captured. These links do not establish response times, escalation contacts or which office covers an address.

## What the scraper adds

`fetch.py` reads these public pages to refresh `txt_source.txt`: form labels, available categories and input hints, grouped by link with a scrape time. It is supporting evidence, not a list of actual complaints. RR Number means the water account reference. No raw HTML is saved. This context stays handwritten; review it after refreshing.

From `ooru_be` (requires `uv` and `curl`; no new Python dependencies):

```bash
uv run --group resources resources/documents/bwssb-complaint-filing-tracking/fetch.py
```
