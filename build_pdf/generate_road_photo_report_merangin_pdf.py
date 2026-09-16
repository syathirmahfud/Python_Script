import os
import re
import sys
import math
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk, messagebox

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

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
FONT_STA = ("Helvetica-Bold", 9)

def resource_path(rel_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.abspath(rel_path)

EXIF = resource_path("exiftool.exe")

# =========================
# HELPERS
# =========================
import subprocess

def read_gps_from_jpg(img_path):
    try:
        out = subprocess.check_output(
            [
                EXIF,
                "-n",
                "-GPSLatitude",
                "-GPSLongitude",
                "-s3",
                img_path
            ],
            text=True
        ).strip().splitlines()

        if len(out) == 2:
            return out[0], out[1]
    except:
        pass

    return None, None

def parse_sta(filename):
    """
    STA_1+200.jpg -> STA 1+200
    """
    m = re.search(r"STA[_\s]?(\d+\+\d+)", filename)
    if not m:
        raise ValueError(f"Invalid STA filename: {filename}")
    return f"STA {m.group(1)}"

def sta_to_meters(filename):
    m = re.search(r"STA[_\s]?(\d+)\+(\d+)", filename)
    if not m:
        return float("inf")
    km = int(m.group(1))
    mtr = int(m.group(2))
    return km * 1000 + mtr

def parse_latlon(filename):
    """
    Optional: extract lat/lon if embedded in filename
    If not found, return None, None
    """
    return None, None


# =========================
# UI INPUT
# =========================
def ask_inputs():
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
        "DINAS PEKERJAAN UMUM DAN PENATAAN RUANG KAB. MERANGIN"
    )

    c.setFont(*FONT_SUB)
    c.drawCentredString(
        PAGE_W / 2,
        y_top - 1.2 * cm,
        "Dokumentasi Survey PKRMS Jalan Kab. Merangin"
    )

    c.drawCentredString(
        PAGE_W / 2,
        y_top - 1.7 * cm,
        "Jl. Jenderal Sudirman KM. 3, Pematang Kandis, Kec. Bangko, Kabupaten Merangin, Jambi"
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
    c.drawRightString(PAGE_W - MARGIN_R, meta_y, f"PANJANG RUAS : {ruas_length} km")

    return meta_y - 0.8 * cm


# =========================
# PHOTO GRID
# =========================
def draw_photos(c, photos, start_y):
    usable_w = PAGE_W - MARGIN_L - MARGIN_R
    cell_w = (usable_w - GAP_X) / 2

    y = start_y
    idx = 0

    for row in range(2):
        x_left = MARGIN_L
        x_right = MARGIN_L + cell_w + GAP_X

        for col in range(2):
            if idx >= len(photos):
                return

            img_path = photos[idx]
            sta = parse_sta(os.path.basename(img_path))
            lat, lon = read_gps_from_jpg(img_path)

            img = ImageReader(img_path)
            iw, ih = img.getSize()

            draw_w = cell_w * PHOTO_SCALE
            draw_h = draw_w * ih / iw

            if col == 0:
                img_x = x_left
            else:
                img_x = x_right + (cell_w - draw_w)

            img_y = y - draw_h

            c.drawImage(
                img,
                img_x,
                img_y,
                draw_w,
                draw_h,
                preserveAspectRatio=True,
                anchor='sw'
            )

            # Metadata under photo (LEFT-ALIGNED WITH IMAGE)
            text_y = img_y - 0.35 * cm
            label_w = 1.4 * cm   # MUST be the SAME as Lat/Lon block

            c.setFont(*FONT_STA)

            # STA label
            c.drawString(img_x, text_y, "STA")
            c.drawRightString(img_x + label_w, text_y, ":")

            # STA value
            sta_value = sta.replace("STA_", "").replace("STA ", "")
            c.drawString(
                img_x + label_w + 0.15 * cm,
                text_y,
                sta_value
            )


            c.setFont(*FONT_META)
            if lat is not None and lon is not None:
                label_w = 1.4 * cm   # fixed label column width

                # Latitude
                c.drawString(img_x, text_y - 0.35 * cm, "Lat")
                c.drawRightString(img_x + label_w, text_y - 0.35 * cm, ":")
                c.drawString(
                    img_x + label_w + 0.15 * cm,
                    text_y - 0.35 * cm,
                    f"{float(lat):.6f}"
                )

                # Longitude
                c.drawString(img_x, text_y - 0.70 * cm, "Lon")
                c.drawRightString(img_x + label_w, text_y - 0.70 * cm, ":")
                c.drawString(
                    img_x + label_w + 0.15 * cm,
                    text_y - 0.70 * cm,
                    f"{float(lon):.6f}"
                )

            idx += 1

        y -= (draw_h + GAP_Y + 1.2 * cm)


# =========================
# MAIN
# =========================
def main():
    screenshot_dir, save_pdf, ruas_number, ruas_name, ruas_length = ask_inputs()

    logo_left = os.path.join("assets", "logo_Merangin.png")
    logo_right = os.path.join("assets", "logo_pupr.png")

    if not os.path.exists(logo_left) or not os.path.exists(logo_right):
        messagebox.showerror("Error", "Logo files not found in assets/")
        return

    images = sorted(
        [
        os.path.join(screenshot_dir, f)
        for f in os.listdir(screenshot_dir)
        if f.lower().endswith(".jpg")
        ],
        key=lambda p: sta_to_meters(os.path.basename(p))
        )


    if not images:
        messagebox.showerror("Error", "No JPG images found")
        return

    # Progress window
    prog = tk.Toplevel()
    prog.title("Generating PDF")
    bar = ttk.Progressbar(prog, length=300, mode="determinate")
    bar.pack(padx=20, pady=20)
    label = tk.Label(prog, text="Starting...")
    label.pack()

    c = canvas.Canvas(save_pdf, pagesize=landscape(A4))

    total_pages = math.ceil(len(images) / 4)
    img_idx = 0

    for page in range(total_pages):
        bar["value"] = (page / total_pages) * 100
        label.config(text=f"Page {page+1} / {total_pages}")
        prog.update()

        start_y = draw_header(
            c,
            logo_left,
            logo_right,
            ruas_number,
            ruas_name,
            ruas_length
        )

        draw_photos(c, images[img_idx:img_idx+4], start_y)

        img_idx += 4
        c.showPage()

    bar["value"] = 100
    label.config(text="Done")
    prog.update()

    c.save()
    prog.destroy()

    messagebox.showinfo("Done", "PDF generated successfully")


if __name__ == "__main__":
    main()
