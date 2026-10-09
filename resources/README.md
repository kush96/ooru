# Resources

- **`documents/`**: laws and reference guides. Read `resource_context.md` first, then `txt_source.txt` for supporting details. Check the original PDF or official link when needed.
- **`datasets/`**: structured records for database use, including CSVs and map data. Read the source notes before choosing a file to query or import. Being here does not mean it is already in the database.

## Where to look

| Resource | Helps with |
|---|---|
| [Greater Bengaluru Governance Act](documents/greater-bengaluru-governance-act/resource_context.md) | Full Act: city governance, authorities' roles and powers |
| [Bangalore Water Supply and Sewerage Act](documents/bangalore-water-supply-sewerage-act/resource_context.md) | Full Act: water supply, sewage and property drainage |
| [BWSSB complaint filing and tracking](documents/bwssb-complaint-filing-tracking/resource_context.md) | Public complaint forms: links, fields and categories for water/sewage and other board services |
| [Public-agency contact directory](documents/bengaluru-public-agency-contact-directory/resource_context.md) | District-published agency office contacts; includes old entries, so verify before use |
| [Janaspandana grievance guide](documents/karnataka-janaspandana-grievance-guide/resource_context.md) | Official guide and link to Karnataka's general complaint portal |
| [Sakala service guarantees](documents/karnataka-sakala-service-guarantees/resource_context.md) | Introduction to time-bound government services; not a service deadline list |
| [District health department](documents/bengaluru-district-health-department/resource_context.md) | Health department programmes and published office contact |
| [District veterinary services](documents/bengaluru-district-veterinary-services/resource_context.md) | Animal healthcare and livestock services; not municipal stray-dog routing |
| [Municipal accounts](datasets/municipal-accounts/upstream/DATA.md) | Bills, payments, receipts and DC bills |
| [Citizen grievances](datasets/citizen-grievances/upstream/DATA.md) | Recorded complaints and their status |
| [Work orders](datasets/work-orders/resource_context.md) | Work-order/payment records for different ward schemes |
| [Wards](datasets/wards/README.md) | Ward boundaries |
| [Roads](datasets/roads/) | Road geometry and map-download cache |

PDF resources keep `fetch.py`, `pdf_source.pdf`, `txt_source.txt` and `resource_context.md`. Link-based resources keep `fetch.py`, `txt_source.txt` and `resource_context.md`: the context explains useful links; the scraper saves supporting text, not raw HTML.

Name each folder after the specific law or information it contains, not a broad topic like `sewage`. Multiple sources can share a folder when they serve that same purpose; label their contributions in the text and explain the scope in the context.

New web scrapers share `_fetch_web.py` to keep each `fetch.py` short. They use `beautifulsoup4` from the `resources` dependency group, preserve table labels, and save no HTML. The earlier PDF and complaint-form scripts remain independent.

**Coverage is incomplete:** current municipal complaint channels, roads/streetlights/waste contacts, BESCOM (electricity) contacts and address-to-local-office mapping still need verified sources. Several agency sites timed out on 9 October 2026. Do not infer current coverage from old directory entries.

[Dataset notes](datasets/README.md) explain source files and caveats. `manifest.json` is the older download log, not a complete resource catalog; its local paths are relative to this folder. Failed downloads remain in the log, but have no local file.
