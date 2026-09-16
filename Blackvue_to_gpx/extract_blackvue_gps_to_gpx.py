import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone
import tkinter as tk
from tkinter import filedialog
import xml.etree.ElementTree as ET

# ==================================================
# EXE-SAFE RESOURCE PATH
# ==================================================
def resource_path(rel_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.abspath(rel_path)

EXIF = resource_path("exiftool.exe")

# ==================================================
# READ GPS FROM ONE VIDEO
# ==================================================
def read_gps(video):
    try:
        start_raw = subprocess.check_output(
            [EXIF, "-api", "QuickTimeUTC=1", "-StartTime", "-s3", video],
            text=True
        ).strip()
    except:
        return []

    if not start_raw:
        return []

    start = datetime.strptime(
        start_raw.split(".")[0],
        "%Y:%m:%d %H:%M:%S"
    ).replace(tzinfo=timezone.utc)

    cmd = [
        EXIF, "-ee", "-n",
        "-p", "$SampleTime,$GPSLatitude,$GPSLongitude",
        video
    ]

    try:
        out = subprocess.check_output(cmd, text=True)
    except:
        return []

    pts = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            t, lat, lon = line.split(",")
            abs_t = start + timedelta(seconds=float(t))
            pts.append((abs_t, float(lat), float(lon)))
        except:
            pass

    return pts

# ==================================================
# WINDOWS FOLDER PICKER
# ==================================================
root = tk.Tk()
root.withdraw()

video_dir = filedialog.askdirectory(
    title="Select folder containing BlackVue FRONT videos (EF / NF)"
)
if not video_dir:
    sys.exit("No video folder selected.")

out_dir = filedialog.askdirectory(
    title="Select folder to save GPX file"
)
if not out_dir:
    sys.exit("No output folder selected.")

# ==================================================
# LOAD FRONT CAMERA VIDEOS
# ==================================================
videos = sorted(
    os.path.join(video_dir, f)
    for f in os.listdir(video_dir)
    if f.lower().endswith(".mp4") and ("_EF" in f or "_NF" in f)
)

print(f"\nUsing {len(videos)} front-camera videos")

all_pts = []
for v in videos:
    gps = read_gps(v)
    print(f"{os.path.basename(v)}: {len(gps)} GPS points")
    all_pts.extend(gps)

if not all_pts:
    sys.exit("No GPS data found.")

# ==================================================
# SORT + DEDUPLICATE (1 SECOND)
# ==================================================
all_pts.sort(key=lambda x: x[0])

track = []
for p in all_pts:
    if not track or (p[0] - track[-1][0]).total_seconds() > 1:
        track.append(p)

print(f"\nWriting {len(track)} points to GPX")

# ==================================================
# WRITE GPX
# ==================================================
gpx = ET.Element("gpx", {
    "version": "1.1",
    "creator": "BlackVue GPS Export",
    "xmlns": "http://www.topografix.com/GPX/1/1"
})

trk = ET.SubElement(gpx, "trk")
ET.SubElement(trk, "name").text = "BlackVue Front Camera Track"
trkseg = ET.SubElement(trk, "trkseg")

for t, lat, lon in track:
    trkpt = ET.SubElement(trkseg, "trkpt", {
        "lat": f"{lat:.8f}",
        "lon": f"{lon:.8f}"
    })
    ET.SubElement(trkpt, "time").text = t.strftime("%Y-%m-%dT%H:%M:%SZ")

gpx_path = os.path.join(out_dir, "blackvue_track.gpx")
ET.ElementTree(gpx).write(
    gpx_path,
    encoding="utf-8",
    xml_declaration=True
)

print(f"\nDONE. GPX saved to:\n{gpx_path}")
