from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import math
import tkinter as tk
from tkinter import filedialog

PREFIX = "15.06."
EARTH_RADIUS = 6371000  # meters

def strip_ns(tag):
    return tag.split("}")[-1]

def parse_time(t):
    return datetime.fromisoformat(t.replace("Z", ""))

def haversine(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def bearing(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1)*math.sin(phi2) - math.sin(phi1)*math.cos(phi2)*math.cos(dlambda)

    return (math.degrees(math.atan2(x, y)) + 360) % 360

def process_track(trk, fallback_name, txt_index=None):
    """Build the text lines for a single <trk> element. Returns (name, lines) or None if empty."""
    name = next((c.text for c in trk if strip_ns(c.tag) == "name"), fallback_name)
    txt_track_name = PREFIX + name

    trkpts = [e for e in trk.iter() if strip_ns(e.tag) == "trkpt"]
    if not trkpts:
        return None

    points = []
    for pt in trkpts:
        lat = float(pt.attrib["lat"])
        lon = float(pt.attrib["lon"])
        ele = None
        t = None

        for c in pt:
            tag = strip_ns(c.tag)
            if tag == "ele":
                ele = int(float(c.text))
            elif tag == "time":
                t = parse_time(c.text)

        if t:
            points.append((lat, lon, ele, t))

    if len(points) < 2:
        return None

    start_time = points[0][3]
    end_time = points[-1][3]
    elapsed = end_time - start_time

    total_dist_m = 0
    for i in range(1, len(points)):
        total_dist_m += haversine(
            points[i-1][0], points[i-1][1],
            points[i][0], points[i][1]
        )

    total_dist_km = total_dist_m / 1000
    seconds = elapsed.total_seconds()
    avg_speed = (total_dist_km / (seconds / 3600)) if seconds > 0 else 0

    lines = []
    lines.append("Grid\tLat/Lon hddd.ddddd°")
    lines.append("Datum\tWGS 84\n")
    lines.append("Header\tName\tStart Time\tElapsed Time\tLength\tAverage Speed\tLink\n")
    lines.append(
        f"Track\t{txt_track_name}\t"
        f"{start_time.strftime('%d/%m/%Y %H:%M:%S')}\t"
        f"{str(elapsed)}\t"
        f"{total_dist_km:.1f} km\t"
        f"{int(avg_speed)} kph\t\n"
    )
    lines.append(
        "Header\tPosition\tTime\tAltitude\tDepth\tTemperature\t"
        "Leg Length\tLeg Time\tLeg Speed\tLeg Course\n"
    )

    prev = None
    for lat, lon, ele, t in points:
        pos = f"S{abs(lat):.5f} E{abs(lon):.5f}"
        time_txt = t.strftime("%d/%m/%Y %H:%M:%S")
        ele_txt = f"{ele} m" if ele is not None else ""

        leg_len = leg_time = leg_speed = leg_course = ""

        if prev:
            dist = haversine(prev[0], prev[1], lat, lon)
            dt = (t - prev[3]).total_seconds()
            if dt > 0:
                leg_len = f"{int(dist)} m"
                leg_time = str(timedelta(seconds=int(dt)))
                leg_speed = f"{int((dist / dt) * 3.6)} kph"
                leg_course = f"{int(bearing(prev[0], prev[1], lat, lon))}° true"

        lines.append(
            f"Trackpoint\t{pos}\t{time_txt}\t{ele_txt}\t\t\t"
            f"{leg_len}\t{leg_time}\t{leg_speed}\t{leg_course}"
        )

        prev = (lat, lon, ele, t)

    return name, lines


# ---- folder picker ----
root = tk.Tk()
root.withdraw()

gpx_folder = filedialog.askdirectory(title="Select folder containing GPX files")
if not gpx_folder:
    raise RuntimeError("No folder selected")

GPX_FOLDER = Path(gpx_folder)
OUT_FOLDER = GPX_FOLDER / "TXT_OUT"
OUT_FOLDER.mkdir(exist_ok=True)

gpx_files = list(GPX_FOLDER.glob("*.gpx"))
if not gpx_files:
    raise RuntimeError("No GPX files found")

for gpx_file in gpx_files:
    print(f"Processing: {gpx_file.name}")

    tree = ET.parse(gpx_file)
    root_xml = tree.getroot()

    # Grab ALL <trk> elements, not just the first one
    trks = [e for e in root_xml.iter() if strip_ns(e.tag) == "trk"]
    if not trks:
        print(f"  (no tracks found in {gpx_file.name})")
        continue

    all_lines = []
    written_any = False
    used_names = {}

    for idx, trk in enumerate(trks, start=1):
        fallback_name = f"{gpx_file.stem}_{idx}"
        result = process_track(trk, fallback_name)
        if result is None:
            print(f"  (skipped empty/short track #{idx})")
            continue

        name, lines = result

        # combined file content
        all_lines.extend(lines)
        all_lines.append("")  # blank line between tracks
        written_any = True

        # ---- individual per-track file, named after the track name ----
        safe_name = "".join(c if c not in '\\/:*?"<>|' else "_" for c in name).strip()
        if not safe_name:
            safe_name = fallback_name

        # avoid collisions if two tracks share the same name
        count = used_names.get(safe_name, 0)
        used_names[safe_name] = count + 1
        file_name = safe_name if count == 0 else f"{safe_name}_{count+1}"

        individual_txt = OUT_FOLDER / (file_name + ".txt")
        individual_txt.write_text("\n".join(lines), encoding="cp1252")
        print(f"  ✅ Written: {individual_txt.name} (track: {name})")

    if written_any:
        out_txt = OUT_FOLDER / (gpx_file.stem + ".txt")
        out_txt.write_text("\n".join(all_lines).rstrip() + "\n", encoding="cp1252")
        print(f"  ✅ Written combined: {out_txt.name} ({len(trks)} track section(s))")