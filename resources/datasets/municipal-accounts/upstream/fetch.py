#!/usr/bin/env python3
"""Fetch payments, receipts, and DC bills from the IFMS Portal and the Works Bill Portal."""

import argparse
import calendar
import json
import logging
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

IFMS_BASE_URL = "https://account.bbmpgov.in/vsswb/vss00CvStatusData.php"
PUBLIC_VIEW_BASE_URL = "https://account.bbmpgov.in/PublicView/vss00CvStatusData.php"
PUBLIC_VIEW_HOME_URL = "https://account.bbmpgov.in/PublicView/?l=1"

# The portal answers requests made without a primed session with this error.
SESSION_ERROR = "dgLanguage"

# PublicView detail endpoints, keyed by the name each response is stored under.
PUBLIC_VIEW_DETAIL_ACTIONS = {
    "details": ("POST", "LoadWorksbillDetails"),
    "approval_levels": ("GET", "LoadGridApprovalLevels"),
    "files": ("POST", "LoadWBFiles"),
}

MAX_CONSECUTIVE_FAILURES = 5
FAILURE_BACKOFF_SECONDS = 60
ROW_KEY = {"payments": "work_bill_id", "receipts": "receipt_id", "dc_bills": "dc_bill_id"}
RESOLVED_OUTCOMES = frozenset({"updated", "complete", "skipped"})
FAILED_OUTCOMES = ("failed", "partial", "no_endpoints", "no_id")

_backoff_until = 0.0
_backoff_lock = threading.Lock()

WARD_IDS = [
    300, *range(2001, 2226), *range(301, 319), *range(1001, 1242), *range(1, 199)
]
DDO_IDS = (
    [*range(15, 501), *range(502, 544)]
    + [value for value in range(545, 609) if value not in {562, 565, 579, 582, 589, 596}]
    + [*range(708, 870), *range(871, 884), *range(901, 911)]
)
ZONE_IDS = [7, 1, 10, 4, 8, 9, 3, 5, 6]
WARD_IDS_PARAM = ",".join(map(str, WARD_IDS))
DDO_IDS_PARAM = ",".join(map(str, DDO_IDS))
ZONE_IDS_PARAM = ",".join(map(str, ZONE_IDS))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/x-www-form-urlencoded",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Priority": "u=0",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}


# --- URL building -----------------------------------------------------------


def _ts():
    return int(time.time() * 1000)


def _url(action, **params):
    query = "&".join(f"{key}={value}" for key, value in {"pAction": action, **params}.items())
    return f"{BASE_URL}?{query}"


def _paging(page_size=10, record_end=None, timestamp=None):
    return {
        "filterscount": 0,
        "groupscount": 0,
        "pagenum": 0,
        "pagesize": page_size,
        "recordstartindex": 0,
        "recordendindex": page_size if record_end is None else record_end,
        "_": _ts() if timestamp is None else timestamp,
    }


def _get(action, record_end=None, timestamp=None, **params):
    return "GET", _url(action, **params, **_paging(10, record_end, timestamp))


def _post(action, **params):
    return "POST", _url(action, **params)


def _first_id(entry, *keys):
    return str(next((entry.get(key) for key in keys if entry.get(key)), ""))


def _extract_job_number(wodetails):
    if not wodetails:
        return None
    match = re.search(r"vssFillData\([^,]+,\s*['\"]([^'\"]+)['\"]", wodetails)
    if match:
        return match.group(1)
    match = re.search(r"\d{3}-\d{2}-\d{6}", wodetails)
    return match.group(0) if match else None


def _payment_endpoints(entry):
    work_bill_id = str(entry.get("id", ""))
    job_number = _extract_job_number(entry.get("wodetails", ""))
    if not (work_bill_id and job_number):
        return None
    timestamp = _ts()
    return {
        "type_combo": _get(
            "LoadTypeCombo", 17.8, timestamp, pJobNumber=job_number, pSelection=1),
        "approval_levels": _get(
            "LoadGridApprovalLevels", timestamp=timestamp, pWorkBillID=work_bill_id),
        "files": _post("LoadWBFiles", pWorkBillID=work_bill_id),
        "details": _post("LoadDetails", pWorkBillID=work_bill_id),
    }


