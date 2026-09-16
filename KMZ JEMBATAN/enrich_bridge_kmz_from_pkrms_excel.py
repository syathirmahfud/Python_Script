#!/usr/bin/env python3
"""
Proses KMZ mentah dari Avenza Maps (disusun ulang & disimpan lewat Google
Earth Pro) dan gabungkan dengan data PKRMS (.xlsx) untuk mengisi TABLE_FIELDS
secara lengkap, lalu hasilkan KMZ baru dengan tabel info per Placemark.

- Dialog tkinter untuk memilih: KMZ input, Excel PKRMS input, lokasi simpan KMZ output.
- Join dilakukan berdasarkan No. Jembatan (Bridge_Number), yang diambil dari
  nama Placemark dan dicocokkan ke kolom Bridge_Number di PKRMS.
- Field kode (Bridge_Type, PondasiType, BangbwahType, LantaiType) diterjemahkan
  ke label Bahasa Indonesia memakai tabel kode CODE_* (lihat CODE_TABLES di bawah).
- Field "Kondisi" dihitung memakai port Python dari fungsi BridgeCondition()
  resmi (Access VBA) - lihat bridge_condition().
- Aman dijalankan berulang kali: Placemark yang sudah diproses tidak diproses ulang.
"""

import os
import re
import sys
import zipfile
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import openpyxl
except ImportError:
    openpyxl = None


# --- KML Namespace ---
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def k(tag):
    return f"{{{KML_NS}}}{tag}"


# --- Bridge Info Table Fields (order matters — this is what gets rendered) ---
TABLE_FIELDS = [
    "No. Jembatan", "Nama Jembatan", "Longitude", "Latitude", "Kecamatan",
    "STA(m)", "Panjang(m)", "Lebar(m)", "Jumlah Bentang",
    "Bangunan Atas - Kode", "Bangunan Atas - Tipe", "Bangunan Atas - Kondisi",
    "Bangunan Bawah - Tipe", "Bangunan Bawah - Bahan", "Bangunan Bawah - Kondisi",
    "Fondasi - Tipe", "Fondasi - Bahan", "Fondasi - Kondisi",
    "Permukaan Jembatan - Tipe", "Permukaan Jembatan - Kondisi",
    "Tahun Konstruksi", "Kondisi Jembatan (Keseluruhan)", "Tahun Survey",
]

PROCESSED_MARKER = "<!--BRIDGE_TABLE_PROCESSED_V3-->"

# Pin color by prefix: "G-..." (Gorong-gorong/culvert) vs "J-..." (Jembatan/bridge)
PIN_STYLE_G_ID = "pinStyleG"
PIN_STYLE_J_ID = "pinStyleJ"
PIN_ICON_G = "http://download.avenza.com/images/pdfmaps_icons/yellow_pin.png"  # G = Gorong-gorong (culvert)
PIN_ICON_J = "http://download.avenza.com/images/pdfmaps_icons/blue_pin.png"    # J = Jembatan (bridge)

# Default PKRMS Excel location - offered as a quick choice in the dialog,
# but the user can always browse for a different file instead.
DEFAULT_PKRMS_PATH = r"D:\15.09 TANJUNG JABUNG BARAT\SURVEY KONDISI JEMBATAN\DOKUMEN\INPUT_PKRMS_JEMBATAN.xlsx"

CODE_PATTERN = re.compile(r"^[GJ]-\d+(?:\.\d+)*-\d+$")
CODE_PLUS_NAME_PATTERN = re.compile(r"^([GJ]-\d+(?:\.\d+)*-\d+)\s+(.+)$")

# Kondisi rating scale used throughout PKRMS (from Form_Load: txtBridgeCond.RowSource)
CONDITION_LABELS = {
    1: "Baik",
    2: "Sedang",
    3: "Rusak Ringan",
    4: "Rusak Berat",
}


def condition_label(value):
    """Map a BridgeCondition() result (always 1-4, see bridge_condition())
    to its Indonesian label. Falls back to '-' only for genuinely invalid
    input, which should not happen in normal operation."""
    if value is None:
        return "-"
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "-"
    return CONDITION_LABELS.get(v, "-")


