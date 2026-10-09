#!/usr/bin/env python3
"""Parse raw JSON files from the IFMS Portal and the Works Bill Portal into Parquet and zipped CSV."""

import argparse
import json
import logging
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import polars as pl
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
PARSER_VERSION = {"payments": "2", "receipts": "1", "dc_bills": "1"}

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_MONTH_RE = re.compile(r"^(\d{1,2})_")
ZERO_AMOUNTS = ("0.00", "0", "0.0")


# --- Field name normalization -----------------------------------------------

# (category, [(pattern, normalized name), ...]) - first match wins. Patterns are
# "a|b" alternatives of "+"-joined terms, where "!a" negates, "a$" matches a
# suffix, and "*" matches anything.
FIELD_PATTERNS = [
    ("date|dt", [
        ("sbr", "sbr_date"), ("dbr", "dbr_date"), ("cbr", "cbr_date"),
        ("commonbr|common_br", "common_br_date"), ("rtgs", "rtgs_date"),
        ("approval", "approval_date"), ("receipt", "receipt_date"),
        ("payment", "payment_date"), ("entry", "entry_date"),
        ("transaction", "transaction_date"), ("release", "release_date"),
        ("ref", "reference_date"), ("*", "date"),
    ]),
    ("amount|amt", [
        ("total|gross", "total_amount"), ("net", "net_amount"),
        ("deduct", "deduction_amount"), ("paid", "paid_amount"),
        ("received", "received_amount"), ("release+gross", "release_gross_amount"),
        ("release+net", "release_net_amount"), ("release", "release_amount"),
        ("*", "amount"),
    ]),
    ("id$", [
        ("receipt+main", "receipt_main_id"), ("receipt", "receipt_id"),
        ("payment+main", "payment_main_id"), ("payment", "payment_id"),
        ("bill+main", "bill_main_id"), ("work+bill|wb+bill", "work_bill_id"),
        ("dc+bill", "dc_bill_id"), ("bill", "bill_id"), ("ward", "ward_id"),
        ("ddo", "ddo_id"), ("budget", "budget_head_id"), ("approval", "approval_id"),
        ("work|wb", "work_bill_id"),
    ]),
    ("name", [
        ("payer|paid", "payer_name"), ("contractor", "contractor_name"),
        ("ddo", "ddo_name"), ("ward", "ward_name"), ("approval", "approval_name"),
        ("*", "name"),
    ]),
    ("number|no+!note|num", [
        ("sbr", "sbr_number"), ("dbr", "dbr_number"), ("cbr", "cbr_number"),
        ("commonbr|common_br", "common_br_number"), ("receipt", "receipt_number"),
        ("payment", "payment_number"), ("bill", "bill_number"),
        ("voucher", "voucher_number"), ("ref", "reference_number"),
        ("job", "job_number"), ("*", "number"),
    ]),
    ("description|desc|remarks", [
        ("work|wc", "work_description"), ("approval", "approval_remarks"),
        ("*", "description"),
    ]),
    ("status|state", [("*", "status")]),
    ("type", [
        ("payment", "payment_type"), ("bill", "bill_type"), ("system", "system_type"),
        ("*", "type"),
    ]),
    ("mode", [("payment", "payment_mode"), ("*", "mode")]),
    ("bank", [
        ("name", "bank_name"), ("account|acct", "bank_account_number"),
        ("ifsc", "bank_ifsc_code"), ("*", "bank"),
    ]),
    ("address|addr", [("*", "address")]),
    ("mobile|phone", [("contractor", "contractor_mobile"), ("*", "mobile_number")]),
    ("email|mail", [("contractor", "contractor_email"), ("*", "email")]),
    ("words|inwords", [
        ("gross", "gross_amount_in_words"), ("net", "net_amount_in_words"),
        ("deduction", "deduction_amount_in_words"), ("*", "amount_in_words"),
    ]),
    ("rtgs", [("date", "rtgs_date"), ("*", "rtgs_number")]),
    ("release", [
        ("per", "release_percentage"), ("gross", "release_gross_amount"),
        ("net", "release_net_amount"), ("*", "release"),
    ]),
    ("tds|tr+!contractor", [
        ("conu|contds", "contractor_tds"), ("dedu|dedtds", "deduction_tds"), ("*", "tds"),
    ]),
    ("level", [
        ("current+name", "current_level_name"), ("current", "current_level"), ("*", "level"),
    ]),
    ("category", [("*", "category")]),
    ("tvcc", [("required|yn", "tvcc_required"), ("*", "tvcc")]),
    ("file", [
        ("count", "file_count"), ("name", "file_name"), ("path|url", "file_path"),
        ("*", "file"),
    ]),
    ("photo", [("count", "photo_count"), ("*", "photo")]),
]

STRIP_PREFIXES = ["fill_data_", "item_", "type_combo_", "details_", "deduction_"]


def _matches(pattern, field):
    def term_matches(term):
        negated = term.startswith("!")
        term = term.removeprefix("!")
        found = field.endswith(term[:-1]) if term.endswith("$") else term in field
        return found != negated

    return pattern == "*" or any(
        all(term_matches(term) for term in alternative.split("+"))
        for alternative in pattern.split("|")
    )


@lru_cache(maxsize=10000)
def normalize_field_name(field_name):
    lower = field_name.lower()
    for category, mappings in FIELD_PATTERNS:
        if _matches(category, lower):
            for pattern, normalized in mappings:
                if _matches(pattern, lower):
                    return normalized
            break

    if lower.endswith("_id") or "count" in lower:
        return field_name

    cleaned = field_name
    for prefix in STRIP_PREFIXES:
        cleaned = cleaned.removeprefix(prefix)
    cleaned = cleaned.removesuffix("_first")
    return _CAMEL_RE.sub(r"\1_\2", cleaned).lower() or field_name


def rename_fields(fields, prefix=""):
    return {
        normalize_field_name(f"{prefix}_{key}" if prefix else key): value
        for key, value in fields.items()
    }


def flatten_dict(obj, prefix=""):
    if not isinstance(obj, dict):
        return {}
    result = {}
    for key, value in obj.items():
        field = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_dict(value, field))
        elif isinstance(value, list):
            result[f"{field}_count"] = len(value)
            if value:
                if isinstance(value[0], dict):
                    result.update(flatten_dict(value[0], f"{field}_first"))
                elif isinstance(value[0], (str, int, float, bool, type(None))):
                    result[f"{field}_first"] = value[0]
        else:
            result[field] = value
    return result


# --- Value helpers ----------------------------------------------------------


