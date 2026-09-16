#!/usr/bin/env python3
"""
export_bridge_kmz_to_pkrms_excel.py — Safe Merge + Name Sync Edition

- Reads .kmz/.kml
- Cleans unknown XML prefixes (gx:, atom:, ns1:, etc.)
- For each Placemark:
    * Syncs <description> table rows "No. Jembatan" & "Nama Jembatan" to match <name>
      (if missing, "-", or different)
    * Parses table robustly (Indonesian & PKRMS labels; tolerant to spaces/()/-/_/.)
    * Non-destructive: preserves existing values
- Outputs bridges_{KecamatanCode}.xlsx with:
    * Sheet "Editor" (23 fields, your working schema)
    * Sheet "PKRMS_61" (61 fields, auto-filled from Editor)

Usage:
    python export_bridge_kmz_to_pkrms_excel.py Processed-input.kmz
"""

import os, re, zipfile, tempfile, shutil, html, xml.etree.ElementTree as ET
import pandas as pd

# ================== KML Namespace ==================
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)
def k(tag): return f"{{{KML_NS}}}{tag}"

# ================== Editor (23 fields) ==================
EDITOR_COLUMNS = [
    "No. Jembatan", "Nama Jembatan", "Longitude", "Latitude", "Kecamatan",
    "STA(m)", "Panjang(m)", "Lebar(m)", "Jumlah Bentang",
    "Bangunan Atas - Kode", "Bangunan Atas - Tipe", "Bangunan Atas - Kondisi",
    "Bangunan Bawah - Tipe", "Bangunan Bawah - Kondisi",
    "Fondasi - Tipe", "Fondasi - Kondisi",
    "Permukaan Jembatan - Tipe", "Permukaan Jembatan - Kondisi",
    "Aliran - Tipe", "Aliran - Kondisi",
    "Tahun Konstruksi", "Tahun Survey"
]

# ================== PKRMS (61 fields) ==================
PKRMS_COLUMNS = [
    "Year","Province_Code","Kabupaten_Code","Link_No","Bridge_Number","Chainage",
    "DRP_From","Offset_From","Bridge_Name","Bridge_Length","Bridge_Type",
    "Number_Spans","Road_Width","Footpath_Width_L","Footpath_Width_R","Crossing",
    "Year_Construction","Bridge_North_Deg","Bridge_North_Min","Bridge_North_Sec",
    "Bridge_East_Deg","Bridge_East_Min","Bridge_East_Sec","Handrails","Cond_Handrails",
    "Guardrail","Cond_Guardrails","RoadSurface","Cond_RoadSurface","Deck","Cond_Deck",
    "DeckJoints","Cond_DeckJoints","Beam","Cond_Beam","WingWalls","Cond_WingWalls",
    "Abutment","Cond_Abutment","Piers","Cond_Piers","Bearings","Cond_Bearings",
    "Foundations","Cond_Foundations","StormwaterDrain","Cond_StormwaterDrain",
    "Obstruction","Cond_Obstruction","Scouring","Cond_Scouring","AnalysisBaseYear",
    "SurveyBy","EntryStatus","PondasiType","BangbwahType","LantaiType","Bahanbangatas",
    "AsalBangatas","BahanBangbwah","BahanPond"
]

# ================== Label normalization ==================
def canon(label: str) -> str:
    """normalize label -> lowercase, strip spaces, punctuation, ()-_.:"""
    if label is None: return ""
    s = str(label).strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[._:()\-]+", "", s)
    return s

