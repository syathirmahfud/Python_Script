#!/usr/bin/env python3
"""Generate a kabupaten-level PDF statistical report from BMS KMZ files.

Script version 1.0.0 (first explicitly versioned optimized release).
Dependencies: matplotlib, numpy, lxml. Python 3.10 or newer.

Layout: ONE CHART PER PAGE (tables also get dedicated pages).
Empty/unknown-only detail charts and single-year charts are skipped by default.
Use --include-empty-pages for the full set, --issues-detail for the full audit
inside the PDF, or --issues-csv issues.csv for an Excel-compatible audit.

Prefix logic:
    J...  = Jembatan
    G...  = Gorong-gorong
    other = Prefix lain

Usage:
    py sta_PDF.py D:\\KMZ_KECAMATAN --output laporan.pdf

    py sta_PDF.py kec1.kmz kec2.kmz --output statistik.pdf ^
        --kabupaten "Tanjung Jabung Barat" --tahun 2026

    py sta_PDF.py D:\\KMZ_KECAMATAN --logo logo1.png --logo logo2.png
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import re
import sys
import tempfile
import textwrap
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.image as mpimg
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from lxml import etree as ET
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.font_manager import FontProperties

__version__ = "1.0.0"
MAX_KML_BYTES = 64 * 1024 * 1024


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

KML = "http://www.opengis.net/kml/2.2"
NS = {"k": KML}

PAGE_SIZE = (11.693, 8.267)  # A4 landscape

NAVY = "#0F2D44"
TEAL = "#0E8C7F"
GOLD = "#C89B3C"
GREY = "#64748B"
WHITE = "#FFFFFF"
PAGE_BG = "#F7FAFC"
GRID = "#E7EEF4"
BORDER = "#D8E2EA"

J_COLOR = "#1F5C99"
G_COLOR = "#128C79"
OTHER_COLOR = "#C89B3C"

PREFIX_J = "J"
PREFIX_G = "G"
PREFIX_OTHER = "Lainnya"
PREFIX_ORDER = [PREFIX_J, PREFIX_G, PREFIX_OTHER]

PREFIX_LABELS = {
    PREFIX_J: "Jembatan (J)",
    PREFIX_G: "Gorong-gorong (G)",
    PREFIX_OTHER: "Prefix lain",
}

PREFIX_SHORT = {
    PREFIX_J: "J",
    PREFIX_G: "G",
    PREFIX_OTHER: "Lain",
}

PREFIX_COLORS = {
    PREFIX_J: J_COLOR,
    PREFIX_G: G_COLOR,
    PREFIX_OTHER: OTHER_COLOR,
}

CONDITIONS = ["Baik", "Sedang", "Rusak Ringan", "Rusak Berat"]
UNKNOWN = "Tidak diketahui"
ALL_CONDITIONS = CONDITIONS + [UNKNOWN]

CONDITION_COLORS = {
    "Baik": "#2E9E63",
    "Sedang": "#F2C14E",
    "Rusak Ringan": "#E8863C",
    "Rusak Berat": "#C0392B",
    "Tidak diketahui": "#8C9BAB",
}

MISSING = {"", "-", "–", "—", "n/a", "na", "none", "null", "nan"}

PKRMS_RAW_PREFIX = "pkrms_raw:"

IGNORED_EXTENDED_NAMES = {
    "bms_original_description",
    "bms_data_authority",
    "bms_nk_status",
    "qa_length_conflict",
    "STA_formatted",
    "Sumber Koordinat",
    "Status PKRMS",
    "Sumber nilai",
    "Sumber",
}

GENERATED_ROWS = {
    "Catatan asli (Description)",
    "Status penilaian",
    "Sumber nilai",
    "STA tampilan",
}

BRIDGE_NAME_PATTERN = re.compile(
    r"^([GJ]-\d+(?:\.\d+)*-\d+)(?:\s+(.*))?$",
    re.IGNORECASE,
)

KNOWN_FIELDS = (
    "No. Jembatan",
    "Nama Jembatan",
    "Longitude",
    "Latitude",
    "Kecamatan",
    "STA(m)",
    "Panjang(m)",
    "Lebar(m)",
    "Jumlah Bentang",
    "Bangunan Atas - Kode",
    "Bangunan Atas - Tipe",
    "Bangunan Atas - Kondisi",
    "Bangunan Bawah - Tipe",
    "Bangunan Bawah - Bahan",
    "Bangunan Bawah - Kondisi",
    "Fondasi - Tipe",
    "Fondasi - Bahan",
    "Fondasi - Kondisi",
    "Permukaan Jembatan - Tipe",
    "Permukaan Jembatan - Kondisi",
    "Tahun Konstruksi",
    "Kondisi Jembatan (Keseluruhan)",
    "Tahun Survey",
)

LENGTH_CLASSES = [
    ("< 6 m", None, 6),
    ("6-<12 m", 6, 12),
    ("12-<25 m", 12, 25),
    ("25-<50 m", 25, 50),
    ("≥ 50 m", 50, None),
]


plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": BORDER,
    "axes.labelcolor": NAVY,
    "text.color": NAVY,
    "xtick.color": GREY,
    "ytick.color": GREY,
    "axes.titlecolor": NAVY,
    "figure.facecolor": PAGE_BG,
    "savefig.facecolor": PAGE_BG,
    "axes.unicode_minus": False,
    "text.parse_math": False,
})


# -----------------------------------------------------------------------------
# Text and numeric helpers
# -----------------------------------------------------------------------------

def clean_text(value):
    return "".join(
        c for c in str(value if value is not None else "")
        if unicodedata.category(c) != "Cf"
    )


def field_token(value):
    return re.sub(r"[^\w]", "", clean_text(value).casefold()).replace("_", "")


FIELD_LOOKUP = {field_token(k): k for k in KNOWN_FIELDS}
FIELD_LOOKUP.update({
    "tahunsurvei": "Tahun Survey",
    "pondasitipe": "Fondasi - Tipe",
    "pondasibahan": "Fondasi - Bahan",
    "pondasikondisi": "Fondasi - Kondisi",
})
CONDITION_LOOKUP = {k.casefold(): k for k in CONDITIONS}


def is_missing(value):
    return clean_text(value).strip().casefold() in MISSING


def bridge_key(value):
    return clean_text(value).strip().upper()


def display(value):
    return "-" if is_missing(value) else str(value).strip()


@lru_cache(maxsize=512)
def canonical_field(value):
    key = re.sub(r"\s+", " ", clean_text(value)).strip().rstrip(":").strip()
    return FIELD_LOOKUP.get(field_token(key), key)


def condition_name(value):
    if is_missing(value):
        return UNKNOWN

    normalized = re.sub(r"[\s_\-]+", " ", clean_text(value).strip()).casefold()
    return CONDITION_LOOKUP.get(normalized, UNKNOWN)


def classify_prefix(ident):
    key = bridge_key(ident)

    if re.match(r"^J(?:-|\d)", key):
        return PREFIX_J

    if re.match(r"^G(?:-|\d)", key):
        return PREFIX_G

    return PREFIX_OTHER


def parse_number(value):
    if is_missing(value):
        return None

    s = clean_text(value).strip()
    # A single separator remains decimal, as in the original script.
    # With BOTH separators, accept only correctly grouped thousands.
    if "," in s and "." in s:
        if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+,\d+", s):
            s = s.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+\.\d+", s):
            s = s.replace(",", "")
        else:
            raise ValueError(f"ambiguous number format: {value!r}")
    else:
        s = s.replace(",", ".")

    try:
        n = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"invalid number: {value!r}") from exc

    if not n.is_finite():
        raise ValueError(f"non-finite number: {value!r}")

    result = float(n)
    if not math.isfinite(result):
        raise ValueError(f"number outside float range: {value!r}")
    return result


def parse_integer(value):
    n = parse_number(value)

    if n is None:
        return None

    if abs(n - round(n)) > 1e-6:
        raise ValueError(f"not an integer: {value!r}")

    return int(round(n))


def length_class(value):
    if value is None:
        return None

    for label, low, high in LENGTH_CLASSES:
        low_ok = low is None or value >= low
        high_ok = high is None or value < high

        if low_ok and high_ok:
            return label

    return LENGTH_CLASSES[-1][0]


def format_int(value):
    if value is None:
        return "-"

    try:
        return f"{int(round(float(value))):,}".replace(",", ".")
    except Exception:
        return str(value)


def format_decimal(value, digits=1):
    if value is None:
        return "-"

    try:
        s = f"{float(value):,.{digits}f}"
    except Exception:
        return str(value)

    return s.replace(",", "#").replace(".", ",").replace("#", ".")


def format_percent(value, digits=1):
    if value is None:
        return "-"

    return format_decimal(value * 100, digits) + "%"


def wrap_label(text, width=18):
    text = clean_text(text).strip()

    if not text:
        return "-"

    parts = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=True,
    )

    return "\n".join(parts) if parts else text


def truncate(text, width):
    text = str(text)

    if len(text) <= width:
        return text

    return text[: max(0, width - 1)] + "…"


def hex_to_rgb(value):
    value = str(value).lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def lighten(color, amount=0.84):
    r, g, b = hex_to_rgb(color)
    return (
        r + (1 - r) * amount,
        g + (1 - g) * amount,
        b + (1 - b) * amount,
    )


def contrast_color(rgb):
    r, g, b, *_ = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#1F2933" if luminance > 0.62 else WHITE


def clean_kecamatan_text(value):
    text = clean_text(value).strip()

    if not text or is_missing(text):
        return ""

    text = text.replace("_", " ")
    text = re.sub(r"(?i)^kecamatan\s+", "", text)
    text = re.sub(r"\s*/\s*\d{4}$", "", text)
    text = re.sub(r"[\s\-]+(?:19|20)\d{2}$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -/")

    return text.title() if text else ""


def axis_label_font(count):
    return max(6.5, min(9.0, 200 / max(1, count) + 3))


# -----------------------------------------------------------------------------
# KMZ parsing
# -----------------------------------------------------------------------------

def parse_extended_data(pm):
    fields = {}
    extended = pm.find("k:ExtendedData", NS)
    if extended is None:
        return fields
    for data in extended.iter():
        if not isinstance(data.tag, str):
            continue
        tag = ET.QName(data).localname
        if tag not in ("Data", "SimpleData"):
            continue
        name = data.get("name") or ""
        if not name or name.startswith(PKRMS_RAW_PREFIX) or name in IGNORED_EXTENDED_NAMES:
            continue
        value = (data.findtext("k:value", default="", namespaces=NS)
                 if tag == "Data" else data.text or "")
        key = canonical_field(name)
        if key not in fields or not is_missing(value):
            fields[key] = value
    return fields


def parse_popup_table(pm):
    desc = pm.findtext("k:description", default="", namespaces=NS) or ""
    if "<table" not in desc.lower():
        return {}
    h = ET.HTML(desc, parser=ET.HTMLParser(no_network=True))
    if h is None:
        return {}
    fields = {}
    for tr in h.iter("tr"):
        cells = [cell for cell in tr if cell.tag in ("td", "th")]
        if len(cells) != 2:
            continue
        if any(el.tag in ("img", "table") for cell in cells for el in cell.iterdescendants()):
            continue
        key = canonical_field("".join(cells[0].itertext()).strip())
        value = "".join(cells[1].itertext()).strip()
        if key and key not in GENERATED_ROWS and key not in fields:
            fields[key] = value
    return fields


def kecamatan_from_placemark(pm):
    for parent in pm.iterancestors():
        if not isinstance(parent.tag, str):
            continue

        if ET.QName(parent).localname not in ("Folder", "Document"):
            continue

        label = parent.findtext("k:name", default="", namespaces=NS)
        label = clean_text(label).strip()

        if not label:
            continue

        match = re.search(
            r"\bKECAMATAN\s+(.+?)(?:\s*/\s*\d{4})?$",
            label,
            re.IGNORECASE,
        )

        if match:
            return clean_kecamatan_text(match.group(1))

        match = re.fullmatch(
            r"([^/]+?)\s*/\s*\d{4}",
            label,
            re.IGNORECASE,
        )

        if match:
            candidate = match.group(1)

            if not re.search(
                r"\b(RUAS|JALAN|ROAD|SURVEY|INVENTARIS)\b",
                candidate,
                re.IGNORECASE,
            ):
                return clean_kecamatan_text(candidate)

    return ""


def read_kmz(path, explicit_kecamatan="", issues=None):
    """Read the entry KML only; photos are never decompressed or extracted."""
    path = Path(path)
    if issues is None:
        issues = []
    records = []
    try:
        with zipfile.ZipFile(path) as z:
            candidates = [info for info in z.infolist() if info.filename.lower().endswith(".kml")]
            if not candidates:
                raise ValueError("No KML file found inside KMZ.")
            roots = [info for info in candidates if info.filename.casefold() == "doc.kml"]
            if not roots and len(candidates) > 1:
                raise ValueError("Multiple KML files without a root doc.kml; entry document is ambiguous.")
            info = roots[0] if roots else candidates[0]
            if len(roots) > 1:
                raise ValueError("Multiple root doc.kml entries inside KMZ.")
            if info.file_size > MAX_KML_BYTES:
                raise ValueError(f"KML exceeds {MAX_KML_BYTES // (1024 * 1024)} MiB limit.")
            parser = ET.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
            with z.open(info) as stream:
                tree = ET.parse(stream, parser)
            root = tree.getroot()
            if ET.QName(root).localname != "kml":
                raise ValueError("Root element is not KML.")
            if tree.docinfo.doctype:
                raise ValueError("KML with a DTD is not supported.")
            namespace = ET.QName(root).namespace
            if namespace not in (None, KML):
                raise ValueError(f"Unsupported KML namespace: {namespace}")
            if namespace is None:
                for node in root.iter():
                    if isinstance(node.tag, str) and ET.QName(node).namespace is None:
                        node.tag = f"{{{KML}}}{node.tag}"
            for pm in root.iter(f"{{{KML}}}Placemark"):
                popup = parse_popup_table(pm)
                extended = parse_extended_data(pm)
                fields = dict(popup)
                for key, value in extended.items():
                    # Non-empty ExtendedData remains authoritative; blanks must
                    # not erase real popup values.
                    if not is_missing(value):
                        if key in KNOWN_FIELDS and not is_missing(popup.get(key)):
                            if clean_text(value).strip() != clean_text(popup[key]).strip():
                                issues.append(("Field conflict", path.name,
                                               extended.get("No. Jembatan") or popup.get("No. Jembatan", "-"),
                                               f"{key}: popup={popup[key]!r}; ExtendedData={value!r}; using ExtendedData"))
                        fields[key] = value
                    elif key not in fields:
                        fields[key] = value
                ident_value = fields.get("No. Jembatan", "")
                name = clean_text(pm.findtext("k:name", default="", namespaces=NS)).strip()
                match = BRIDGE_NAME_PATTERN.fullmatch(name)
                if is_missing(ident_value) and match:
                    ident_value = match.group(1)
                    fields["No. Jembatan"] = ident_value
                if is_missing(ident_value):
                    # Ignore unrelated map features, but report survey records
                    # that cannot be identified instead of silently losing them.
                    if any(key in fields for key in KNOWN_FIELDS):
                        issues.append(("Missing ID", path.name, "-", f"Placemark: {name or '(unnamed)'}"))
                    continue
                if match and bridge_key(match.group(1)) != bridge_key(ident_value):
                    issues.append(("ID conflict", path.name, str(ident_value),
                                   f"Placemark name uses {match.group(1)}; keeping field ID"))
                if match and is_missing(fields.get("Nama Jembatan")):
                    fields["Nama Jembatan"] = match.group(2) or "-"
                rec = {canonical_field(k): display(v) for k, v in fields.items()}
                rec.update({"No. Jembatan": display(ident_value), "_ident": bridge_key(ident_value),
                            "_source_file": path.name, "_source_path": str(path)})
                kecamatan = (clean_kecamatan_text(explicit_kecamatan)
                             or clean_kecamatan_text(rec.get("Kecamatan", ""))
                             or kecamatan_from_placemark(pm)
                             or clean_kecamatan_text(path.stem)
                             or clean_kecamatan_text(path.parent.name) or "Unknown")
                rec["Kecamatan Report"] = kecamatan
                coords_text = pm.findtext("k:Point/k:coordinates", default="", namespaces=NS).strip()
                coords = coords_text.split()[0].split(",") if coords_text else []
                if len(coords) >= 2:
                    for key, value in zip(("Longitude", "Latitude"), coords):
                        if is_missing(rec.get(key)):
                            rec[key] = value.strip()
                records.append(rec)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ET.XMLSyntaxError) as exc:
        issues.append(("Read error", path.name, "-", str(exc)))
    return records


def collect_inputs(patterns):
    files = []
    seen = set()

    def add_path(p):
        p = Path(p).expanduser()

        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() == ".kmz":
                    add_path(f)

        elif p.is_file() and p.suffix.lower() == ".kmz":
            resolved = p.resolve()

            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)

        else:
            raise ValueError(f"Input not found or not a KMZ file: {p}")

    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            matches = [Path(x) for x in glob.glob(pattern, recursive=True)]

            if not matches:
                raise ValueError(f"No KMZ files match: {pattern}")

            for match in matches:
                add_path(match)
        else:
            add_path(pattern)

    if not files:
        raise ValueError("No KMZ files found.")

    return files


def build_kecamatan_map(files, values):
    if not values:
        return {}

    if len(values) == 1:
        return {f: clean_kecamatan_text(values[0]) for f in files}

    if len(values) == len(files):
        return {
            f: clean_kecamatan_text(v)
            for f, v in zip(files, values)
        }

    raise ValueError(
        "--kecamatan must be provided once, or once for each KMZ file."
    )


def prepare_records(records, issues, allow_duplicates=False):
    seen = {}
    included = []
    duplicate_count = 0
    for original in records:
        rec = dict(original)
        ident = rec["_ident"]
        if ident in seen:
            duplicate_count += 1
            issues.append(("Duplicate ID", rec["_source_file"], rec.get("No. Jembatan", "-"),
                           f"First seen in {seen[ident]['_source_file']}; "
                           + ("included by --allow-duplicates" if allow_duplicates else "excluded")))
            if not allow_duplicates:
                continue
        else:
            seen[ident] = rec
        rec["_prefix"] = classify_prefix(ident)
        if rec["_prefix"] == PREFIX_OTHER:
            issues.append(("Unknown prefix", rec["_source_file"], ident, "ID does not begin with a J/G code"))
        raw_condition = rec.get("Kondisi Jembatan (Keseluruhan)")
        rec["_condition"] = condition_name(raw_condition)
        if rec["_condition"] == UNKNOWN:
            kind = "Missing condition" if is_missing(raw_condition) else "Unknown condition"
            issues.append((kind, rec["_source_file"], ident,
                           f"Kondisi Jembatan (Keseluruhan): {display(raw_condition)}"))
        for field, key, converter in (("Panjang(m)", "_length", parse_number),
                                      ("Lebar(m)", "_width", parse_number),
                                      ("Jumlah Bentang", "_spans", parse_integer)):
            try:
                value = converter(rec.get(field))
                if value is not None and value <= 0:
                    raise ValueError("must be positive; zero is not a measured dimension/span count")
                rec[key] = value
                if value is None:
                    issues.append(("Missing value", rec["_source_file"], ident, field))
            except ValueError as exc:
                rec[key] = None
                issues.append(("Invalid number", rec["_source_file"], ident,
                               f"{field}: {rec.get(field)} ({exc})"))
        included.append(rec)
    return included, duplicate_count


def top_counter(counter, n=10):
    items = [(k, v) for k, v in counter.items() if v]
    items.sort(key=lambda item: (-item[1], item[0]))
    return items[:n]


def year_sort_key(item):
    try:
        return (0, int(item[0]))
    except Exception:
        return (1, item[0])


def aggregate(records):
    stats = {
        "total": 0,
        "prefix": Counter(),
        "kec_prefix": defaultdict(Counter),
        "kec_total": Counter(),
        "condition_by_scope": defaultdict(Counter),
        "kec_condition": defaultdict(Counter),
        "kec_prefix_condition": defaultdict(Counter),
        "length_total": defaultdict(float),
        "length_count": defaultdict(int),
        "length_values": defaultdict(list),
        "width_total": defaultdict(float),
        "width_count": defaultdict(int),
        "width_values": defaultdict(list),
        "span_total": defaultdict(int),
        "span_count": defaultdict(int),
        "kec_length": defaultdict(lambda: defaultdict(float)),
        "kec_length_count": defaultdict(lambda: defaultdict(int)),
        "kec_width_total": defaultdict(lambda: defaultdict(float)),
        "kec_width_count": defaultdict(lambda: defaultdict(int)),
        "kec_spans": defaultdict(lambda: defaultdict(int)),
        "length_class": defaultdict(Counter),
        "type": defaultdict(Counter),
        "foundation": defaultdict(Counter),
        "surface": defaultdict(Counter),
        "bawah_material": defaultdict(Counter),
        "survey_year": defaultdict(Counter),
        "construction_year": defaultdict(Counter),
        "source_prefix": defaultdict(Counter),
        "source_total": Counter(),
        "source_kec": defaultdict(Counter),
        "source_length": defaultdict(float),
    }

    for rec in records:
        stats["total"] += 1

        prefix = rec["_prefix"]
        kecamatan = rec.get("Kecamatan Report") or "Unknown"
        condition = rec["_condition"]
        source = rec["_source_file"]

        stats["prefix"][prefix] += 1
        stats["kec_prefix"][kecamatan][prefix] += 1

        for scope in (prefix, "ALL"):
            stats["condition_by_scope"][scope][condition] += 1

        stats["kec_condition"][kecamatan][condition] += 1
        stats["kec_prefix_condition"][(kecamatan, prefix)][condition] += 1

        length = rec.get("_length")
        width = rec.get("_width")
        spans = rec.get("_spans")

        if length is not None:
            cls = length_class(length)

            for scope in (prefix, "ALL"):
                stats["length_total"][scope] += length
                stats["length_count"][scope] += 1
                stats["length_values"][scope].append(length)
                if cls:
                    stats["length_class"][scope][cls] += 1

            stats["kec_length"][prefix][kecamatan] += length
            stats["kec_length"]["ALL"][kecamatan] += length
            stats["kec_length_count"][prefix][kecamatan] += 1
            stats["kec_length_count"]["ALL"][kecamatan] += 1
            stats["source_length"][source] += length

        if width is not None:
            for scope in (prefix, "ALL"):
                stats["width_total"][scope] += width
                stats["width_count"][scope] += 1
                stats["width_values"][scope].append(width)

            stats["kec_width_total"][prefix][kecamatan] += width
            stats["kec_width_total"]["ALL"][kecamatan] += width
            stats["kec_width_count"][prefix][kecamatan] += 1
            stats["kec_width_count"]["ALL"][kecamatan] += 1

        if spans is not None:
            for scope in (prefix, "ALL"):
                stats["span_total"][scope] += spans
                stats["span_count"][scope] += 1

            stats["kec_spans"][prefix][kecamatan] += spans
            stats["kec_spans"]["ALL"][kecamatan] += spans

        bridge_type = rec.get("Bangunan Atas - Tipe", "")

        if is_missing(bridge_type):
            bridge_type = rec.get("Bangunan Atas - Kode", "")

        bridge_type = UNKNOWN if is_missing(bridge_type) else display(bridge_type)

        foundation = rec.get("Fondasi - Tipe", "")
        foundation = UNKNOWN if is_missing(foundation) else display(foundation)

        surface = rec.get("Permukaan Jembatan - Tipe", "")
        surface = UNKNOWN if is_missing(surface) else display(surface)

        bawah_material = rec.get("Bangunan Bawah - Bahan", "")
        bawah_material = UNKNOWN if is_missing(bawah_material) else display(bawah_material)

        for scope in (prefix, "ALL"):
            stats["type"][scope][bridge_type] += 1
            stats["foundation"][scope][foundation] += 1
            stats["surface"][scope][surface] += 1
            stats["bawah_material"][scope][bawah_material] += 1

        survey_year = rec.get("Tahun Survey", "")

        if not is_missing(survey_year):
            year_value = display(survey_year)
            for scope in (prefix, "ALL"):
                stats["survey_year"][scope][year_value] += 1

        construction_year = rec.get("Tahun Konstruksi", "")

        if not is_missing(construction_year):
            year_value = display(construction_year)
            for scope in (prefix, "ALL"):
                stats["construction_year"][scope][year_value] += 1

        stats["source_prefix"][source][prefix] += 1
        stats["source_kec"][source][kecamatan] += 1

    stats["kec_total"] = Counter({
        kecamatan: sum(counter.values())
        for kecamatan, counter in stats["kec_prefix"].items()
    })

    stats["source_total"] = Counter({
        source: sum(counter.values())
        for source, counter in stats["source_prefix"].items()
    })

    return stats


# -----------------------------------------------------------------------------
# Matplotlib helpers
# -----------------------------------------------------------------------------

def rounded_box(ax, x=0.02, y=0.05, w=0.96, h=0.90,
                fc=WHITE, ec=BORDER, lw=1.2, radius=0.08,
                zorder=1, alpha=1.0):
    box = mpatches.FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        alpha=alpha,
        zorder=zorder,
        clip_on=False,
    )
    ax.add_patch(box)


def kpi_card(ax, value, label, color, sublabel=""):
    ax.set_axis_off()

    rounded_box(ax, fc=WHITE, ec=color, lw=1.4, radius=0.10)

    ax.add_patch(mpatches.Rectangle(
        (0.10, 0.79),
        0.80,
        0.045,
        transform=ax.transAxes,
        facecolor=color,
        edgecolor="none",
        zorder=2,
        clip_on=False,
    ))

    ax.text(
        0.5, 0.55, str(value),
        transform=ax.transAxes,
        ha="center", va="center",
        fontsize=20, fontweight="bold", color=color,
    )

    ax.text(
        0.5, 0.30, wrap_label(label, 24),
        transform=ax.transAxes,
        ha="center", va="center",
        fontsize=8.5, color=GREY,
    )

    if sublabel:
        ax.text(
            0.5, 0.13, sublabel,
            transform=ax.transAxes,
            ha="center", va="center",
            fontsize=7, color=GREY,
        )


def style_ax(ax, title=None, xlabel=None, ylabel=None,
             grid_axis="x", title_size=11.0):
    ax.set_facecolor(WHITE)

    if title:
        ax.set_title(
            title,
            fontsize=title_size,
            fontweight="bold",
            color=NAVY,
            pad=10,
        )

    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8.5, color=GREY)

    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8.5, color=GREY)

    ax.tick_params(colors=GREY, labelsize=8, length=2)

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    for side in ("left", "bottom"):
        ax.spines[side].set_color(BORDER)

    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)


def no_data(ax, message="Data tidak tersedia"):
    ax._report_no_data = True
    ax.set_axis_off()
    ax.text(
        0.5, 0.5, message,
        transform=ax.transAxes,
        ha="center", va="center",
        fontsize=10, color=GREY,
    )


def donut(ax, labels, values, colors, center_value, center_label,
          title=None, legend_ncol=2):
    pairs = [
        (label, value, color)
        for label, value, color in zip(labels, values, colors)
        if value and value > 0
    ]

    if not pairs:
        no_data(ax, title or "Data tidak tersedia")
        return

    if all(p[0] == UNKNOWN for p in pairs):
        ax._report_uninformative = True
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    colors = [p[2] for p in pairs]

    if title:
        ax.set_title(title, fontsize=11, fontweight="bold", color=NAVY, pad=10)

    def autopct(pct):
        return f"{pct:.0f}%" if pct >= 5 else ""

    wedges, _, autotexts = ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops=dict(width=0.38, edgecolor=WHITE, linewidth=2),
        autopct=autopct,
        pctdistance=0.79,
    )

    for wedge, text in zip(wedges, autotexts):
        text.set_fontsize(8)
        text.set_fontweight("bold")
        text.set_color(contrast_color(wedge.get_facecolor()))

    ax.text(
        0, 0.07, center_value,
        ha="center", va="center",
        fontsize=24, fontweight="bold", color=NAVY,
    )

    ax.text(
        0, -0.17, center_label,
        ha="center", va="center",
        fontsize=9, color=GREY,
    )

    legend_labels = [
        f"{wrap_label(label, 24)}: {format_int(value)}"
        for label, value in zip(labels, values)
    ]

    ax.legend(
        wedges,
        legend_labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=legend_ncol,
        fontsize=7.5,
        frameon=False,
        handlelength=1.1,
        handleheight=1.1,
        columnspacing=0.9,
        labelspacing=0.35,
    )


def hbar_simple(ax, labels, values, color, title=None,
                xlabel=None, wrap=22, number_format=None, font_size=None):
    if number_format is None:
        number_format = format_int

    if not labels:
        no_data(ax, title or "Data tidak tersedia")
        return

    labels = [wrap_label(label, wrap) for label in labels][::-1]
    values = list(values)[::-1]

    y = np.arange(len(labels), dtype=float)
    bars = ax.barh(
        y,
        values,
        color=color,
        height=0.62,
        edgecolor=WHITE,
        zorder=3,
    )

    fs = font_size or axis_label_font(len(labels))
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=fs, color=NAVY)

    max_value = max(values) if values else 1
    max_value = max_value if max_value > 0 else 1
    ax.set_xlim(0, max_value * 1.15)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_width() + max_value * 0.012,
            bar.get_y() + bar.get_height() / 2,
            number_format(value),
            va="center",
            fontsize=7.8,
            color=GREY,
        )

    style_ax(ax, title, xlabel, grid_axis="x")


def grouped_vbar(ax, categories, series, title=None,
                 ylabel=None, wrap=10, legend_ncol=2):
    if not categories:
        no_data(ax, title or "Data tidak tersedia")
        return

    x = np.arange(len(categories), dtype=float)
    count = max(1, len(series))
    width = 0.78 / count

    all_values = [v for _, values, _ in series for v in values]
    max_y = max(all_values) if all_values else 1
    max_y = max_y if max_y > 0 else 1

    for i, (label, values, color) in enumerate(series):
        pos = x + (i - (count - 1) / 2) * width
        vals = [float(v) for v in values]

        bars = ax.bar(
            pos,
            vals,
            width,
            color=color,
            label=label,
            edgecolor=WHITE,
            zorder=3,
        )

        for bar, value in zip(bars, vals):
            if value > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    value + max_y * 0.012,
                    format_int(value),
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                    color=GREY,
                )

    ax.set_ylim(0, max_y * 1.20)
    ax.set_xticks(x)
    ax.set_xticklabels([wrap_label(c, wrap) for c in categories], fontsize=8)

    style_ax(ax, title, ylabel=ylabel, grid_axis="y")

    ax.legend(fontsize=8, frameon=False, ncol=legend_ncol, loc="upper right")


def grouped_hbar_prefix(ax, labels, series, title=None, wrap=26):
    if not labels:
        no_data(ax, title or "Data tidak tersedia")
        return

    labels = labels[::-1]
    y = np.arange(len(labels), dtype=float)
    count = max(1, len(series))
    height = 0.78 / count
    max_value = 1

    for i, (label, values, color) in enumerate(series):
        vals = [float(v) for v in values][::-1]

        if vals:
            max_value = max(max_value, max(vals))

        offset = (i - (count - 1) / 2) * height

        ax.barh(
            y + offset,
            vals,
            height,
            color=color,
            label=label,
            edgecolor=WHITE,
            zorder=3,
        )

    fs = axis_label_font(len(labels))
    ax.set_yticks(y)
    ax.set_yticklabels([wrap_label(label, wrap) for label in labels], fontsize=fs)
    ax.set_xlim(0, max_value * 1.10)

    style_ax(ax, title, grid_axis="x")

    ax.legend(fontsize=8, frameon=False, ncol=count, loc="lower right")


def stacked_hbar_prefix(ax, stats, top_n=None, title=None):
    items = sorted(
        stats["kec_prefix"].items(),
        key=lambda item: (-sum(item[1].values()), item[0]),
    )

    if not items:
        no_data(ax, title or "Data tidak tersedia")
        return

    truncated = top_n is not None and len(items) > top_n
    items = items[:top_n] if top_n else items
    items = items[::-1]

    labels = [wrap_label(kecamatan, 22) for kecamatan, _ in items]
    y = np.arange(len(items), dtype=float)
    left = np.zeros(len(items), dtype=float)

    active_prefixes = [
        prefix for prefix in PREFIX_ORDER
        if stats["prefix"].get(prefix, 0) > 0
    ]

    for prefix in active_prefixes:
        values = np.array([counter.get(prefix, 0) for _, counter in items], dtype=float)

        ax.barh(
            y,
            values,
            left=left,
            color=PREFIX_COLORS[prefix],
            height=0.62,
            edgecolor=WHITE,
            label=PREFIX_SHORT[prefix],
            zorder=3,
        )

        left += values

    totals = left
    max_total = float(max(totals.max(), 1)) if len(totals) else 1.0

    for i, total in enumerate(totals):
        if total > 0:
            ax.text(
                total + max_total * 0.012,
                y[i],
                format_int(total),
                va="center",
                fontsize=7.8,
                color=GREY,
            )

    fs = axis_label_font(len(items))
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=fs)
    ax.set_xlim(0, max_total * 1.10)

    shown_title = title
    if truncated:
        shown_title = (title or "") + f" (Top {top_n})"

    style_ax(ax, shown_title, grid_axis="x")

    ax.legend(fontsize=8, frameon=False, ncol=len(active_prefixes), loc="lower right")


def stacked_length_by_kec(ax, stats, top_n=None, title=None):
    totals = stats["kec_length"].get("ALL", {})

    if not totals:
        no_data(ax, title or "Data tidak tersedia")
        return

    items = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    items = items[:top_n] if top_n else items
    items = items[::-1]

    labels = [wrap_label(kecamatan, 22) for kecamatan, _ in items]
    y = np.arange(len(items), dtype=float)
    left = np.zeros(len(items), dtype=float)

    active_prefixes = [
        prefix for prefix in PREFIX_ORDER
        if stats["length_count"].get(prefix, 0) > 0
    ]

    for prefix in active_prefixes:
        values = np.array(
            [stats["kec_length"][prefix].get(kecamatan, 0.0) for kecamatan, _ in items],
            dtype=float,
        )

        ax.barh(
            y,
            values,
            left=left,
            color=PREFIX_COLORS[prefix],
            height=0.62,
            edgecolor=WHITE,
            label=PREFIX_SHORT[prefix],
            zorder=3,
        )

        left += values

    totals_arr = left
    max_total = float(max(totals_arr.max(), 1)) if len(totals_arr) else 1.0

    for i, total in enumerate(totals_arr):
        if total > 0:
            ax.text(
                total + max_total * 0.012,
                y[i],
                format_decimal(total, 0),
                va="center",
                fontsize=7.5,
                color=GREY,
            )

    fs = axis_label_font(len(items))
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=fs)
    ax.set_xlim(0, max_total * 1.12)

    style_ax(ax, title, xlabel="Meter", grid_axis="x")
    ax.legend(fontsize=8, frameon=False, ncol=len(active_prefixes), loc="lower right")


def stacked_condition_by_prefix(ax, stats, title=None):
    scopes = [
        prefix for prefix in PREFIX_ORDER
        if stats["prefix"].get(prefix, 0) > 0
    ]

    if not scopes:
        no_data(ax, title or "Data tidak tersedia")
        return

    y = np.arange(len(scopes), dtype=float)[::-1]
    left = np.zeros(len(scopes), dtype=float)

    for condition in ALL_CONDITIONS:
        values = []

        for scope in scopes:
            total = sum(stats["condition_by_scope"][scope].values())
            count = stats["condition_by_scope"][scope].get(condition, 0)
            values.append((count / total * 100) if total else 0.0)

        bars = ax.barh(
            y,
            values,
            left=left,
            color=CONDITION_COLORS[condition],
            height=0.48,
            edgecolor=WHITE,
            label=condition,
            zorder=3,
        )

        text_color = contrast_color(hex_to_rgb(CONDITION_COLORS[condition]))

        for bar, value in zip(bars, values):
            if value >= 7:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_y() + bar.get_height() / 2,
                    format_decimal(value, 0) + "%",
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    fontweight="bold",
                    color=text_color,
                )

        left += np.array(values, dtype=float)

    ax.set_yticks(y)
    ax.set_yticklabels([PREFIX_LABELS[scope] for scope in scopes], fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Persentase (%)", fontsize=8.5, color=GREY)

    style_ax(ax, title, grid_axis="x")

    ax.legend(
        fontsize=7.5,
        frameon=False,
        ncol=5,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.10),
    )


def stacked_condition_by_kec(ax, stats, top_n=None, title=None):
    items = sorted(
        stats["kec_total"].items(),
        key=lambda item: (-item[1], item[0]),
    )

    items = items[:top_n] if top_n else items
    items = items[::-1]

    if not items:
        no_data(ax, title or "Data tidak tersedia")
        return

    kecamatans = [kecamatan for kecamatan, _ in items]
    y = np.arange(len(kecamatans), dtype=float)
    left = np.zeros(len(kecamatans), dtype=float)

    for condition in ALL_CONDITIONS:
        values = []

        for kecamatan in kecamatans:
            total = stats["kec_total"][kecamatan]
            count = stats["kec_condition"][kecamatan].get(condition, 0)
            values.append((count / total * 100) if total else 0.0)

        bars = ax.barh(
            y,
            values,
            left=left,
            color=CONDITION_COLORS[condition],
            height=0.60,
            edgecolor=WHITE,
            label=condition,
            zorder=3,
        )

        text_color = contrast_color(hex_to_rgb(CONDITION_COLORS[condition]))

        for bar, value in zip(bars, values):
            if value >= 8:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_y() + bar.get_height() / 2,
                    format_decimal(value, 0) + "%",
                    ha="center",
                    va="center",
                    fontsize=7,
                    fontweight="bold",
                    color=text_color,
                )

        left += np.array(values, dtype=float)

    fs = axis_label_font(len(kecamatans))
    ax.set_yticks(y)
    ax.set_yticklabels([wrap_label(k, 22) for k in kecamatans], fontsize=fs)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Persentase (%)", fontsize=8.5, color=GREY)

    style_ax(ax, title, grid_axis="x")

    ax.legend(
        fontsize=7.5,
        frameon=False,
        ncol=5,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.10),
    )


def length_class_chart(ax, stats, scopes=None, title=None):
    if scopes is None:
        scopes = [
            prefix for prefix in PREFIX_ORDER
            if stats["prefix"].get(prefix, 0) > 0
        ]

    if not scopes:
        no_data(ax, title or "Data tidak tersedia")
        return

    categories = [label for label, _, _ in LENGTH_CLASSES]
    series = []

    for scope in scopes:
        values = [stats["length_class"][scope].get(label, 0) for label in categories]

        if sum(values) > 0:
            series.append((PREFIX_SHORT[scope], values, PREFIX_COLORS[scope]))

    if not series:
        no_data(ax, title or "Data tidak tersedia")
        return

    grouped_vbar(ax, categories, series, title=title, ylabel="Jumlah", wrap=9)


def histogram(ax, values, color, title=None, xlabel="Panjang (m)"):
    values = [v for v in values if v is not None]

    if not values:
        no_data(ax, title or "Data tidak tersedia")
        return

    bins = max(6, min(24, int(math.sqrt(len(values)) * 2) + 1))

    ax.hist(
        values,
        bins=bins,
        color=color,
        edgecolor=WHITE,
        alpha=0.95,
        zorder=3,
    )

    mean_value = sum(values) / len(values)
    ax.axvline(mean_value, color=NAVY, linestyle="--", linewidth=1.4, zorder=4)

    top = ax.get_ylim()[1]

    ax.text(
        mean_value,
        top * 0.94,
        f"Rata-rata {format_decimal(mean_value, 1)} m",
        ha="center",
        va="top",
        fontsize=8,
        color=NAVY,
        bbox=dict(
            facecolor=WHITE,
            edgecolor=BORDER,
            boxstyle="round,pad=0.3",
        ),
    )

    style_ax(ax, title, xlabel=xlabel, ylabel="Jumlah", grid_axis="y")


def top_counter_hbar(ax, counter, color, title=None, top_n=12,
                     wrap=28, xlabel="Jumlah"):
    if not any(k != UNKNOWN and v for k, v in counter.items()):
        ax._report_uninformative = True
    items = top_counter(counter, top_n)

    if not items:
        no_data(ax, title or "Data tidak tersedia")
        return

    labels = [label for label, _ in items]
    values = [value for _, value in items]

    hbar_simple(
        ax,
        labels,
        values,
        color,
        title=title,
        xlabel=xlabel,
        wrap=wrap,
    )


def year_chart(ax, counter, color, title=None):
    if len(counter) <= 1:
        ax._report_uninformative = True
    items = [(k, v) for k, v in counter.items() if v]
    items.sort(key=year_sort_key)

    if not items:
        no_data(ax, title or "Data tidak tersedia")
        return

    items = items[-16:]

    labels = [k for k, _ in items]
    values = [v for _, v in items]
    x = np.arange(len(labels), dtype=float)

    bars = ax.bar(
        x,
        values,
        color=color,
        width=0.62,
        edgecolor=WHITE,
        zorder=3,
    )

    max_value = max(values) if values else 1
    max_value = max_value if max_value > 0 else 1

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + max_value * 0.02,
            format_int(value),
            ha="center",
            va="bottom",
            fontsize=7.5,
            color=GREY,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7.5)
    ax.set_ylim(0, max_value * 1.20)

    style_ax(ax, title, ylabel="Jumlah", grid_axis="y")


def condition_heatmap(ax, stats, prefix, cmap_name, title=None):
    kecamatans = [
        kecamatan
        for kecamatan, counter in stats["kec_prefix"].items()
        if counter.get(prefix, 0) > 0
    ]

    kecamatans.sort(
        key=lambda kecamatan: (
            -stats["kec_prefix"][kecamatan].get(prefix, 0),
            kecamatan,
        )
    )

    if not kecamatans:
        no_data(ax, title or "Data tidak tersedia")
        return

    if not any(stats["condition_by_scope"][prefix].get(c, 0) for c in CONDITIONS):
        ax._report_uninformative = True
    columns = ALL_CONDITIONS

    matrix = np.array(
        [
            [
                stats["kec_prefix_condition"][(kecamatan, prefix)].get(condition, 0)
                for condition in columns
            ]
            for kecamatan in kecamatans
        ],
        dtype=float,
    )

    vmax = max(1.0, float(matrix.max()))

    ax.imshow(matrix, cmap=cmap_name, aspect="auto", vmin=0, vmax=vmax)

    ax.set_xticks(np.arange(len(columns)))
    ax.set_xticklabels([wrap_label(c, 11) for c in columns], fontsize=8)

    y_fontsize = axis_label_font(len(kecamatans))
    ax.set_yticks(np.arange(len(kecamatans)))
    ax.set_yticklabels([wrap_label(k, 24) for k in kecamatans], fontsize=y_fontsize)

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = int(matrix[i, j])
            text_color = WHITE if value > vmax * 0.60 else NAVY

            ax.text(
                j, i, format_int(value),
                ha="center",
                va="center",
                fontsize=8,
                color=text_color,
            )

    ax.set_xticks(np.arange(len(columns) + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(len(kecamatans) + 1) - 0.5, minor=True)
    ax.grid(which="minor", color=WHITE, linewidth=1.2)
    ax.tick_params(which="both", length=0)

    if title:
        ax.set_title(title, fontsize=11, fontweight="bold", color=NAVY, pad=10)


# -----------------------------------------------------------------------------
# Table helpers
# -----------------------------------------------------------------------------

def normalize_widths(widths):
    total = sum(widths) or 1
    return [w / total for w in widths]


def table_col_widths(headers, rows, extra_weights=None, max_chars=70):
    lengths = []

    for c, header in enumerate(headers):
        longest = len(str(header))

        for row in rows:
            if c < len(row):
                longest = max(longest, min(len(str(row[c])), max_chars))

        lengths.append(longest + 2)

    if extra_weights:
        for i, weight in enumerate(extra_weights):
            if i < len(lengths):
                lengths[i] = max(lengths[i], weight)

    # Reserve enough width for the longest header word, including cell padding.
    # This avoids headings such as "Jumlah" breaking into "Jumla / h".
    minimums = [(max((text_width(word, 9, True) for word in str(h).split()), default=0) + 14)
                / (PAGE_SIZE[0] * 72 * 0.84) for h in headers]
    if sum(minimums) < 0.95:
        remaining = 1 - sum(minimums)
        weights = normalize_widths(lengths)
        return [base + remaining * weight for base, weight in zip(minimums, weights)]
    return normalize_widths(lengths)


@lru_cache(maxsize=8192)
def text_width(text, size, bold=False):
    # Measure at 72 dpi: one pixel equals one PDF point.
    renderer = RendererAgg(1, 1, 72)
    font = FontProperties(family="DejaVu Sans", size=size,
                          weight="bold" if bold else "normal")
    return renderer.get_text_width_height_descent(text, font, ismath=False)[0]


def wrap_cell(value, width_points, size, bold=False):
    lines = []
    for paragraph in str(value).split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if text_width(candidate, size, bold) <= width_points:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            # Break a long filename/ID rather than crop it.
            while word and text_width(word, size, bold) > width_points:
                lo, hi = 1, len(word)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if text_width(word[:mid], size, bold) <= width_points:
                        lo = mid
                    else:
                        hi = mid - 1
                lines.append(word[:lo])
                word = word[lo:]
            line = word
        lines.append(line)
    return "\n".join(lines)


def table_layout(headers, rows, widths, fontsize, width_points):
    wrapped = []
    heights = []
    for r, row in enumerate([headers] + list(rows)):
        cells = [wrap_cell(value, max(8, width_points * widths[c] - 12),
                           fontsize, bold=(r == 0)) for c, value in enumerate(row)]
        wrapped.append(cells)
        heights.append(max(22, max(text.count("\n") + 1 for text in cells)
                           * fontsize * 1.3 + 10))
    return wrapped, heights


def make_table(ax, headers, rows, col_widths=None, fontsize=7.6,
               row_scale=None, header_color=NAVY, total_row=None,
               row_facecolors=None):
    ax.set_axis_off()
    cell_rows = list(rows) + ([total_row] if total_row is not None else [])
    if not cell_rows:
        no_data(ax)
        return None
    widths = col_widths or table_col_widths(headers, cell_rows)
    width_points = ax.get_position().width * ax.figure.get_figwidth() * 72
    height_points = ax.get_position().height * ax.figure.get_figheight() * 72
    wrapped, heights = table_layout(headers, cell_rows, widths, fontsize, width_points)
    if sum(heights) > height_points + 0.1:
        raise ValueError("Table exceeds page height; use build_table_pages or fewer rows per page.")
    table = ax.table(cellText=wrapped[1:], colLabels=wrapped[0], cellLoc="center",
                     loc="center", colWidths=widths)
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)
    last = len(cell_rows) if total_row is not None else None
    for (r, c), cell in table.get_celld().items():
        cell.set_height(heights[r] / height_points)
        cell.PAD = 0.025
        cell.set_edgecolor("#E4EBF1")
        cell.set_linewidth(0.6)
        if r == 0:
            cell.set_facecolor(header_color)
            cell.get_text().set_color(WHITE)
            cell.get_text().set_fontweight("bold")
        elif r == last:
            cell.set_facecolor("#E8EFF5")
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(row_facecolors[r - 1] if row_facecolors and row_facecolors[r - 1]
                               else ("#F6F9FC" if r % 2 == 0 else WHITE))
        if c == 0 and r > 0:
            cell.get_text().set_ha("left")
    return table


def chunks(values, size):
    values = list(values)

    for i in range(0, len(values), size):
        yield values[i:i + size]


def build_table_pages(report, title, subtitle, headers, rows,
                      total_row=None, per_page=20, row_facecolors=None,
                      fontsize=7.8, col_widths=None):
    rows = list(rows)
    widths = col_widths or table_col_widths(headers, rows + ([total_row] if total_row else []))
    width_points = PAGE_SIZE[0] * 72 * 0.92
    capacity = PAGE_SIZE[1] * 72 * 0.755
    _, heights = table_layout(headers, rows, widths, fontsize, width_points)
    total_height = (table_layout(headers, [total_row], widths, fontsize, width_points)[1][1]
                    if total_row is not None else 0)
    # Reserve a total row on every page to guarantee the last page fits.
    pages, current, used = [], [], heights[0] + total_height
    for idx, row in enumerate(rows):
        height = heights[idx + 1]
        if heights[0] + total_height + height > capacity:
            raise ValueError(f"A table row is too tall to fit: {title}")
        if current and (len(current) >= per_page or used + height > capacity):
            pages.append(current)
            current, used = [], heights[0] + total_height
        current.append(idx)
        used += height
    if current or not pages:
        pages.append(current)
    for number, indices in enumerate(pages, 1):
        note = subtitle or ""
        if len(pages) > 1:
            note += f" - Bagian {number}/{len(pages)}"
        fig = report.new_page(title, note)
        ax = fig.add_axes([0.04, 0.085, 0.92, 0.755])
        colors = [row_facecolors[i] for i in indices] if row_facecolors else None
        make_table(ax, headers, [rows[i] for i in indices], widths, fontsize=fontsize,
                   total_row=total_row if number == len(pages) else None, row_facecolors=colors)
        report.save(fig)


# -----------------------------------------------------------------------------
# PDF report helper
# -----------------------------------------------------------------------------

def load_logo_images(paths):
    images = []

    for raw in paths or []:
        path = Path(raw).expanduser()

        try:
            images.append(mpimg.imread(path))
        except Exception as exc:
            print(f"WARNING: cannot load logo {path}: {exc}", file=sys.stderr)

    return images


class PDFReport:
    def __init__(self, output, title, subtitle, footer, logos=(), include_empty_pages=False,
                 quiet=False):
        self.output = Path(output)
        self.title = title
        self.subtitle = subtitle
        self.footer = footer
        self.logos = logos
        self.page = 0
        self.skipped_pages = 0
        self.include_empty_pages = include_empty_pages
        self.quiet = quiet
        self.output.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{self.output.stem}_", suffix=".pdf",
                                    dir=self.output.parent)
        os.close(fd)
        self.temporary = Path(name)

        metadata = {
            "Title": title,
            "Subject": subtitle,
            "Creator": f"KMZ Bridge Statistics PDF {__version__}",
        }

        try:
            self.pdf = PdfPages(self.temporary, metadata=metadata)
        except TypeError:
            self.pdf = PdfPages(self.temporary)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.pdf.close()
            if exc_type is None:
                os.replace(self.temporary, self.output)
        finally:
            self.temporary.unlink(missing_ok=True)
        return False

    def new_page(self, title=None, subtitle=None, header=True):
        fig = plt.figure(figsize=PAGE_SIZE, dpi=100)
        fig._report_title = title or self.title
        fig.patch.set_facecolor(PAGE_BG)

        if header:
            self.draw_header(fig, title or self.title, subtitle or self.subtitle)

        return fig

    def draw_header(self, fig, title, subtitle):
        fig.patches.append(mpatches.Rectangle(
            (0, 0.900), 1, 0.100,
            transform=fig.transFigure,
            facecolor=NAVY,
            edgecolor="none",
            zorder=0,
            clip_on=False,
        ))

        fig.patches.append(mpatches.Rectangle(
            (0, 0.894), 1, 0.006,
            transform=fig.transFigure,
            facecolor=TEAL,
            edgecolor="none",
            zorder=1,
            clip_on=False,
        ))

        fig.text(
            0.035, 0.953, title,
            color=WHITE,
            fontsize=16,
            fontweight="bold",
            va="center",
        )

        if subtitle:
            fig.text(
                0.035, 0.921, subtitle,
                color="#C7DCE8",
                fontsize=9,
                va="center",
            )

        if self.logos:
            x = 0.965

            for img in reversed(self.logos[-2:]):
                h, w = img.shape[:2]
                aspect = w / max(1, h)

                box_h = 0.050
                box_w = box_h * aspect

                if box_w > 0.10:
                    box_w = 0.10
                    box_h = box_w / aspect

                x -= box_w + 0.012

                ax = fig.add_axes([x, 0.918, box_w, box_h])
                ax.imshow(img)
                ax.axis("off")

        fig.patches.append(mpatches.Rectangle(
            (0.035, 0.055), 0.93, 0.0016,
            transform=fig.transFigure,
            facecolor=BORDER,
            edgecolor="none",
            zorder=1,
            clip_on=False,
        ))

        fig.text(
            0.035, 0.033, self.footer,
            fontsize=7.2,
            color=GREY,
        )

        fig.text(
            0.965, 0.033, f"Halaman {self.page + 1}",
            fontsize=7.2,
            color=GREY,
            ha="right",
        )

    def save(self, fig):
        try:
            self.pdf.savefig(fig)
            self.page += 1
            if not self.quiet:
                print(f"[PDF {self.page:02d}] {fig._report_title}", flush=True)
        finally:
            plt.close(fig)


def draw_cover_logos(fig, logos):
    if not logos:
        return False

    specs = []
    total_width = 0.0
    gap = 0.020

    for img in logos[:3]:
        h, w = img.shape[:2]
        aspect = w / max(1, h)

        box_h = 0.070
        box_w = box_h * aspect

        if box_w > 0.18:
            box_w = 0.18
            box_h = box_w / aspect

        specs.append((img, box_w, box_h))
        total_width += box_w + gap

    if specs:
        total_width -= gap

    x = 0.5 - total_width / 2
    y = 0.895

    for img, box_w, box_h in specs:
        ax = fig.add_axes([x, y, box_w, box_h])
        ax.imshow(img)
        ax.axis("off")
        x += box_w + gap

    return True


def chart_page(report, title, subtitle, draw, left=0.21, right=0.95,
               top=0.86, bottom=0.15):
    """One full-page chart."""
    fig = report.new_page(title, subtitle)
    gs = fig.add_gridspec(1, 1, left=left, right=right, top=top, bottom=bottom)
    ax = fig.add_subplot(gs[0, 0])
    draw(ax)
    if (getattr(ax, "_report_no_data", False) or getattr(ax, "_report_uninformative", False)) and not report.include_empty_pages:
        report.skipped_pages += 1
        plt.close(fig)
    else:
        report.save(fig)


def table_page(report, title, subtitle, headers, rows, total_row=None,
               row_facecolors=None, fontsize=8.4, row_scale=None):
    """One full-page table."""
    fig = report.new_page(title, subtitle)
    gs = fig.add_gridspec(1, 1, left=0.08, right=0.92, top=0.84, bottom=0.12)
    ax = fig.add_subplot(gs[0, 0])
    make_table(
        ax,
        headers,
        rows,
        fontsize=fontsize,
        total_row=total_row,
        row_facecolors=row_facecolors,
        row_scale=row_scale,
    )
    report.save(fig)


# -----------------------------------------------------------------------------
# Derived statistics helpers
# -----------------------------------------------------------------------------

def average_length(stats, scope):
    count = stats["length_count"].get(scope, 0)

    if not count:
        return None

    return stats["length_total"].get(scope, 0.0) / count


def average_width(stats, scope):
    count = stats["width_count"].get(scope, 0)

    if not count:
        return None

    return stats["width_total"].get(scope, 0.0) / count


PREFIX_SUMMARY_HEADERS = [
    "Prefix",
    "Jumlah",
    "Panjang Total (m)",
    "Rata-rata Panjang (m)",
    "Rata-rata Lebar (m)",
    "Total Bentang",
    "Kondisi Tidak Diketahui",
]


def prefix_summary_rows(stats):
    rows = []

    scopes = [
        prefix for prefix in PREFIX_ORDER
        if stats["prefix"].get(prefix, 0) > 0
    ]

    for scope in scopes:
        avg_len = average_length(stats, scope)
        avg_width = average_width(stats, scope)

        rows.append([
            PREFIX_LABELS[scope],
            format_int(stats["prefix"].get(scope, 0)),
            format_decimal(stats["length_total"].get(scope, 0.0), 1) if stats["length_count"].get(scope) else "-",
            format_decimal(avg_len, 1),
            format_decimal(avg_width, 2),
            format_int(stats["span_total"].get(scope)) if stats["span_count"].get(scope) else "-",
            format_int(stats["condition_by_scope"][scope].get(UNKNOWN, 0)),
        ])

    total_avg_len = average_length(stats, "ALL")
    total_avg_width = average_width(stats, "ALL")

    total_row = [
        "Total",
        format_int(stats["total"]),
        format_decimal(stats["length_total"].get("ALL", 0.0), 1) if stats["length_count"].get("ALL") else "-",
        format_decimal(total_avg_len, 1),
        format_decimal(total_avg_width, 2),
        format_int(stats["span_total"].get("ALL")) if stats["span_count"].get("ALL") else "-",
        format_int(stats["condition_by_scope"]["ALL"].get(UNKNOWN, 0)),
    ]

    return rows, total_row


def condition_summary_rows(stats):
    rows = []

    total_all = stats["total"]

    for condition in ALL_CONDITIONS:
        j = stats["condition_by_scope"][PREFIX_J].get(condition, 0)
        g = stats["condition_by_scope"][PREFIX_G].get(condition, 0)
        other = stats["condition_by_scope"][PREFIX_OTHER].get(condition, 0)
        total = j + g + other
        fraction = total / total_all if total_all else 0

        rows.append([
            condition,
            format_int(j),
            format_int(g),
            format_int(other),
            format_int(total),
            format_percent(fraction),
        ])

    total_row = [
        "Total",
        format_int(stats["prefix"].get(PREFIX_J, 0)),
        format_int(stats["prefix"].get(PREFIX_G, 0)),
        format_int(stats["prefix"].get(PREFIX_OTHER, 0)),
        format_int(total_all),
        "100,0%" if total_all else "0,0%",
    ]

    return rows, total_row


PROFILE_HEADERS = [
    "Jumlah",
    "Panjang Total (m)",
    "Rata-rata Panjang (m)",
    "Rata-rata Lebar (m)",
    "Total Bentang",
    "Baik",
    "Sedang",
    "Rusak Ringan",
    "Rusak Berat",
    "Tidak Diketahui",
]


def prefix_profile_rows(stats, prefix):
    return [[
        format_int(stats["prefix"].get(prefix, 0)),
        format_decimal(stats["length_total"].get(prefix, 0.0), 1) if stats["length_count"].get(prefix) else "-",
        format_decimal(average_length(stats, prefix), 1),
        format_decimal(average_width(stats, prefix), 2),
        format_int(stats["span_total"].get(prefix)) if stats["span_count"].get(prefix) else "-",
        format_int(stats["condition_by_scope"][prefix].get("Baik", 0)),
        format_int(stats["condition_by_scope"][prefix].get("Sedang", 0)),
        format_int(stats["condition_by_scope"][prefix].get("Rusak Ringan", 0)),
        format_int(stats["condition_by_scope"][prefix].get("Rusak Berat", 0)),
        format_int(stats["condition_by_scope"][prefix].get(UNKNOWN, 0)),
    ]]


# -----------------------------------------------------------------------------
# Page builders (one chart / one table per page)
# -----------------------------------------------------------------------------

def build_cover(report, stats, files_count):
    fig = report.new_page(header=False)

    fig.patches.append(mpatches.Rectangle(
        (0, 0.640), 1, 0.360,
        transform=fig.transFigure,
        facecolor=NAVY,
        edgecolor="none",
        zorder=0,
        clip_on=False,
    ))

    fig.patches.append(mpatches.Rectangle(
        (0, 0.634), 1, 0.006,
        transform=fig.transFigure,
        facecolor=TEAL,
        edgecolor="none",
        zorder=1,
        clip_on=False,
    ))

    has_logos = draw_cover_logos(fig, report.logos)

    title_y = 0.820 if has_logos else 0.855

    fig.text(
        0.5, title_y, wrap_label(report.title, 48),
        ha="center", va="center",
        color=WHITE,
        fontsize=21,
        fontweight="bold",
    )

    fig.text(
        0.5, title_y - 0.090, report.subtitle,
        ha="center", va="center",
        color="#C9DCE9",
        fontsize=13,
    )

    fig.text(
        0.5, title_y - 0.132,
        "Prefix J = Jembatan    •    Prefix G = Gorong-gorong",
        ha="center", va="center",
        color="#8FB6C9",
        fontsize=9.5,
    )

    fig.text(
        0.5, title_y - 0.170,
        f"Dibuat {datetime.now():%Y-%m-%d %H:%M}  •  {format_int(files_count)} file KMZ dibaca",
        ha="center", va="center",
        color="#8FB6C9",
        fontsize=8.5,
    )

    gs = fig.add_gridspec(
        2, 4,
        left=0.05, right=0.95,
        top=0.56, bottom=0.12,
        hspace=0.55, wspace=0.25,
    )

    cards = [
        ("Total Objek", format_int(stats["total"]), NAVY),
        ("Jembatan (J)", format_int(stats["prefix"].get(PREFIX_J, 0)), J_COLOR),
        ("Gorong-gorong (G)", format_int(stats["prefix"].get(PREFIX_G, 0)), G_COLOR),
        ("Prefix Lain", format_int(stats["prefix"].get(PREFIX_OTHER, 0)), OTHER_COLOR),
        ("Kecamatan", format_int(len(stats["kec_total"])), TEAL),
        ("Panjang J (m)", format_decimal(stats["length_total"].get(PREFIX_J), 1) if stats["length_count"].get(PREFIX_J) else "-", J_COLOR),
        ("Panjang G (m)", format_decimal(stats["length_total"].get(PREFIX_G), 1) if stats["length_count"].get(PREFIX_G) else "-", G_COLOR),
        ("Kondisi Tidak Diketahui", format_int(stats["condition_by_scope"]["ALL"].get(UNKNOWN, 0)), GREY),
    ]

    for i, (label, value, color) in enumerate(cards):
        ax = fig.add_subplot(gs[i // 4, i % 4])
        kpi_card(ax, value, label, color)

    fig.text(0.05, 0.055,
             "Tanda '-' = data tidak tersedia. Total dan rata-rata dimensi hanya memakai nilai positif yang valid.",
             fontsize=8, color=GREY)
    report.save(fig)


def build_overview_pages(report, stats):
    donut_labels, donut_values, donut_colors = [], [], []

    for prefix in PREFIX_ORDER:
        count = stats["prefix"].get(prefix, 0)

        if count > 0:
            donut_labels.append(PREFIX_LABELS[prefix])
            donut_values.append(count)
            donut_colors.append(PREFIX_COLORS[prefix])

    chart_page(
        report,
        "Komposisi Prefix",
        "Perbandingan jumlah objek Jembatan (J), Gorong-gorong (G), dan prefix lain",
        lambda ax: donut(
            ax,
            donut_labels,
            donut_values,
            donut_colors,
            format_int(stats["total"]),
            "Total Objek",
        ),
        left=0.22, right=0.78,
    )

    chart_page(
        report,
        "Proporsi Kondisi per Prefix",
        "Persentase distribusi kondisi untuk setiap prefix",
        lambda ax: stacked_condition_by_prefix(ax, stats),
        left=0.18, right=0.90,
    )

    chart_page(
        report,
        "Jumlah Objek per Kecamatan",
        "Stacked bar J dan G untuk seluruh kecamatan",
        lambda ax: stacked_hbar_prefix(ax, stats),
    )

    chart_page(
        report,
        "Panjang Total per Kecamatan",
        "Akumulasi panjang (meter) menurut prefix untuk seluruh kecamatan",
        lambda ax: stacked_length_by_kec(ax, stats),
    )

    chart_page(
        report,
        "Kelas Panjang",
        "Distribusi jumlah objek berdasarkan kelas panjang",
        lambda ax: length_class_chart(ax, stats),
        left=0.10,
    )

    rows, total_row = prefix_summary_rows(stats)

    table_page(
        report,
        "Ringkasan Prefix",
        "Dimensi hanya dari data valid; lihat Kelengkapan Data untuk jumlah pengamatan.",
        PREFIX_SUMMARY_HEADERS,
        rows,
        total_row=total_row,
        fontsize=9,
    )


def build_condition_pages(report, stats):
    for prefix in PREFIX_ORDER:
        count = stats["prefix"].get(prefix, 0)

        if count <= 0:
            continue

        values = [stats["condition_by_scope"][prefix].get(c, 0) for c in ALL_CONDITIONS]

        chart_page(
            report,
            f"Kondisi {PREFIX_LABELS[prefix]}",
            "Distribusi kondisi",
            lambda ax, p=prefix, v=values, c=count: donut(
                ax,
                ALL_CONDITIONS,
                v,
                [CONDITION_COLORS[x] for x in ALL_CONDITIONS],
                format_int(c),
                f"Total {p}",
            ),
            left=0.25, right=0.75,
        )

    active = [p for p in PREFIX_ORDER if stats["prefix"].get(p, 0) > 0]

    def draw_grouped(ax):
        series = [
            (
                PREFIX_SHORT[p],
                [stats["condition_by_scope"][p].get(c, 0) for c in ALL_CONDITIONS],
                PREFIX_COLORS[p],
            )
            for p in active
        ]
        grouped_vbar(ax, ALL_CONDITIONS, series, ylabel="Jumlah", wrap=12, legend_ncol=len(active))

    chart_page(
        report,
        "Perbandingan Kondisi menurut Prefix",
        "Jumlah objek per kondisi untuk J, G, dan prefix lain",
        draw_grouped,
        left=0.10,
    )

    rows, total_row = condition_summary_rows(stats)

    table_page(
        report,
        "Tabel Kondisi",
        "Rekap kondisi menurut prefix",
        ["Kondisi", "J", "G", "Lainnya", "Total", "Persen"],
        rows,
        total_row=total_row,
        row_facecolors=[lighten(CONDITION_COLORS[c], 0.88) for c in ALL_CONDITIONS],
        fontsize=9,
    )

    chart_page(
        report,
        "Proporsi Kondisi per Kecamatan",
        "Komposisi kondisi 100% untuk seluruh kecamatan",
        lambda ax: stacked_condition_by_kec(ax, stats),
    )


def build_prefix_pages(report, stats, prefix):
    has_details = (stats["length_count"].get(prefix) or stats["width_count"].get(prefix)
                   or stats["span_count"].get(prefix)
                   or any(stats["condition_by_scope"][prefix].get(c) for c in CONDITIONS)
                   or any(k != UNKNOWN and v for field in ("type", "foundation", "surface")
                          for k, v in stats[field][prefix].items())
                   or len(stats["survey_year"][prefix]) > 1
                   or len(stats["construction_year"][prefix]) > 1)
    if not has_details and not report.include_empty_pages:
        report.skipped_pages += 7
        return
    color = PREFIX_COLORS[prefix]
    label = PREFIX_LABELS[prefix]

    table_page(
        report,
        f"Ringkasan {label}",
        "Indikator utama",
        PROFILE_HEADERS,
        prefix_profile_rows(stats, prefix),
        fontsize=9,
    )

    chart_page(
        report,
        f"Distribusi Panjang {label}",
        "Histogram panjang (meter)",
        lambda ax: histogram(ax, stats["length_values"].get(prefix, []), color),
        left=0.10,
    )

    chart_page(
        report,
        f"Tipe Bangunan Atas {label}",
        "Tipe terbanyak",
        lambda ax: top_counter_hbar(ax, stats["type"][prefix], color, top_n=14, wrap=34),
    )

    chart_page(
        report,
        f"Kelas Panjang {label}",
        "Jumlah objek per kelas panjang",
        lambda ax: length_class_chart(ax, stats, scopes=[prefix]),
        left=0.10,
    )

    chart_page(
        report,
        f"Fondasi {label}",
        "Tipe fondasi terbanyak",
        lambda ax: top_counter_hbar(ax, stats["foundation"][prefix], color, top_n=12, wrap=30),
    )

    chart_page(
        report,
        f"Tipe Permukaan {label}",
        "Tipe permukaan terbanyak",
        lambda ax: top_counter_hbar(ax, stats["surface"][prefix], color, top_n=12, wrap=30),
    )

    survey = stats["survey_year"][prefix]
    construction = stats["construction_year"][prefix]

    if survey:
        year_counter, year_title = survey, "Tahun Survey"
    else:
        year_counter, year_title = construction, "Tahun Konstruksi"

    chart_page(
        report,
        f"{year_title} {label}",
        "Distribusi jumlah objek per tahun",
        lambda ax: year_chart(ax, year_counter, color),
        left=0.10,
    )


def build_composition_pages(report, stats):
    fields = [
        ("type", "Bangunan Atas - Tipe"),
        ("foundation", "Fondasi - Tipe"),
        ("surface", "Permukaan Jembatan - Tipe"),
        ("bawah_material", "Bangunan Bawah - Bahan"),
    ]

    for field, name in fields:
        def draw(ax, f=field):
            labels = [label for label, _ in top_counter(stats[f]["ALL"], 12)]

            if labels == [UNKNOWN]:
                ax._report_uninformative = True
            if not labels:
                no_data(ax, name)
                return

            active = [p for p in PREFIX_ORDER if stats["prefix"].get(p, 0) > 0]

            series = [
                (
                    PREFIX_SHORT[p],
                    [stats[f][p].get(label, 0) for label in labels],
                    PREFIX_COLORS[p],
                )
                for p in active
            ]

            grouped_hbar_prefix(ax, labels, series, wrap=32)

        chart_page(
            report,
            f"Perbandingan {name}",
            "Komposisi menurut prefix J dan G",
            draw,
        )


def build_kecamatan_table_pages(report, stats):
    has_other = stats["prefix"].get(PREFIX_OTHER, 0) > 0

    headers = ["Kecamatan", "J", "G"]

    if has_other:
        headers.append("Lainnya")

    headers += [
        "Total",
        "Panjang J (m)",
        "Panjang G (m)",
        "Panjang Total (m)",
        "Rata-rata Panjang (m)",
        "Rata-rata Lebar (m)",
    ]

    rows = []

    for kecamatan in sorted(stats["kec_prefix"]):
        counters = stats["kec_prefix"][kecamatan]

        j = counters.get(PREFIX_J, 0)
        g = counters.get(PREFIX_G, 0)
        other = counters.get(PREFIX_OTHER, 0)
        total = j + g + other

        length_j = stats["kec_length"][PREFIX_J].get(kecamatan, 0.0)
        length_g = stats["kec_length"][PREFIX_G].get(kecamatan, 0.0)
        length_all = stats["kec_length"]["ALL"].get(kecamatan, 0.0)

        length_count_all = stats["kec_length_count"]["ALL"].get(kecamatan, 0)
        width_count_all = stats["kec_width_count"]["ALL"].get(kecamatan, 0)

        avg_len = length_all / length_count_all if length_count_all else None
        avg_width = (
            stats["kec_width_total"]["ALL"].get(kecamatan, 0.0) / width_count_all
            if width_count_all
            else None
        )

        row = [kecamatan, format_int(j), format_int(g)]

        if has_other:
            row.append(format_int(other))

        row += [
            format_int(total),
            format_decimal(length_j, 1) if stats["kec_length_count"][PREFIX_J].get(kecamatan) else "-",
            format_decimal(length_g, 1) if stats["kec_length_count"][PREFIX_G].get(kecamatan) else "-",
            format_decimal(length_all, 1) if length_count_all else "-",
            format_decimal(avg_len, 1),
            format_decimal(avg_width, 2),
        ]

        rows.append(row)

    total_row = ["TOTAL", format_int(stats["prefix"].get(PREFIX_J, 0)), format_int(stats["prefix"].get(PREFIX_G, 0))]

    if has_other:
        total_row.append(format_int(stats["prefix"].get(PREFIX_OTHER, 0)))

    total_length_all = stats["length_total"].get("ALL", 0.0)
    total_length_count = stats["length_count"].get("ALL", 0)

    total_row += [
        format_int(stats["total"]),
        format_decimal(stats["length_total"].get(PREFIX_J, 0.0), 1) if stats["length_count"].get(PREFIX_J) else "-",
        format_decimal(stats["length_total"].get(PREFIX_G, 0.0), 1) if stats["length_count"].get(PREFIX_G) else "-",
        format_decimal(total_length_all, 1) if total_length_count else "-",
        format_decimal(average_length(stats, "ALL"), 1),
        format_decimal(average_width(stats, "ALL"), 2),
    ]

    build_table_pages(
        report,
        "Rekapitulasi Kecamatan",
        "Dimensi hanya dari nilai positif yang tersedia; bukan estimasi untuk data yang belum diisi.",
        headers,
        rows,
        total_row=total_row,
        per_page=20,
        fontsize=8.0,
    )


def build_heatmap_pages(report, stats):
    cmaps = {
        PREFIX_J: "Blues",
        PREFIX_G: "Greens",
        PREFIX_OTHER: "Oranges",
    }

    for prefix in PREFIX_ORDER:
        if stats["prefix"].get(prefix, 0) <= 0:
            continue

        chart_page(
            report,
            f"Heatmap Kondisi {PREFIX_LABELS[prefix]}",
            "Jumlah kondisi per kecamatan",
            lambda ax, p=prefix: condition_heatmap(ax, stats, p, cmaps[p]),
            left=0.16, right=0.94,
        )


def build_sources_page(report, files, kec_map, stats, issues):
    issue_counts = Counter(
        issue[1] for issue in issues
        if len(issue) > 1
    )

    has_other = stats["prefix"].get(PREFIX_OTHER, 0) > 0

    headers = ["File KMZ", "Kecamatan", "J", "G"]

    if has_other:
        headers.append("Lainnya")

    headers += ["Total", "Panjang (m)", "Masalah"]

    rows = []

    for file in files:
        source = stats.get("source_labels", {}).get(file, file.name)

        kecamatan_counter = stats["source_kec"].get(source)

        if kecamatan_counter:
            kecamatan = kecamatan_counter.most_common(1)[0][0]
        else:
            kecamatan = kec_map.get(file) or "-"

        prefix_counter = stats["source_prefix"].get(source, Counter())

        row = [
            source,
            kecamatan,
            format_int(prefix_counter.get(PREFIX_J, 0)),
            format_int(prefix_counter.get(PREFIX_G, 0)),
        ]

        if has_other:
            row.append(format_int(prefix_counter.get(PREFIX_OTHER, 0)))

        row += [
            format_int(stats["source_total"].get(source, 0)),
            format_decimal(stats["source_length"].get(source), 1),
            format_int(issue_counts.get(source, 0)),
        ]

        rows.append(row)

    total_row = ["TOTAL", f"{format_int(len(files))} file",
                 format_int(stats["prefix"].get(PREFIX_J, 0)),
                 format_int(stats["prefix"].get(PREFIX_G, 0))]

    if has_other:
        total_row.append(format_int(stats["prefix"].get(PREFIX_OTHER, 0)))

    total_row += [
        format_int(stats["total"]),
        format_decimal(stats["length_total"].get("ALL"), 1),
        format_int(len(issues)),
    ]

    build_table_pages(
        report,
        "Sumber Data",
        "File KMZ yang dibaca dan jumlah record yang masuk statistik",
        headers,
        rows,
        total_row=total_row,
        per_page=18,
        fontsize=7.8,
        col_widths=([0.47, 0.14, 0.04, 0.04, 0.055, 0.055, 0.10, 0.10]
                    if has_other else [0.50, 0.15, 0.04, 0.04, 0.06, 0.11, 0.10]),
    )


def build_issues_pages(report, issues):
    if not issues:
        fig = report.new_page("Data Quality", "Pemeriksaan pembacaan, identitas, kondisi, dan dimensi")
        fig.text(0.5, 0.5, "Tidak ada masalah yang terdeteksi oleh pemeriksaan ini.",
                 ha="center", fontsize=14, color=TEAL)
        report.save(fig)
        return
    counts = Counter(issue[0] for issue in issues)
    rows = [[kind, format_int(count)] for kind, count in sorted(counts.items())]
    build_table_pages(report, "Data Quality", "Jumlah temuan, bukan jumlah objek; satu objek dapat memiliki beberapa temuan.",
                      ["Jenis temuan", "Jumlah"], rows,
                      total_row=["TOTAL TEMUAN", format_int(len(issues))], fontsize=9,
                      col_widths=[0.78, 0.22])
    if getattr(report, "issues_detail", False):
        build_table_pages(report, "Detail Data Quality", "Daftar lengkap tanpa pemotongan teks",
                          ["Jenis", "File", "No. Jembatan", "Detail"], issues,
                          per_page=12, fontsize=7.5, col_widths=[0.14, 0.25, 0.18, 0.43])


def build_completeness_page(report, stats):
    rows = []
    for p in PREFIX_ORDER:
        count = stats["prefix"].get(p, 0)
        if not count:
            continue
        known = count - stats["condition_by_scope"][p].get(UNKNOWN, 0)
        def available(n):
            return f"{format_int(n)}/{format_int(count)} ({format_percent(n / count)})"
        rows.append([PREFIX_LABELS[p], available(stats["length_count"].get(p, 0)),
                     available(stats["width_count"].get(p, 0)),
                     available(stats["span_count"].get(p, 0)), available(known)])
    table_page(report, "Kelengkapan Data", "Data valid / seluruh objek pada masing-masing prefix",
               ["Prefix", "Panjang", "Lebar", "Bentang", "Kondisi dikenal"], rows, fontsize=9)


def write_issues_csv(path, issues):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".csv", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Jenis", "File", "No. Jembatan", "Detail"])
            for issue in issues:
                # Keep user-supplied strings inert when opened in Excel.
                writer.writerow([("'" + str(v) if str(v).lstrip().startswith(("=", "+", "-", "@")) else str(v))
                                 for v in issue])
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "inputs",
        nargs="+",
        help="KMZ files, folders, or wildcard patterns.",
    )

    parser.add_argument(
        "--output",
        default="statistik_jembatan_gorong_kabupaten.pdf",
        help="Output PDF file.",
    )

    parser.add_argument(
        "--kabupaten",
        default="Kabupaten",
        help="Nama kabupaten untuk judul laporan.",
    )

    parser.add_argument(
        "--tahun",
        default=None,
        help="Tahun laporan. Jika kosong, diambil dari Tahun Survey terbaru bila tersedia.",
    )

    parser.add_argument(
        "--title",
        default=None,
        help="Judul utama laporan.",
    )

    parser.add_argument(
        "--kecamatan",
        action="append",
        help=(
            "Explicit kecamatan name. Provide once for all files, "
            "or once per KMZ file using repeated flags."
        ),
    )

    parser.add_argument(
        "--logo",
        action="append",
        help="Optional logo image path. Can be repeated.",
    )

    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Include duplicate bridge IDs instead of keeping only the first record.",
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--include-empty-pages", action="store_true",
                        help="Keep empty, unknown-only, and single-year detail charts.")
    parser.add_argument("--issues-detail", action="store_true",
                        help="Append the complete issue list to the PDF (may be long).")
    parser.add_argument("--issues-csv", metavar="PATH",
                        help="Also export the full issue list to a UTF-8 CSV file.")
    parser.add_argument("--allow-read-errors", action="store_true",
                        help="Allow a partial report if a KMZ cannot be read; failures remain in the audit.")
    parser.add_argument("--quiet", action="store_true", help="Hide per-file and per-page progress.")

    args = parser.parse_args(argv)
    started = time.perf_counter()

    try:
        files = collect_inputs(args.inputs)
        kec_map = build_kecamatan_map(files, args.kecamatan or [])

        issues = []
        records = []
        name_counts = Counter(file.name for file in files)
        # Keep identically named files from different folders separate in all
        # source totals and audit rows. Full paths are used only for collisions.
        source_labels = {file: str(file) if name_counts[file.name] > 1 else file.name for file in files}

        for index, file in enumerate(files, 1):
            first_issue = len(issues)
            batch = read_kmz(file, explicit_kecamatan=kec_map.get(file, ""), issues=issues)
            for rec in batch:
                rec["_source_file"] = source_labels[file]
            for i in range(first_issue, len(issues)):
                kind, _, ident, detail = issues[i]
                issues[i] = (kind, source_labels[file], ident, detail)
            records.extend(batch)
            if not args.quiet:
                print(f"[KMZ {index}/{len(files)}] {file.name}: {len(batch)} record", flush=True)
        read_errors = [issue for issue in issues if issue[0] == "Read error"]
        if read_errors and not args.allow_read_errors:
            detail = "; ".join(f"{row[1]}: {row[3]}" for row in read_errors)
            raise ValueError(f"KMZ read failed. No PDF replaced. {detail}. "
                             "Use --allow-read-errors only if a partial report is intended.")

        included, duplicate_count = prepare_records(
            records,
            issues,
            allow_duplicates=args.allow_duplicates,
        )

        if not included:
            raise ValueError("No bridge records found in the supplied KMZ files.")

        stats = aggregate(included)
        stats["source_labels"] = source_labels
        parsed_at = time.perf_counter()

        tahun = args.tahun

        if not tahun:
            numeric_years = []

            for year_value in stats["survey_year"].get("ALL", {}):
                if re.fullmatch(r"\d{4}", str(year_value)):
                    numeric_years.append(int(year_value))

            if numeric_years:
                tahun = str(max(numeric_years))

        title = args.title or "Laporan Statistik Jembatan dan Gorong-gorong"

        subtitle = args.kabupaten

        if tahun:
            subtitle += f" | Tahun {tahun}"
        if read_errors:
            subtitle += " | DATA PARSIAL"

        footer = f"{subtitle} | Prefix J = Jembatan, G = Gorong-gorong | {datetime.now():%Y-%m-%d %H:%M}"

        output = Path(args.output).expanduser().resolve()

        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")
        csv_path = Path(args.issues_csv).expanduser().resolve() if args.issues_csv else None
        if csv_path:
            if csv_path.suffix.lower() != ".csv":
                raise ValueError("--issues-csv requires a .csv filename.")
            if csv_path in files or csv_path == output:
                raise ValueError("Audit output must differ from the inputs and PDF.")

        output.parent.mkdir(parents=True, exist_ok=True)

        logos = load_logo_images(args.logo)

        with PDFReport(output, title, subtitle, footer, logos,
                       include_empty_pages=args.include_empty_pages, quiet=args.quiet) as report:
            report.issues_detail = args.issues_detail
            build_cover(report, stats, len(files))
            build_completeness_page(report, stats)
            build_overview_pages(report, stats)
            build_condition_pages(report, stats)

            for prefix in PREFIX_ORDER:
                if stats["prefix"].get(prefix, 0) > 0:
                    build_prefix_pages(report, stats, prefix)

            build_composition_pages(report, stats)
            build_kecamatan_table_pages(report, stats)
            build_heatmap_pages(report, stats)
            build_sources_page(report, files, kec_map, stats, issues)
            build_issues_pages(report, issues)

            page_count = report.page

        if csv_path:
            try:
                write_issues_csv(csv_path, issues)
            except OSError as exc:
                raise OSError(f"PDF saved successfully at {output}, but audit CSV failed: {exc}") from exc

        print(
            "OK: "
            f"{len(files)} KMZ dibaca; "
            f"{stats['total']} record; "
            f"J={stats['prefix'].get(PREFIX_J, 0)}; "
            f"G={stats['prefix'].get(PREFIX_G, 0)}; "
            f"Lainnya={stats['prefix'].get(PREFIX_OTHER, 0)}; "
            f"{duplicate_count} duplikat; "
            f"{page_count} halaman PDF."
        )

        print(f"Output: {output}")
        if csv_path:
            print(f"Audit CSV: {csv_path}")
        print(f"Audit: {len(issues)} temuan; {report.skipped_pages} halaman dilewati. "
              f"Read/aggregate: {parsed_at - started:.2f}s; "
              f"PDF/output: {time.perf_counter() - parsed_at:.2f}s; "
              f"Total: {time.perf_counter() - started:.2f}s.")

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
