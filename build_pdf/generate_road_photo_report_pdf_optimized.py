"""
Optimized Road Photo Report PDF Generator

This is a consolidated, optimized version of the road photo report PDF generators.
Key optimizations:
1. Batch ExifTool processing (one call instead of one per image)
2. Pre-computed metadata before PDF generation
3. Proper error handling with informative messages
4. Configurable regional settings via parameters

Usage:
    from generate_road_photo_report_pdf_optimized import generate_pdf
    
    generate_pdf(
        screenshot_dir="/path/to/photos",
        output_pdf="/path/to/output.pdf",
        ruas_number="001",
        ruas_name="Jalan Raya Jambi",
        ruas_length="15.5",
        region="jambi"  # or "sarolangun", "merangin", "tanjab_barat"
    )
"""

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
from typing import Optional, Tuple, Dict, List

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# =========================
# REGIONAL CONFIGURATIONS
# =========================
@dataclass(frozen=True)
class RegionConfig:
    """Regional configuration for header text and logos."""
    name: str
    header_title: str
    header_subtitle: str
    header_address: str
    logo_left: str
    logo_right: str
    font_sta: Tuple[str, float] = ("Helvetica-Bold", 9)


REGION_CONFIGS = {
    "jambi": RegionConfig(
        name="jambi",
        header_title="DINAS PEKERJAAN UMUM DAN PERUMAHAN RAKYAT PROVINSI JAMBI",
        header_subtitle="Dokumentasi Survey PKRMS Jalan Provinsi Jambi",
        header_address="Jl. H. Agus Salim No.02, Paal Lima, Kec. Kota Baru, Kota Jambi, Jambi",
        logo_left="logo_jambi.png",
        logo_right="logo_pupr.png",
    ),
    "sarolangun": RegionConfig(
        name="sarolangun",
        header_title="Dinas Pekerjaan Umum dan Perumahan Rakyat Kabupaten Sarolangun",
        header_subtitle="Dokumentasi Survey UKL dan UPL Kabupaten Sarolangun 2025",
        header_address="Jl. H.M. Kamil No.18, Sarolangun, Provinsi Jambi",
        logo_left="sarolangun.png",
        logo_right="logo_pupr.png",
        font_sta=("Courier-Bold", 5.75),
    ),
    "merangin": RegionConfig(
        name="merangin",
        header_title="Dinas Pekerjaan Umum dan Perumahan Rakyat Kabupaten Merangin",
        header_subtitle="Dokumentasi Survey PKRMS Kabupaten Merangin",
        header_address="Jl. Jend. Sudirman No.1, Bangko, Kabupaten Merangin, Jambi",
        logo_left="merangin.png",
        logo_right="logo_pupr.png",
        font_sta=("Courier-Bold", 5.75),
    ),
    "tanjab_barat": RegionConfig(
        name="tanjab_barat",
        header_title="Dinas Pekerjaan Umum dan Perumahan Rakyat Kabupaten Tanjung Jabung Barat",
        header_subtitle="Dokumentasi Survey PKRMS Kabupaten Tanjung Jabung Barat",
        header_address="Jl. Lintas Sumatera KM 7, Kuala Tungkal, Tanjung Jabung Barat, Jambi",
        logo_left="tanjab_barat.png",
        logo_right="logo_pupr.png",
        font_sta=("Courier-Bold", 5.75),
    ),
}


# =========================
# CONSTANTS (LOCKED LAYOUT)
# =========================
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

DEBUG = False
STA_RE = re.compile(r"STA[_\s]?(\d+)\+(\d+)", re.IGNORECASE)