# Canonical name -> Editor column (handles Indonesian & PKRMS)
CANON_TO_EDITOR = {
    # primary
    "nojembatan": "No. Jembatan",
    "bridgenumber": "No. Jembatan",
    "namajembatan": "Nama Jembatan",
    "bridgename": "Nama Jembatan",

    # coords
    "longitude": "Longitude",
    "latitude": "Latitude",

    # station/dims
    "stam": "STA(m)",
    "chainage": "STA(m)",
    "panjangm": "Panjang(m)",
    "bridgelength": "Panjang(m)",
    "lebarm": "Lebar(m)",
    "roadwidth": "Lebar(m)",
    "jumlahbentang": "Jumlah Bentang",
    "numberspans": "Jumlah Bentang",

    # superstructure
    "bangunanataskode": "Bangunan Atas - Kode",
    "bahanbangatas": "Bangunan Atas - Kode",
    "asalbangatas": "Bangunan Atas - Kode",
    "bangunanatastipe": "Bangunan Atas - Tipe",
    "bridgetype": "Bangunan Atas - Tipe",
    "lantaitype": "Bangunan Atas - Tipe",
    "bangunanataskondisi": "Bangunan Atas - Kondisi",
    "conddeck": "Bangunan Atas - Kondisi",

    # substructure
    "bangunanbawahtipe": "Bangunan Bawah - Tipe",
    "bangbwahtype": "Bangunan Bawah - Tipe",
    "bangunanbawahkondisi": "Bangunan Bawah - Kondisi",
    "condabutment": "Bangunan Bawah - Kondisi",

    # foundation
    "fondasitipe": "Fondasi - Tipe",
    "pondasitype": "Fondasi - Tipe",
    "fondasikondisi": "Fondasi - Kondisi",
    "condfoundations": "Fondasi - Kondisi",

    # surface
    "permukaanjembatantipe": "Permukaan Jembatan - Tipe",
    "roadsurface": "Permukaan Jembatan - Tipe",
    "permukaanjembatankondisi": "Permukaan Jembatan - Kondisi",
    "condroadsurface": "Permukaan Jembatan - Kondisi",

    # hydrology
    "alirantipe": "Aliran - Tipe",
    "crossing": "Aliran - Tipe",
    "alirankondisi": "Aliran - Kondisi",
    "condscouring": "Aliran - Kondisi",

    # misc
    "kecamatan": "Kecamatan",
    "tahunkonstruksi": "Tahun Konstruksi",
    "yearconstruction": "Tahun Konstruksi",
    "tahunsurvey": "Tahun Survey",
    "analysisbaseyear": "Tahun Survey",
}

# PKRMS direct names -> Editor column (for building PKRMS sheet)
PKRMS_TO_EDITOR_DIRECT = {
    "Bridge_Number": "No. Jembatan",
    "Bridge_Name": "Nama Jembatan",
    "Chainage": "STA(m)",
    "Bridge_Length": "Panjang(m)",
    "Road_Width": "Lebar(m)",
    "Number_Spans": "Jumlah Bentang",
    "Year_Construction": "Tahun Konstruksi",
    "AnalysisBaseYear": "Tahun Survey",
    "RoadSurface": "Permukaan Jembatan - Tipe",
    "Cond_RoadSurface": "Permukaan Jembatan - Kondisi",
    "Crossing": "Aliran - Tipe",
    "Cond_Scouring": "Aliran - Kondisi",
    "Deck": "Bangunan Atas - Tipe",
    "Cond_Deck": "Bangunan Atas - Kondisi",
    "BangbwahType": "Bangunan Bawah - Tipe",
    "Cond_Abutment": "Bangunan Bawah - Kondisi",
    "PondasiType": "Fondasi - Tipe",
    "Cond_Foundations": "Fondasi - Kondisi",
    "Bahanbangatas": "Bangunan Atas - Kode",
}

# ================== Regex for table rows ==================
ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*(?:<b>)?\s*(?P<label>[^<]+?)\s*(?:</b>)?\s*</td>\s*"
    r"<td[^>]*>\s*(?P<value>.*?)\s*</td>\s*</tr>", re.I | re.S
)

# ================== Helpers ==================
def clean_namespaces(xml_text: str) -> str:
    """Remove unknown namespace decls and prefixes (gx:, atom:, ns1:...)."""
    xml_text = re.sub(r'\s+xmlns:[^=]+="[^"]+"', '', xml_text)
    xml_text = re.sub(r'<(/?)([A-Za-z0-9_]+):', r'<\1', xml_text)
    return xml_text

