# Downloaded source datasets

These are structured source files for local review and database imports. This folder is not
a record of what is currently loaded in PostgreSQL.
`../manifest.json` records the older downloads' source URLs, pinned GitHub commits,
timestamps, SHA-256 hashes, file sizes, CSV headers and row counts. It is not a complete inventory.

## Where to look

- `wards/`: unchanged December 2025 ward-boundary KML, with download provenance.
- `roads/`: road CSV and OpenStreetMap download cache used by the road importer.
- `municipal-accounts/csv/`: extracted bills, payments, DC bills and receipts.
- `citizen-grievances/csv/`: extracted Sahaaya complaints.
- `work-orders/`: four FY2025–26 work-order/payment CSVs; start with `resource_context.md`. `metadata.json` preserves the source website's description.
- Each GitHub collection's `original/`: untouched compressed CSV and Parquet downloads.
- Each collection's `upstream/`: source README, data dictionary, license and collector/parser
  scripts, preserved as reference files. These scripts have not been executed.

## Sources

- Municipal accounts: https://github.com/Vonter/blr-municipal-accounts
- Citizen grievances: https://github.com/Vonter/bbmp-citizen-grievances
- OpenCity: https://data.opencity.in/dataset/bbmp-work-orders-and-payments-2025-26

The GitHub datasets are third-party parsed collections of source-portal records. They are
not original portal HTML/JSON dumps; those dumps and the actual attachments mentioned in
dataset cells are not included. The compressed files and Parquet contain equivalent data,
not additional records. Extracted CSVs are decompressed copies, with no cleaning or AI edits.

Accounts include modules beyond roads. Receipts are incoming money, not road spending.
Bills and payments can overlap; do not add their totals together. Ward numbers need their
ward scheme. Complaints do not provide an established exact-road location in their schema.

The repository licenses and OpenCity metadata are retained alongside the data. The originals
can contain names, contact details and financial identifiers; they are local source archives,
not public app assets.

The `roads/` folder contains separately collected OpenStreetMap road data. This collection
does not include Google imagery or establish matches between roads and work orders.