def clean_text(value):
    """Collapse portal line breaks and whitespace."""
    if value is None:
        return None
    text = str(value).replace("<br/>", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip() or None


def json_or_none(obj):
    """Serialize a non-empty collection."""
    return json.dumps(obj, ensure_ascii=False) if obj else None


def _clean_object(source, fields):
    return {
        name: value
        for name, key in fields.items()
        if (value := clean_text(source.get(key)))
    }


def _dicts(value):
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _first_dict(value):
    return value[0] if isinstance(value, list) and value and isinstance(value[0], dict) else {}


def files_to_json(files):
    fields = {"name": "rFileName", "type": "rFileType", "remarks": "rRemarks"}
    return json_or_none([
        obj for entry in _dicts(files) if (obj := _clean_object(entry, fields))
    ])


def approvals_to_json(levels):
    fields = {"date": "date", "remarks": "remarks", "system_type": "systemtype", "id": "id"}
    out = []
    for entry in _dicts(levels):
        obj = _clean_object(entry, fields)
        name = clean_text(entry.get("firstname") or entry.get("name"))
        if name:
            obj = {"name": name, **obj}
        if obj:
            out.append(obj)
    return json_or_none(out)


def indexed_fields_to_json(source, keys, count=20):
    """Group numbered fields into JSON objects."""
    out = []
    for index in range(1, count + 1):
        obj = {
            label: value for label, prefix in keys.items()
            if (value := clean_text(source.get(f"{prefix}{index}")))
        }
        if obj:
            out.append(obj)
    return json_or_none(out)


def captioned_amounts_to_json(source, value_prefix="others", caption_suffix="caption", count=10):
    """Map non-zero captioned amounts into a JSON object."""
    out = {}
    for index in range(1, count + 1):
        caption = clean_text(source.get(f"{value_prefix}{index}{caption_suffix}"))
        amount = clean_text(source.get(f"{value_prefix}{index}"))
        if caption and amount and amount not in ZERO_AMOUNTS:
            out[caption] = amount
    return json_or_none(out)


def receipt_items_to_json(section):
    """Fold receipt account-head lines into JSON."""
    out = []
    for entry in _dicts(section):
        recovery = clean_text(entry.get("auditrecovery"))
        obj = {
            "head": clean_text(entry.get("name")),
            "amount": clean_text(entry.get("amount")),
            "audit_recovery": None if recovery in ZERO_AMOUNTS else recovery,
        }
        if obj := {key: value for key, value in obj.items() if value}:
            out.append(obj)
    return json_or_none(out)


def payment_list_rtgs(entry):
    match = re.search(
        r"Rtgs\s*-\s*([^/<]+?)\s*/\s*(\d{2}-[A-Za-z]{3}-\d{4})",
        str((entry or {}).get("brnumber", "")),
        re.IGNORECASE,
    )
    return (clean_text(match.group(1)), match.group(2)) if match else (None, None)


# A PublicView list row folds its ward, work order, and disbursements into the
# markup of two cells instead of returning them as fields: jobcode carries
# "Ward : ...", brdetails carries "Order : <number> / <date>" and a "Payment :"
# tail of one or more "<number> / <date>" legs.
_WARD_RE = re.compile(r"\bWard : ([^|]*)")
_ORDER_RE = re.compile(r"\bOrder : ([^/|]*?) / (\d{2}-[A-Za-z]{3}-\d{4})")
_LEG_RE = re.compile(r"([^\s/;|]+) / (\d{2}-[A-Za-z]{3}-\d{4})")


def _flatten_markup(html):
    """Flatten a cell's markup, leaving "|" wherever a tag separated content."""
    text = re.sub(r"<[^>]+>", "|", str(html or "")).replace("&nbsp;", " ")
    return re.sub(r"[^\S\n]+", " ", text)


def _public_view_rtgs_legs(entry):
    """Every (number, date) disbursement leg the row reports, oldest first."""
    brdetails = _flatten_markup((entry or {}).get("brdetails"))
    _, marker, payment = brdetails.partition("Payment :")
    return _LEG_RE.findall(payment) if marker else []


def _public_view_markup_fields(entry):
    """Recover the fields a PublicView row publishes only inside its markup."""
    entry = entry or {}
    ward = _WARD_RE.search(_flatten_markup(entry.get("jobcode")))
    order = _ORDER_RE.search(_flatten_markup(entry.get("brdetails")))
    legs = _public_view_rtgs_legs(entry)

    fields = {
        "ward": ward.group(1).strip() or None if ward else None,
        # Shaped like the IFMS "job" and "wodetails" cells the parser reads.
        "job": f"{entry.get('wcname', '')}<br/>{entry.get('nameofwork', '')}",
        "wodetails": f"WO-{order.group(1)}/{order.group(2)}" if order else None,
    }
    if legs:
        fields["rtgs_number"], fields["rtgs_date"] = legs[0]
    return fields


def extract_path_info(file_path):
    year = month = None
    for part in file_path.parts:
        if part.isdigit() and len(part) == 4:
            year = int(part)
        elif part.isdigit() and len(part) <= 2:
            month = int(part)
        elif (m := _MONTH_RE.match(part)) and 1 <= int(m.group(1)) <= 12:
            month = int(m.group(1))
    return year, month


def denull_columns(df):
    """Cast all-null columns to Utf8 so batch concat never mixes Null with String."""
    null_cols = [c for c, t in df.schema.items() if t == pl.Null]
    return df.with_columns([pl.col(c).cast(pl.Utf8) for c in null_cols]) if null_cols else df


# --- Detail parsers ---------------------------------------------------------


def _load_detail(json_path):
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return data if data and isinstance(data, dict) else None
    except Exception as e:
        logger.error(f"Error loading {json_path}: {e}")
        return None


def _merge_list(record, value, prefix, count_key, expand=False):
    """Merge the first item and optionally every item from a list section."""
    if not isinstance(value, list):
        return []
    record[count_key] = len(value)
    if value and isinstance(value[0], dict):
        record.update(rename_fields(flatten_dict(value[0]), prefix))
    if expand:
        for index, item in enumerate(value):
            if isinstance(item, dict):
                record.update(rename_fields(flatten_dict(item), f"{prefix}_{index}"))
    return value


def _start_detail(json_path, list_lookup, ward_lookup):
    """Seed a detail record with its monthly list row and ward, if known."""
    record = {
        f"list_{key}": value
        for key, value in (list_lookup or {}).get(json_path.stem, {}).items()
    }
    ward = (ward_lookup or {}).get(json_path.stem)
    if ward is not None:
        record["ward"] = ward
    return record


def _finish_detail(record, json_path, id_label, source_version):
    year, month = extract_path_info(json_path)
    record.update({
        id_label: json_path.stem,
        "year": year,
        "month": month,
        "source_file": str(json_path),
        "source_version": source_version,
    })
    return pl.DataFrame([record])


def parse_payment_detail(json_path, list_lookup, ward_lookup, source_version):
    data = _load_detail(json_path)
    if data is None:
        return None

    record = _start_detail(json_path, list_lookup, ward_lookup)
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    record.update(rename_fields(flatten_dict(details)))

    type_combo = _first_dict(data.get("type_combo"))
    record.update(rename_fields(flatten_dict(type_combo)))

    approvals = _merge_list(
        record, data.get("approval_levels", []), "approval",
        "approval_levels_count", expand=True,
    )
    files = _merge_list(record, data.get("files", []), "file", "file_count")

    # Preserve curated values lost to generic field-name collisions.
    record["current_level_name"] = clean_text(details.get("currentlevelname"))
    if type_combo:
        record["work_order_details"] = clean_text(type_combo.get("wodetails"))
        record["job"] = clean_text(type_combo.get("job"))
    if approvals and isinstance(approvals[-1], dict):
        last = approvals[-1]
        record["approval_id"] = clean_text(last.get("id"))
        record["approval_system_type"] = clean_text(last.get("systemtype"))
        record["approval_remarks"] = clean_text(last.get("remarks"))
    record["files"] = files_to_json(files)

    list_entry = (list_lookup or {}).get(json_path.stem, {})
    list_rtgs_number, list_rtgs_date = payment_list_rtgs(list_entry)
    if list_rtgs_date:
        record["detail_rtgs_number"] = record.get("rtgs_number")
        record["detail_rtgs_date"] = record.get("rtgs_date")
        record["rtgs_number"] = list_rtgs_number
        record["rtgs_date"] = list_rtgs_date

    return _finish_detail(record, json_path, "work_bill_id", source_version)


def parse_receipt_detail(json_path, list_lookup, ward_lookup, source_version):
    data = _load_detail(json_path)
    if data is None:
        return None

    record = _start_detail(json_path, list_lookup, ward_lookup)
    prefixes = {"fill_data_1": "", "fill_data_2": "receipt_item", "fill_data_3": "receipt_additional"}
    for section_key, prefix in prefixes.items():
        section = data.get(section_key, [])
        if isinstance(section, dict):
            record.update(rename_fields(flatten_dict(section)))
        elif isinstance(section, list) and section:
            if prefix:
                record[f"{prefix}s_count"] = len(section)
            if isinstance(section[0], dict):
                record.update(rename_fields(flatten_dict(section[0]), prefix))

    # Preserve fields that collide across the three generic sections.
    header = _first_dict(data.get("fill_data_1"))
    items = data.get("fill_data_2") if isinstance(data.get("fill_data_2"), list) else []
    first_item = _first_dict(items)
    first_instrument = _first_dict(data.get("fill_data_3"))

    record["detail_payer_name"] = clean_text(header.get("receiptname"))
    record["account_head"] = clean_text(first_item.get("name"))
    record["audit_recovery"] = clean_text(first_item.get("auditrecovery"))
    record["receipt_items"] = receipt_items_to_json(items)

    # Split instrument name and number/date blobs.
    instrument = clean_text(first_instrument.get("name")) or ""
    kind, _, bank = (part.strip() for part in instrument.partition(","))
    record["instrument_type"] = kind or None
    record["instrument_bank"] = bank if bank and bank.replace("-", "").strip() else None

    number = clean_text(first_instrument.get("fnumber"))
    if number:
        value, separator, date = number.partition("/")
        record["instrument_number"] = clean_text(value)
        record["instrument_date"] = clean_text(date) if separator else None
    else:
        record["instrument_number"] = None

    if record.get("list_fdate") and not record.get("date"):
        record["date"] = record["list_fdate"]

    return _finish_detail(record, json_path, "receipt_id", source_version)


def parse_dc_bill_detail(json_path, list_lookup, ward_lookup, source_version):
    data = _load_detail(json_path)
    if data is None:
        return None

    record = _start_detail(json_path, list_lookup, ward_lookup)
    fill_data = data.get("fill_data") if isinstance(data.get("fill_data"), dict) else {}
    deductions = data.get("deductions") if isinstance(data.get("deductions"), dict) else {}
    record.update(rename_fields(flatten_dict(fill_data)))
    record.update(rename_fields(flatten_dict(deductions), "deduction"))

    approvals = _merge_list(
        record, data.get("approval_levels", []), "approval",
        "approval_levels_count", expand=True,
    )
    files = _merge_list(record, data.get("files", []), "file", "file_count")
    _merge_list(record, data.get("photos", []), "photo", "photo_count")

    # Preserve curated values that later RTGS fields overwrite under generic
    # field-name normalization.
    record.update({
        "date": clean_text(fill_data.get("datefdate")),
        "bill_number": clean_text(fill_data.get("txtfnumber")),
        "internal_id": clean_text(fill_data.get("id")),
        "main_remarks": clean_text(fill_data.get("txtmainremarks")),
        "budget_head_name": clean_text(fill_data.get("budgetheadname")),
        "cheque_favouring_name": clean_text(fill_data.get("chequefavouringname")),
        "cheque_favouring_bank": clean_text(fill_data.get("checkfavbankname")),
        "cheque_favouring_account": clean_text(fill_data.get("chequefavouringaccount")),
        "cheque_favouring_gstin": clean_text(deductions.get("chequefavouringgstin")),
        "rtgs_sub_name": clean_text(fill_data.get("rtgssubname")),
        "rtgs_number": clean_text(fill_data.get("rtgsfnumber")),
        "deduction_value": clean_text(deductions.get("value")),
        "paying_ddo_id": clean_text(fill_data.get("pddoid")),
        "submit_to": clean_text(fill_data.get("submitto")),
        "saved": clean_text(fill_data.get("vsavedyn")),
        "certifications": json_or_none([
            c for i in range(1, 6)
            if (c := clean_text(fill_data.get(f"certification{i}")))
        ]),
        "bill_items": indexed_fields_to_json(
            fill_data,
            {"caption": "billcaption", "nature": "billnature", "value": "dcbillvalue"},
        ),
        "other_deductions": captioned_amounts_to_json(deductions),
        "files": files_to_json(files),
        "approvals": approvals_to_json(approvals),
    })

    return _finish_detail(record, json_path, "dc_bill_id", source_version)


def parse_public_view_detail(json_path, list_lookup, ward_lookup, source_version):
    """Parse one PublicView work bill from its detail endpoints and list row."""
    data = _load_detail(json_path)
    if data is None:
        return None

    record = _start_detail(json_path, list_lookup, ward_lookup)
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    record.update(rename_fields(flatten_dict(details)))

    approvals = _merge_list(
        record, data.get("approval_levels", []), "approval",
        "approval_levels_count", expand=True,
    )
    files = _merge_list(record, data.get("files", []), "file", "file_count")

    # Preserve curated values lost to generic field-name collisions.
    record["current_level_name"] = clean_text(details.get("currentlevelname"))
    if approvals and isinstance(approvals[-1], dict):
        last = approvals[-1]
        record["approval_id"] = clean_text(last.get("id"))
        record["approval_system_type"] = clean_text(last.get("systemtype"))
        record["approval_remarks"] = clean_text(last.get("remarks"))
    record["files"] = files_to_json(files)

    # Ward, work order, and RTGS live only in the list row's markup.
    record.update(_public_view_markup_fields((list_lookup or {}).get(json_path.stem, {})))

    return _finish_detail(record, json_path, "work_bill_id", source_version)


def _ifms_payment_list_fields(entry):
    number, date = payment_list_rtgs(entry)
    return {"rtgs_number": number, "rtgs_date": date}


def _ifms_rtgs_legs(entry):
    """An IFMS list row reports at most the one disbursement it was listed for."""
    number, date = payment_list_rtgs(entry)
    return [(number, date)] if date else []


def _public_view_list_fields(entry):
    """Curated fields a PublicView list row carries even without a detail file."""
    return {
        **_public_view_markup_fields(entry),
        "work_description": clean_text(entry.get("nameofwork")),
        "gross": clean_text(entry.get("amount")),
    }


def parse_list_entry(entry, year, month, list_file, cfg, source_version):
    """Parse a monthly list row for an entry that has no detail file yet."""
    if not isinstance(entry, dict):
        return None
    record = rename_fields(flatten_dict(entry))
    record[cfg["row_key"]] = str(entry.get("id") or entry.get(cfg["list_id_key"], ""))
    if list_fields := cfg.get("list_fields"):
        record.update(list_fields(entry))
    record.update(
        year=year, month=month, source_file=str(list_file),
        source_type="list_file", source_version=source_version,
    )
    return pl.DataFrame([record])


# --- Sources ----------------------------------------------------------------

# Each source names its own raw and published namespaces, the data types it
# covers, and how a monthly list reports RTGS disbursements.

SOURCES = {
    "ifms": {
        "raw_dir": Path("raw"),
        "data_dir": Path("data"),
        "rtgs_legs": _ifms_rtgs_legs,
        # IFMS lists a bill under the month of each disbursement it carries.
        "rtgs_sets_period": True,
        "parse_config": {
            "payments": {
                "parser": parse_payment_detail, "wards": True,
                "list_id_key": "id", "row_key": "work_bill_id",
                "list_fields": _ifms_payment_list_fields,
            },
            "receipts": {
                "parser": parse_receipt_detail, "wards": True,
                "list_id_key": "receiptmainid", "row_key": "receipt_id",
            },
            "dc_bills": {
                "parser": parse_dc_bill_detail, "wards": False,
                "list_id_key": "dcbillmainid", "row_key": "dc_bill_id",
            },
        },
    },
    "publicview": {
        "raw_dir": Path("raw") / "publicview",
        "data_dir": Path("data"),
        "rtgs_legs": _public_view_rtgs_legs,
        # PublicView groups months by bill-register date, so a later RTGS leg
        # must not move a row out of the month it was registered in.
        "rtgs_sets_period": False,
        "parse_config": {
            "payments": {
                "parser": parse_public_view_detail, "wards": False,
                "list_id_key": "wbid", "row_key": "work_bill_id",
                "list_fields": _public_view_list_fields,
                "slug": "bills", "curated": "bills",
            },
        },
    },
}
DEFAULT_SOURCE = "publicview"


def use_source(name):
    """Point the module at one source's paths and data types."""
    global SOURCE, RAW_DIR, DATA_DIR, PARSE_CONFIG
    SOURCE = SOURCES[name]
    RAW_DIR = SOURCE["raw_dir"]
    DATA_DIR = SOURCE["data_dir"]
    PARSE_CONFIG = SOURCE["parse_config"]


use_source(DEFAULT_SOURCE)


# --- Raw file discovery and lookups -----------------------------------------

LIST_ID_KEYS = (
    "id", "receiptmainid", "receiptMainID", "dcbillmainid",
    "dcBillMainID", "workbillid", "workBillID", "wbid",
)


def _load_raw(path, expected=list):
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
        return None
    return data if isinstance(data, expected) else None


def _list_entry_id(entry):
    return next((entry.get(key) for key in LIST_ID_KEYS if entry.get(key)), None)


def read_list_entries(list_file):
    """Read a monthly list file as raw entries; an ID can repeat within a month."""
    return [entry for entry in (_load_raw(list_file) or []) if isinstance(entry, dict)]


def list_path(data_type, year, month):
    return RAW_DIR / data_type / str(year) / f"{month:02d}.json"


def load_list_lookup(data_type, year, month):
    """Map each portal ID in a monthly list to its row."""
    return {
        str(entry_id): entry
        for entry in read_list_entries(list_path(data_type, year, month))
        if (entry_id := _list_entry_id(entry))
    }


def load_ward_dropdown():
    entries = _load_raw(RAW_DIR / "ward_dropdown.json") or []
    return {
        str(entry["rid"]): entry["rname"]
        for entry in entries
        if isinstance(entry, dict) and {"rid", "rname"}.issubset(entry)
    }


def load_ward_lookup(data_type, year, ward_names):
    """Map each portal ID to the ward-wise lists it appears in."""
    wards_dir = RAW_DIR / data_type / str(year) / "wards"
    if not wards_dir.exists():
        return {}
    lookup = {}
    for ward_file in wards_dir.glob("*.json"):
        ward_name = (ward_names or {}).get(ward_file.stem, ward_file.stem)
        for entry in _load_raw(ward_file) or []:
            if isinstance(entry, dict) and (entry_id := str(entry.get("id") or "")):
                lookup.setdefault(entry_id, set()).add(ward_name)
    return {key: ",".join(sorted(names)) for key, names in lookup.items()}


def find_detail_files(data_type):
    base = RAW_DIR / data_type
    return sorted(base.rglob("*_details/*.json")) if base.exists() else []


def find_list_months(data_type):
    months = {}
    for year_dir in sorted((RAW_DIR / data_type).glob("[0-9][0-9][0-9][0-9]")):
        for month_file in sorted(year_dir.glob("*.json")):
            if month_file.stem.isdigit() and 1 <= int(month_file.stem) <= 12:
                months[(int(year_dir.name), int(month_file.stem))] = month_file
    return months


def path_version(*paths):
    """Return a compact version from the inputs that shape a parsed row."""
    parts = []
    for path in paths:
        if path is None:
            continue
        path = Path(path)
        if path.is_dir():
            stats = [p.stat() for p in path.glob("*.json")]
            parts.append(f"d:{max((s.st_mtime_ns for s in stats), default=0)}:{len(stats)}")
        elif path.exists():
            stat = path.stat()
            parts.append(f"f:{stat.st_mtime_ns}:{stat.st_size}")
        else:
            parts.append("missing")
    return "|".join(parts)


def context_version(data_type, year, month, cfg):
    """Version the parser plus every shared input a detail row depends on."""
    wards = cfg["wards"]
    inputs = path_version(
        list_path(data_type, year, month),
        RAW_DIR / data_type / str(year) / "wards" if wards else None,
        RAW_DIR / "ward_dropdown.json" if wards else None,
    )
    return f"parser:{PARSER_VERSION[data_type]}|{inputs}"


# --- Typing and dataset assembly --------------------------------------------

FLOAT_COLUMNS = {
    "amount", "gross", "nett", "deduction", "release_gross_amount", "release_net_amount",
    "release_percentage", "value", "deduction_amount", "tds",
    "it", "vat", "royalty", "fine", "fsd", "cbf", "md", "labourcess",
    "mobilizationadvance", "otheradvances", "differenceemd",
    "cgstper", "sgstper", "igstper",
    "others1", "others2", "others3", "others4", "others5",
    "others6", "others7", "others8", "others9", "others10",
    "list_amount", "deduction_value", "audit_recovery",
}

INT_COLUMNS = {
    "approval_id", "approval_levels_count", "current_level", "ddo_id",
    "file_count", "file_r_id", "photo_count",
    "receipt_items_count", "receipt_additionals_count",
    "list_slno", "list_id",
    "tvcc_required", "paying_ddo_id", "submit_to", "saved", "internal_id",
}

DATE_COLUMNS = {
    "rtgs_date", "common_br_date", "date", "list_fdate", "list_refdate",
    "instrument_date",
}

DATETIME_COLUMNS = {"approval_date"}

ISO_DATE_COLUMNS = {"sbr_date", "dbr_date", "cbr_date"}

# (columns, cast applied to the stripped Utf8 column) - first match wins.
COLUMN_CASTS = [
    (FLOAT_COLUMNS, lambda c: c.str.replace_all(",", "").cast(pl.Float64, strict=False)),
    (INT_COLUMNS, lambda c: c.cast(pl.Int64, strict=False)),
    (DATE_COLUMNS, lambda c: c.str.to_date("%d-%b-%Y", strict=False)),
    (DATETIME_COLUMNS, lambda c: c.str.replace_all(r"<br/>\s*", " ")
        .str.to_datetime("%d-%b-%Y %H:%M:%S", strict=False)),
    (ISO_DATE_COLUMNS, lambda c: c.str.to_date("%Y-%m-%d", strict=False)),
]


def cast_columns(df):
    casts = [
        cast(pl.col(col).str.strip_chars()).alias(col)
        for col in df.columns
        if df[col].dtype == pl.Utf8
        and (cast := next((f for cols, f in COLUMN_CASTS if col in cols), None))
    ]
    return df.with_columns(casts) if casts else df


SORT_DATE_COL = "sort_date"
SORT_DATE_SOURCE = {"payments": "rtgs_date", "receipts": "list_fdate", "dc_bills": "date"}
RTGS_LEGS_COL = "rtgs_legs"


def _listed_rtgs_legs(list_months):
    """Collect the RTGS legs the monthly payment lists report per work bill."""
    legs = {}
    for list_file in list_months.values():
        for entry in read_list_entries(list_file):
            entry_id = _list_entry_id(entry)
            if not entry_id:
                continue
            for number, date in SOURCE["rtgs_legs"](entry):
                iso = datetime.strptime(date, "%d-%b-%Y").strftime("%Y-%m-%d")
                legs.setdefault(str(entry_id), set()).add((iso, number))
    return legs


def _stored_rtgs_legs(df):
    """Recover legs already published, for bills whose lists are no longer on disk."""
    if RTGS_LEGS_COL not in df.columns:
        return {}
    rows = df.select(["work_bill_id", RTGS_LEGS_COL]).filter(pl.col(RTGS_LEGS_COL).is_not_null())
    return {
        str(key): {(leg["date"], leg.get("number")) for leg in json.loads(value)}
        for key, value in rows.iter_rows()
    }


def apply_rtgs_legs(df, data_type, list_months):
    """Pin each payment to its first RTGS leg and record any further legs.

    The portal lists a bill once per RTGS transaction it carries, while the bill
    detail only ever reports the first. One row per bill would therefore drop the
    later legs, so they are folded into a JSON column instead.
    """
    if data_type != "payments" or "work_bill_id" not in df.columns:
        return df, 0
    if RTGS_LEGS_COL not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias(RTGS_LEGS_COL))

    listed = _listed_rtgs_legs(list_months)
    stored = _stored_rtgs_legs(df)
    legs = {
        key: sorted(listed.get(key, set()) | stored.get(key, set()))
        for key in set(listed) | set(stored)
    }
    if not legs:
        return df, 0

    pinned = pl.DataFrame({
        "work_bill_id": list(legs),
        "_legs": [
            json.dumps([{"number": number, "date": date} for date, number in bill])
            if len(bill) > 1 else None
            for bill in legs.values()
        ],
        "_number": [bill[0][1] for bill in legs.values()],
        "_date": [bill[0][0] for bill in legs.values()],
    }).with_columns(pl.col("_date").str.to_date("%Y-%m-%d"))

    joined = df.join(pinned, on="work_bill_id", how="left")
    changed = joined.filter(
        pl.col("_date").is_not_null()
        & (
            pl.col("_number").ne_missing(pl.col("rtgs_number"))
            | pl.col("_date").ne_missing(pl.col("rtgs_date"))
            | pl.col("_legs").ne_missing(pl.col(RTGS_LEGS_COL))
        )
    ).height
    period = [
        pl.coalesce(pl.col("_date").dt.year(), "year").cast(df["year"].dtype).alias("year"),
        pl.coalesce(pl.col("_date").dt.month(), "month").cast(df["month"].dtype).alias("month"),
    ] if SOURCE["rtgs_sets_period"] else []
    updated = joined.with_columns(
        pl.coalesce("_legs", RTGS_LEGS_COL).alias(RTGS_LEGS_COL),
        pl.coalesce("_number", "rtgs_number").alias("rtgs_number"),
        pl.coalesce("_date", "rtgs_date").alias("rtgs_date"),
        *period,
    ).drop("_legs", "_number", "_date")
    repeat = sum(1 for bill in legs.values() if len(bill) > 1)
    logger.info(f"RTGS legs: {repeat} bills disbursed more than once, {changed} rows updated")
    return updated, changed


