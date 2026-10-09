# blr-municipal-accounts

Tidy dataset of municipal accounts for Bengaluru. Works bills, payments, receipts and DC bills for BBMP/GBA, sourced from the [IFMS Portal](https://account.bbmpgov.in/vsswb/) and the [Works Bill Portal](https://account.bbmpgov.in/PublicView/?l=1).

View the raw dataset for:
- [Bills](https://hyparam.github.io/demos/hyparquet/?key=https%3A%2F%2Fraw.githubusercontent.com%2FVonter%2Fblr-municipal-accounts%2Fmain%2Fdata%2Fbills.parquet)
- [Payments](https://hyparam.github.io/demos/hyparquet/?key=https%3A%2F%2Fraw.githubusercontent.com%2FVonter%2Fblr-municipal-accounts%2Fmain%2Fdata%2Fpayments.parquet)
- [Receipts](https://hyparam.github.io/demos/hyparquet/?key=https%3A%2F%2Fraw.githubusercontent.com%2FVonter%2Fblr-municipal-accounts%2Fmain%2Fdata%2Freceipts.parquet)
- [DC Bills](https://hyparam.github.io/demos/hyparquet/?key=https%3A%2F%2Fraw.githubusercontent.com%2FVonter%2Fblr-municipal-accounts%2Fmain%2Fdata%2Fdc-bills.parquet)

## Data

Four datasets are published, each as a Parquet file and an equivalent zipped CSV:

* Bills: [bills.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/bills.parquet) and [bills.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/bills.csv.zip)
* Payments: [payments.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/payments.parquet) and [payments.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/payments.csv.zip)
* Receipts: [receipts.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/receipts.parquet) and [receipts.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/receipts.csv.zip)
* DC Bills: [dc-bills.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/dc-bills.parquet) and [dc-bills.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/dc-bills.csv.zip)

See [DATA.md](DATA.md) for the schema and data dictionary.

## Sources

The source data is fetched from one of two BBMP portals:

| Source | Datasets |
|--------|----------|
| `publicview` (default) | `bills` |
| `ifms` | `payments`, `receipts`, `dc-bills` |

## Scripts

* [`fetch.py`](fetch.py): Fetch monthly lists, and details of works bills, payments, receipts and DC bills
* [`parse.py`](parse.py): Parse lists and details into the published Parquet and zipped CSV datasets

## Generate

Install [uv](https://docs.astral.sh/uv/), then run:

```sh
uv sync
uv run fetch.py
uv run parse.py
```

## License

This blr-municipal-accounts dataset is made available under the Open Database License: http://opendatacommons.org/licenses/odbl/1.0/. 
Some individual contents of the database are under copyright by BBMP.

You are free:

* **To share**: To copy, distribute and use the database.
* **To create**: To produce works from the database.
* **To adapt**: To modify, transform and build upon the database.

As long as you:

* **Attribute**: You must attribute any public use of the database, or works produced from the database, in the manner specified in the ODbL. For any use or redistribution of the database, or works produced from it, you must make clear to others the license of the database and keep intact any notices on the original database.
* **Share-Alike**: If you publicly use any adapted version of this database, or works produced from an adapted database, you must also offer that adapted database under the ODbL.
* **Keep open**: If you redistribute the database, or an adapted version of it, then you may use technological measures that restrict the work (such as DRM) as long as you also redistribute a version without such measures.

## Credits

- [IFMS Portal](https://account.bbmpgov.in/vsswb/)
- [BBMP Works Bill Public View](https://account.bbmpgov.in/PublicView/?l=1)

## AI Declaration

Components of this repository, including code and documentation, were written with AI assistance.