def _receipt_endpoints(entry):
    receipt_id = _first_id(entry, "id", "receiptmainid", "receiptMainID")
    if not receipt_id:
        return None
    timestamp = _ts()
    return {
        f"fill_data_{where}": (
            _post("LoadReceiptsFillData", pFromWhere=where, pReceiptMainID=receipt_id)
            if where == 1 else
            _get("LoadReceiptsFillData", 32, timestamp,
                 pFromWhere=where, pReceiptMainID=receipt_id)
        )
        for where in (1, 2, 3)
    }


def _dc_bill_endpoints(entry):
    dc_bill_main_id = _first_id(entry, "id", "dcbillmainid", "dcBillMainID")
    work_bill_id = _first_id(entry, "id", "workbillid", "workBillID")
    if not (dc_bill_main_id and work_bill_id):
        return None
    return {
        "fill_data": _post("LoadDCBillFillData", pDCBillMainID=dc_bill_main_id),
        "deductions": _post("LoadDeductions", pWorkBillID=work_bill_id),
        "approval_levels": _get("LoadGridApprovalLevels", pWorkBillID=work_bill_id),
        "files": _post("LoadFilesDetails", pMainID=dc_bill_main_id, pCheck=1),
    }


def _public_view_id(entry):
    return str((entry or {}).get("wbid") or "")


def _public_view_endpoints(entry):
    work_bill_id = _public_view_id(entry)
    if not work_bill_id:
        return None
    return {
        key: (method, _url(action, pWorkBillID=work_bill_id))
        for key, (method, action) in PUBLIC_VIEW_DETAIL_ACTIONS.items()
    }


def _ifms_list_url(data_type, date_from, date_to, ward_id=None):
    """Build a monthly, yearly, or single-ward IFMS list request."""
    cfg = DATA_TYPES[data_type]
    suffix = cfg["suffix"]
    params = {
        f"pDateFrom{suffix}": date_from,
        f"pDateTo{suffix}": date_to,
        f"pBudgetHeadID{suffix}": "-1",
    }
    if cfg["wards"]:
        params[f"pWardIDs{suffix}"] = WARD_IDS_PARAM if ward_id is None else str(ward_id)
    params[f"pDDOID{suffix}"] = "-1"
    if cfg["zones"]:
        params[f"pZoneIDs{suffix}"] = ZONE_IDS_PARAM
    params[f"pDDOIDs{suffix}"] = DDO_IDS_PARAM
    return _url(cfg["action"], **params, **_paging(5))


def _public_view_list_url(data_type, date_from, date_to, ward_id=None):
    """Build an unfiltered PublicView list of the bills registered in a range.

    pOrderBy picks the date the range filters on: 1 the work order, 2 the
    Detailed Bill Register. Filtering on the register date rather than the RTGS
    date makes a monthly list the bills registered that month, disbursed or not.
    """
    return _url(
        "LoadPaymentGridData",
        pCriteria="", pDateFrom=date_from, pDateTo=date_to, pDateType="pDT",
        pDateFilterYN="true", pOrderBy=2, pFinancialYearID=-1, pBudgetHeadID=-1,
        pDDOIDs=-1, pWardIDs="", pWardID=-1,
    )


# --- Sources ----------------------------------------------------------------

# Each source supplies its endpoints, its on-disk namespace, and the data types
# it publishes. Switching sources rebinds the module globals they configure.