def finalize_dataset(df, data_type, list_months):
    """Fold in cross-month list facts, then order the dataset for output."""
    df, changed = apply_rtgs_legs(df, data_type, list_months)
    source = SORT_DATE_SOURCE.get(data_type)
    if source and source in df.columns:
        df = df.with_columns(pl.col(source).alias(SORT_DATE_COL))
    if SORT_DATE_COL in df.columns:
        return df.sort(SORT_DATE_COL, descending=True, nulls_last=True), changed
    if {"year", "month"}.issubset(df.columns):
        return df.sort(["year", "month"], descending=True, nulls_last=True), changed
    return df, changed


def ensure_row_key(df, cfg):
    row_key = cfg["row_key"]
    if row_key == "work_bill_id" and "source_file" in df.columns:
        derived = (
            pl.when(pl.col("source_file").str.contains("_details"))
            .then(pl.col("source_file").str.extract(r"/(\d+)\.json$", 1))
            .otherwise(None)
        )
        value = pl.col(row_key) if row_key in df.columns else pl.lit(None, dtype=pl.String)
        return df.with_columns(pl.coalesce([derived, value.cast(pl.String)]).alias(row_key))
    return df


def dedupe_dataset(df, cfg):
    """Keep the newest detail row for each stable portal ID."""
    df = ensure_row_key(df, cfg)
    row_key = cfg["row_key"]
    if row_key not in df.columns:
        return df

    keyed = df.filter(pl.col(row_key).is_not_null())
    unkeyed = df.filter(pl.col(row_key).is_null())
    sort_cols, descending = [], []
    if "source_type" in keyed.columns:
        keyed = keyed.with_columns(pl.col("source_type").is_null().alias("_detail"))
        sort_cols.append("_detail")
        descending.append(True)
    if "source_version" in keyed.columns:
        sort_cols.append("source_version")
        descending.append(True)
    if sort_cols:
        keyed = keyed.sort(sort_cols, descending=descending, nulls_last=True)
    keyed = keyed.unique(subset=[row_key], keep="first", maintain_order=True)
    if "_detail" in keyed.columns:
        keyed = keyed.drop("_detail")
    return pl.concat([keyed, unkeyed], how="diagonal_relaxed")