def resource_path(rel_path: str) -> str:
    """Resolve resources without depending on where the script is stored.

    Search order:
    1. PyInstaller bundle directory (when packaged)
    2. Current working directory
    3. Script directory
    4. Script parent directory
    5. Script grandparent directory
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


def get_exiftool_path() -> Optional[str]:
    """Prefer a bundled ExifTool, then fall back to common paths."""
    candidates = [
        resource_path("exiftool.exe"),
        resource_path("exiftool"),
        r"D:\DEV\tools\exiftool.exe",
        "/usr/local/bin/exiftool",
        "/usr/bin/exiftool",
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
    """Pre-computed photo metadata for efficient PDF generation."""
    path: str
    sta: str
    sta_m: int
    lat: Optional[float]
    lon: Optional[float]
    width: float
    height: float


def parse_sta_info(filename: str) -> Tuple[str, int]:
    """Return display STA and numeric stationing from a filename."""
    match = STA_RE.search(filename)
    if not match:
        raise ValueError(f"Invalid STA filename: {filename}")

    km = int(match.group(1))
    mtr = int(match.group(2))
    return f"STA {match.group(1)}+{match.group(2)}", km * 1000 + mtr


def parse_sta(filename: str) -> str:
    """Extract STA string from filename."""
    sta, _ = parse_sta_info(filename)
    return sta


def sta_to_meters(filename: str) -> int:
    """Convert STA filename to meters for sorting."""
    match = STA_RE.search(filename)
    if not match:
        return float("inf")
    return int(match.group(1)) * 1000 + int(match.group(2))


def _norm_path(path: str) -> str:
    """Normalize path for consistent dictionary lookups."""
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def read_gps_batch(image_paths: List[str]) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """
    Read GPS from all JPEGs with ONE ExifTool process.

    This replaces the original one-process-per-photo implementation, which is
    the largest avoidable runtime cost on large road-survey folders.
    
    Args:
        image_paths: List of image file paths
        
    Returns:
        Dictionary mapping normalized paths to (latitude, longitude) tuples
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


