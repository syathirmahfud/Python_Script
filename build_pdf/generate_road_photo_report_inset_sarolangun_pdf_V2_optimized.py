import json
import math
import os
import re
import subprocess
import sys
import tempfile
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, simpledialog, ttk, messagebox

import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# =========================
# CONSTANTS (LOCKED LAYOUT)
# =========================
# These values are intentionally unchanged from the original script.
PAGE_W, PAGE_H = landscape(A4)

MARGIN_L = 2.75 * cm
MARGIN_R = 2.75 * cm
MARGIN_T = 1.5 * cm
MARGIN_B = 1.8 * cm

LOGO_SIZE = 2.0 * cm  # 2x2 cm square
HEADER_HEIGHT = 2.75 * cm

PHOTO_SCALE = 0.875  # scale down photo (LOCKED)

GAP_X = 0.8 * cm
GAP_Y = 0.3 * cm

FONT_TITLE = ("Helvetica-Bold", 14)
FONT_SUB = ("Helvetica", 9)
FONT_META = ("Helvetica", 9)
FONT_STA = ("Courier-Bold", 5.75)

# Keep source JPEGs untouched so the generated PDF has the same visual quality.
# The main speed optimization is batching EXIF extraction instead of launching
# ExifTool once for every photo.
DEBUG = False

STA_RE = re.compile(r"STA[_\s]?(\d+)\+(\d+)", re.IGNORECASE)


def resource_path(rel_path):
    """Resolve resources without depending on where the script is stored.

    Search order:
    1. PyInstaller bundle directory (when packaged)
    2. Current working directory (e.g. D:/DEV/assets)
    3. Script directory
    4. Script parent directory
    5. Script grandparent directory (e.g. D:/DEV for D:/DEV/Python/build_pdf)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    bases = []
    if hasattr(sys, "_MEIPASS"):
        bases.append(sys._MEIPASS)

    bases.extend([
        os.getcwd(),
        script_dir,
        os.path.dirname(script_dir),
        os.path.dirname(os.path.dirname(script_dir)),
    ])

    # Avoid checking duplicate locations while preserving search order.
    seen = set()
    for base_dir in bases:
        candidate = os.path.abspath(os.path.join(base_dir, rel_path))
        key = os.path.normcase(candidate)
        if key in seen:
            continue
        seen.add(key)
        if os.path.exists(candidate):
            return candidate

    # Return the most natural unresolved path for useful diagnostics.
    return os.path.abspath(os.path.join(os.getcwd(), rel_path))


def get_exiftool_path():
    """Prefer a bundled ExifTool, then fall back to the user's existing path."""
    candidates = [
        resource_path("exiftool.exe"),
        r"D:\DEV\tools\exiftool.exe",
    ]

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


# =========================
# DATA MODEL / HELPERS
# =========================
@dataclass(frozen=True)
class PhotoRecord:
    path: str
    inset_path: str | None
    sta: str
    sta_m: int
    pavement: str
    condition: str
    lat: float | None
    lon: float | None
    width: float
    height: float
    inset_width: float | None
    inset_height: float | None


def parse_sta_info(filename):
    """Return display STA and numeric stationing from a filename."""
    match = STA_RE.search(filename)
    if not match:
        raise ValueError(f"Invalid STA filename: {filename}")

    km = int(match.group(1))
    mtr = int(match.group(2))
    return f"STA {match.group(1)}+{match.group(2)}", km * 1000 + mtr


def parse_sta(filename):
    sta, _ = parse_sta_info(filename)
    return sta


def sta_to_meters(filename):
    match = STA_RE.search(filename)
    if not match:
        return float("inf")
    return int(match.group(1)) * 1000 + int(match.group(2))


def load_sections(excel_file):
    """Load only the columns required for photo metadata lookup."""
    df = pd.read_excel(
        excel_file,
        usecols=["STA_FROM", "PAVE_TYPE", "CONDITION"],
    )

    lookup = {}
    for row in df.itertuples(index=False):
        sta_from = int(row.STA_FROM)
        lookup[sta_from] = (
            str(row.PAVE_TYPE).strip(),
            str(row.CONDITION).strip(),
        )

    if DEBUG:
        print("LOOKUP SIZE =", len(lookup))

    return lookup