def merge_incremental(existing, new_df, cfg):
    """Replace IDs present in new rows, append the remainder, and deduplicate."""
    existing = ensure_row_key(existing, cfg)
    new_df = ensure_row_key(new_df, cfg)
    row_key = cfg["row_key"]
    if row_key in existing.columns and row_key in new_df.columns:
        replaced = new_df[row_key].drop_nulls().unique().to_list()
        if replaced:
            existing = existing.filter(~pl.col(row_key).is_in(replaced))
    return dedupe_dataset(pl.concat([existing, new_df], how="diagonal_relaxed"), cfg)


def build_source_versions(existing, cfg):
    """Map parsed detail paths and list IDs to their source versions."""
    detail_versions, list_versions = {}, {}
    if existing is None:
        return detail_versions, list_versions
    if {"source_file", "source_version"}.issubset(existing.columns):
        details = existing.filter(
            pl.col("source_file").str.contains("_details")
            & pl.col("source_version").is_not_null()
        )
        detail_versions = dict(details.select(["source_file", "source_version"]).iter_rows())
    if {"source_type", "source_version", cfg["row_key"]}.issubset(existing.columns):
        lists = existing.filter(pl.col("source_type") == "list_file")
        list_versions = {
            str(key): version
            for key, version in lists.select([cfg["row_key"], "source_version"]).iter_rows()
            if key is not None
        }
    return detail_versions, list_versions