# ==========================================================
# ===========  PKRMS CODE LOOKUP TABLES (Ind)  ==============
# ==========================================================
# Source: CODE_BridgeType / CODE_PondasiType / CODE_BangbwahType / CODE_LantaiType
# tables shown in the Access application (screenshots), CodeDescription_Ind column.

CODE_BRIDGE_TYPE = {
    1: "Gorong-gorong Bulat", 2: "Gorong-gorong Oval", 3: "Gorong-gorong Kotak",
    4: "Oval", 5: "Gelagar", 6: "Balok Oval", 7: "Komposit", 8: "Plat",
    9: "Rangka Baja", 10: "Jembatan Gantung", 11: "Jembatan Kabel Pancang",
    12: "Jembatan Sementara", 13: "Lintasan Kereta", 14: "Lintasan Sungai",
    15: "Lintasan Feri", 16: "Lainnya", 17: "Struktur Diperlukan",
}

# CODE_BridgeType_BMS.ShortCode - the actual abbreviation shown for
# "Bangunan Atas - Kode" (e.g. Code 8/Plat -> "PTI").
CODE_BRIDGE_TYPE_SHORTCODE = {
    1: "YTI", 2: "API", 3: "BTI", 4: "EMI", 5: "GBI", 6: "LLI", 7: "MLI",
    8: "PTI", 9: "RBA", 10: "TBI", 11: "CBI", 12: "SBW", 13: "KLI",
    14: "WTI", 15: "FLI", 16: "ULL", 17: "XXX",
}

CODE_PONDASI_TYPE = {
    1: "Cakar Ayam", 2: "Langsung", 3: "Tiang Pancang", 4: "Tiang Bor",
    5: "Tiang Ulir", 6: "Sumuran", 7: "Lainnya",
}

CODE_BANGBWAH_TYPE = {
    1: "Cap (Kepala Tiang)", 2: "Dinding Penuh", 3: "Kepala Jembatan Khusus",
}

CODE_LANTAI_TYPE = {
    1: "Kayu", 2: "Pasangan Bata", 3: "Pasangan Batu", 4: "Bronjong Dan Sejenisnya",
    5: "Pasangan Batu Kosong", 6: "Beton Bertulang", 7: "Beton Bertulang",
    8: "Beton Pratekan", 9: "Baja", 10: "Plat Baja Bergelombang",
    11: "Komposit Baja-Beton", 12: "Aluminium", 13: "Neoprene/Karet",
    14: "Teflon", 15: "PVC", 16: "Geotextile",
    17: "Tanah Biasa/Lempung atau Timbunan", 18: "Aspal", 19: "Kerikil",
    20: "Macadam", 21: "Bahan Asli", 22: "Lain-Lain",
}

# Not currently used by TABLE_FIELDS, kept here for future extension.
CODE_BAHAN_BANGATAS = {
    1: "Kayu", 2: "Pasangan Bata", 3: "Pasangan Batu", 4: "Bronjong Dan Sejenisnya",
    5: "Pasangan Batu Kosong", 6: "Beton Tak Bertulang", 7: "Beton Bertulang",
    8: "Beton Pratekan", 9: "Baja", 10: "Plat Baja Bergelombang",
    11: "Komposit Baja-Beton", 12: "Aluminium", 13: "Neoprene/Karet",
    14: "Teflon", 15: "PVC", 16: "Geotextile",
    17: "Tanah Biasa/Lempung atau Timbunan", 18: "Aspal", 19: "Kerikil",
    20: "Macadam", 21: "Bahan Asli", 22: "Lain-Lain",
}
CODE_ASAL_BANGATAS = {
    1: "Australia", 2: "Australia (Sementara)", 3: "Belanda (Tipe Baru)",
    4: "Belanda (Tipe Lama)", 5: "Indonesia", 6: "Jepang", 7: "Austria",
    8: "Spanyol", 9: "Callender Hamilton (UK/Inggris)", 10: "Acrow/Bailey",
}
CODE_BAHAN_BANGBWAH = dict(CODE_BAHAN_BANGATAS)
CODE_BAHAN_POND = dict(CODE_BAHAN_BANGATAS)