def _norm_path(path):
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def read_gps_batch(image_paths):
    """
    Read GPS from all JPEGs with ONE ExifTool process.

    This replaces the original one-process-per-photo implementation, which is
    the largest avoidable runtime cost on large road-survey folders.
    """
    gps = {_norm_path(path): (None, None) for path in image_paths}

    exiftool = get_exiftool_path()
    if not exiftool:
        print("WARNING: ExifTool not found. GPS fields will be shown as '-'.")
        return gps

    argfile_path = None
    try:
        # -@ avoids the Windows command-line length limit even for large surveys.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            suffix=".txt",
            delete=False,
        ) as argfile:
            argfile_path = argfile.name
            for path in image_paths:
                argfile.write(os.path.abspath(path) + "\n")

        command = [
            exiftool,
            "-j",
            "-n",
            "-charset",
            "filename=UTF8",
            "-GPSLatitude",
            "-GPSLongitude",
            "-@",
            argfile_path,
        ]

        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=creationflags,
        )

        if result.returncode not in (0, 1):
            # ExifTool may return 1 for warnings while still producing valid JSON.
            print(
                f"WARNING: ExifTool returned code {result.returncode}. "
                "Missing GPS values will be shown as '-'."
            )

        if not result.stdout.strip():
            return gps

        records = json.loads(result.stdout)
        for record in records:
            source = record.get("SourceFile")
            if not source:
                continue

            key = _norm_path(source)
            lat = record.get("GPSLatitude")
            lon = record.get("GPSLongitude")

            try:
                lat = float(lat) if lat is not None else None
            except (TypeError, ValueError):
                lat = None

            try:
                lon = float(lon) if lon is not None else None
            except (TypeError, ValueError):
                lon = None

            gps[key] = (lat, lon)

    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: Could not batch-read GPS metadata: {exc}")
    finally:
        if argfile_path:
            try:
                os.remove(argfile_path)
            except OSError:
                pass

    return gps