def existing_detail_keys(existing, row_key):
    """IDs already covered by a parsed detail row."""
    if existing is None or row_key not in existing.columns:
        return set()
    detail = (
        pl.col("source_type").is_null() if "source_type" in existing.columns else pl.lit(True)
    )
    return {str(value) for value in existing.filter(detail)[row_key].drop_nulls().to_list()}


# --- Curated datasets -------------------------------------------------------

# Curated entries map internal source columns to published columns.

CURATED_SCHEMAS = {
    "payments": [
        ("rtgs_date", "date"),              # primary date: RTGS disbursement date
        ("ward_number", "ward_number"),     # numeric ward, derived from the ward string
        ("ward_name", "ward_name"),         # clean ward name, derived from the ward string
        ("ward_scheme", "ward_scheme"),     # delimitation: 198 / 243 / 225 / special
        ("work_bill_id", "work_bill_id"),   # derived from the detail file id
        ("job_number", "job_number"),       # derived from the raw "job" field
        ("work_description", "work_description"),
        ("work_order_title", "work_order_title"),   # work-order title from "job", when it differs
        ("work_order_number", "work_order_number"),  # derived from "wodetails"
        ("work_order_date", "work_order_date"),      # derived from "wodetails"
        ("bill_type", "bill_type"),
        ("category", "category"),
        ("budget", "budget_head"),
        ("type", "work_type"),              # work-order document stage (Estimates, AS, TS, DPR, ...)
        ("contractor_name", "contractor_name"),
        ("contractor_mobile", "contractor_mobile"),
        ("contractor_email", "contractor_email"),
        ("ddo_name", "ddo_name"),
        ("approval_name", "approver_name"),
        ("gross", "gross_amount"),
        ("nett", "net_amount"),
        ("deduction", "deduction_amount"),
        ("release_percentage", "release_percentage"),
        ("release_gross_amount", "release_gross_amount"),
        ("release_net_amount", "release_net_amount"),
        ("contractor_tds", "contractor_utr"),   # bank UTR for the contractor-payment leg
        ("deduction_tds", "deduction_utr"),      # bank UTR for the deduction leg
        ("sbr_number", "sbr_number"),
        ("sbr_date", "sbr_date"),
        ("dbr_number", "dbr_number"),
        ("dbr_date", "dbr_date"),
        ("cbr_number", "cbr_number"),
        ("cbr_date", "cbr_date"),
        ("common_br_number", "common_br_number"),
        ("common_br_date", "common_br_date"),
        ("rtgs_number", "rtgs_number"),
        ("rtgs_date", "rtgs_date"),
        ("rtgs_legs", "rtgs_legs"),         # every RTGS leg, when the bill has more than one
        ("current_level", "current_level"),
        ("current_level_name", "current_level_name"),
        ("tvcc_required", "tvcc_required"),
        ("approval_date", "approval_date"),
        ("approval_id", "approval_id"),
        ("approval_system_type", "approval_system_type"),
        ("approval_remarks", "approval_remarks"),
        ("files", "files"),
        ("year", "year"),
        ("month", "month"),
    ],
    "receipts": [
        ("date", "date"),                   # primary date: receipt date (fdate)
        ("ward_number", "ward_number"),     # numeric ward, derived from the ward string
        ("ward_name", "ward_name"),         # clean ward name, derived from the ward string
        ("ward_scheme", "ward_scheme"),     # delimitation: 198 / 243 / 225 / special
        ("receipt_id", "receipt_id"),
        ("number", "receipt_number"),       # header receipt number (fnumber)
        ("type", "receipt_type"),
        ("payer_name", "payer_name"),       # list receiptname, falling back to detail
        ("account_head", "account_head"),   # primary revenue head (fill_data_2)
        ("amount", "amount"),
        ("audit_recovery", "audit_recovery"),  # was mislabeled "tds" (fill_data_2.auditrecovery)
        ("instrument_type", "payment_mode"),   # Cash / DD / Cheque (fill_data_3.name)
        ("instrument_bank", "instrument_bank"),
        ("instrument_number", "instrument_number"),  # instrument no., split from fnumber
        ("instrument_date", "instrument_date"),      # instrument date, split from fnumber
        ("receipt_items", "receipt_items"),          # all revenue heads as JSON
        ("year", "year"),
        ("month", "month"),
    ],
    "dc_bills": [
        ("date", "date"),                   # primary date: bill date (datefdate)
        ("dc_bill_id", "dc_bill_id"),
        ("bill_number", "bill_number"),
        ("main_remarks", "remarks"),
        ("list_budgethead", "budget_head"),
        ("list_favname", "payee_name"),
        ("address", "payee_address"),
        ("city", "payee_city"),
        ("ddo_name", "ddo_name"),
        ("paying_ddo_id", "paying_ddo_id"),
        ("approval_name", "approver_name"),
        ("gross", "gross_amount"),
        ("nett", "net_amount"),
        ("deduction_amount", "deduction_amount"),  # recomputed as gross - net (see build_curated)
        ("it", "income_tax"),
        ("vat", "vat"),
        ("royalty", "royalty"),
        ("labourcess", "labour_cess"),
        ("cbf", "corpus_fund"),
        ("fsd", "security_deposit"),
        ("fine", "fine"),
        ("md", "measurement_deduction"),
        ("mobilizationadvance", "mobilization_advance"),
        ("otheradvances", "other_advances"),
        ("differenceemd", "difference_emd"),
        ("cgstper", "cgst_percentage"),
        ("sgstper", "sgst_percentage"),
        ("igstper", "igst_percentage"),
        ("other_deductions", "other_deductions"),
        ("cheque_favouring_name", "cheque_favouring_name"),
        ("cheque_favouring_bank", "cheque_favouring_bank"),
        ("cheque_favouring_account", "cheque_favouring_account"),
        ("cheque_favouring_gstin", "cheque_favouring_gstin"),
        ("rtgs_sub_name", "rtgs_sub_name"),
        ("rtgs_number", "rtgs_number"),
        ("rtgs_date", "rtgs_date"),
        ("approval_date", "approval_date"),
        ("submit_to", "submit_to"),
        ("saved", "saved"),
        ("certifications", "certifications"),
        ("bill_items", "bill_items"),
        ("files", "files"),
        ("approvals", "approvals"),
        ("year", "year"),
        ("month", "month"),
    ],
}

