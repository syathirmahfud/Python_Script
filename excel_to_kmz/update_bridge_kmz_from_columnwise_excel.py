#!/usr/bin/env python3
"""
update_bridge_kmz_from_columnwise_excel.py

EXCEL FORMAT (STRICT):
    Column A = numbering only (ignored)
    Column B = field names (32 rows, B1..B32)
    Column C..Z = bridges (one bridge per column)

BEHAVIOR:
- ALWAYS deletes ALL <table> blocks inside <description>
- ALWAYS inserts ONE fresh table built from Excel fields
- Placemark order = Excel bridge column order
- Backs up KMZ before overwrite
- Interactive file selection
"""

import os
import re
import zipfile
import tempfile
import shutil
import pandas as pd
from datetime import datetime

# =========================
# REGEX
# =========================
PLACEMARK_RE = re.compile(r"(?is)<Placemark\b.*?</Placemark>")
DESC_RE = re.compile(r"(?is)<description>\s*<!\[CDATA\[(.*?)\]\]>\s*</description>")
TABLE_RE = re.compile(r"(?is)<table\b.*?</table>")

# =========================
# HELPERS
# =========================
def ask_for_file(label):
    while True:
        p = input(f"📂 Enter path to {label}: ").strip().strip('"')
        if not p:
            continue
        if not os.path.exists(p):
            print("❌ File not found. Try again.")
            continue
        return p

def safe_val(v):
    if v is None:
        return "-"
    try:
        if pd.isna(v):
            return "-"
    except Exception:
        pass
    s = str(v).strip()
    return s if s else "-"

def build_table(fields, row):
    lines = []
    for f in fields:
        lines.append(
            f'            <tr><td><b>{f}</b></td><td>{safe_val(row.get(f))}</td></tr>'
        )

    return (
        '        <table style="border-collapse:collapse; width:100%;" '
        'border="1" cellpadding="4">\n'
        '            <colgroup>\n'
        '                <col style="width: 35%;">\n'
        '                <col style="width: 65%;">\n'
        '            </colgroup>\n'
        + "\n".join(lines) +
        "\n        </table>\n"
    )

# =========================
# EXCEL LOADER (NO HEADER, POSITIONAL, EXACT 32)
# =========================
def load_excel(path, expected_fields=32):
    """
    Reads:
      A = numbering (ignored)
      B = fields (B1..B32)
      C..Z = bridges
    """
    xl = pd.ExcelFile(path)
    sheet = xl.sheet_names[0]

    # header=None is CRITICAL — keeps B1 as data, not column name
    df = xl.parse(sheet, header=None)

    if df.shape[1] < 3:
        raise RuntimeError("❌ Excel must have at least 3 columns (A, B, C)")

    field_col = 1  # Column B

    fields = []
    rows = []

    for i in range(len(df)):
        val = df.iat[i, field_col]
        if pd.isna(val):
            continue
        name = str(val).strip()
        if not name:
            continue
        fields.append(name)
        rows.append(i)

    if len(fields) != expected_fields:
        raise RuntimeError(
            f"❌ Field count mismatch: expected {expected_fields}, got {len(fields)}"
        )

    bridges = []
    for col in range(2, df.shape[1]):
        rec = {}
        for f, r in zip(fields, rows):
            rec[f] = df.iat[r, col]
        bridges.append(rec)

    if not bridges:
        raise RuntimeError("❌ No bridge data found")

    return fields, bridges

# =========================
# KML FORCE REWRITE
# =========================
def rewrite_kml(raw_xml, fields, bridges):
    placemarks = list(PLACEMARK_RE.finditer(raw_xml))

    if not placemarks:
        raise RuntimeError("❌ No <Placemark> found in KML")

    if len(bridges) > len(placemarks):
        print("⚠️ More bridges in Excel than Placemarks in KML")

    result = []
    last = 0
    updated = 0

    for i, m in enumerate(placemarks):
        start, end = m.span()
        pm = m.group(0)

        result.append(raw_xml[last:start])

        if i < len(bridges):
            row = bridges[i]
            table = build_table(fields, row)

            desc_m = DESC_RE.search(pm)
            if desc_m:
                inner = desc_m.group(1)
                # NUKE ALL TABLES
                cleaned = TABLE_RE.sub("", inner)
                new_desc = (
                    "<description><![CDATA[\n"
                    + cleaned.rstrip()
                    + "\n"
                    + table
                    + "    ]]></description>"
                )
                pm = pm[:desc_m.start()] + new_desc + pm[desc_m.end():]
            else:
                # No description at all → add one
                insert = (
                    "<description><![CDATA[\n"
                    + table
                    + "    ]]></description>\n"
                )
                pm = re.sub(r"(?is)</Placemark>\s*$", insert + "</Placemark>", pm)

            updated += 1

        result.append(pm)
        last = end

    result.append(raw_xml[last:])
    print(f"🧩 Rewrite summary: {updated} placemarks rewritten")
    return "".join(result)

# =========================
# KMZ PIPELINE
# =========================
def update_kmz(kmz_path, excel_path):
    temp = tempfile.mkdtemp(prefix="kmz_force_")
    try:
        backup = kmz_path + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(kmz_path, backup)
        print(f"💾 Backup: {backup}")

        with zipfile.ZipFile(kmz_path, "r") as z:
            z.extractall(temp)

        kml_path = None
        for root, _, files in os.walk(temp):
            for f in files:
                if f.lower().endswith(".kml"):
                    kml_path = os.path.join(root, f)
                    break
            if kml_path:
                break

        if not kml_path:
            raise RuntimeError("❌ No KML file inside KMZ")

        print("📄 Loading Excel...")
        fields, bridges = load_excel(excel_path, expected_fields=32)
        print(f"📑 Fields: {len(fields)} | ⚙️ Bridges: {len(bridges)}")

        with open(kml_path, "r", encoding="utf-8") as f:
            raw = f.read()

        updated = rewrite_kml(raw, fields, bridges)

        if not updated.startswith("<?xml"):
            updated = '<?xml version="1.0" encoding="UTF-8"?>\n' + updated

        with open(kml_path, "w", encoding="utf-8") as f:
            f.write(updated)

        print("📦 Repacking KMZ...")
        with zipfile.ZipFile(kmz_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(temp):
                for f in files:
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, temp)
                    z.write(full, arcname=arc)

        print("✅ KMZ updated")

    finally:
        shutil.rmtree(temp, ignore_errors=True)

# =========================
# CLI
# =========================
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        kmz = sys.argv[1]
        xls = sys.argv[2]
    else:
        print("🧭 Interactive mode")
        kmz = ask_for_file("KMZ file")
        xls = ask_for_file("Excel file")

    update_kmz(kmz, xls)