def collect_images(screenshot_dir):
    """Find and station-sort the forward-facing road photos."""
    images = []

    with os.scandir(screenshot_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue

            name_lower = entry.name.lower()
            if not name_lower.endswith(".jpg"):
                continue
            if "_nr" in name_lower:
                continue

            images.append(entry.path)

    return sorted(images, key=lambda p: sta_to_meters(os.path.basename(p)))


def build_photo_records(images, sections):
    """Precompute stationing, lookup data, GPS and image geometry once."""
    # Read GPS for both main and inset photos in one ExifTool invocation.
    gps_paths = list(images)
    inset_by_main = {}

    for img_path in images:
        base, ext = os.path.splitext(img_path)
        candidate = f"{base}_NR{ext}"
        inset_path = candidate if os.path.exists(candidate) else None
        inset_by_main[img_path] = inset_path
        if inset_path:
            gps_paths.append(inset_path)

    gps_lookup = read_gps_batch(gps_paths)
    records = []

    for img_path in images:
        filename = os.path.basename(img_path)
        sta, sta_m = parse_sta_info(filename)
        pavement, condition = sections.get(sta_m, ("-", "-"))
        lat, lon = gps_lookup.get(_norm_path(img_path), (None, None))

        img = ImageReader(img_path)
        iw, ih = img.getSize()

        inset_path = inset_by_main[img_path]
        inset_width = None
        inset_height = None
        if inset_path:
            inset_img = ImageReader(inset_path)
            inset_width, inset_height = inset_img.getSize()

        if DEBUG:
            print(filename, "STA=", sta_m, "LOOKUP=", sections.get(sta_m))

        records.append(
            PhotoRecord(
                path=img_path,
                inset_path=inset_path,
                sta=sta,
                sta_m=sta_m,
                pavement=pavement,
                condition=condition,
                lat=lat,
                lon=lon,
                width=iw,
                height=ih,
                inset_width=inset_width,
                inset_height=inset_height,
            )
        )

    return records


# =========================
# UI INPUT
# =========================
def ask_inputs():
    root = tk.Tk()
    root.withdraw()

    screenshot_dir = filedialog.askdirectory(title="Select Screenshot Folder")
    if not screenshot_dir:
        raise SystemExit("No screenshot folder selected")

    excel_file = filedialog.askopenfilename(
        title="Select Excel File",
        filetypes=[("Excel Files", "*.xlsx *.xls")],
    )
    if not excel_file:
        raise SystemExit("No Excel file selected")

    save_pdf = filedialog.asksaveasfilename(
        title="Save PDF As",
        defaultextension=".pdf",
        filetypes=[("PDF", "*.pdf")],
    )
    if not save_pdf:
        raise SystemExit("No output PDF selected")

    ruas_number = simpledialog.askstring("Input", "Ruas Number:")
    ruas_name = simpledialog.askstring("Input", "Ruas Name:")
    ruas_length = simpledialog.askstring("Input", "Ruas Length (km):")

    if not all([ruas_number, ruas_name, ruas_length]):
        raise SystemExit("Incomplete metadata")

    return (
        screenshot_dir,
        save_pdf,
        excel_file,
        ruas_number,
        ruas_name,
        ruas_length,
    )


# =========================
# HEADER DRAW
# =========================
def draw_header(c, logo_left, logo_right, ruas_number, ruas_name, ruas_length):
    y_top = PAGE_H - MARGIN_T

    # Logos
    c.drawImage(
        logo_left,
        MARGIN_L,
        y_top - LOGO_SIZE,
        LOGO_SIZE,
        LOGO_SIZE,
        preserveAspectRatio=True,
        anchor="nw",
        mask="auto",
    )

    c.drawImage(
        logo_right,
        PAGE_W - MARGIN_R - LOGO_SIZE,
        y_top - LOGO_SIZE,
        LOGO_SIZE,
        LOGO_SIZE,
        preserveAspectRatio=True,
        anchor="nw",
        mask="auto",
    )

    # Header text (CENTERED)
    c.setFont(*FONT_TITLE)
    c.drawCentredString(
        PAGE_W / 2,
        y_top - 0.6 * cm,
        "Dinas Pekerjaan Umum dan Perumahan Rakyat Kabupaten Sarolangun",
    )

    c.setFont(*FONT_SUB)
    c.drawCentredString(
        PAGE_W / 2,
        y_top - 1.2 * cm,
        "Dokumentasi Survey UKL dan UPL Kabupaten Sarolangun 2025",
    )

    c.drawCentredString(
        PAGE_W / 2,
        y_top - 1.7 * cm,
        "Jl. H.M. Kamil No.18, Sarolangun, Provinsi Jambi",
    )

    # Line under header
    line_y = y_top - HEADER_HEIGHT
    c.setLineWidth(2.8)
    c.line(MARGIN_L, line_y, PAGE_W - MARGIN_R, line_y)

    # Metadata BELOW line (LOCKED)
    meta_y = line_y - 0.6 * cm
    c.setFont(*FONT_META)
    c.drawString(MARGIN_L, meta_y, f"NOMOR RUAS : {ruas_number}")
    c.drawCentredString(PAGE_W / 2, meta_y, f"NAMA RUAS : {ruas_name}")
    c.drawRightString(
        PAGE_W - MARGIN_R,
        meta_y,
        f"PANJANG RUAS : {ruas_length} km",
    )

    return meta_y - 0.8 * cm


# =========================
# PHOTO GRID
# =========================
def draw_photos(c, photos, start_y):
    usable_w = PAGE_W - MARGIN_L - MARGIN_R
    cell_w = (usable_w - GAP_X) / 2

    y = start_y
    idx = 0

    for _row in range(2):
        x_left = MARGIN_L
        x_right = MARGIN_L + cell_w + GAP_X
        row_heights = []

        for col in range(2):
            if idx >= len(photos):
                break

            photo = photos[idx]

            draw_w = cell_w * PHOTO_SCALE
            draw_h = draw_w * photo.height / photo.width
            row_heights.append(draw_h)

            if col == 0:
                img_x = x_left
            else:
                img_x = x_right + (cell_w - draw_w)

            img_y = y - draw_h

            # Passing the filename directly avoids keeping every image decoded in
            # memory while preserving the exact same rendered dimensions.
            c.drawImage(
                photo.path,
                img_x,
                img_y,
                draw_w,
                draw_h,
                preserveAspectRatio=True,
                anchor="sw",
            )

            if photo.inset_path is not None:
                inset_w = draw_w * 0.25
                inset_h = inset_w * photo.inset_height / photo.inset_width

                c.drawImage(
                    photo.inset_path,
                    img_x + 5,
                    img_y + draw_h - inset_h - 5,
                    inset_w,
                    inset_h,
                    preserveAspectRatio=True,
                    anchor="sw",
                )

            # Metadata under photo (LEFT-ALIGNED WITH IMAGE)
            text_y = img_y - 0.35 * cm
            label_w = 1.4 * cm

            c.setFont(*FONT_STA)

            # STA label
            c.drawString(img_x, text_y, "STA")
            c.drawRightString(img_x + label_w + 1.5 * cm, text_y, ":")

            # STA value
            sta_value = photo.sta.replace("STA_", "").replace("STA ", "")
            c.drawString(img_x + label_w + 1.75 * cm, text_y, sta_value)

            # Condition
            c.drawString(img_x, text_y - 0.2 * cm, "KONDISI")
            c.drawRightString(
                img_x + label_w + 1.5 * cm,
                text_y - 0.2 * cm,
                ":",
            )
            c.drawString(
                img_x + label_w + 1.75 * cm,
                text_y - 0.2 * cm,
                photo.condition,
            )

            # Pavement
            c.drawString(img_x, text_y - 0.4 * cm, "JENIS PERKERASAN")
            c.drawRightString(
                img_x + label_w + 1.5 * cm,
                text_y - 0.4 * cm,
                ":",
            )
            c.drawString(
                img_x + label_w + 1.75 * cm,
                text_y - 0.4 * cm,
                photo.pavement,
            )

            # Missing GPS now renders safely as '-' instead of aborting the PDF.
            lat_text = f"{photo.lat:.6f}" if photo.lat is not None else "-"
            lon_text = f"{photo.lon:.6f}" if photo.lon is not None else "-"

            # Latitude
            c.drawString(img_x, text_y - 0.6 * cm, "LATITUDE")
            c.drawRightString(
                img_x + label_w + 1.5 * cm,
                text_y - 0.6 * cm,
                ":",
            )
            c.drawString(
                img_x + label_w + 1.75 * cm,
                text_y - 0.6 * cm,
                lat_text,
            )

            # Longitude
            c.drawString(img_x, text_y - 0.8 * cm, "LONGITUDE")
            c.drawRightString(
                img_x + label_w + 1.5 * cm,
                text_y - 0.8 * cm,
                ":",
            )
            c.drawString(
                img_x + label_w + 1.75 * cm,
                text_y - 0.8 * cm,
                lon_text,
            )

            idx += 1

        # With the normal same-aspect survey screenshots this is numerically
        # identical to the original. If one image has a different aspect ratio,
        # use the tallest cell so rows cannot overlap.
        if row_heights:
            y -= max(row_heights) + GAP_Y + 1.2 * cm


# =========================
# MAIN
# =========================
def main():
    (
        screenshot_dir,
        save_pdf,
        excel_file,
        ruas_number,
        ruas_name,
        ruas_length,
    ) = ask_inputs()

    sections = load_sections(excel_file)

    logo_left = resource_path(os.path.join("assets", "sarolangun.png"))
    logo_right = resource_path(os.path.join("assets", "logo_pupr.png"))

    if not os.path.exists(logo_left) or not os.path.exists(logo_right):
        messagebox.showerror("Error", "Logo files not found in assets/")
        return

    images = collect_images(screenshot_dir)

    if not images:
        messagebox.showerror("Error", "No JPG images found")
        return

    # Progress window
    prog = tk.Toplevel()
    prog.title("Generating PDF")
    bar = ttk.Progressbar(prog, length=300, mode="determinate")
    bar.pack(padx=20, pady=20)
    label = tk.Label(prog, text="Reading photo metadata...")
    label.pack()
    prog.update()

    try:
        # Precompute all file metadata once before page drawing.
        records = build_photo_records(images, sections)

        c = canvas.Canvas(save_pdf, pagesize=landscape(A4))

        total_pages = math.ceil(len(records) / 4)
        img_idx = 0

        for page in range(total_pages):
            bar["value"] = (page / total_pages) * 100
            label.config(text=f"Page {page + 1} / {total_pages}")
            prog.update()

            start_y = draw_header(
                c,
                logo_left,
                logo_right,
                ruas_number,
                ruas_name,
                ruas_length,
            )

            draw_photos(c, records[img_idx : img_idx + 4], start_y)
            img_idx += 4
            c.showPage()

        c.save()

        bar["value"] = 100
        label.config(text="Done")
        prog.update()

    except Exception as exc:
        try:
            prog.destroy()
        except tk.TclError:
            pass
        messagebox.showerror("Error", f"Failed to generate PDF:\n\n{exc}")
        raise

    prog.destroy()
    messagebox.showinfo("Done", "PDF generated successfully")


if __name__ == "__main__":
    main()