# PublicView serves no release breakdown, no bank UTRs, and no common bill
# register, so the payments columns fed by those are dropped rather than
# published empty.
PUBLIC_VIEW_ABSENT = frozenset({
    "release_percentage", "release_gross_amount", "release_net_amount",
    "contractor_utr", "deduction_utr", "common_br_number", "common_br_date",
})
CURATED_SCHEMAS["bills"] = [
    entry for entry in CURATED_SCHEMAS["payments"] if entry[1] not in PUBLIC_VIEW_ABSENT
]


def curated_schema(data_type):
    """The published columns, which a source may narrow to what it can fill."""
    return CURATED_SCHEMAS[PARSE_CONFIG[data_type].get("curated") or data_type]

# Receipts use reporting month because some source dates are corrupt.
CURATED_SORT_COLS = {
    "payments": ["rtgs_date"],
    "receipts": ["year", "month"],
    "dc_bills": ["date"],
}

_DC_DATE_PAT = r"(\d{2}-[A-Za-z]{3}-\d{4})"
_PAYMENT_EMPTY_TO_NULL = (
    "work_type", "work_order_title", "work_order_number", "contractor_utr", "deduction_utr"
)


def _column(df, name, dtype=pl.Utf8):
    return pl.col(name) if name in df.columns else pl.lit(None, dtype=dtype)


def _reconstruct_dc_list_rows(work):
    """Recover curated DC-bill fields from list-only rows."""
    if "source_type" not in work.columns:
        return work
    is_list = pl.col("source_type") == "list_file"

    def col(name, dtype=pl.Utf8):
        return _column(work, name, dtype)

    type_col, rtgs_blob = col("type"), col("rtgs_number")
    return work.with_columns([
        pl.when(is_list)
        .then(type_col.str.extract(_DC_DATE_PAT, 1).str.to_date("%d-%b-%Y", strict=False))
        .otherwise(col("date", pl.Date)).alias("date"),
        pl.when(is_list).then(type_col.str.extract(r"/\s*([0-9A-Za-z\-]+)\s*$", 1))
        .otherwise(col("bill_number")).alias("bill_number"),
        pl.when(is_list).then(rtgs_blob.str.extract(r"^\s*([^<]+?)\s*</br>", 1).str.strip_chars())
        .otherwise(col("rtgs_sub_name")).alias("rtgs_sub_name"),
        pl.when(is_list)
        .then(rtgs_blob.str.extract(_DC_DATE_PAT, 1).str.to_date("%d-%b-%Y", strict=False))
        .otherwise(col("rtgs_date", pl.Date)).alias("rtgs_date"),
        pl.when(is_list).then(rtgs_blob.str.extract(r"/\s*([0-9A-Za-z\-]+)\s*</a>", 1))
        .otherwise(rtgs_blob).alias("rtgs_number"),
        pl.coalesce([col("list_budgethead"), col("budget_head_name"),
                     pl.when(is_list).then(col("budgethead")).otherwise(None)]
                    ).alias("list_budgethead"),
        pl.coalesce([col("list_favname"),
                     pl.when(is_list).then(col("name")).otherwise(None)]).alias("list_favname"),
        pl.coalesce([col("gross", pl.Float64),
                     pl.when(is_list).then(col("amount", pl.Float64)).otherwise(None)]
                    ).alias("gross"),
    ])


