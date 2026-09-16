"""
Convert SIPDJDC master-format Excel file into KONDISI P.31 format,
splitting the output into one file per road (NAMA RUAS).

INPUT FORMAT (e.g. SIPDJDC_15_06.xlsx, sheet "Master"):
    Header rows 1-6, data starts row 7.
    Columns (A..O):
      A  NOMOR RUAS
      B  NAMA RUAS
      C  STA Awal        (e.g. "0+000", "1+100")
      D  STA Akhir
      E  PANJANG (M)
      F  BAIK            (meters in good condition)
      G  SEDANG          (meters in fair condition)
      H  RUSAK RINGAN    (meters lightly damaged)
      I  RUSAK BERAT     (meters heavily damaged)
      J  MANTAP
      K  TIDAK MANTAP
      L  JENIS PENANGANAN
      M  A/B/K/T code    (A=ASPAL, B=BETON, K=KERIKIL, T=TANAH)
      N  LEBAR (M)
      O  TAHUN SURVEI

OUTPUT FORMAT (one .xlsx per road, named after the road):
    STA_FROM | STA_TO | PAVE_TYPE | CONDITION

Usage:
    Just run the script - it will open dialogs asking you to:
      1) pick the input .xlsx file
      2) pick a folder to save the converted road files into

    python convert_sipdjdc.py
"""

import os
import re
import sys

import openpyxl
from openpyxl import Workbook
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

PAVE_TYPE_MAP = {
    "A": "ASPAL",
    "B": "BETON",
    "K": "KERIKIL",
    "T": "TANAH",
}


def sta_to_meters(sta_value):
    """Convert STA notation like '1+100' (or a plain number) to meters (int)."""
    if sta_value is None:
        return None
    if isinstance(sta_value, (int, float)):
        return int(sta_value)
    s = str(sta_value).strip()
    if "+" in s:
        km_str, m_str = s.split("+", 1)
        km = int(km_str) if km_str.strip() != "" else 0
        m = int(m_str)
        return km * 1000 + m
    try:
        return int(float(s))
    except ValueError:
        return None


def determine_condition(baik, sedang, rusak_ringan, rusak_berat):
    """Pick whichever condition column holds the (non-zero / max) value."""
    values = {
        "BAIK": baik or 0,
        "SEDANG": sedang or 0,
        "RUSAK RINGAN": rusak_ringan or 0,
        "RUSAK BERAT": rusak_berat or 0,
    }
    return max(values, key=values.get)


def sanitize_filename(name):
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', "-", name)
    return name


def convert(input_file, sheet_name=None, output_dir="output", header_row=6):
    """
    header_row: number of header rows to skip (data starts at header_row + 1,
    1-indexed). For the SIPDJDC layout, data starts at Excel row 7, so
    header_row=6.
    """
    wb = openpyxl.load_workbook(input_file, data_only=True)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active

    os.makedirs(output_dir, exist_ok=True)

    roads = {}  # (nomor_ruas, nama_ruas) -> list of (sta_from, sta_to, pave_type, condition)

    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if row is None or len(row) < 13 or row[1] is None:
            continue  # skip blank / incomplete rows

        nomor_ruas = str(row[0]).strip() if row[0] is not None else ""
        nama_ruas = str(row[1]).strip()
        if not nama_ruas:
            continue

        sta_awal = row[2]
        sta_akhir = row[3]
        baik = row[5]
        sedang = row[6]
        rusak_ringan = row[7]
        rusak_berat = row[8]
        pave_code = row[12]

        sta_from = sta_to_meters(sta_awal)
        sta_to = sta_to_meters(sta_akhir)
        condition = determine_condition(baik, sedang, rusak_ringan, rusak_berat)
        pave_type = PAVE_TYPE_MAP.get(str(pave_code).strip().upper(), pave_code) if pave_code else ""

        key = (nomor_ruas, nama_ruas)
        roads.setdefault(key, []).append((sta_from, sta_to, pave_type, condition))

    written_files = []
    for (nomor_ruas, nama_ruas), rows in roads.items():
        out_wb = Workbook()
        out_ws = out_wb.active
        out_ws.title = "Sheet1"
        out_ws.append(["STA_FROM", "STA_TO", "PAVE_TYPE", "CONDITION"])
        for r in rows:
            out_ws.append(list(r))

        if nomor_ruas:
            base_name = f"{nomor_ruas} {nama_ruas}"
        else:
            base_name = nama_ruas
        filename = sanitize_filename(base_name) + ".xlsx"
        filepath = os.path.join(output_dir, filename)
        out_wb.save(filepath)
        written_files.append(filepath)
        print(f"Saved: {filepath}  ({len(rows)} segments)")

    print(f"\nDone. {len(written_files)} road file(s) written to '{output_dir}/'.")
    return written_files


def main():
    root = tk.Tk()
    root.withdraw()  # hide the main tkinter window, we only want dialogs

    # 1) Pick input file
    input_file = filedialog.askopenfilename(
        title="Select the SIPDJDC master Excel file",
        filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")],
    )
    if not input_file:
        messagebox.showinfo("Cancelled", "No input file selected. Exiting.")
        sys.exit(0)

    # 2) Ask for sheet name (defaults to "Master")
    sheet_name = simpledialog.askstring(
        "Sheet name",
        "Sheet name to read:",
        initialvalue="Master",
    )
    if sheet_name is not None:
        sheet_name = sheet_name.strip() or "Master"
    else:
        sheet_name = "Master"

    # 3) Pick output folder
    output_dir = filedialog.askdirectory(
        title="Select a folder to save the converted road files into"
    )
    if not output_dir:
        messagebox.showinfo("Cancelled", "No output folder selected. Exiting.")
        sys.exit(0)

    try:
        written_files = convert(input_file, sheet_name=sheet_name, output_dir=output_dir, header_row=6)
    except Exception as e:
        messagebox.showerror("Error", f"Conversion failed:\n{e}")
        sys.exit(1)

    messagebox.showinfo(
        "Done",
        f"Conversion complete.\n\n{len(written_files)} road file(s) saved to:\n{output_dir}",
    )


if __name__ == "__main__":
    main()