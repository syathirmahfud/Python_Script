from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import math
import tkinter as tk
from tkinter import filedialog

PREFIX = ""
EARTH_RADIUS = 6371000  # meters


def strip_ns(tag):
    return tag.split("}")[-1]


def parse_time(t):
    return datetime.fromisoformat(t.replace("Z", ""))


def haversine(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)

    return (math.degrees(math.atan2(x, y)) + 360) % 360


def safe_filename(name):
    invalid = '<>:"/\\|?*'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name


# -------------------------------------------------------
# Select Folder
# -------------------------------------------------------
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

# -------------------------------------------------------
# Process every GPX
# -------------------------------------------------------
for gpx_file in gpx_files:

    print(f"\nProcessing GPX: {gpx_file.name}")

    tree = ET.parse(gpx_file)
    root_xml = tree.getroot()

    # Find ALL tracks in the GPX
    tracks = [e for e in root_xml.iter() if strip_ns(e.tag) == "trk"]

    if not tracks:
        print("  No tracks found.")
        continue

    # ---------------------------------------------------
    # Process every track
    # ---------------------------------------------------
    for track_index, trk in enumerate(tracks, start=1):

        # Track name
        name = next(
            (c.text for c in trk if strip_ns(c.tag) == "name"),
            f"{gpx_file.stem}_{track_index}"
        )

        txt_track_name = PREFIX + name

        print(f"  Converting Track: {txt_track_name}")

        trkpts = [e for e in trk.iter() if strip_ns(e.tag) == "trkpt"]

        if not trkpts:
            print("     Skipped (no trackpoints)")
            continue

        # -----------------------------------------------
        # Collect points
        # -----------------------------------------------
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
            print("     Skipped (less than 2 points)")
            continue

        # -----------------------------------------------
        # Track statistics
        # -----------------------------------------------
        start_time = points[0][3]
        end_time = points[-1][3]

        elapsed = end_time - start_time

        total_dist_m = 0

        for i in range(1, len(points)):
            total_dist_m += haversine(
                points[i - 1][0],
                points[i - 1][1],
                points[i][0],
                points[i][1]
            )

        total_dist_km = total_dist_m / 1000

        if elapsed.total_seconds() > 0:
            avg_speed = total_dist_km / (elapsed.total_seconds() / 3600)
        else:
            avg_speed = 0

        # -----------------------------------------------
        # Write TXT
        # -----------------------------------------------
        lines = []

        lines.append("Grid\tLat/Lon hddd.ddddd°")
        lines.append("Datum\tWGS 84\n")

        lines.append(
            "Header\tName\tStart Time\tElapsed Time\tLength\tAverage Speed\tLink\n"
        )

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

            leg_len = ""
            leg_time = ""
            leg_speed = ""
            leg_course = ""

            if prev:

                dist = haversine(
                    prev[0],
                    prev[1],
                    lat,
                    lon
                )

                dt = (t - prev[3]).total_seconds()

                if dt > 0:

                    leg_len = f"{int(dist)} m"

                    leg_time = str(
                        timedelta(seconds=int(dt))
                    )

                    leg_speed = f"{int((dist / dt) * 3.6)} kph"

                    leg_course = f"{int(bearing(prev[0], prev[1], lat, lon))}° true"

            lines.append(
                f"Trackpoint\t{pos}\t{time_txt}\t{ele_txt}\t\t\t"
                f"{leg_len}\t{leg_time}\t{leg_speed}\t{leg_course}"
            )

            prev = (lat, lon, ele, t)

        filename = safe_filename(txt_track_name) + ".txt"

        out_txt = OUT_FOLDER / filename

        out_txt.write_text(
            "\n".join(lines),
            encoding="cp1252"
        )

        print(f"     ✅ Written: {filename}")

print("\nFinished.")