SOURCES = {
    "ifms": {
        "base_url": IFMS_BASE_URL,
        "referer": "https://account.bbmpgov.in/vsswb/",
        "home_url": None,
        "raw_dir": Path("raw"),
        "data_dir": Path("data"),
        "first_year": 2014,
        "entry_id": lambda entry: str(entry.get("id", "")),
        "list_url": _ifms_list_url,
        "data_types": {
            "payments": {
                "action": "LoadPaymentGridData", "suffix": "", "wards": True, "zones": False,
                "endpoints": _payment_endpoints,
            },
            "receipts": {
                "action": "LoadReceiptsGridData", "suffix": "Receipts", "wards": True,
                "zones": False, "endpoints": _receipt_endpoints,
            },
            "dc_bills": {
                "action": "LoadDCBillGridData", "suffix": "DCBill", "wards": False,
                "zones": True, "endpoints": _dc_bill_endpoints,
            },
        },
    },
    "publicview": {
        "base_url": PUBLIC_VIEW_BASE_URL,
        "referer": PUBLIC_VIEW_HOME_URL,
        "home_url": PUBLIC_VIEW_HOME_URL,
        "raw_dir": Path("raw") / "publicview",
        "data_dir": Path("data"),
        "first_year": 2010,
        "entry_id": _public_view_id,
        "list_url": _public_view_list_url,
        # Wards ride along in each list row, so no per-ward crawl is needed.
        "data_types": {
            "payments": {
                "wards": False, "endpoints": _public_view_endpoints, "slug": "bills",
            },
        },
    },
}
DEFAULT_SOURCE = "publicview"


def use_source(name):
    """Point the module at one source's endpoints, paths, and data types."""
    global SOURCE, BASE_URL, RAW_DIR, DATA_DIR, PENDING_FILE, DATA_TYPES, FIRST_YEAR
    SOURCE = SOURCES[name]
    BASE_URL = SOURCE["base_url"]
    RAW_DIR = SOURCE["raw_dir"]
    DATA_DIR = SOURCE["data_dir"]
    PENDING_FILE = RAW_DIR / "pending-details.json"
    DATA_TYPES = SOURCE["data_types"]
    FIRST_YEAR = SOURCE["first_year"]
    HEADERS["Referer"] = SOURCE["referer"]


use_source(DEFAULT_SOURCE)


def _list_url(data_type, date_from, date_to, ward_id=None):
    return SOURCE["list_url"](data_type, date_from, date_to, ward_id)


# --- HTTP and storage -------------------------------------------------------


SESSION = requests.Session()


def prime_session():
    """Open the portal's landing page, which is what grants a usable session."""
    home = SOURCE["home_url"]
    if not home:
        return
    try:
        SESSION.get(home, headers=HEADERS, timeout=60, verify=False)
    except requests.RequestException as exc:
        logger.warning(f"Could not prime a session at {home}: {exc}")


def _portal_error(result):
    """The portal reports failures as HTTP 200 with an rError body."""
    return result.get("rError") if isinstance(result, dict) else None


def make_request(url, method="GET", max_retries=5, timeout=300):
    for attempt in range(1, max_retries + 1):
        try:
            headers = dict(HEADERS)
            if method == "POST":
                headers["Content-Length"] = "0"
            response = SESSION.request(
                method, url, headers=headers, timeout=timeout, verify=False
            )
            if response.status_code == 200:
                result = response.json()
                error = _portal_error(result)
                if error is None:
                    return result
                logger.warning(f"Portal error for {url}: {error}")
                if SESSION_ERROR in str(error):
                    prime_session()
            else:
                logger.warning(
                    f"HTTP {response.status_code} for {url} (attempt {attempt}/{max_retries})"
                )
        except requests.exceptions.SSLError as exc:
            logger.error(f"SSL error for {url}: {exc}")
            return None
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                f"Request error for {url} (attempt {attempt}/{max_retries}): {exc}"
            )
        if attempt < max_retries:
            time.sleep(2**attempt)
    return None


def extract_records(result):
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("records", "data", "rows", "Records", "Data", "Rows"):
            if key in result:
                return result[key]
    return []


def load_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return None


