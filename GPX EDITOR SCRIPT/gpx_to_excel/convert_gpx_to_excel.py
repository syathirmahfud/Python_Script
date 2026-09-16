#!/usr/bin/env python3
"""
convert_gpx_to_excel.py

Convert a GPX track file into a formatted Excel (.xlsx) file with columns:
    #, Latitude, Longitude, Elevation (m), Time (UTC), Interval (s), Cumulative Distance (km)

Usage:
    python convert_gpx_to_excel.py

A window will pop up asking you to pick the .gpx file to convert, then
where to save the resulting .xlsx file. (You can still pass paths on the
command line instead if you prefer: `python convert_gpx_to_excel.py input.gpx
[output.xlsx]` skips the dialogs.)

Dependencies:
    pip install openpyxl
(GPX parsing is done with the standard library's xml.etree, so no gpxpy
dependency is required. tkinter ships with most Python installs; on Linux
you may need to install it separately, e.g. `sudo apt install python3-tk`.)
"""

import os
import sys
import math
from datetime import datetime
from xml.etree import ElementTree as ET

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


GPX_NAMESPACES_CANDIDATES = [
    "{http://www.topografix.com/GPX/1/1}",
    "{http://www.topografix.com/GPX/1/0}",
]


def parse_gpx(path):
    """Parse a GPX file and return a list of dicts with lat, lon, ele, time."""
    tree = ET.parse(path)
    root = tree.getroot()

    # Detect the correct namespace prefix used in this file
    ns = ""
    for candidate in GPX_NAMESPACES_CANDIDATES:
        if root.tag.startswith(candidate):
            ns = candidate
            break

    def tag(name):
        return f"{ns}{name}"

    points = []

    # Prefer track points; fall back to route points, then waypoints
    trkpts = root.findall(f".//{tag('trkpt')}")
    src = trkpts
    if not src:
        src = root.findall(f".//{tag('rtept')}")
    if not src:
        src = root.findall(f".//{tag('wpt')}")

    for pt in src:
        lat = pt.get("lat")
        lon = pt.get("lon")
        if lat is None or lon is None:
            continue

        ele_el = pt.find(tag("ele"))
        ele = float(ele_el.text) if ele_el is not None and ele_el.text else None

        time_el = pt.find(tag("time"))
        time_val = None
        if time_el is not None and time_el.text:
            raw = time_el.text.strip().replace("Z", "+00:00")
            try:
                time_val = datetime.fromisoformat(raw)
                # Excel/openpyxl cannot store timezone-aware datetimes.
                # Normalize to UTC, then drop tzinfo so it writes cleanly.
                if time_val.tzinfo is not None:
                    from datetime import timezone
                    time_val = time_val.astimezone(timezone.utc).replace(tzinfo=None)
            except ValueError:
                time_val = None

        points.append({
            "lat": float(lat),
            "lon": float(lon),
            "ele": ele,
            "time": time_val,
        })

    return points


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in kilometers."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_workbook(points):
    wb = Workbook()
    ws = wb.active
    ws.title = "GPX Track"

    headers = [
        "#", "Latitude", "Longitude", "Elevation (m)",
        "Time (UTC)", "Interval (s)", "Elapsed Time (s)", "Cum. Distance (km)"
    ]

    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    body_font = Font(name="Arial", size=11)

    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border

    ws.freeze_panes = "A2"

    prev_time = None
    start_time = None
    prev_lat = prev_lon = None
    cum_km = 0.0

    for i, p in enumerate(points, start=1):
        row = i + 1

        interval = None
        if prev_time is not None and p["time"] is not None:
            interval = (p["time"] - prev_time).total_seconds()

        if p["time"] is not None and start_time is None:
            start_time = p["time"]

        elapsed = None
        if start_time is not None and p["time"] is not None:
            elapsed = (p["time"] - start_time).total_seconds()

        if prev_lat is not None:
            cum_km += haversine_km(prev_lat, prev_lon, p["lat"], p["lon"])

        values = [
            i,
            p["lat"],
            p["lon"],
            p["ele"] if p["ele"] is not None else None,
            p["time"] if p["time"] is not None else None,
            interval,
            elapsed,
            round(cum_km, 3),
        ]

        for col, val in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = body_font
            cell.border = border
            cell.alignment = Alignment(horizontal="center")

        ws.cell(row=row, column=2).number_format = "0.000000"
        ws.cell(row=row, column=3).number_format = "0.000000"
        if p["ele"] is not None:
            ws.cell(row=row, column=4).number_format = "0.0"
        if p["time"] is not None:
            ws.cell(row=row, column=5).number_format = "yyyy-mm-dd hh:mm:ss"
        if interval is not None:
            ws.cell(row=row, column=6).number_format = "0"
        if elapsed is not None:
            ws.cell(row=row, column=7).number_format = "0"
        ws.cell(row=row, column=8).number_format = "0.000"

        prev_time = p["time"] if p["time"] is not None else prev_time
        prev_lat, prev_lon = p["lat"], p["lon"]

    # Column widths
    widths = [6, 14, 14, 14, 20, 12, 16, 18]
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w

    # Summary sheet
    ws2 = wb.create_sheet("Summary")
    total_points = len(points)
    total_distance = cum_km
    times = [p["time"] for p in points if p["time"] is not None]
    duration_s = (times[-1] - times[0]).total_seconds() if len(times) >= 2 else None

    summary_rows = [
        ("Total Points", total_points),
        ("Total Distance (km)", round(total_distance, 3)),
        ("Start Time", times[0].strftime("%Y-%m-%d %H:%M:%S") if times else "N/A"),
        ("End Time", times[-1].strftime("%Y-%m-%d %H:%M:%S") if times else "N/A"),
        ("Duration (s)", duration_s if duration_s is not None else "N/A"),
    ]
    ws2.cell(row=1, column=1, value="Metric").font = header_font
    ws2.cell(row=1, column=1).fill = header_fill
    ws2.cell(row=1, column=2, value="Value").font = header_font
    ws2.cell(row=1, column=2).fill = header_fill
    for r, (label, val) in enumerate(summary_rows, start=2):
        ws2.cell(row=r, column=1, value=label).font = body_font
        ws2.cell(row=r, column=2, value=val).font = body_font
    ws2.column_dimensions["A"].width = 22
    ws2.column_dimensions["B"].width = 22

    return wb