def lookup_code(table, raw_value):
    """Look up a coded PKRMS value in one of the CODE_* dicts. Returns '-' if
    missing/blank/unrecognized."""
    if raw_value is None or str(raw_value).strip() == "":
        return "-"
    try:
        code_int = int(str(raw_value).strip())
    except ValueError:
        return "-"
    return table.get(code_int, "-")


# ==========================================================
# ===========  Official BridgeCondition() (Access VBA)  =======
# ==========================================================
def bridge_condition(*values):
    """
    Exact Python port of the production Access VBA function:

        Public Function BridgeCondition(ParamArray varMyVals() As Variant) As Variant
            Dim Idx As Integer
            Dim MyMax As Variant
            If (UBound(varMyVals) < 0) Then
                BridgeCondition = 1
                Exit Function
            Else
                If varMyVals(0) < 6 Then
                    MyMax = varMyVals(0)
                Else
                    MyMax = 1
                End If
            End If
            For Idx = 0 To UBound(varMyVals())
                If (Not IsMissing(varMyVals(Idx))) Then
                    If varMyVals(Idx) < 6 Then      ' ignore 99 as a condition mark
                        If (varMyVals(Idx) > MyMax) Then
                            MyMax = varMyVals(Idx)
                        End If
                    End If
                End If
            Next Idx
            MyMax = IIf(MyMax <= 0, 1, MyMax)
            BridgeCondition = IIf(MyMax = 5, 4, MyMax)
            Exit Function
        End Function

    Takes the worst (max) of all inputs below 6 (values >= 6, e.g. the
    sentinel 99, mean "not applicable" and are ignored), then clamps the
    result: <= 0 becomes 1, and exactly 5 becomes 4. Output is always in
    {1, 2, 3, 4}.
    """
    vals = list(values)
    if len(vals) == 0:
        return 1

    first = vals[0]
    my_max = first if (first is not None and first < 6) else 1

    for v in vals:
        if v is not None and v < 6:
            if v > my_max:
                my_max = v

    if my_max <= 0:
        my_max = 1
    if my_max == 5:
        return 4
    return my_max


# ==========================================================
# ===============  PKRMS EXCEL LOADER  =======================
# ==========================================================
def load_pkrms_data(xlsx_path):
    """Read the PKRMS export and return {Bridge_Number: {column: value}}."""
    if openpyxl is None:
        raise RuntimeError("Modul 'openpyxl' tidak tersedia. Install dengan: "
                            "pip install openpyxl")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]

    data = {}
    for row in rows[1:]:
        record = dict(zip(headers, row))
        bridge_no = str(record.get("Bridge_Number", "")).strip()
        if not bridge_no:
            continue
        data[bridge_no] = record
    return data


def get_num(record, field, default=0):
    val = record.get(field, default)
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val) if "." in str(val) else int(val)
    except (TypeError, ValueError):
        return default


# ==========================================================
# ===============  UTILITY FUNCTIONS  =======================
# ==========================================================
def split_name(name_text: str):
    """
    Split a Placemark <name> into (No. Jembatan, Nama Jembatan).
      - code only:   "G-15.06.01.002-1"              -> ("G-15.06.01.002-1", "-")
      - code + name: "G-15.06.01.002-1 Sungai Air"    -> ("G-15.06.01.002-1", "Sungai Air")
      - name only:   "Sungai Air Hitam"               -> ("-", "Sungai Air Hitam")
    """
    text = (name_text or "").strip()
    if not text:
        return "-", "-"

    combined = CODE_PLUS_NAME_PATTERN.match(text)
    if combined:
        return combined.group(1), combined.group(2).strip()

    if CODE_PATTERN.match(text):
        return text, "-"

    return "-", text