def _add_payment_columns(work):
    """Derive payment IDs, job fields, and work-order fields."""
    detail = pl.col("source_file").str.contains("_details")
    exprs = [
        pl.when(detail)
        .then(pl.col("source_file").str.extract(r"/(\d+)\.json$", 1))
        .otherwise(_column(work, "work_bill_id", pl.String).cast(pl.String))
        .alias("work_bill_id")
    ]

    if "job" in work.columns:
        job_flat = pl.col("job").str.replace_all("<br/>", " ")
        # Omit titles that merely repeat the work description.
        title = (job_flat.str.replace(r"^\s*\S+\s*", "")
                 .str.replace_all(r"\s+", " ").str.strip_chars())
        described = (_column(work, "work_description")
                     .str.replace_all(r"\s+", " ").str.strip_chars().str.to_lowercase())
        exprs += [
            job_flat.str.extract(r"^\s*(\S+)", 1).alias("job_number"),
            pl.when((title == "") | (title.str.to_lowercase() == described))
            .then(None).otherwise(title).alias("work_order_title"),
        ]
    else:
        exprs += [pl.lit(None, dtype=pl.Utf8).alias("job_number"),
                  pl.lit(None, dtype=pl.Utf8).alias("work_order_title")]

    if "wodetails" in work.columns:
        work_order = pl.col("wodetails").str.replace_all("<br/>", " ")
        exprs += [
            work_order.str.extract(r"^\s*([^/]+?)\s*/", 1).alias("work_order_number"),
            work_order.str.extract(r"^[^/]*/\s*(\d{2}-[A-Za-z]{3}-\d{4})", 1)
            .str.to_date("%d-%b-%Y", strict=False).alias("work_order_date"),
        ]
    return work.with_columns(exprs)


def _add_receipt_payer(work):
    """Resolve payer names across detail and list-only rows."""
    def nonblank(expr):
        return pl.when(expr.cast(pl.Utf8).str.strip_chars() == "").then(None).otherwise(expr)

    list_only = (
        (pl.col("source_type") == "list_file") if "source_type" in work.columns else pl.lit(False)
    )
    return work.with_columns(
        pl.coalesce([
            nonblank(_column(work, "list_receiptname")),
            _column(work, "detail_payer_name"),
            pl.when(list_only).then(nonblank(_column(work, "name"))).otherwise(None),
        ]).alias("payer_name")
    )


def _add_ward_columns(work):
    """Split a ward string into number, name, and delimitation scheme."""
    if "ward" not in work.columns:
        return work
    ward = pl.col("ward")
    prefix = ward.str.extract(r"^(o*)\d", 1)
    number = ward.str.extract(r"^o*(\d+)", 1).cast(pl.Int32, strict=False)
    name = ward.str.replace(r"^o*\d+\s*", "").str.strip_chars()
    scheme = (
        pl.when(ward.is_null()).then(None)
        .when(prefix == "oo").then(pl.lit("198"))
        .when(prefix == "o").then(pl.lit("243"))
        .when((number == 0) | ((number >= 300) & (number <= 399))).then(pl.lit("special"))
        .when(number.is_not_null()).then(pl.lit("225"))
        .otherwise(None)
    )
    return work.with_columns([
        number.alias("ward_number"),
        pl.when(name == "").then(None).otherwise(name).alias("ward_name"),
        scheme.alias("ward_scheme"),
    ])


def build_curated(df, data_type):
    """Build the typed, ordered, published dataset."""
    work = df
    if data_type == "payments":
        work = _add_payment_columns(work)
    if data_type == "receipts":
        work = _add_receipt_payer(work)
    if data_type in ("payments", "receipts"):
        work = _add_ward_columns(work)
    if data_type == "dc_bills":
        work = _reconstruct_dc_list_rows(work)

    curated = work.select([
        pl.col(src).alias(out)
        for src, out in curated_schema(data_type) if src in work.columns
    ])

    blankable = [c for c in _PAYMENT_EMPTY_TO_NULL if c in curated.columns]
    if blankable:
        curated = curated.with_columns([
            pl.when(pl.col(c).cast(pl.Utf8).str.strip_chars() == "").then(None)
            .otherwise(pl.col(c)).alias(c) for c in blankable
        ])

    int_casts = [pl.col(c).cast(pl.Int32) for c in ("year", "month") if c in curated.columns]
    if int_casts:
        curated = curated.with_columns(int_casts)

    # Portal deduction totals are unreliable; gross minus net is consistent.
    if data_type == "dc_bills" and {"gross_amount", "net_amount"}.issubset(curated.columns):
        curated = curated.with_columns(
            (pl.col("gross_amount") - pl.col("net_amount")).alias("deduction_amount"))

    sort_cols = [c for c in CURATED_SORT_COLS.get(data_type, []) if c in curated.columns]
    if not sort_cols and {"year", "month"}.issubset(curated.columns):
        sort_cols = ["year", "month"]
    return curated.sort(sort_cols, descending=True, nulls_last=True) if sort_cols else curated


# --- Output -----------------------------------------------------------------


def dataset_slug(data_type):
    """The published file stem, which a source may rename to avoid a clash."""
    return PARSE_CONFIG[data_type].get("slug") or data_type.replace("_", "-")


def dataset_paths(data_type):
    """The internal full dataset, plus the published Parquet and zipped CSV."""
    slug = dataset_slug(data_type)
    return (
        DATA_DIR / "full" / f"{slug}.parquet",
        DATA_DIR / f"{slug}.parquet",
        DATA_DIR / f"{slug}.csv.zip",
    )


def write_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    df.write_parquet(temporary, compression="zstd")
    temporary.replace(path)


