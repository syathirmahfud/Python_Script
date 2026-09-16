#!/usr/bin/env python3
import sys
import os
import re
import zipfile
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET

# --- KML Namespace ---
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)
def k(tag): return f"{{{KML_NS}}}{tag}"

# --- Bridge Info Table Fields ---
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

# ==========================================================
# ===============  UTILITY FUNCTIONS  =======================
# ==========================================================
def split_name(name_text: str):
    """Split <name> content into (No., Name)."""
    if not name_text:
        return "-", "-"
    parts = name_text.strip().split(" ", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "-")

def build_table_html(no_jbt, nama_jbt, lon, lat):
    """Build the standardized HTML info table."""
    rows = []
    for label in TABLE_FIELDS:
        if label == "No. Jembatan":
            val = no_jbt
        elif label == "Nama Jembatan":
            val = nama_jbt
        elif label == "Longitude":
            val = lon or "-"
        elif label == "Latitude":
            val = lat or "-"
        elif label == "Kecamatan":
            val = "-"
        else:
            val = "-"
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
    """Ensure <Snippet maxLines="0"> exists."""
    sn = pm.find(k("Snippet"))
    if sn is None:
        sn = ET.Element(k("Snippet"))
        sn.set("maxLines", "0")
        pm.insert(1, sn)
    else:
        sn.set("maxLines", "0")

def clean_namespaces(xml_text):
    """Remove unknown prefixes (gx:, ns1:, atom:) and invalid xmlns attributes."""
    xml_text = re.sub(r'\s+xmlns:[^=]+="[^"]+"', '', xml_text)
    xml_text = re.sub(r'<(/?)([A-Za-z0-9_]+):', r'<\1', xml_text)
    return xml_text

# ==========================================================
# ===============  CORE PROCESSING  =========================
# ==========================================================
def process_kml_text(xml_text):
    """Main KML processor — safe, idempotent."""
    xml_text = clean_namespaces(xml_text)

    # Detect already processed file early
    if "<Snippet maxLines=\"0\"" in xml_text and "<description><![CDATA[" in xml_text:
        print("⏩ Entire KMZ already processed — skipping reprocessing.")
        return xml_text

    root = ET.fromstring(xml_text)
    token_map = {}
    skipped, appended, added = 0, 0, 0

    for pm in root.iterfind(".//" + k("Placemark")):
        try:
            name_el = pm.find(k("name"))
            name_text = (name_el.text or "-").strip()
            no_jbt, nama_jbt = split_name(name_text)

            coord_el = pm.find(".//" + k("coordinates"))
            lon, lat = ("-", "-")
            if coord_el is not None and coord_el.text:
                coords = coord_el.text.strip().split(",")
                if len(coords) >= 2:
                    lon, lat = coords[:2]

            desc_el = pm.find(k("description"))
            if desc_el is not None and desc_el.text:
                desc_text = desc_el.text

                if "&lt;img" in desc_text or "&lt;table" in desc_text:
                    skipped += 1
                    continue
                if "<table" in desc_text:
                    skipped += 1
                    continue
                if "<img" in desc_text and "<table" not in desc_text:
                    new_table = build_table_html(no_jbt, nama_jbt, lon, lat)
                    desc_el.text = desc_text.rstrip() + "\n" + new_table
                    appended += 1
                    continue

            # Build new description if missing
            photos_raw = ""
            for sd in pm.findall(".//" + k("SimpleData")):
                if sd.get("name") == "pdfmaps_photos":
                    photos_raw = sd.text or ""
                    break

            ensure_snippet(pm)

            photo_section = ""
            if photos_raw:
                photo_section = (
                    "        <br><b>Foto:</b><br>\n"
                    + photos_raw.strip()
                    + "\n        <hr style=\"border:2px solid black;\">\n"
                )

            table_html = build_table_html(no_jbt, nama_jbt, lon, lat)
            cdata_body = "\n" + photo_section + table_html + "    "

            token = f"__CDATA_{uuid.uuid4().hex}__"
            token_map[token] = cdata_body

            if desc_el is None:
                desc_el = ET.SubElement(pm, k("description"))
            desc_el.text = token
            added += 1

        except Exception as e:
            print(f"❌ Error processing {no_jbt}: {e}")
            continue

    raw_xml = ET.tostring(root, encoding="utf-8").decode("utf-8")
    for token, body in token_map.items():
        raw_xml = raw_xml.replace(
            f"<description>{token}</description>",
            f"<description><![CDATA[{body}]]></description>"
        )

    if not raw_xml.startswith("<?xml"):
        raw_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw_xml

    print(f"⏩ Skipped {skipped} | ➕ Appended {appended} | 🆕 Added {added}")
    return raw_xml

# ==========================================================
# ===============  KMZ HANDLER  =============================
# ==========================================================
def process_kmz(in_path, out_path=None):
    if not os.path.exists(in_path):
        print("❌ Input file not found.")
        return

    temp_dir = tempfile.mkdtemp(prefix="kmz_")
    try:
        print(f"📁 Extracting: {in_path}")
        with zipfile.ZipFile(in_path, "r") as zf:
            zf.extractall(temp_dir)

        doc_path = os.path.join(temp_dir, "doc.kml")
        if not os.path.exists(doc_path):
            for root, _, files in os.walk(temp_dir):
                for f in files:
                    if f.lower().endswith(".kml"):
                        doc_path = os.path.join(root, f)
                        break
                if os.path.exists(doc_path): break

        with open(doc_path, "r", encoding="utf-8") as f:
            xml_text = f.read()

        processed = process_kml_text(xml_text)

        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(processed)

        if not out_path:
            base = os.path.basename(in_path)
            out_path = f"Processed-{base}"

        print("📦 Repacking KMZ...")
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as new_zip:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    fp = os.path.join(root, file)
                    arc = os.path.relpath(fp, temp_dir)
                    new_zip.write(fp, arcname=arc)

        print("🧹 Cleaning up temp files...")
        print(f"✅ Done! Output KMZ: {out_path}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ==========================================================
# ===============  ENTRY POINT  =============================
# ==========================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: python format_bridge_kmz_tables.py input.kmz [output.kmz]")
        sys.exit(1)
    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    process_kmz(in_path, out_path)

if __name__ == "__main__":
    main()