def extract_kecamatan(doc_title: str):
    """'SURVEY KONDISI JEMBATAN KECAMATAN TUNGKAL ULU' -> 'Tungkal Ulu'
    (title case: only the first letter of each word capitalized)."""
    if not doc_title:
        return "-"
    m = re.search(r"KECAMATAN\s+(.+)$", doc_title.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip().title()
    return "-"


def build_bridge_fields(no_jbt, nama_jbt, lon, lat, kecamatan, pkrms_record):
    """Build the full dict of TABLE_FIELDS values, combining KMZ-derived data
    with the matched PKRMS record (if any)."""
    values = {
        "No. Jembatan": no_jbt or "-",
        "Nama Jembatan": nama_jbt or "-",
        "Longitude": lon or "-",
        "Latitude": lat or "-",
        "Kecamatan": kecamatan or "-",
    }

    if pkrms_record is None:
        for label in TABLE_FIELDS:
            values.setdefault(label, "-")
        return values

    r = pkrms_record

    # Direct numeric fields
    values["STA(m)"] = r.get("Chainage", "-") if r.get("Chainage") not in (None, "") else "-"
    values["Panjang(m)"] = r.get("Bridge_Length", "-") if r.get("Bridge_Length") not in (None, "") else "-"
    values["Lebar(m)"] = r.get("Road_Width", "-") if r.get("Road_Width") not in (None, "") else "-"
    values["Jumlah Bentang"] = r.get("Number_Spans", "-") if r.get("Number_Spans") not in (None, "") else "-"

    # Bangunan Atas
    bridge_type_raw = r.get("Bridge_Type", "-")
    values["Bangunan Atas - Kode"] = lookup_code(CODE_BRIDGE_TYPE_SHORTCODE, bridge_type_raw)
    values["Bangunan Atas - Tipe"] = lookup_code(CODE_BRIDGE_TYPE, bridge_type_raw)
    ba_cond = bridge_condition(get_num(r, "Cond_DeckJoints") - 1, get_num(r, "Cond_Beam"))
    values["Bangunan Atas - Kondisi"] = condition_label(ba_cond)

    # Bangunan Bawah
    values["Bangunan Bawah - Tipe"] = lookup_code(CODE_BANGBWAH_TYPE, r.get("BangbwahType"))
    values["Bangunan Bawah - Bahan"] = lookup_code(CODE_BAHAN_BANGBWAH, r.get("BahanBangbwah"))
    bb_cond = bridge_condition(
        get_num(r, "Cond_Piers"), get_num(r, "Cond_Bearings"),
        get_num(r, "Cond_WingWalls") - 1, get_num(r, "Cond_Abutment"),
    )
    values["Bangunan Bawah - Kondisi"] = condition_label(bb_cond)

    # Fondasi (single-input, still routed through bridge_condition() for
    # exact parity - e.g. it clamps 0/negative up to 1 "Baik" rather than
    # showing a raw value straight through)
    values["Fondasi - Tipe"] = lookup_code(CODE_PONDASI_TYPE, r.get("PondasiType"))
    values["Fondasi - Bahan"] = lookup_code(CODE_BAHAN_POND, r.get("BahanPond"))
    fond_cond = bridge_condition(get_num(r, "Cond_Foundations"))
    values["Fondasi - Kondisi"] = condition_label(fond_cond)

    # Permukaan Jembatan
    values["Permukaan Jembatan - Tipe"] = lookup_code(CODE_LANTAI_TYPE, r.get("LantaiType"))
    lan_cond = bridge_condition(get_num(r, "Cond_RoadSurface") - 2, get_num(r, "Cond_Deck") - 1)
    values["Permukaan Jembatan - Kondisi"] = condition_label(lan_cond)

    # Aliran removed per request (no longer part of TABLE_FIELDS)

    # Tahun
    year_constr = r.get("Year_Construction", "-")
    values["Tahun Konstruksi"] = year_constr if year_constr not in (None, "", 0) else "-"
    year_survey = r.get("Year", "-")
    values["Tahun Survey"] = year_survey if year_survey not in (None, "") else "-"

    # Overall bridge condition - same BridgeCondition() call as production's
    # UpdateBC / ExportXL_DD2, combining all 10 components at once (worst case).
    overall_cond = bridge_condition(
        get_num(r, "Cond_Piers"), get_num(r, "Cond_Bearings"),
        get_num(r, "Cond_Foundations"), get_num(r, "Cond_Scouring") - 1,
        get_num(r, "Cond_RoadSurface") - 2, get_num(r, "Cond_Deck") - 1,
        get_num(r, "Cond_DeckJoints") - 1, get_num(r, "Cond_Beam"),
        get_num(r, "Cond_WingWalls") - 1, get_num(r, "Cond_Abutment"),
    )
    values["Kondisi Jembatan (Keseluruhan)"] = condition_label(overall_cond)

    for label in TABLE_FIELDS:
        values.setdefault(label, "-")
    return values


def build_table_html(values):
    rows = []
    for label in TABLE_FIELDS:
        val = values.get(label, "-")
        rows.append(f'            <tr><td><b>{label}</b></td><td>{val}</td></tr>')
    return (
        '        <table style="border-collapse:collapse; table-layout:fixed; width:100%;" '
        'border="1" cellpadding="4">\n'
        '            <colgroup>\n'
        '                <col style="width: 30%;">\n'
        '                <col style="width: 70%;">\n'
        '            </colgroup>\n'
        + "\n".join(rows)
        + "\n        </table>\n"
    )


def ensure_snippet(pm):
    sn = pm.find(k("Snippet"))
    if sn is None:
        sn = ET.Element(k("Snippet"))
        sn.set("maxLines", "0")
        pm.insert(1, sn)
    else:
        sn.set("maxLines", "0")


def clean_namespaces(xml_text):
    """Remove unknown prefixes (gx:, ns1:, atom:, xsi:, etc.) and their xmlns
    declarations so ElementTree (which only knows the plain KML namespace)
    can parse cleanly. Strips prefixes from both element tags AND attribute
    names (e.g. xsi:schemaLocation="...") - a prefixed attribute left behind
    after its xmlns:xsi="..." declaration is removed causes ElementTree to
    raise "unbound prefix"."""
    # Remove xmlns:prefix="uri" declarations entirely
    xml_text = re.sub(r'\s+xmlns:[^=]+="[^"]+"', '', xml_text)
    # Strip prefix from element tag names: <prefix:tag ...> / </prefix:tag>
    xml_text = re.sub(r'<(/?)([A-Za-z0-9_]+):', r'<\1', xml_text)
    # Strip prefix from attribute names: prefix:attr="value" -> attr="value"
    xml_text = re.sub(r'(?<=[\s])([A-Za-z0-9_]+):([A-Za-z0-9_]+)=', r'\2=', xml_text)
    return xml_text


def get_simple_data(pm, field_name):
    for sd in pm.findall(".//" + k("SimpleData")):
        if sd.get("name") == field_name:
            return sd.text or ""
    return ""


# ==========================================================
# ===============  CORE PROCESSING  =========================
# ==========================================================
def build_pin_styles():
    """Two <Style> elements: an orange pin for "G-..." (Gorong-gorong/culvert)
    placemarks and a blue pin for "J-..." (Jembatan/bridge) placemarks."""
    styles = []
    for style_id, icon_url in ((PIN_STYLE_G_ID, PIN_ICON_G), (PIN_STYLE_J_ID, PIN_ICON_J)):
        style = ET.Element(k("Style"))
        style.set("id", style_id)
        icon_style = ET.SubElement(style, k("IconStyle"))
        icon = ET.SubElement(icon_style, k("Icon"))
        href = ET.SubElement(icon, k("href"))
        href.text = icon_url
        styles.append(style)
    return styles


def ensure_pin_styles(doc_el):
    """Insert the two pin <Style> definitions into <Document> once (skips
    re-adding them if already present, e.g. on a re-run)."""
    if doc_el is None:
        return
    existing_ids = {s.get("id") for s in doc_el.findall(k("Style"))}
    for style in build_pin_styles():
        if style.get("id") not in existing_ids:
            doc_el.append(style)


def apply_pin_style(pm, no_jbt):
    """Set/overwrite this Placemark's <styleUrl> based on the first letter
    of its No. Jembatan code: G -> orange pin, J -> blue pin. Leaves the
    existing styleUrl untouched if no_jbt doesn't start with G or J."""
    prefix = (no_jbt or "")[:1].upper()
    if prefix == "G":
        style_url = "#" + PIN_STYLE_G_ID
    elif prefix == "J":
        style_url = "#" + PIN_STYLE_J_ID
    else:
        return
    su_el = pm.find(k("styleUrl"))
    if su_el is None:
        su_el = ET.SubElement(pm, k("styleUrl"))
    su_el.text = style_url


def process_kml_text(xml_text, pkrms_data):
    xml_text = clean_namespaces(xml_text)
    root = ET.fromstring(xml_text)

    doc_title = "-"
    doc_el = root.find(k("Document"))
    if doc_el is not None:
        title_el = doc_el.find(k("name"))
        if title_el is not None and title_el.text:
            doc_title = title_el.text.strip()
    kecamatan = extract_kecamatan(doc_title)

    ensure_pin_styles(doc_el)

    token_map = {}
    updated = 0
    matched, unmatched = [], []

    for pm in root.iterfind(".//" + k("Placemark")):
        name_text = "?"
        try:
            name_el = pm.find(k("name"))
            name_text = (name_el.text or "").strip() if name_el is not None else ""
            no_jbt, nama_jbt = split_name(name_text)

            apply_pin_style(pm, no_jbt)

            # Always rebuild the table fresh (rather than skip if already
            # processed) - safe to re-run on an already-processed KMZ any
            # time PKRMS data/structure has been updated, since the whole
            # <description> gets overwritten below rather than appended to.
            desc_el = pm.find(k("description"))

            coord_el = pm.find(".//" + k("coordinates"))
            lon, lat = "-", "-"
            if coord_el is not None and coord_el.text:
                coords = coord_el.text.strip().split(",")
                if len(coords) >= 2:
                    lon, lat = coords[0].strip(), coords[1].strip()

            ensure_snippet(pm)

            photos_raw = get_simple_data(pm, "pdfmaps_photos")
            photo_section = ""
            if photos_raw.strip():
                photo_section = (
                    "        <br><b>Foto:</b><br>\n"
                    + photos_raw.strip()
                    + "\n        <hr style=\"border:2px solid black;\">\n"
                )

            pkrms_record = pkrms_data.get(no_jbt) if no_jbt != "-" else None
            if no_jbt != "-":
                if pkrms_record is not None:
                    matched.append(no_jbt)
                else:
                    unmatched.append(no_jbt)

            # If the Placemark's <name> has no usable name text (empty or
            # missing tag), fall back to PKRMS's Bridge_Name - both for the
            # "Nama Jembatan" table field AND to actually rewrite the
            # Placemark's <name> element itself, so Google Earth's label and
            # future re-runs' split_name() both pick it up correctly.
            if nama_jbt == "-" and pkrms_record is not None:
                bridge_name_pkrms = str(pkrms_record.get("Bridge_Name", "") or "").strip()
                if bridge_name_pkrms:
                    nama_jbt = bridge_name_pkrms
                    new_name_text = f"{no_jbt} {bridge_name_pkrms}" if no_jbt != "-" else bridge_name_pkrms
                    if name_el is None:
                        name_el = ET.SubElement(pm, k("name"))
                    name_el.text = new_name_text

            field_values = build_bridge_fields(no_jbt, nama_jbt, lon, lat, kecamatan, pkrms_record)
            table_html = build_table_html(field_values)
            cdata_body = "\n" + PROCESSED_MARKER + "\n" + photo_section + table_html + "    "

            token = f"__CDATA_{uuid.uuid4().hex}__"
            token_map[token] = cdata_body

            if desc_el is None:
                desc_el = ET.SubElement(pm, k("description"))
            desc_el.text = token
            updated += 1

        except Exception as e:
            print(f"[!] Gagal memproses placemark '{name_text}': {e}")
            continue

    raw_xml = ET.tostring(root, encoding="utf-8").decode("utf-8")
    for token, body in token_map.items():
        raw_xml = raw_xml.replace(
            f"<description>{token}</description>",
            f"<description><![CDATA[{body}]]></description>",
        )

    if not raw_xml.startswith("<?xml"):
        raw_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw_xml

    print(f"Kecamatan terdeteksi: {kecamatan}")
    print(f"Placemark diperbarui (tabel dibangun ulang): {updated}")
    if pkrms_data:
        print(f"Cocok dengan data PKRMS: {len(matched)}")
        if unmatched:
            print(f"TIDAK ditemukan di PKRMS ({len(unmatched)}): {', '.join(unmatched)}")
        pkrms_unused = set(pkrms_data.keys()) - set(matched)
        if pkrms_unused:
            print(f"Baris PKRMS tanpa placemark yang cocok ({len(pkrms_unused)}): {', '.join(sorted(pkrms_unused))}")

    return raw_xml


# ==========================================================
# ===============  KMZ HANDLER  =============================
# ==========================================================
def process_kmz(in_path, out_path, pkrms_xlsx_path=None):
    if not os.path.exists(in_path):
        raise FileNotFoundError(f"File input tidak ditemukan: {in_path}")

    pkrms_data = {}
    if pkrms_xlsx_path:
        print(f"Membaca data PKRMS: {pkrms_xlsx_path}")
        pkrms_data = load_pkrms_data(pkrms_xlsx_path)
        print(f"Jumlah baris PKRMS terbaca: {len(pkrms_data)}")

    temp_dir = tempfile.mkdtemp(prefix="kmz_")
    try:
        print(f"Mengekstrak: {in_path}")
        with zipfile.ZipFile(in_path, "r") as zf:
            zf.extractall(temp_dir)

        doc_path = os.path.join(temp_dir, "doc.kml")
        if not os.path.exists(doc_path):
            for r, _, files in os.walk(temp_dir):
                for f in files:
                    if f.lower().endswith(".kml"):
                        doc_path = os.path.join(r, f)
                        break
                if os.path.exists(doc_path):
                    break

        if not os.path.exists(doc_path):
            raise FileNotFoundError("Tidak ditemukan file .kml di dalam KMZ.")

        with open(doc_path, "r", encoding="utf-8") as f:
            xml_text = f.read()

        processed = process_kml_text(xml_text, pkrms_data)

        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(processed)

        print("Mengemas ulang KMZ...")
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as new_zip:
            for r, _, files in os.walk(temp_dir):
                for file in files:
                    fp = os.path.join(r, file)
                    arc = os.path.relpath(fp, temp_dir)
                    new_zip.write(fp, arcname=arc)

        print(f"Selesai! Output: {out_path}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==========================================================
# ===============  TKINTER FILE DIALOGS  =====================
# ==========================================================
def select_files():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    in_path = filedialog.askopenfilename(
        parent=root,
        title="Pilih file KMZ mentah dari Avenza Maps",
        filetypes=[("KMZ files", "*.kmz"), ("All files", "*.*")],
    )
    if not in_path:
        root.destroy()
        return None, None, None

    use_pkrms = messagebox.askyesno(
        "Data PKRMS",
        "Apakah Anda ingin mengisi tabel dari data PKRMS (.xlsx)?",
        parent=root,
    )
    pkrms_path = None
    if use_pkrms:
        use_default = False
        if os.path.exists(DEFAULT_PKRMS_PATH):
            use_default = messagebox.askyesno(
                "Data PKRMS",
                f"Gunakan file PKRMS default ini?\n\n{DEFAULT_PKRMS_PATH}",
                parent=root,
            )
        if use_default:
            pkrms_path = DEFAULT_PKRMS_PATH
        else:
            pkrms_path = filedialog.askopenfilename(
                parent=root,
                title="Pilih file Excel PKRMS (INPUT_PKRMS_JEMBATAN.xlsx)",
                filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            )

    default_name = f"Processed-{os.path.basename(in_path)}"
    out_path = filedialog.asksaveasfilename(
        parent=root,
        title="Simpan KMZ hasil proses sebagai",
        defaultextension=".kmz",
        initialfile=default_name,
        filetypes=[("KMZ files", "*.kmz"), ("All files", "*.*")],
    )
    root.destroy()

    if not out_path:
        return in_path, pkrms_path, None

    return in_path, pkrms_path, out_path


def main():
    in_path, pkrms_path, out_path = select_files()
    if not in_path or not out_path:
        print("Dibatalkan oleh pengguna.")
        return

    try:
        process_kmz(in_path, out_path, pkrms_path)
    except Exception as e:
        print(f"[ERROR] {e}")
        try:
            m_root = tk.Tk()
            m_root.withdraw()
            messagebox.showerror("Gagal memproses KMZ", str(e))
            m_root.destroy()
        except Exception:
            pass
        return

    try:
        m_root = tk.Tk()
        m_root.withdraw()
        messagebox.showinfo("Selesai", f"File berhasil diproses:\n{out_path}")
        m_root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    main()