def split_name(full: str):
    if not full: return "-", "-"
    parts = full.strip().split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "-")

def dms_from_decimal(value):
    try:
        v = float(str(value).strip())
    except Exception:
        return "-", "-", "-"
    deg = int(abs(v)); frac = abs(v) - deg
    minutes_full = frac * 60.0
    minu = int(minutes_full)
    sec = (minutes_full - minu) * 60.0
    if v < 0: deg = -deg
    return str(deg), str(minu), f"{sec:.2f}"

def sync_name_in_description(desc_text: str, full_name: str) -> str:
    """
    Ensure 'No. Jembatan' and 'Nama Jembatan' in <description> match <name>.
    If the cell is '-' or different, update it. If missing, append row before </table>.
    """
    if not desc_text or not full_name:
        return desc_text

    parts = full_name.strip().split(" ", 1)
    no_jbt = parts[0].strip() if parts else "-"
    nama_jbt = parts[1].strip() if len(parts) > 1 else "-"

    def upsert_row(label, new_val, text):
        pat = re.compile(
            rf'(<tr><td><b>{re.escape(label)}</b></td><td>)(.*?)(</td></tr>)',
            re.I | re.S
        )
        m = pat.search(text)
        if m:
            cur = m.group(2).strip()
            if cur in ["", "-", None] or cur != new_val:
                text = pat.sub(rf"\1{new_val}\3", text, count=1)
        else:
            # insert before closing </table> if table exists
            insert = f'<tr><td><b>{label}</b></td><td>{html.escape(new_val)}</td></tr>'
            if "</table>" in text.lower():
                # find case-insensitively
                close_idx = re.search(r"</table>", text, flags=re.I).start()
                text = text[:close_idx] + insert + text[close_idx:]
        return text

    t = desc_text
    t = upsert_row("No. Jembatan", no_jbt, t)
    t = upsert_row("Nama Jembatan", nama_jbt, t)
    return t

def parse_table(desc_text: str):
    """Parse table rows into {EditorColumn: value}, bilingual + tolerant labels."""
    out = {}
    if not desc_text:
        return out
    text = html.unescape(desc_text)
    for m in ROW_RE.finditer(text):
        raw_label = m.group("label").strip()
        raw_value = re.sub(r"<[^>]+>", "", m.group("value")).strip()
        c = canon(raw_label)
        editor_key = CANON_TO_EDITOR.get(c)
        if editor_key is None:
            # try direct PKRMS names
            editor_key = PKRMS_TO_EDITOR_DIRECT.get(raw_label)
            if editor_key is None:
                # try canon of PKRMS names
                for pk_name, ed_name in PKRMS_TO_EDITOR_DIRECT.items():
                    if canon(pk_name) == c:
                        editor_key = ed_name
                        break
        if editor_key:
            out[editor_key] = html.unescape(raw_value)
    return out

# ================== Core extraction ==================
def extract_from_kml_text(kml_text: str):
    root = ET.fromstring(kml_text)
    out_rows = []
    synced = 0

    for pm in root.iterfind(".//" + k("Placemark")):
        row = {}

        # <name>
        name_el = pm.find(k("name"))
        full_name = (name_el.text or "").strip()
        bridge_no, bridge_nm = split_name(full_name)

        # coords
        lon = lat = "-"
        coord_el = pm.find(".//" + k("coordinates"))
        if coord_el is not None and coord_el.text:
            parts = re.split(r"[\s,]+", coord_el.text.strip())
            if len(parts) >= 2:
                lon, lat = parts[0], parts[1]

        # <description>
        desc_el = pm.find(k("description"))
        desc_text = desc_el.text if desc_el is not None else ""

        # 1) Sync table name/number to <name>
        if desc_text and "<table" in desc_text and not ("&lt;table" in desc_text):
            synced_text = sync_name_in_description(desc_text, full_name)
            if synced_text != desc_text and desc_el is not None:
                desc_el.text = synced_text
                desc_text = synced_text
                synced += 1

        # 2) Parse table values
        table_vals = parse_table(desc_text)

        # Non-destructive merge
        row["No. Jembatan"] = table_vals.get("No. Jembatan", bridge_no or "-")
        row["Nama Jembatan"] = table_vals.get("Nama Jembatan", bridge_nm or "-")
        row["Longitude"] = lon or "-"
        row["Latitude"] = lat or "-"

        for key in EDITOR_COLUMNS:
            if key in table_vals and table_vals[key] not in ["", None]:
                row[key] = table_vals[key]

        # fill defaults
        for col in EDITOR_COLUMNS:
            if col not in row or row[col] in ["", None]:
                row[col] = "-"

        out_rows.append(row)

    if synced:
        print(f"🔄 Synced name/number inside description for {synced} placemark(s).")
    return out_rows

