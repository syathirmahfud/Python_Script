import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from math import atan2, cos, radians, sin, sqrt

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# ==================================================
# PATHS AND CONSTANTS
# ==================================================
def resource_path(relative_path):
    """Resolve bundled resources when running as a script or PyInstaller EXE."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


FFMPEG = r"D:\DEV\tools\ffmpeg.exe"
EXIFTOOL = r"D:\DEV\tools\exiftool.exe"

STEP_M = 100.0
MIN_SPEED_KMH = 3.0

PAGE_W, PAGE_H = landscape(A4)
MARGIN_L = 2.75 * cm
MARGIN_R = 2.75 * cm
MARGIN_T = 1.5 * cm
LOGO_SIZE = 2.0 * cm
HEADER_HEIGHT = 2.75 * cm
PHOTO_SCALE = 0.875
GAP_X = 0.8 * cm
GAP_Y = 0.3 * cm

FONT_TITLE = ("Helvetica-Bold", 14)
FONT_SUB = ("Helvetica", 9)
FONT_META = ("Helvetica", 9)
FONT_STA = ("Courier-Bold", 5.75)


# ==================================================
# GENERAL HELPERS
# ==================================================
def require_file(path, description):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{description} not found:\n{path}")


def find_logo(root, filename, title):
    candidates = [
        resource_path(os.path.join("assets", filename)),
        os.path.join(os.getcwd(), "assets", filename),
        os.path.join(r"D:\DEV\Python\build_pdf\assets", filename),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    selected = filedialog.askopenfilename(
        parent=root,
        title=title,
        filetypes=[("PNG images", "*.png"), ("Image files", "*.png *.jpg *.jpeg")],
    )
    if not selected:
        raise RuntimeError(f"No file selected for {filename}.")
    return selected


def run_command(command):
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def haversine(lat1, lon1, lat2, lon2):
    radius_m = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * radius_m * atan2(sqrt(a), sqrt(1 - a))


def parse_user_time(prompt):
    while True:
        value = input(prompt).strip()
        try:
            time_format = "%Y-%m-%d %H:%M:%S.%f" if "." in value else "%Y-%m-%d %H:%M:%S"
            return datetime.strptime(value, time_format).replace(tzinfo=timezone.utc)
        except ValueError:
            print("Invalid format.")
            print("Use: YYYY-MM-DD HH:MM:SS or YYYY-MM-DD HH:MM:SS.sss")


def sta_name(meters):
    km = int(meters // 1000)
    remainder = int(meters % 1000)
    return f"STA_{km}+{remainder:03d}.jpg"


def parse_sta(filename):
    match = re.search(r"STA[_\s]?(\d+\+\d+)", filename, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid STA filename: {filename}")
    return f"STA {match.group(1)}"


def sta_to_meters(filename):
    match = re.search(r"STA[_\s]?(\d+)\+(\d+)", filename, re.IGNORECASE)
    if not match:
        return float("inf")
    return int(match.group(1)) * 1000 + int(match.group(2))


# ==================================================
# STAGE 1: EXTRACT STA SCREENSHOTS
# ==================================================
def embed_gps_to_photo(jpg_path, lat, lon, sta_text):
    run_command(
        [
            EXIFTOOL,
            "-overwrite_original",
            f"-GPSLatitude={lat}",
            f"-GPSLongitude={lon}",
            f"-ImageDescription={sta_text}",
            jpg_path,
        ]
    )


def save_sta_frame(video, timestamp, output_path, lat, lon, sta_meters):
    run_command(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{timestamp:.2f}",
            "-i",
            video,
            "-frames:v",
            "1",
            output_path,
        ]
    )

    sta_text = f"STA {int(sta_meters) // 1000}+{int(sta_meters % 1000):03d}"
    embed_gps_to_photo(output_path, lat, lon, sta_text)


def read_gps_from_video(video):
    try:
        start_raw = subprocess.check_output(
            [EXIFTOOL, "-api", "QuickTimeUTC=1", "-StartTime", "-s3", video],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return []

    if not start_raw:
        return []

    try:
        start = datetime.strptime(
            start_raw.split(".")[0], "%Y:%m:%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return []

    command = [
        EXIFTOOL,
        "-ee",
        "-n",
        "-p",
        "$SampleTime,$GPSLatitude,$GPSLongitude,$GPSSpeed",
        video,
    ]

    try:
        output = subprocess.check_output(
            command, text=True, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    points = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            sample_time, lat, lon, speed = line.split(",")
            relative_seconds = float(sample_time)
            absolute_time = start + timedelta(seconds=relative_seconds)
            points.append(
                (
                    absolute_time,
                    relative_seconds,
                    float(lat),
                    float(lon),
                    float(speed),
                    video,
                )
            )
        except (ValueError, TypeError):
            continue

    return points


def extract_sta_screenshots(root):
    require_file(FFMPEG, "FFmpeg")
    require_file(EXIFTOOL, "ExifTool")

    video_dir = filedialog.askdirectory(
        parent=root,
        title="Select folder containing BlackVue FRONT videos (EF / NF)",
    )
    if not video_dir:
        return None

    output_dir = filedialog.askdirectory(
        parent=root,
        title="Select folder to save STA screenshots",
    )
    if not output_dir:
        return None

    videos = sorted(
        os.path.join(video_dir, filename)
        for filename in os.listdir(video_dir)
        if filename.lower().endswith(".mp4")
        and ("_EF" in filename.upper() or "_NF" in filename.upper())
    )

    if not videos:
        raise RuntimeError("No EF or NF MP4 videos were found in the selected folder.")

    print(f"\nUsing {len(videos)} front-camera videos")

    all_points = []
    for video in videos:
        points = read_gps_from_video(video)
        print(f"{os.path.basename(video)}: {len(points)} GPS samples")
        all_points.extend(points)

    if not all_points:
        raise RuntimeError("No GPS data was found in the selected videos.")

    all_points.sort(key=lambda point: point[0])

    gps = []
    for point in all_points:
        if not gps or (point[0] - gps[-1][0]).total_seconds() > 1:
            gps.append(point)

    print("\nAVAILABLE TIME RANGE")
    print("Start:", gps[0][0])
    print("End  :", gps[-1][0])

    start_time = parse_user_time("\nEnter STA 0+000 time: ")
    end_time = parse_user_time("Enter END time      : ")

    if end_time <= start_time:
        raise ValueError("END time must be after STA 0+000 time.")

    section = [point for point in gps if start_time <= point[0] <= end_time]
    if len(section) < 2:
        raise RuntimeError("The selected time section is too short.")

    print(f"\nUsing {len(section)} GPS points")

    _, timestamp, lat, lon, _, video = section[0]
    first_output = os.path.join(output_dir, "STA_0+000.jpg")
    save_sta_frame(video, timestamp, first_output, lat, lon, 0)
    print("Saved", os.path.basename(first_output))

    total = 0.0
    next_sta = STEP_M
    previous = section[0]

    for current in section[1:]:
        _, previous_timestamp, previous_lat, previous_lon, previous_speed, previous_video = previous
        _, timestamp, lat, lon, speed, video = current

        # Samples in separate video files cannot share relative timestamps.
        if video != previous_video:
            previous = current
            continue

        if speed < MIN_SPEED_KMH and previous_speed < MIN_SPEED_KMH:
            previous = current
            continue

        distance = haversine(previous_lat, previous_lon, lat, lon)
        if distance <= 0:
            previous = current
            continue

        while total + distance >= next_sta:
            ratio = (next_sta - total) / distance
            frame_time = previous_timestamp + ratio * (timestamp - previous_timestamp)
            frame_lat = previous_lat + ratio * (lat - previous_lat)
            frame_lon = previous_lon + ratio * (lon - previous_lon)

            output_path = os.path.join(output_dir, sta_name(next_sta))
            save_sta_frame(video, frame_time, output_path, frame_lat, frame_lon, next_sta)
            print("Saved", os.path.basename(output_path))
            next_sta += STEP_M

        total += distance
        previous = current

    _, timestamp, lat, lon, _, video = section[-1]
    final_output = os.path.join(output_dir, sta_name(total))

    # Avoid extracting the final frame twice when it lands exactly on a step.
    if os.path.normcase(final_output) != os.path.normcase(first_output) and not os.path.exists(final_output):
        save_sta_frame(video, timestamp, final_output, lat, lon, total)
        print("Saved", os.path.basename(final_output))

    print(f"\nScreenshot extraction complete. Total length: {total:.1f} m")
    return output_dir


# ==================================================
# STAGE 2: BUILD PDF
# ==================================================
def read_gps_from_jpg(image_path):
    try:
        output = subprocess.check_output(
            [
                EXIFTOOL,
                "-n",
                "-GPSLatitude",
                "-GPSLongitude",
                "-s3",
                image_path,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip().splitlines()
    except (OSError, subprocess.CalledProcessError):
        return None, None

    if len(output) == 2:
        return output[0], output[1]
    return None, None


def load_sections(excel_file):
    dataframe = pd.read_excel(excel_file)
    required_columns = {"STA_FROM", "PAVE_TYPE", "CONDITION"}
    missing_columns = required_columns.difference(dataframe.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Excel file is missing required columns: {missing}")

    lookup = {}
    for _, row in dataframe.iterrows():
        if pd.isna(row["STA_FROM"]):
            continue
        lookup[int(row["STA_FROM"])] = (
            str(row["PAVE_TYPE"]).strip(),
            str(row["CONDITION"]).strip(),
        )

    print("Excel section records:", len(lookup))
    return lookup


def ask_pdf_inputs(root):
    excel_file = filedialog.askopenfilename(
        parent=root,
        title="Select Excel File",
        filetypes=[("Excel Files", "*.xlsx *.xls")],
    )
    if not excel_file:
        return None

    save_pdf = filedialog.asksaveasfilename(
        parent=root,
        title="Save PDF As",
        defaultextension=".pdf",
        filetypes=[("PDF", "*.pdf")],
    )
    if not save_pdf:
        return None

    ruas_number = simpledialog.askstring("Input", "Ruas Number:", parent=root)
    ruas_name = simpledialog.askstring("Input", "Ruas Name:", parent=root)
    ruas_length = simpledialog.askstring("Input", "Ruas Length (km):", parent=root)

    if not all([ruas_number, ruas_name, ruas_length]):
        return None

    return save_pdf, excel_file, ruas_number, ruas_name, ruas_length


def draw_header(pdf, logo_left, logo_right, ruas_number, ruas_name, ruas_length):
    y_top = PAGE_H - MARGIN_T

    pdf.drawImage(
        logo_left,
        MARGIN_L,
        y_top - LOGO_SIZE,
        LOGO_SIZE,
        LOGO_SIZE,
        preserveAspectRatio=True,
        anchor="nw",
        mask="auto",
    )
    pdf.drawImage(
        logo_right,
        PAGE_W - MARGIN_R - LOGO_SIZE,
        y_top - LOGO_SIZE,
        LOGO_SIZE,
        LOGO_SIZE,
        preserveAspectRatio=True,
        anchor="nw",
        mask="auto",
    )

    pdf.setFont(*FONT_TITLE)
    pdf.drawCentredString(
        PAGE_W / 2,
        y_top - 0.6 * cm,
        "DINAS PEKERJAAN UMUM DAN PERUMAHAN RAKYAT PROVINSI JAMBI",
    )

    pdf.setFont(*FONT_SUB)
    pdf.drawCentredString(
        PAGE_W / 2,
        y_top - 1.2 * cm,
        "Dokumentasi Survey PKRMS Jalan Provinsi Jambi",
    )
    pdf.drawCentredString(
        PAGE_W / 2,
        y_top - 1.7 * cm,
        "Jl. H. Agus Salim No.02, Paal Lima, Kec. Kota Baru, Kota Jambi, Jambi",
    )

    line_y = y_top - HEADER_HEIGHT
    pdf.setLineWidth(2.8)
    pdf.line(MARGIN_L, line_y, PAGE_W - MARGIN_R, line_y)

    meta_y = line_y - 0.6 * cm
    pdf.setFont(*FONT_META)
    pdf.drawString(MARGIN_L, meta_y, f"NOMOR RUAS : {ruas_number}")
    pdf.drawCentredString(PAGE_W / 2, meta_y, f"NAMA RUAS : {ruas_name}")
    pdf.drawRightString(
        PAGE_W - MARGIN_R, meta_y, f"PANJANG RUAS : {ruas_length} km"
    )
    return meta_y - 0.8 * cm


def draw_photo_metadata(pdf, image_x, text_y, sta, pavement, condition, lat, lon):
    label_colon_x = image_x + 1.4 * cm + 1.5 * cm
    value_x = image_x + 1.4 * cm + 1.75 * cm
    sta_value = sta.replace("STA ", "")

    values = [
        ("STA", sta_value),
        ("KONDISI", condition),
        ("JENIS PERKERASAN", pavement),
        ("LATITUDE", f"{float(lat):.6f}" if lat is not None else "-"),
        ("LONGITUDE", f"{float(lon):.6f}" if lon is not None else "-"),
    ]

    pdf.setFont(*FONT_STA)
    for line_number, (label, value) in enumerate(values):
        line_y = text_y - line_number * 0.2 * cm
        pdf.drawString(image_x, line_y, label)
        pdf.drawRightString(label_colon_x, line_y, ":")
        pdf.drawString(value_x, line_y, str(value))


def draw_photos(pdf, photos, start_y, sections):
    usable_width = PAGE_W - MARGIN_L - MARGIN_R
    cell_width = (usable_width - GAP_X) / 2
    y = start_y

    for row_start in range(0, len(photos), 2):
        row_photos = photos[row_start : row_start + 2]
        row_height = 0

        for column, image_path in enumerate(row_photos):
            base, extension = os.path.splitext(image_path)
            inset_candidate = f"{base}_NR{extension}"
            inset_path = inset_candidate if os.path.exists(inset_candidate) else None

            sta = parse_sta(os.path.basename(image_path))
            sta_meters = sta_to_meters(os.path.basename(image_path))
            pavement, condition = sections.get(sta_meters, ("-", "-"))
            lat, lon = read_gps_from_jpg(image_path)

            image = ImageReader(image_path)
            source_width, source_height = image.getSize()
            draw_width = cell_width * PHOTO_SCALE
            draw_height = draw_width * source_height / source_width
            row_height = max(row_height, draw_height)

            cell_x = MARGIN_L + column * (cell_width + GAP_X)
            image_x = cell_x if column == 0 else cell_x + cell_width - draw_width
            image_y = y - draw_height

            pdf.drawImage(
                image,
                image_x,
                image_y,
                draw_width,
                draw_height,
                preserveAspectRatio=True,
                anchor="sw",
            )

            if inset_path:
                inset = ImageReader(inset_path)
                inset_source_width, inset_source_height = inset.getSize()
                inset_width = draw_width * 0.25
                inset_height = inset_width * inset_source_height / inset_source_width
                pdf.drawImage(
                    inset,
                    image_x + 5,
                    image_y + draw_height - inset_height - 5,
                    inset_width,
                    inset_height,
                    preserveAspectRatio=True,
                    anchor="sw",
                )

            draw_photo_metadata(
                pdf,
                image_x,
                image_y - 0.35 * cm,
                sta,
                pavement,
                condition,
                lat,
                lon,
            )

        y -= row_height + GAP_Y + 1.2 * cm


def build_pdf(root, screenshot_dir):
    require_file(EXIFTOOL, "ExifTool")

    inputs = ask_pdf_inputs(root)
    if inputs is None:
        return None

    save_pdf, excel_file, ruas_number, ruas_name, ruas_length = inputs
    sections = load_sections(excel_file)

    logo_left = find_logo(root, "logo_jambi.png", "Select the Jambi logo")
    logo_right = find_logo(root, "logo_pupr.png", "Select the PUPR logo")

    images = sorted(
        [
            os.path.join(screenshot_dir, filename)
            for filename in os.listdir(screenshot_dir)
            if filename.lower().endswith(".jpg") and "_NR" not in filename.upper()
        ],
        key=lambda path: sta_to_meters(os.path.basename(path)),
    )

    if not images:
        raise RuntimeError("No JPG images were found in the screenshot folder.")

    progress = tk.Toplevel(root)
    progress.title("Generating PDF")
    progress.resizable(False, False)
    bar = ttk.Progressbar(progress, length=300, mode="determinate")
    bar.pack(padx=20, pady=(20, 10))
    label = tk.Label(progress, text="Starting...")
    label.pack(pady=(0, 20))

    pdf = canvas.Canvas(save_pdf, pagesize=landscape(A4))
    total_pages = math.ceil(len(images) / 4)

    try:
        for page_number in range(total_pages):
            bar["value"] = page_number / total_pages * 100
            label.config(text=f"Page {page_number + 1} / {total_pages}")
            progress.update()

            start_y = draw_header(
                pdf,
                logo_left,
                logo_right,
                ruas_number,
                ruas_name,
                ruas_length,
            )
            page_start = page_number * 4
            draw_photos(
                pdf, images[page_start : page_start + 4], start_y, sections
            )
            pdf.showPage()

        pdf.save()
    finally:
        progress.destroy()

    messagebox.showinfo("Done", f"PDF generated successfully:\n{save_pdf}", parent=root)
    return save_pdf


# ==================================================
# MAIN PIPELINE
# ==================================================
def main():
    root = tk.Tk()
    root.withdraw()

    try:
        screenshot_dir = extract_sta_screenshots(root)
        if screenshot_dir is None:
            return

        build_pdf(root, screenshot_dir)
    except Exception as error:
        messagebox.showerror("Error", str(error), parent=root)
        raise
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