def write_csv_zip(df, zip_path, arcname):
    """Write df to a single CSV compressed inside a .csv.zip archive."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / arcname
        df.write_csv(csv_path)
        temporary = zip_path.with_suffix(f"{zip_path.suffix}.tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(csv_path, arcname=arcname)
        temporary.replace(zip_path)


def load_existing_dataset(data_type):
    path = dataset_paths(data_type)[0]
    if not path.exists():
        return None
    try:
        return pl.read_parquet(path)
    except Exception as e:
        logger.warning(f"Could not read existing {path} ({e}); rebuilding from scratch")
        return None


def write_outputs(combined, data_type):
    """Persist the full working set plus the curated Parquet and zipped CSV."""
    full_path, curated_path, csv_path = dataset_paths(data_type)
    write_parquet(combined, full_path)
    logger.info(
        f"Full set: {combined.height} rows, {len(combined.columns)} columns -> {full_path}")

    curated = build_curated(combined, data_type)
    write_parquet(curated, curated_path)
    write_csv_zip(curated, csv_path, csv_path.name.removesuffix(".zip"))
    logger.info(f"Curated set: {curated.height} rows, {len(curated.columns)} columns "
                f"-> {curated_path} (+ .csv.zip)")


# --- Pipeline ---------------------------------------------------------------


def _group_detail_files(detail_files):
    grouped = {}
    for path in detail_files:
        year, month = extract_path_info(path)
        if year and month:
            grouped.setdefault((year, month), []).append(path)
    return grouped


def _write_batches(frames, temp_dir, name, intermediate):
    """Concatenate parsed frames into intermediate Parquet files of BATCH_SIZE rows."""
    batch, index = [], 0
    for frame in frames:
        batch.append(frame)
        if len(batch) >= BATCH_SIZE:
            _flush_batch(batch, temp_dir / f"{name}_{index}.parquet", intermediate)
            batch, index = [], index + 1
    _flush_batch(batch, temp_dir / f"{name}_{index}.parquet", intermediate)


def _flush_batch(batch, path, intermediate):
    if batch:
        pl.concat(batch, how="diagonal").write_parquet(path, compression="zstd")
        intermediate.append(path)


def _parse_jobs(jobs, desc):
    """Run each parse job, skipping the ones that fail."""
    for label, parse, args in tqdm(jobs, desc=desc, unit="rec"):
        try:
            frame = parse(*args)
        except Exception as e:
            logger.error(f"Error processing {label}: {e}")
            continue
        if frame is not None:
            yield denull_columns(frame)


def _combine_batches(intermediate):
    logger.info(f"Combining {len(intermediate)} intermediate files...")
    columns, types = set(), {}
    for path in intermediate:
        schema = pl.read_parquet_schema(path)
        columns.update(schema)
        for name, dtype in schema.items():
            types.setdefault(name, dtype)
    columns = sorted(columns)
    logger.info(f"Found {len(columns)} unique columns")

    chunks = []
    for start in range(0, len(intermediate), 50):
        frames = []
        for path in intermediate[start:start + 50]:
            frame = pl.read_parquet(path)
            missing = [
                pl.lit(None, dtype=types.get(name, pl.Utf8)).alias(name)
                for name in columns if name not in frame.columns
            ]
            if missing:
                frame = frame.with_columns(missing)
            frames.append(frame.select(columns))
        if frames:
            chunks.append(pl.concat(frames, how="diagonal"))
    return chunks[0] if len(chunks) == 1 else pl.concat(chunks, how="diagonal")


def _log_date_range(frame):
    if not {"year", "month"}.issubset(frame.columns):
        return
    year_min, year_max = frame["year"].min(), frame["year"].max()
    if year_min is None or year_max is None:
        return
    month_min = frame.filter(pl.col("year") == year_min)["month"].min()
    month_max = frame.filter(pl.col("year") == year_max)["month"].max()
    if month_min is not None and month_max is not None:
        logger.info(f"Date range: {year_min}-{month_min:02d} to {year_max}-{month_max:02d}")


def _parse_changed_months(data_type, cfg, ward_names, versions, temp_dir, intermediate):
    """Parse every detail file and list-only entry whose source version changed."""
    detail_versions, list_versions, detail_keys = versions
    detail_files = find_detail_files(data_type)
    list_months = find_list_months(data_type)
    files_by_month = _group_detail_files(detail_files)
    logger.info(
        f"Found {len(detail_files)} detail files across {len(files_by_month)} months, "
        f"{len(list_months)} list files"
    )

    for year, month in sorted(set(files_by_month) | set(list_months)):
        month_files = files_by_month.get((year, month), [])
        file_versions = {}
        if month_files:
            context = context_version(data_type, year, month, cfg)
            file_versions = {p: f"{path_version(p)}|{context}" for p in month_files}
            month_files = [
                p for p in month_files if detail_versions.get(str(p)) != file_versions[p]
            ]

        list_file = list_path(data_type, year, month)
        list_version = path_version(list_file)
        list_lookup = load_list_lookup(data_type, year, month)
        detailed = {p.stem for p in files_by_month.get((year, month), [])}
        extra_list = [
            (entry_id, entry) for entry_id, entry in list_lookup.items()
            if entry_id not in detailed
            and entry_id not in detail_keys
            and list_versions.get(entry_id) != list_version
        ]
        if not month_files and not extra_list:
            continue

        logger.info(f"Processing {data_type} {year}-{month:02d} ({len(month_files)} new "
                    f"detail files, {len(extra_list)} list-only entries)")
        ward_lookup = (
            load_ward_lookup(data_type, year, ward_names)
            if month_files and cfg["wards"] else None
        )
        jobs = [
            (str(path), cfg["parser"], (path, list_lookup, ward_lookup, file_versions[path]))
            for path in month_files
        ] + [
            (f"list entry {entry_id}", parse_list_entry,
             (entry, year, month, list_file, cfg, list_version))
            for entry_id, entry in extra_list
        ]
        _write_batches(
            _parse_jobs(jobs, f"{year}-{month:02d}"),
            temp_dir, f"batch_{year}_{month:02d}", intermediate,
        )

    return list_months


def process_data_type(data_type, ward_names, reparse=False):
    logger.info(f"Processing {data_type}..." + (" (full reparse)" if reparse else ""))
    cfg = PARSE_CONFIG[data_type]

    existing = None if reparse else load_existing_dataset(data_type)
    if existing is not None:
        existing = ensure_row_key(existing, cfg)
    detail_versions, list_versions = build_source_versions(existing, cfg)
    versions = (detail_versions, list_versions, existing_detail_keys(existing, cfg["row_key"]))
    if existing is not None:
        logger.info(
            f"Incremental: {existing.height} existing rows; "
            f"{len(detail_versions)} versioned details, {len(list_versions)} versioned list rows"
        )

    temp_dir = Path(tempfile.mkdtemp(prefix=f"parse_{data_type}_"))
    intermediate = []
    try:
        list_months = _parse_changed_months(
            data_type, cfg, ward_names, versions, temp_dir, intermediate
        )

        if not intermediate:
            if existing is None:
                logger.warning(f"No data extracted for {data_type}")
                return
            row_key = cfg["row_key"]
            duplicates = (
                existing.height - existing[row_key].n_unique()
                if row_key in existing.columns else 0
            )
            logger.info(f"No changed sources; {existing.height} rows")
            if duplicates:
                logger.info(f"Removing {duplicates} duplicate IDs")
                existing = dedupe_dataset(existing, cfg)
            combined, legs_changed = finalize_dataset(existing, data_type, list_months)
            if duplicates or legs_changed or not dataset_paths(data_type)[1].exists():
                write_outputs(combined, data_type)
            return

        new_df = cast_columns(_combine_batches(intermediate))
        if existing is not None:
            combined = merge_incremental(existing, new_df, cfg)
            logger.info(f"Merged {new_df.height} new rows into {existing.height} existing")
        else:
            combined = dedupe_dataset(new_df, cfg)
        combined, _ = finalize_dataset(combined, data_type, list_months)
        logger.info(f"Combined: {len(combined)} rows, {len(combined.columns)} columns")

        write_outputs(combined, data_type)
        _log_date_range(combined)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _types(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build BBMP Parquet and zipped CSV datasets from raw JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source", choices=sorted(SOURCES), default=DEFAULT_SOURCE,
                        help="Which fetched source to parse")
    parser.add_argument("--types", type=_types, default=None,
                        help="Comma-separated data types (default: every type of the source)")
    parser.add_argument("--reparse", action="store_true",
                        help="Rebuild each dataset from all raw files, ignoring the "
                             "existing Parquet")
    args = parser.parse_args(argv)
    use_source(args.source)
    args.types = args.types or list(PARSE_CONFIG)
    if unknown := sorted(set(args.types) - set(PARSE_CONFIG)):
        parser.error(
            f"source {args.source} does not publish: {','.join(unknown)} "
            f"(available: {','.join(PARSE_CONFIG)})"
        )

    if not RAW_DIR.exists():
        parser.error(f"raw directory does not exist: {RAW_DIR}")
    (DATA_DIR / "full").mkdir(parents=True, exist_ok=True)

    ward_names = load_ward_dropdown()
    failures = 0
    for data_type in args.types:
        try:
            process_data_type(data_type, ward_names, reparse=args.reparse)
        except Exception as e:
            failures += 1
            logger.error(f"Error processing {data_type}: {e}", exc_info=True)

    if failures:
        logger.error(f"Parsing incomplete: {failures} dataset(s) failed")
        return 1
    logger.info("Parsing complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
