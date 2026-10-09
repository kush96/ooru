# blr-municipal-accounts

The source data is fetched from two BBMP portals:

| Source | Endpoint | Datasets |
|--------|----------|----------|
| `publicview` | [Works Bill Public View](https://account.bbmpgov.in/PublicView/?l=1) | bills |
| `ifms` | [IFMS Portal](https://account.bbmpgov.in/vsswb/) | payments, receipts, DC bills |

The `ifms` endpoints no longer return data. Only `publicview` is used by default.
It has details on works bills, published as the `bills` dataset that contains
similar columns to the `payments` dataset from `ifms`.

Each dataset is published as a Parquet file and an equivalent zipped CSV.
The two formats carry identical rows and columns.

Amounts are in Indian Rupees. Dates are calendar dates (`YYYY-MM-DD`); the
`approval_date` fields also carry a time component. Rows are ordered
in reverse chronological order.

`year` and `month` are the reporting period the row was listed under at source.
They are kept alongside `date` because they both can vary. For
payments and receipts `date` always falls inside the reporting period. For DC
bills it is the bill date, which precedes the period, the period follows the RTGS
disbursement, for about two thirds of rows. Use `year`/`month` for period
filtering, and `date` for the event the row records. In `bills` the period
is the bill-register month instead.

## Wards

Where a row carries a ward it is split into three columns placed just after
`date`:

| Column | Description |
|--------|-------------|
| ward_number | Ward number within its delimitation scheme |
| ward_name | Ward name |
| ward_scheme | Which delimitation the number follows: `198`, `243`, `225`, or `special` |

BBMP has undergone multiple rounds of delimitation, so the same area can appear under a
different number in each scheme. `ward_scheme` records which one a row's
`ward_number` belongs to — the original **198**-ward system, the **243**-ward
(2022) system, or the more recent **225**-ward system. `special` marks BBMP-wide units
that are not geographic wards (e.g. `0 Common`, `301 Mayor`, and the Chief
Engineer wings numbered 300+). DC bills carry no ward.

## Data Dictionary

### [bills.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/bills.parquet) / [bills.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/bills.csv.zip)

Each row is a work bill as published on the
[Works Bill Public View](https://account.bbmpgov.in/PublicView/?l=1).

PublicView lists a bill under the month its Detailed Bill Register (BR) entry was
raised. `year`/`month` therefore track the BR date, which `dbr_date` also
records. `date` is still the RTGS disbursement date.

The columns mirror the `payments` dataset, minus the ones PublicView does not
serve: the release breakdown (`release_percentage`, `release_gross_amount`,
`release_net_amount`), the bank UTRs (`contractor_utr`, `deduction_utr`), and the
common bill register (`common_br_number`, `common_br_date`). These are dropped
rather than published empty.

| Column | Type | Description |
|--------|------|-------------|
| date | date | Payment date (RTGS disbursement date) |
| ward_number | int32 | Ward number (see [Wards](#wards)) |
| ward_name | string | Ward name |
| ward_scheme | string | Ward delimitation scheme (`198`/`243`/`225`/`special`) |
| work_bill_id | string | Work bill identifier |
| job_number | string | Work order / job number |
| work_description | string | Description of the work billed |
| work_order_title | string | Parent work-order title; populated only when it differs from `work_description` |
| work_order_number | string | Work order number |
| work_order_date | date | Work order date |
| bill_type | string | Bill instalment (e.g. First and Final, Second and Final) |
| category | string | Fund / scheme category |
| budget_head | string | Budget head the bill is drawn against |
| work_type | string | Work-order document stage (Estimates, AS, TS, DPR, Agreement, …) |
| contractor_name | string | Name of the contractor |
| contractor_mobile | string | Contractor mobile number |
| contractor_email | string | Contractor email address |
| ddo_name | string | Drawing and Disbursing Officer name |
| approver_name | string | Name of the final approver |
| gross_amount | float | Gross bill amount |
| net_amount | float | Net amount paid after deductions |
| deduction_amount | float | Total deductions |
| sbr_number | string | Sub Bill Register number |
| sbr_date | date | Sub Bill Register date |
| dbr_number | string | Detailed Bill Register number |
| dbr_date | date | Detailed Bill Register date |
| cbr_number | string | Consolidated Bill Register number |
| cbr_date | date | Consolidated Bill Register date |
| rtgs_number | string | RTGS transaction number |
| rtgs_date | date | RTGS transaction date |
| rtgs_legs | string | JSON array of every RTGS leg (`number`, `date`), oldest first; populated only when the bill was disbursed more than once |
| current_level | int64 | Current workflow level |
| current_level_name | string | Name of the current workflow level |
| tvcc_required | int64 | Whether TVCC clearance is required |
| approval_date | datetime | Final approval timestamp |
| approval_id | int64 | Final approval identifier |
| approval_system_type | string | System type recorded against the final approval |
| approval_remarks | string | Final approval remarks |
| files | string | JSON array of attached files (`name`, `type`, `remarks`) |
| year | int32 | Reporting year |
| month | int32 | Reporting month |

### [payments.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/payments.parquet) / [payments.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/payments.csv.zip)

Each row is a payment (work bill) against a work order on the IFMS Portal.

A bill is sometimes disbursed more than once, as a re-issued RTGS for the same
amount. It still gets a single row: `rtgs_number`, `rtgs_date`, `year` and `month`
describe the first disbursement, and `rtgs_legs` lists every leg.

| Column | Type | Description |
|--------|------|-------------|
| date | date | Payment date (RTGS disbursement date) |
| ward_number | int32 | Ward number (see [Wards](#wards)) |
| ward_name | string | Ward name |
| ward_scheme | string | Ward delimitation scheme (`198`/`243`/`225`/`special`) |
| work_bill_id | string | Work bill identifier |
| job_number | string | Work order / job number |
| work_description | string | Description of the work billed |
| work_order_title | string | Parent work-order title; populated only when it differs from `work_description` |
| work_order_number | string | Work order number |
| work_order_date | date | Work order date |
| bill_type | string | Bill instalment (e.g. First and Final, Second and Final) |
| category | string | Fund / scheme category |
| budget_head | string | Budget head the payment is drawn against |
| work_type | string | Work-order document stage (Estimates, AS, TS, DPR, Agreement, …) |
| contractor_name | string | Name of the contractor |
| contractor_mobile | string | Contractor mobile number |
| contractor_email | string | Contractor email address |
| ddo_name | string | Drawing and Disbursing Officer name |
| approver_name | string | Name of the final approver |
| gross_amount | float | Gross bill amount |
| net_amount | float | Net amount paid after deductions |
| deduction_amount | float | Total deductions |
| release_percentage | float | Percentage of the work value released in this instalment |
| release_gross_amount | float | Gross amount released in this instalment |
| release_net_amount | float | Net amount released in this instalment |
| contractor_utr | string | Bank UTR reference for the contractor-payment leg |
| deduction_utr | string | Bank UTR reference for the deduction leg |
| sbr_number | string | Sub Bill Register number |
| sbr_date | date | Sub Bill Register date |
| dbr_number | string | Detailed Bill Register number |
| dbr_date | date | Detailed Bill Register date |
| cbr_number | string | Consolidated Bill Register number |
| cbr_date | date | Consolidated Bill Register date |
| common_br_number | string | Common Bill Register number |
| common_br_date | date | Common Bill Register date |
| rtgs_number | string | RTGS transaction number |
| rtgs_date | date | RTGS transaction date |
| rtgs_legs | string | JSON array of every RTGS leg (`number`, `date`), oldest first; populated only when the bill was disbursed more than once |
| current_level | int64 | Current workflow level |
| current_level_name | string | Name of the current workflow level |
| tvcc_required | string | Whether TVCC clearance is required |
| approval_date | datetime | Final approval timestamp |
| approval_id | int64 | Final approval identifier |
| approval_system_type | string | System type recorded against the final approval |
| approval_remarks | string | Final approval remarks |
| files | string | JSON array of attached files (`name`, `type`, `remarks`) |
| year | int32 | Reporting year |
| month | int32 | Reporting month |

### [receipts.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/receipts.parquet) / [receipts.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/receipts.csv.zip)

Each row is a receipt (collection) recorded on the IFMS Portal.

| Column | Type | Description |
|--------|------|-------------|
| date | date | Receipt date as recorded at source (occasionally unreliable) |
| ward_number | int32 | Ward number (see [Wards](#wards)) |
| ward_name | string | Ward name |
| ward_scheme | string | Ward delimitation scheme (`198`/`243`/`225`/`special`) |
| receipt_id | string | Receipt identifier |
| receipt_number | string | Receipt serial number |
| receipt_type | string | Receipt type code (e.g. RE-ifms083-RC) |
| payer_name | string | Name of the payer / depositor |
| account_head | string | Primary revenue head the receipt is credited to (e.g. `R0175 Rent from Shops`) |
| amount | float | Receipt amount |
| audit_recovery | float | Audit recovery amount on the primary account head |
| payment_mode | string | Payment instrument type (e.g. Cash, DD, Cheque) |
| instrument_bank | string | Bank and branch for the payment instrument, when applicable |
| instrument_number | string | Payment instrument (DD/cheque) number |
| instrument_date | date | Payment instrument date |
| receipt_items | JSON | All revenue heads on the receipt, each `{head, amount, audit_recovery}` |
| year | int32 | Reporting year |
| month | int32 | Reporting month |

### [dc-bills.parquet](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/dc-bills.parquet) / [dc-bills.csv.zip](https://raw.githubusercontent.com/Vonter/blr-municipal-accounts/main/data/dc-bills.csv.zip)

Each row is a DC (Detailed Contingent) bill on the IFMS Portal, including its
deduction breakdown.

| Column | Type | Description |
|--------|------|-------------|
| date | date | Bill date |
| dc_bill_id | string | DC bill identifier |
| bill_number | string | Bill number |
| remarks | string | Bill remarks |
| budget_head | string | Budget head the bill is drawn against |
| payee_name | string | Name the bill is drawn in favour of |
| payee_address | string | Payee address |
| payee_city | string | Payee city |
| ddo_name | string | Drawing and Disbursing Officer name |
| paying_ddo_id | int64 | Paying DDO identifier |
| approver_name | string | Name of the final approver |
| gross_amount | float | Gross bill amount |
| net_amount | float | Net amount paid after deductions |
| deduction_amount | float | Total deductions (gross amount minus net amount) |
| income_tax | float | Income tax deducted |
| vat | float | VAT deducted |
| royalty | float | Royalty deducted |
| labour_cess | float | Labour cess deducted |
| corpus_fund | float | Corpus / building fund deduction |
| security_deposit | float | Further security deposit (FSD) |
| fine | float | Fine deducted |
| measurement_deduction | float | Measurement deduction |
| mobilization_advance | float | Mobilization advance recovered |
| other_advances | float | Other advances recovered |
| difference_emd | float | Difference in earnest money deposit |
| cgst_percentage | float | CGST percentage |
| sgst_percentage | float | SGST percentage |
| igst_percentage | float | IGST percentage |
| other_deductions | string | JSON object of further captioned deductions (`caption`: amount) |
| cheque_favouring_name | string | Name the cheque/RTGS is drawn in favour of |
| cheque_favouring_bank | string | Bank the cheque/RTGS is drawn in favour of |
| cheque_favouring_account | string | Account the cheque/RTGS is drawn in favour of |
| cheque_favouring_gstin | string | GSTIN of the favouring party |
| rtgs_sub_name | string | RTGS sub-account name |
| rtgs_number | string | RTGS transaction number |
| rtgs_date | date | RTGS transaction date |
| approval_date | datetime | Final approval timestamp |
| submit_to | int64 | Identifier of the officer the bill is submitted to |
| saved | int64 | Draft/saved status flag |
| certifications | string | JSON array of certification statements |
| bill_items | string | JSON array of bill line items (`caption`, `nature`, `value`) |
| files | string | JSON array of attached files (`name`, `type`, `remarks`) |
| approvals | string | JSON array of the approval chain (`name`, `date`, `remarks`, `system_type`, `id`) |
| year | int32 | Reporting year |
| month | int32 | Reporting month |

## Pipeline

Various options are available when running `fetch.py`:

```sh
# Rebuild the bills dataset from the Public View portal
uv run fetch.py --parse

# Rebuilt the datasets from the IFMS portal
uv run fetch.py --source ifms --parse

# Limit a routine run to recent months
uv run fetch.py --recent 3 --parse

# Fetch specific periods or data types
uv run fetch.py --period 2024,2025-01
uv run fetch.py --source ifms --types payments,receipts --parse

# Repair missing or partial details using lists already on disk
uv run fetch.py --skip lists

# Force a detail refresh when portal-side changes are not visible in its lists
uv run fetch.py --recent 3 --refresh --parse
```

Various options are available when running `parse.py`:

```sh
# Update datasets from changed raw files already on disk
uv run parse.py

# Rebuild from all available raw JSON
uv run parse.py --reparse

# Parse the raw files of a specific source
uv run parse.py --source ifms
```

Incremental parsing detects changed raw files, replaces existing rows by their stable
portal IDs, and keeps full detail rows when older raw files are no longer present.
Changed and incomplete detail refreshes remain queued across interrupted or list-only
runs, and are removed from the queue only after every fresh endpoint succeeds.
