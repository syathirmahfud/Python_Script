#!/usr/bin/env python3
"""
Konversi KMZ yang SUDAH DIPROSES (hasil dari enrich_bridge_kmz_from_pkrms_excel.py -
lengkap dengan popup HTML + foto) menjadi KMZ "siap-SHP": versi terpisah yang
bisa dikonversi ke shapefile di Global Mapper / ArcGIS tanpa error attribute
table, karena:

  - Setiap nilai tabel (No. Jembatan, STA, Kondisi, dst.) dipecah jadi
    <SimpleData> tersendiri di <ExtendedData>/<SchemaData>, dengan nama field
    pendek (maks. 10 karakter - batas nama kolom .dbf shapefile), BUKAN
    digabung jadi satu blok HTML raksasa di <description> (blok HTML itu bisa
    2000+ karakter, jauh melebihi batas 254 karakter per kolom .dbf).
  - <description> (popup HTML) dan folder foto ("files/") DIHAPUS dari hasil,
    karena tidak berguna untuk shapefile dan hanya memperbesar ukuran file.

PENTING: script ini TIDAK mengubah enrich_bridge_kmz_from_pkrms_excel.py sama
sekali. Ini adalah tool KONVERSI TAMBAHAN yang jalan setelahnya:

    KMZ mentah --[enrich_bridge_kmz_from_pkrms_excel.py]--> KMZ (popup+foto, untuk Google Earth)
                                                            |
                                                            v
                                          [convert_bridge_kmz_to_shapefile_ready.py] (script ini)
                                                            |
                                                            v
                                          KMZ siap-SHP (tanpa foto, field pendek)

Dialog tkinter untuk memilih: KMZ yang sudah diproses (input), lokasi simpan
KMZ siap-SHP (output).
"""

import os
import re
import zipfile
import shutil
import tempfile
import xml.etree.ElementTree as ET

import tkinter as tk
from tkinter import filedialog, messagebox


# --- KML Namespace ---
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def k(tag):
    return f"{{{KML_NS}}}{tag}"


# Must match TABLE_FIELDS in enrich_bridge_kmz_from_pkrms_excel.py exactly (same
# order, same labels) - these are the labels that appear as <b>LABEL</b> in
# the HTML table we're parsing back out.
TABLE_FIELDS = [
    "No. Jembatan", "Nama Jembatan", "Longitude", "Latitude", "Kecamatan",
    "STA(m)", "Panjang(m)", "Lebar(m)", "Jumlah Bentang",
    "Bangunan Atas - Kode", "Bangunan Atas - Tipe", "Bangunan Atas - Kondisi",
    "Bangunan Bawah - Tipe", "Bangunan Bawah - Bahan", "Bangunan Bawah - Kondisi",
    "Fondasi - Tipe", "Fondasi - Bahan", "Fondasi - Kondisi",
    "Permukaan Jembatan - Tipe", "Permukaan Jembatan - Kondisi",
    "Tahun Konstruksi", "Kondisi Jembatan (Keseluruhan)", "Tahun Survey",
]

# Shapefile (.dbf) column names are capped at 10 characters.
FIELD_SHORT_NAMES = {
    "No. Jembatan": "NoJembatan",
    "Nama Jembatan": "NamaJemb",
    "Longitude": "Longitude",
    "Latitude": "Latitude",
    "Kecamatan": "Kecamatan",
    "STA(m)": "STA_m",
    "Panjang(m)": "Panjang_m",
    "Lebar(m)": "Lebar_m",
    "Jumlah Bentang": "JmlBentang",
    "Bangunan Atas - Kode": "BA_Kode",
    "Bangunan Atas - Tipe": "BA_Tipe",
    "Bangunan Atas - Kondisi": "BA_Kondisi",
    "Bangunan Bawah - Tipe": "BB_Tipe",
    "Bangunan Bawah - Bahan": "BB_Bahan",
    "Bangunan Bawah - Kondisi": "BB_Kondisi",
    "Fondasi - Tipe": "Fond_Tipe",
    "Fondasi - Bahan": "Fond_Bahan",
    "Fondasi - Kondisi": "Fond_Kond",
    "Permukaan Jembatan - Tipe": "PJ_Tipe",
    "Permukaan Jembatan - Kondisi": "PJ_Kondisi",
    "Tahun Konstruksi": "ThnKonstr",
    "Kondisi Jembatan (Keseluruhan)": "KondisiJbt",
    "Tahun Survey": "ThnSurvey",
}