# ================== KMZ/KML reading ==================
def kmz_to_text(path):
    if path.lower().endswith(".kml"):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    tmp = tempfile.mkdtemp(prefix="kmz_")
    try:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(tmp)
        doc = os.path.join(tmp, "doc.kml")
        if not os.path.exists(doc):
            for r,_,fs in os.walk(tmp):
                for fn in fs:
                    if fn.lower().endswith(".kml"):
                        doc = os.path.join(r, fn); break
                if os.path.exists(doc): break
        with open(doc, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ================== Editor -> PKRMS ==================
def make_pkrms_row(editor_row: dict) -> dict:
    p = {c: "-" for c in PKRMS_COLUMNS}
    for pk_col, ed_col in PKRMS_TO_EDITOR_DIRECT.items():
        p[pk_col] = editor_row.get(ed_col, "-")

    # coords -> DMS
    lon = editor_row.get("Longitude", "-")
    lat = editor_row.get("Latitude", "-")
    dN,mN,sN = dms_from_decimal(lat)
    dE,mE,sE = dms_from_decimal(lon)
    p["Bridge_North_Deg"], p["Bridge_North_Min"], p["Bridge_North_Sec"] = dN,mN,sN
    p["Bridge_East_Deg"],  p["Bridge_East_Min"],  p["Bridge_East_Sec"]  = dE,mE,sE
    return p

# ================== Excel writer ==================
def write_per_kecamatan(grouped: dict, out_dir: str = "."):
    for kec_code, rows in grouped.items():
        editor_df = pd.DataFrame(rows, columns=EDITOR_COLUMNS)
        pkrms_rows = [make_pkrms_row(r) for r in rows]
        pkrms_df = pd.DataFrame(pkrms_rows, columns=PKRMS_COLUMNS)

        out_path = os.path.join(out_dir, f"bridges_{kec_code}.xlsx")
        with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
            editor_df.to_excel(xw, index=False, sheet_name="Editor")
            pkrms_df.to_excel(xw, index=False, sheet_name="PKRMS_61")
        print(f"✅ Wrote {out_path} — rows: {len(rows)}")

# ================== Main extract ==================
def extract(input_path: str):
    text = kmz_to_text(input_path)

    # Clean invalid namespaces before parsing
    clean = clean_namespaces(text)

    # Early-out if file is clearly already processed and has consistent structures
    # (we still extract; this is just a guard you can enable if desired)
    rows = extract_from_kml_text(clean)

    # group by Kecamatan code from No. Jembatan pattern J-15.AA.BB(.CCC)?-XX
    def parse_codes(noj):
        m = re.match(r"^J-15\.(\d{2})\.(\d{2})(?:\.\d{1,3})?-\d+$", noj or "")
        if not m: return ("--","00")
        return (m.group(1), m.group(2))

    grouped = {}
    for r in rows:
        _, kec = parse_codes(r.get("No. Jembatan","-"))
        grouped.setdefault(kec, []).append(r)

    write_per_kecamatan(grouped)

# ================== CLI ==================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python export_bridge_kmz_to_pkrms_excel.py Processed-input.kmz|doc.kml")
        raise SystemExit(1)
    extract(sys.argv[1])
