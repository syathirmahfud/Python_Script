#!/usr/bin/env python3
"""
update_bridge_kmz_from_excel.py — In-Place Update Edition

Updates an existing KMZ directly (no new file created).

- Preserves photos (only replaces <table> inside <description>)
- Syncs <name> from Excel (handles number + name changes)
- Formats STA(m) as 0+000
- Automatically backs up the original KMZ before overwrite
"""

import os, re, zipfile, tempfile, shutil, pandas as pd
from datetime import datetime

# -------- Table Fields (23 canonical) --------
TABLE_FIELDS = [
    "No. Jembatan", "Nama Jembatan", "Longitude", "Latitude", "Kecamatan",
    "STA(m)", "Panjang(m)", "Lebar(m)", "Jumlah Bentang",
    "Bangunan Atas - Kode", "Bangunan Atas - Tipe", "Bangunan Atas - Kondisi",
    "Bangunan Bawah - Tipe", "Bangunan Bawah - Kondisi",
    "Fondasi - Tipe", "Fondasi - Kondisi",
    "Permukaan Jembatan - Tipe", "Permukaan Jembatan - Kondisi",
    "Aliran - Tipe", "Aliran - Kondisi",
    "Tahun Konstruksi", "Tahun Survey"
]

# -------- Helpers --------
def format_sta(value):
    """Format STA as 0+000 (e.g., 1230 → 1+230)."""
    if value is None:
        return "-"
    s = str(value).strip()
    if s in ["", "-", "nan", "None"]:
        return "-"
    if "+" in s:  # already formatted
        return s
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return s
    try:
        n = int(digits)
        km = n // 1000
        m  = n % 1000
        return f"{km}+{m:03d}"
    except Exception:
        return s

def build_table_html(row):
    """Builds the HTML table inside <description>."""
    def val(v):
        if v is None: return "-"
        try:
            if pd.isna(v): return "-"
        except Exception:
            pass
        s = str(v).strip()
        return s if s else "-"
    rows = []
    for field in TABLE_FIELDS:
        v = val(row.get(field, "-"))
        if field.lower().startswith("sta"):
            v = format_sta(v)
        rows.append(f'            <tr><td><b>{field}</b></td><td>{v}</td></tr>')
    return (
        '        <table style="border-collapse:collapse; table-layout:fixed; width:100%;" border="1" cellpadding="4">\n'
        '            <colgroup>\n'
        '                <col style="width: 30%;">\n'
        '                <col style="width: 70%;">\n'
        '            </colgroup>\n'
        + "\n".join(rows) +
        "\n        </table>\n"
    )

# -------- Regex setup --------
PLACEMARK_RE  = re.compile(r"(?is)<Placemark\b.*?</Placemark>")
NAME_RE       = re.compile(r"(?is)<name>\s*(.*?)\s*</name>")
DESC_CDATA_RE = re.compile(r"(?is)<description>\s*<!\[CDATA\[(.*?)\]\]>\s*</description>")
TABLE_RE      = re.compile(r"(?is)<table\b.*?</table>")

def replace_table_only(cdata_inner, new_table):
    """Replace only first <table>...</table> in description."""
    if TABLE_RE.search(cdata_inner):
        return TABLE_RE.sub(new_table, cdata_inner, count=1)
    prefix = "" if cdata_inner.endswith("\n") else "\n"
    return cdata_inner + prefix + new_table + "    "