def pick_files_with_gui():
    """Ask the user for an input .gpx file and an output .xlsx location."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()       # we only want the dialog boxes, not a blank window
    root.attributes("-topmost", True)

    input_path = filedialog.askopenfilename(
        title="Select a GPX file to convert",
        filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")],
        parent=root,
    )
    if not input_path:
        root.destroy()
        return None, None

    default_name = os.path.splitext(os.path.basename(input_path))[0] + ".xlsx"
    output_path = filedialog.asksaveasfilename(
        title="Save Excel file as",
        defaultextension=".xlsx",
        initialfile=default_name,
        filetypes=[("Excel files", "*.xlsx")],
        parent=root,
    )
    if not output_path:
        root.destroy()
        return None, None

    root.destroy()
    return input_path, output_path


def show_gui_message(title, text, error=False):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if error:
            messagebox.showerror(title, text, parent=root)
        else:
            messagebox.showinfo(title, text, parent=root)
        root.destroy()
    except Exception:
        pass  # if tkinter itself is unavailable, we've already printed to console


def main():
    # If paths are given on the command line, honor them and skip the dialogs.
    args = sys.argv[1:]
    if args:
        input_path = args[0]
        output_path = args[1] if len(args) > 1 else input_path.rsplit(".", 1)[0] + ".xlsx"
    else:
        input_path, output_path = pick_files_with_gui()
        if not input_path:
            print("No file selected. Exiting.")
            return

    try:
        points = parse_gpx(input_path)
    except Exception as e:
        msg = f"Could not read GPX file:\n{e}"
        print(msg, file=sys.stderr)
        show_gui_message("Error", msg, error=True)
        sys.exit(1)

    if not points:
        msg = "No track/route/waypoints with lat/lon found in the GPX file."
        print(msg, file=sys.stderr)
        show_gui_message("Error", msg, error=True)
        sys.exit(1)

    wb = build_workbook(points)
    wb.save(output_path)

    msg = f"Wrote {len(points)} points to:\n{output_path}"
    print(msg)
    show_gui_message("Done", msg)


if __name__ == "__main__":
    main()