BRIDGE_SCHEMA_ID = "BridgeAttrs"

# Matches rows built by enrich_bridge_kmz_from_pkrms_excel.py's build_table_html():
#   <tr><td><b>LABEL</b></td><td>VALUE</td></tr>
HTML_ROW_PATTERN = re.compile(r"<tr><td><b>(.*?)</b></td><td>(.*?)</td></tr>", re.S)

# Photo folder Avenza embeds image files under (as seen in <img src="files/...">).
PHOTO_FOLDER_NAME = "files"


def parse_html_table(description_text):
    """Extract {label: value} from the HTML table already baked into
    <description> by enrich_bridge_kmz_from_pkrms_excel.py."""
    if not description_text:
        return {}
    rows = HTML_ROW_PATTERN.findall(description_text)
    return {label.strip(): value.strip() for label, value in rows}


def build_bridge_schema_element():
    """<Schema> declaring every short field name + its human-readable
    displayName, inserted once into <Document>. No photo fields this time -
    photos are dropped entirely for the shapefile-ready output."""
    schema = ET.Element(k("Schema"))
    schema.set("name", BRIDGE_SCHEMA_ID)
    schema.set("id", BRIDGE_SCHEMA_ID)
    for label in TABLE_FIELDS:
        sf = ET.SubElement(schema, k("SimpleField"))
        sf.set("type", "string")
        sf.set("name", FIELD_SHORT_NAMES[label])
        disp = ET.SubElement(sf, k("displayName"))
        disp.text = label
    return schema


def clean_namespaces(xml_text):
    """Same namespace-prefix cleanup as enrich_bridge_kmz_from_pkrms_excel.py, in
    case this converter is ever pointed at a KMZ that still has stray
    prefixed elements/attributes."""
    xml_text = re.sub(r'\s+xmlns:[^=]+="[^"]+"', '', xml_text)
    xml_text = re.sub(r'<(/?)([A-Za-z0-9_]+):', r'<\1', xml_text)
    xml_text = re.sub(r'(?<=[\s])([A-Za-z0-9_]+):([A-Za-z0-9_]+)=', r'\2=', xml_text)
    return xml_text


def convert_kml_text(xml_text):
    xml_text = clean_namespaces(xml_text)
    root = ET.fromstring(xml_text)

    doc_el = root.find(k("Document"))

    # Drop any existing <Schema> declarations (Avenza's abandoned one, or a
    # BridgeAttrs one from a previous run of this converter) and re-add ours.
    if doc_el is not None:
        for old_schema in list(doc_el.findall(k("Schema"))):
            doc_el.remove(old_schema)
        doc_el.append(build_bridge_schema_element())

        # Document-level ExtendedData (Avenza's <picklist> metadata), if any.
        doc_ext_data = doc_el.find(k("ExtendedData"))
        if doc_ext_data is not None:
            doc_el.remove(doc_ext_data)

    converted, skipped, no_table = 0, 0, 0

    for pm in root.iterfind(".//" + k("Placemark")):
        name_el = pm.find(k("name"))
        name_text = (name_el.text or "").strip() if name_el is not None else "?"

        # Idempotency: already converted by this script -> skip.
        already_converted = any(
            sd.get("schemaUrl") in ("#" + BRIDGE_SCHEMA_ID, BRIDGE_SCHEMA_ID)
            for sd in pm.findall(".//" + k("SchemaData"))
        )
        if already_converted:
            skipped += 1
            continue

        desc_el = pm.find(k("description"))
        values = parse_html_table(desc_el.text if desc_el is not None else None)
        if not values:
            no_table += 1

        # Remove all existing ExtendedData (Avenza's abandoned schema and/or
        # anything else) and the HTML <description> - neither is needed.
        for ext_data in list(pm.findall(k("ExtendedData"))):
            pm.remove(ext_data)
        if desc_el is not None:
            pm.remove(desc_el)

        new_ext_data = ET.SubElement(pm, k("ExtendedData"))
        new_schema_data = ET.SubElement(new_ext_data, k("SchemaData"))
        new_schema_data.set("schemaUrl", "#" + BRIDGE_SCHEMA_ID)
        for label in TABLE_FIELDS:
            sd_el = ET.SubElement(new_schema_data, k("SimpleData"))
            sd_el.set("name", FIELD_SHORT_NAMES[label])
            sd_el.text = values.get(label, "-")

        converted += 1

    raw_xml = ET.tostring(root, encoding="utf-8").decode("utf-8")
    if not raw_xml.startswith("<?xml"):
        raw_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw_xml

    print(f"Placemark dikonversi: {converted} | dilewati (sudah dikonversi): {skipped}")
    if no_table:
        print(f"[!] {no_table} placemark tidak punya tabel HTML untuk dibaca "
              f"(field diisi '-' semua untuk placemark ini).")

    return raw_xml