# -------- Main Update Logic --------
def update_kml_with_excel(raw_xml, df):
    """Updates <name> and table contents from Excel DataFrame."""
    rows = [r for _, r in df.iterrows()]
    by_no = {str(r.get("No. Jembatan", "")).strip(): r for r in rows}
    names_norm = {i: str(r.get("Nama Jembatan", "") or "").strip().lower() for i, r in enumerate(rows)}

    result = []
    last_end = 0

    for match in PLACEMARK_RE.finditer(raw_xml):
        start, end = match.span()
        pm_text = match.group(0)
        result.append(raw_xml[last_end:start])

        name_match = NAME_RE.search(pm_text)
        if not name_match:
            result.append(pm_text)
            last_end = end
            continue

        old_name_text = name_match.group(1).strip()
        old_no = old_name_text.split(" ", 1)[0].strip()
        row = by_no.get(old_no)

        if row is None:
            old_lower = old_name_text.lower()
            for i, nm in names_norm.items():
                if nm and nm in old_lower:
                    row = rows[i]
                    break

        if row is None:
            result.append(pm_text)
            last_end = end
            continue

        new_no = str(row.get("No. Jembatan", old_no)).strip()
        new_name = str(row.get("Nama Jembatan", "") or "").strip()
        new_full = f"{new_no} {new_name}".strip()

        pm_text = re.sub(r"(?is)<name>\s*.*?\s*</name>", f"<name>{new_full}</name>", pm_text, count=1)
        new_table = build_table_html(row)

        desc_m = DESC_CDATA_RE.search(pm_text)
        if not desc_m:
            desc = f"<description><![CDATA[\n{new_table}    ]]></description>"
            pm_text = re.sub(r"(?is)</Placemark>\s*$", desc + "\n</Placemark>", pm_text)
        else:
            inner = desc_m.group(1)
            updated_inner = replace_table_only(inner, new_table)
            pm_text = pm_text[:desc_m.start(1)] + updated_inner + pm_text[desc_m.end(1):]

        result.append(pm_text)
        last_end = end

    result.append(raw_xml[last_end:])
    return "".join(result)

# -------- Excel Input --------
def merge_excels(excel_path):
    """Read either one Excel or folder of bridges_*.xlsx."""
    def load_one(path):
        xl = pd.ExcelFile(path)
        sheet = "Editor" if "Editor" in xl.sheet_names else xl.sheet_names[0]
        df = xl.parse(sheet)
        return df
    if os.path.isdir(excel_path):
        dfs = []
        for fn in os.listdir(excel_path):
            if fn.lower().startswith("bridges_") and fn.lower().endswith(".xlsx"):
                dfs.append(load_one(os.path.join(excel_path, fn)))
        if not dfs:
            raise FileNotFoundError("❌ No bridges_*.xlsx found.")
        return pd.concat(dfs, ignore_index=True)
    else:
        return load_one(excel_path)

# -------- KMZ Update --------
def update_kmz_in_place(input_kmz, excel_path):
    temp_dir = tempfile.mkdtemp(prefix="kmz_edit_")
    try:
        # Backup
        backup = f"{input_kmz}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(input_kmz, backup)
        print(f"💾 Backup created: {backup}")

        with zipfile.ZipFile(input_kmz, "r") as zf:
            zf.extractall(temp_dir)

        doc_path = os.path.join(temp_dir, "doc.kml")
        if not os.path.exists(doc_path):
            for root, _, files in os.walk(temp_dir):
                for f in files:
                    if f.lower().endswith(".kml"):
                        doc_path = os.path.join(root, f)
                        break
                if os.path.exists(doc_path): break

        print(f"📄 Loading Excel data: {excel_path}")
        df = merge_excels(excel_path)
        print(f"⚙️ Updating {len(df)} rows in KML...")

        with open(doc_path, "r", encoding="utf-8") as f:
            raw = f.read()
        updated = update_kml_with_excel(raw, df)
        if not updated.startswith("<?xml"):
            updated = '<?xml version="1.0" encoding="UTF-8"?>\n' + updated
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(updated)

        print("📦 Repacking KMZ...")
        with zipfile.ZipFile(input_kmz, "w", zipfile.ZIP_DEFLATED) as new_zip:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    full = os.path.join(root, file)
                    arc = os.path.relpath(full, temp_dir)
                    new_zip.write(full, arcname=arc)

        print(f"✅ Updated in place: {input_kmz}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# -------- CLI --------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python update_bridge_kmz_from_excel.py input.kmz bridges.xlsx|folder")
        sys.exit(1)

    update_kmz_in_place(sys.argv[1], sys.argv[2])