def save_json(data, path):
    """Write only changed JSON so parsers can use file mtimes incrementally."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if load_json(path) == data:
        return False
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return True


def list_path(data_type, year, month):
    return RAW_DIR / data_type / str(year) / f"{month:02d}.json"


def details_path(data_type, year, month):
    return RAW_DIR / data_type / str(year) / f"{month:02d}_details"


def pending_key(data_type, year, month):
    return f"{data_type}/{year}/{month:02d}"


def load_pending():
    """Detail IDs still queued for a refresh, from earlier or interrupted runs."""
    data = load_json(PENDING_FILE)
    if not isinstance(data, dict):
        return {}
    return {
        key: {str(entry_id) for entry_id in ids}
        for key, ids in data.items()
        if isinstance(ids, list)
    }


def save_pending(pending):
    save_json({key: sorted(ids) for key, ids in sorted(pending.items()) if ids}, PENDING_FILE)


# --- Month selection --------------------------------------------------------


def _prev_month(date):
    return (
        datetime(date.year - 1, 12, 1) if date.month == 1
        else datetime(date.year, date.month - 1, 1)
    )


def _this_month():
    today = datetime.now()
    return datetime(today.year, today.month, 1)


def month_bounds(date):
    last_day = calendar.monthrange(date.year, date.month)[1]
    return date.replace(day=1), date.replace(day=last_day)


def generate_months(periods=None):
    """Every month from the current one back to FIRST_YEAR, newest first."""
    current, months = _this_month(), []
    while current.year >= FIRST_YEAR:
        if not periods or {(current.year, current.month), (current.year, None)} & periods:
            months.append(current)
        current = _prev_month(current)
    return months


def recent_months(count):
    current, months = _this_month(), []
    for _ in range(count):
        months.append(current)
        current = _prev_month(current)
    return months


# --- Lists ------------------------------------------------------------------


def fetch_month_list(data_type, date):
    first, last = month_bounds(date)
    result = make_request(
        _list_url(data_type, first.strftime("%d-%b-%Y"), last.strftime("%d-%b-%Y"))
    )
    if result is None:
        return None
    records = extract_records(result)
    logger.info("  %s: %s items", data_type, len(records))
    return records


def _entry_id(entry):
    return SOURCE["entry_id"](entry)


def _entry_map(records):
    return {
        entry_id: entry
        for entry in records or []
        if isinstance(entry, dict) and (entry_id := _entry_id(entry))
    }


def _changed_ids(old_records, new_records):
    old = _entry_map(old_records)
    return {
        entry_id for entry_id, entry in _entry_map(new_records).items()
        if old.get(entry_id) != entry
    }


def fetch_all_lists(months, data_types, existing_ids, pending):
    """Refresh monthly lists and return new or changed IDs per type and month."""
    consecutive_failures = dict.fromkeys(data_types, 0)
    changed, failures = {}, 0

    for date in months:
        year, month = date.year, date.month
        logger.info(f"Fetching lists for {date.strftime('%B %Y')}")

        for data_type in data_types:
            file_path = list_path(data_type, year, month)
            old_records = load_json(file_path)
            records = fetch_month_list(data_type, date)
            if records is None:
                consecutive_failures[data_type] += 1
                failures += 1
                continue

            ids = _changed_ids(old_records, records)
            if old_records is None:
                ids -= existing_ids.get(data_type, set())
            if ids:
                changed[(data_type, year, month)] = ids
                pending.setdefault(pending_key(data_type, year, month), set()).update(ids)
                save_pending(pending)
            save_json(records, file_path)
            consecutive_failures[data_type] = 0

        if min(consecutive_failures.values()) >= MAX_CONSECUTIVE_FAILURES:
            logger.info(
                f"Stopping after {MAX_CONSECUTIVE_FAILURES} consecutive failures across all types"
            )
            break
        time.sleep(1)
    return changed, failures


def fetch_ward_dropdown():
    dropdown_file = RAW_DIR / "ward_dropdown.json"
    if isinstance(load_json(dropdown_file), list):
        logger.info("  Ward dropdown already exists, skipping fetch")
        return 0
    result = make_request(_url("LoadCombo", pTableName="vssmasters.vss20toward"))
    if not isinstance(result, list):
        logger.error("  Ward dropdown fetch failed")
        return 1
    changed = save_json(result, dropdown_file)
    logger.info(
        "  Ward dropdown: %s entries (%s)", len(result), "updated" if changed else "unchanged"
    )
    return 0


def fetch_ward_lists(data_type, year, skip_existing):
    """Fetch a year of lists one ward at a time, to recover per-entry ward IDs."""
    wards_dir = RAW_DIR / data_type / str(year) / "wards"
    fetched = failures = 0

    for ward_id in WARD_IDS:
        ward_file = wards_dir / f"{ward_id}.json"
        if skip_existing and ward_file.exists():
            continue
        result = make_request(
            _list_url(data_type, f"01-Jan-{year}", f"31-Dec-{year}", ward_id)
        )
        if result is None:
            failures += 1
            continue
        records = extract_records(result)
        save_json(records, ward_file)
        fetched += bool(records)
        time.sleep(0.5)

    logger.info("  %s by ward for %s: %s wards with data", data_type, year, fetched)
    return failures


def fetch_all_ward_lists(months, data_types):
    """Refresh ward lists for the current year; fill earlier years only if missing."""
    ward_types = [dt for dt in data_types if DATA_TYPES[dt]["wards"]]
    if not ward_types:
        return 0

    _log_section("Fetching ward dropdown mapping")
    failures = fetch_ward_dropdown()
    current_year = datetime.now().year
    for data_type in ward_types:
        _log_section(f"Fetching {data_type} ward lists")
        for year in sorted({date.year for date in months}, reverse=True):
            if year != current_year and (RAW_DIR / data_type / str(year) / "wards").exists():
                continue
            logger.info(f"Fetching {data_type} wards for {year}")
            failures += fetch_ward_lists(data_type, year, skip_existing=year != current_year)
            time.sleep(1)
    return failures


# --- Details ----------------------------------------------------------------


def _respect_backoff():
    while (wait := _backoff_until - time.time()) > 0:
        time.sleep(min(wait, 5))


def _trigger_backoff():
    global _backoff_until
    with _backoff_lock:
        _backoff_until = max(_backoff_until, time.time() + FAILURE_BACKOFF_SECONDS)


def _dedup_entries(items):
    seen, unique = set(), []
    for entry in items:
        entry_id = _entry_id(entry)
        if entry_id and entry_id not in seen:
            seen.add(entry_id)
            unique.append(entry)
    return unique


def _detail_complete(path, endpoints):
    data = load_json(path)
    return isinstance(data, dict) and all(data.get(key) is not None for key in endpoints)


def _needs_fetch(cfg, entry, details_dir, refresh_ids, refresh_all, existing_ids):
    entry_id = _entry_id(entry)
    if not entry_id or refresh_all or entry_id in refresh_ids:
        return True
    endpoints = cfg["endpoints"](entry)
    detail_file = details_dir / f"{entry_id}.json"
    if detail_file.exists():
        return endpoints is None or not _detail_complete(detail_file, endpoints)
    return entry_id not in existing_ids


def _fetch_entry(cfg, entry, details_dir, refresh):
    """Fetch the missing endpoints of one entry and return its outcome."""
    entry_id = _entry_id(entry)
    if not entry_id:
        return "no_id"
    endpoints = cfg["endpoints"](entry)
    if not endpoints:
        return "no_endpoints"
    detail_file = details_dir / f"{entry_id}.json"
    if not refresh and _detail_complete(detail_file, endpoints):
        return "skipped"

    _respect_backoff()
    details = load_json(detail_file) or {}
    attempted = succeeded = 0
    for key, (method, url) in endpoints.items():
        if not refresh and details.get(key) is not None:
            continue
        attempted += 1
        result = make_request(url, method=method)
        if result is not None:
            details[key] = result
            succeeded += 1
        time.sleep(0.5)

    changed = False
    if succeeded:
        changed = save_json(details, detail_file)
        time.sleep(1)
    if succeeded < attempted:
        if not succeeded:
            _trigger_backoff()
        return "partial" if succeeded else "failed"
    if all(details.get(key) is not None for key in endpoints):
        return "updated" if changed else "complete"
    if attempted:
        _trigger_backoff()
        return "failed"
    return "skipped"


def fetch_month_details(data_type, date, workers, refresh_ids, refresh_all, existing_ids):
    """Fetch new, changed, or incomplete details for one month, in parallel."""
    cfg = DATA_TYPES[data_type]
    year, month = date.year, date.month
    label = f"{data_type} {year}-{month:02d}"

    items = load_json(list_path(data_type, year, month))
    if items is None:
        return set(), set(refresh_ids), Counter(failed=max(1, len(refresh_ids)))

    details_dir = details_path(data_type, year, month)
    entries = _dedup_entries(items)
    stale = set(refresh_ids) - {_entry_id(entry) for entry in entries}
    todo = [
        entry for entry in entries
        if _needs_fetch(cfg, entry, details_dir, refresh_ids, refresh_all, existing_ids)
    ]
    if not todo:
        return stale, set(), Counter()

    logger.info(f"  {label}: {len(todo)} to fetch ({workers} worker{'s' if workers != 1 else ''})")

    def fetch_one(entry):
        entry_id = _entry_id(entry)
        refresh = refresh_all or entry_id in refresh_ids
        return entry_id, _fetch_entry(cfg, entry, details_dir, refresh)

    counts, resolved, started = Counter(), set(), time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for entry_id, outcome in pool.map(fetch_one, todo):
            counts[outcome] += 1
            if outcome in RESOLVED_OUTCOMES:
                resolved.add(entry_id)
            done = counts.total()
            if done % 500 == 0:
                rate = done / (time.time() - started)
                logger.info(
                    f"    {label}: {done}/{len(todo)} ({rate:.2f}/s, {counts['failed']} failed)"
                )
    logger.info(f"  {label} done: {dict(counts)}")

    attempted = {_entry_id(entry) for entry in todo}
    return resolved | stale, attempted - resolved, counts


def fetch_all_details(months, data_types, changed, workers, refresh_all, existing_ids, pending):
    """Fetch details for every month, keeping unresolved IDs queued for later runs."""
    failures = 0
    for date in months:
        for data_type in data_types:
            key = pending_key(data_type, date.year, date.month)
            queued = pending.get(key, set())
            refresh_ids = set(changed.get((data_type, date.year, date.month), ())) | queued
            resolved, unresolved, counts = fetch_month_details(
                data_type, date, workers, refresh_ids, refresh_all,
                existing_ids.get(data_type, set()),
            )
            remaining = (queued | unresolved) - resolved
            if remaining:
                pending[key] = remaining
            else:
                pending.pop(key, None)
            if queued or unresolved:
                save_pending(pending)
            failures += sum(counts[outcome] for outcome in FAILED_OUTCOMES)
    return failures


def existing_detail_ids(data_type):
    """Read IDs already backed by detail rows from the full Parquet."""
    slug = DATA_TYPES[data_type].get("slug") or data_type.replace("_", "-")
    path = DATA_DIR / "full" / f"{slug}.parquet"
    if not path.exists():
        return set()
    try:
        import polars as pl

        row_key = ROW_KEY[data_type]
        columns = pl.read_parquet_schema(path)
        wanted = [c for c in (row_key, "source_file", "source_type") if c in columns]
        frame = pl.read_parquet(path, columns=wanted)
        if "source_type" in frame.columns:
            frame = frame.filter(pl.col("source_type").is_null())
        if data_type == "payments":
            ids = (
                frame["source_file"]
                .filter(frame["source_file"].str.contains("_details"))
                .str.extract(r"/(\d+)\.json$", 1)
            )
            if row_key in frame.columns:
                ids = pl.concat([ids, frame[row_key].cast(pl.String)])
        else:
            ids = frame[row_key].cast(pl.String)
        return set(ids.drop_nulls().to_list())
    except Exception as exc:
        logger.warning(f"  {data_type}: could not read existing IDs from {path}: {exc}")
        return set()


# --- CLI --------------------------------------------------------------------


def run_parse(source, data_types):
    cmd = [sys.executable, "parse.py", "--source", source, "--types", ",".join(data_types)]
    _log_section(f"Parsing: {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode


def _log_section(title, level=logging.INFO):
    logger.log(level, "\n%s\n%s\n%s", "=" * 60, title, "=" * 60)


def _csv_choices(allowed, label):
    def parse(value):
        items = [item.strip() for item in value.split(",") if item.strip()]
        unknown = sorted(set(items) - set(allowed))
        if unknown or not items:
            raise argparse.ArgumentTypeError(
                f"expected a comma-separated subset of {','.join(allowed)}"
            )
        return items
    parse.__name__ = label
    return parse


def _csv_list(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def _periods(value):
    """Parse "2025,2024-03" into {(2025, None), (2024, 3)}."""
    periods = set()
    for item in value.split(","):
        year, _, month = item.strip().partition("-")
        try:
            year, month = int(year), int(month) if month else None
        except ValueError:
            raise argparse.ArgumentTypeError(f"invalid period: {item}") from None
        if month is not None and not 1 <= month <= 12:
            raise argparse.ArgumentTypeError(f"invalid month: {item}")
        periods.add((year, month))
    return periods


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Incrementally fetch BBMP payments, receipts, and DC bills",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--period", type=_periods, metavar="YYYY[-MM]",
        help="Comma-separated years or months (e.g. 2024,2025-01)",
    )
    scope.add_argument(
        "--recent", type=_positive, metavar="N", help="Process only the latest N calendar months"
    )
    parser.add_argument(
        "--source", choices=sorted(SOURCES), default=DEFAULT_SOURCE,
        help="Upstream portal to fetch from",
    )
    parser.add_argument(
        "--types", type=_csv_list, default=None,
        help="Comma-separated data types (default: every type the source publishes)",
    )
    parser.add_argument(
        "--skip", type=_csv_choices(("lists", "wards", "details"), "stages"), default=[],
        help="Comma-separated stages to skip: lists, wards, details",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Re-download all details in scope"
    )
    parser.add_argument(
        "--workers", type=_positive, default=1,
        help="Parallel detail workers; 6-8 is a safe ceiling",
    )
    parser.add_argument(
        "--parse", action="store_true", help="Update Parquet and CSV outputs after fetching"
    )
    args = parser.parse_args(argv)
    use_source(args.source)
    args.types = args.types or list(DATA_TYPES)
    if unknown := sorted(set(args.types) - set(DATA_TYPES)):
        parser.error(
            f"source {args.source} does not publish: {','.join(unknown)} "
            f"(available: {','.join(DATA_TYPES)})"
        )
    return args


def main(argv=None):
    args = _parse_args(argv)
    months = recent_months(args.recent) if args.recent else generate_months(args.period)
    if not months:
        logger.warning("No months to process")
        return 0

    prime_session()
    logger.info(
        f"Source {args.source}: processing {len(months)} months for: {', '.join(args.types)}"
    )
    if args.skip:
        logger.info(f"Skipping: {', '.join(args.skip)}")

    existing_ids = {data_type: existing_detail_ids(data_type) for data_type in args.types}
    logger.info(
        "Existing detail rows: "
        + ", ".join(f"{data_type}={len(ids):,}" for data_type, ids in existing_ids.items())
    )
    pending = load_pending()
    if pending:
        queued = sum(len(ids) for ids in pending.values())
        logger.info(f"Pending detail refreshes from earlier runs: {queued:,}")

    changed, failures = {}, 0
    if "lists" not in args.skip:
        _log_section("Fetching monthly lists")
        changed, list_failures = fetch_all_lists(months, args.types, existing_ids, pending)
        failures += list_failures

    if "wards" not in args.skip:
        failures += fetch_all_ward_lists(months, args.types)

    if "details" not in args.skip:
        _log_section("Fetching new, changed, or incomplete details")
        failures += fetch_all_details(
            months, args.types, changed, args.workers, args.refresh, existing_ids, pending
        )

    if args.parse:
        if failures:
            logger.error(f"Fetch incomplete ({failures:,} failed request(s)); parsing skipped")
        else:
            failures += int(run_parse(args.source, args.types) != 0)

    if failures:
        _log_section(f"Incomplete: {failures:,} failure(s)", logging.ERROR)
        return 1
    _log_section("Done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