# ==========================================================
# ===============  KMZ HANDLER  =============================
# ==========================================================
def convert_kmz(in_path, out_path):
    if not os.path.exists(in_path):
        raise FileNotFoundError(f"File input tidak ditemukan: {in_path}")

    temp_dir = tempfile.mkdtemp(prefix="kmz_shp_")
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

        converted = convert_kml_text(xml_text)

        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(converted)

        print("Mengemas ulang KMZ (folder foto dikecualikan)...")
        skipped_photo_count = 0
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as new_zip:
            for r, _, files in os.walk(temp_dir):
                for file in files:
                    fp = os.path.join(r, file)
                    arc = os.path.relpath(fp, temp_dir)
                    # Skip the photo folder entirely (e.g. "files/xxx.jpg")
                    first_part = arc.replace("\\", "/").split("/")[0]
                    if first_part.lower() == PHOTO_FOLDER_NAME.lower():
                        skipped_photo_count += 1
                        continue
                    new_zip.write(fp, arcname=arc)

        if skipped_photo_count:
            print(f"Foto dikecualikan dari KMZ hasil: {skipped_photo_count} file "
                  f"(folder '{PHOTO_FOLDER_NAME}/')")

        in_size = os.path.getsize(in_path)
        out_size = os.path.getsize(out_path)
        print(f"Ukuran file: {in_size/1024:.0f} KB -> {out_size/1024:.0f} KB")
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
        title="Pilih KMZ yang SUDAH DIPROSES (hasil enrich_bridge_kmz_from_pkrms_excel.py)",
        filetypes=[("KMZ files", "*.kmz"), ("All files", "*.*")],
    )
    if not in_path:
        root.destroy()
        return None, None

    default_name = f"SHP_READY-{os.path.basename(in_path)}"
    out_path = filedialog.asksaveasfilename(
        parent=root,
        title="Simpan KMZ siap-SHP sebagai",
        defaultextension=".kmz",
        initialfile=default_name,
        filetypes=[("KMZ files", "*.kmz"), ("All files", "*.*")],
    )
    root.destroy()

    if not out_path:
        return in_path, None
    return in_path, out_path


def main():
    in_path, out_path = select_files()
    if not in_path or not out_path:
        print("Dibatalkan oleh pengguna.")
        return

    try:
        convert_kmz(in_path, out_path)
    except Exception as e:
        print(f"[ERROR] {e}")
        try:
            m_root = tk.Tk()
            m_root.withdraw()
            messagebox.showerror("Gagal konversi KMZ", str(e))
            m_root.destroy()
        except Exception:
            pass
        return

    try:
        m_root = tk.Tk()
        m_root.withdraw()
        messagebox.showinfo("Selesai", f"KMZ siap-SHP disimpan:\n{out_path}")
        m_root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    main()