def collect_images(screenshot_dir: str) -> List[str]:
    """Find and station-sort the road photos.
    
    Args:
        screenshot_dir: Directory containing JPG images
        
    Returns:
        Sorted list of image paths
    """
    images = []

    with os.scandir(screenshot_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue

            name_lower = entry.name.lower()
            if not name_lower.endswith(".jpg"):
                continue

            images.append(entry.path)

    return sorted(images, key=lambda p: sta_to_meters(os.path.basename(p)))


def build_photo_records(images: List[str]) -> List[PhotoRecord]:
    """Precompute stationing, GPS and image geometry once.
    
    Args:
        images: List of image paths
        
    Returns:
        List of PhotoRecord objects with pre-computed metadata
    """
    # Read GPS for all photos in one ExifTool invocation.
    gps_lookup = read_gps_batch(images)
    records = []

    for img_path in images:
        filename = os.path.basename(img_path)
        sta, sta_m = parse_sta_info(filename)
        lat, lon = gps_lookup.get(_norm_path(img_path), (None, None))

        img = ImageReader(img_path)
        iw, ih = img.getSize()

        if DEBUG:
            print(filename, "STA=", sta_m, "GPS=", (lat, lon))

        records.append(
            PhotoRecord(
                path=img_path,
                sta=sta,
                sta_m=sta_m,
                lat=lat,
                lon=lon,
                width=iw,
                height=ih,
            )
        )

    return records


# =========================
# UI INPUT
# =========================
def ask_inputs() -> Tuple[str, str, str, str, str]:
    """Prompt user for required inputs via GUI dialogs.
    
    Returns:
        Tuple of (screenshot_dir, save_pdf, ruas_number, ruas_name, ruas_length)
    """
    root = tk.Tk()
    root.withdraw()

    screenshot_dir = filedialog.askdirectory(title="Select Screenshot Folder")
    if not screenshot_dir:
        raise SystemExit("No screenshot folder selected")

    save_pdf = filedialog.asksaveasfilename(
        title="Save PDF As",
        defaultextension=".pdf",
        filetypes=[("PDF", "*.pdf")]
    )
    if not save_pdf:
        raise SystemExit("No output PDF selected")

    ruas_number = simpledialog.askstring("Input", "Ruas Number:")
    ruas_name = simpledialog.askstring("Input", "Ruas Name:")
    ruas_length = simpledialog.askstring("Input", "Ruas Length (km):")

    if not all([ruas_number, ruas_name, ruas_length]):
        raise SystemExit("Incomplete metadata")

    return screenshot_dir, save_pdf, ruas_number, ruas_name, ruas_length


# =========================
# HEADER DRAW
# =========================
def draw_header(
    c: canvas.Canvas,
    logo_left: str,
    logo_right: str,
    ruas_number: str,
    ruas_name: str,
    ruas_length: str,
    config: RegionConfig
) -> float:
    """Draw the PDF header with logos and metadata.
    
    Args:
        c: ReportLab canvas
        logo_left: Path to left logo image
        logo_right: Path to right logo image
        ruas_number: Road section number
        ruas_name: Road section name
        ruas_length: Road section length in km
        config: Regional configuration
        
    Returns:
        Y-coordinate for content below header
    """
    y_top = PAGE_H - MARGIN_T

    # Logos
    c.drawImage(
        logo_left,
        MARGIN_L,
        y_top - LOGO_SIZE,
        LOGO_SIZE,
        LOGO_SIZE,
        preserveAspectRatio=True,
        anchor='nw',
        mask='auto'
    )

    c.drawImage(
        logo_right,
        PAGE_W - MARGIN_R - LOGO_SIZE,
        y_top - LOGO_SIZE,
        LOGO_SIZE,
        LOGO_SIZE,
        preserveAspectRatio=True,
        anchor='nw',
        mask='auto'
    )

    # Header text (CENTERED)
    c.setFont(*FONT_TITLE)
    c.drawCentredString(
        PAGE_W / 2,
        y_top - 0.6 * cm,
        config.header_title
    )

    c.setFont(*FONT_SUB)
    c.drawCentredString(
        PAGE_W / 2,
        y_top - 1.2 * cm,
        config.header_subtitle
    )

    c.drawCentredString(
        PAGE_W / 2,
        y_top - 1.7 * cm,
        config.header_address
    )

    # Line under header
    line_y = y_top - HEADER_HEIGHT
    c.setLineWidth(2.8)
    c.line(MARGIN_L, line_y, PAGE_W - MARGIN_R, line_y)

    # Metadata BELOW line
    meta_y = line_y - 0.6 * cm
    c.setFont(*FONT_META)

    c.drawString(MARGIN_L, meta_y, f"NOMOR RUAS : {ruas_number}")
    c.drawCentredString(PAGE_W / 2, meta_y, f"NAMA RUAS : {ruas_name}")
    c.drawRightString(PAGE_W - MARGIN_R, meta_y, f"PANJANG RUAS : {ruas_length} km")

    return meta_y - 0.8 * cm


# =========================
# PHOTO GRID
# =========================
def draw_photos(c: canvas.Canvas, photos: List[PhotoRecord], start_y: float, 
                font_sta: Tuple[str, float] = FONT_STA) -> None:
    """Draw up to 4 photos on the page with metadata.
    
    Args:
        c: ReportLab canvas
        photos: List of PhotoRecord objects (max 4)
        start_y: Starting Y coordinate
        font_sta: Font for STA text
    """
    usable_w = PAGE_W - MARGIN_L - MARGIN_R
    cell_w = (usable_w - GAP_X) / 2

    y = start_y
    idx = 0

    for row in range(2):
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

            # Passing the filename directly avoids keeping every image decoded in memory
            c.drawImage(
                photo.path,
                img_x,
                img_y,
                draw_w,
                draw_h,
                preserveAspectRatio=True,
                anchor='sw'
            )

            # Metadata under photo (LEFT-ALIGNED WITH IMAGE)
            text_y = img_y - 0.35 * cm
            label_w = 1.4 * cm

            c.setFont(*font_sta)

            # STA label
            c.drawString(img_x, text_y, "STA")
            c.drawRightString(img_x + label_w, text_y, ":")

            # STA value
            sta_value = photo.sta.replace("STA_", "").replace("STA ", "")
            c.drawString(
                img_x + label_w + 0.15 * cm,
                text_y,
                sta_value
            )

            c.setFont(*FONT_META)
            if photo.lat is not None and photo.lon is not None:
                # Latitude
                c.drawString(img_x, text_y - 0.35 * cm, "Lat")
                c.drawRightString(img_x + label_w, text_y - 0.35 * cm, ":")
                c.drawString(
                    img_x + label_w + 0.15 * cm,
                    text_y - 0.35 * cm,
                    f"{photo.lat:.6f}"
                )

                # Longitude
                c.drawString(img_x, text_y - 0.70 * cm, "Lon")
                c.drawRightString(img_x + label_w, text_y - 0.70 * cm, ":")
                c.drawString(
                    img_x + label_w + 0.15 * cm,
                    text_y - 0.70 * cm,
                    f"{photo.lon:.6f}"
                )

            idx += 1

        # Use tallest cell in row to prevent overlap
        if row_heights:
            y -= max(row_heights) + GAP_Y + 1.2 * cm


# =========================
# MAIN FUNCTION
# =========================
def generate_pdf(
    screenshot_dir: Optional[str] = None,
    output_pdf: Optional[str] = None,
    ruas_number: Optional[str] = None,
    ruas_name: Optional[str] = None,
    ruas_length: Optional[str] = None,
    region: str = "jambi"
) -> bool:
    """Generate a road photo report PDF.
    
    Args:
        screenshot_dir: Directory containing JPG images (None for GUI prompt)
        output_pdf: Output PDF path (None for GUI prompt)
        ruas_number: Road section number (None for GUI prompt)
        ruas_name: Road section name (None for GUI prompt)
        ruas_length: Road section length in km (None for GUI prompt)
        region: Regional configuration key
        
    Returns:
        True if successful, False otherwise
    """
    # Get region configuration
    config = REGION_CONFIGS.get(region.lower())
    if not config:
        messagebox.showerror("Error", f"Unknown region: {region}")
        return False

    # Get inputs via GUI if not provided
    if any(x is None for x in [screenshot_dir, output_pdf, ruas_number, ruas_name, ruas_length]):
        try:
            screenshot_dir, output_pdf, ruas_number, ruas_name, ruas_length = ask_inputs()
        except SystemExit as e:
            print(str(e))
            return False

    # Resolve logo paths
    logo_left = resource_path(os.path.join("assets", config.logo_left))
    logo_right = resource_path(os.path.join("assets", config.logo_right))

    if not os.path.exists(logo_left) or not os.path.exists(logo_right):
        messagebox.showerror("Error", f"Logo files not found in assets/\nLooking for: {config.logo_left}, {config.logo_right}")
        return False

    # Collect and sort images
    images = collect_images(screenshot_dir)

    if not images:
        messagebox.showerror("Error", "No JPG images found")
        return False

    # Create progress window
    prog = tk.Toplevel()
    prog.title("Generating PDF")
    bar = ttk.Progressbar(prog, length=300, mode="determinate")
    bar.pack(padx=20, pady=20)
    label = tk.Label(prog, text="Reading photo metadata...")
    label.pack()
    prog.update()

    try:
        # Precompute all photo metadata once (MAJOR OPTIMIZATION)
        records = build_photo_records(images)

        c = canvas.Canvas(output_pdf, pagesize=landscape(A4))

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
                config
            )

            draw_photos(c, records[img_idx:img_idx + 4], start_y, config.font_sta)
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
    return True


def main():
    """CLI entry point with GUI prompts."""
    generate_pdf()


if __name__ == "__main__":
    main()
