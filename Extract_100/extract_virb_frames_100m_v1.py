import os
import sys
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from math import radians, sin, cos, atan2, sqrt
import tkinter as tk
from tkinter import filedialog

# ==================================================
# CONFIG
# ==================================================
STEP_M = 100.0
MIN_SPEED_KMH = 3.0

TOOLS_DIR = r"D:\DEV\tools"

FFMPEG = os.path.join(TOOLS_DIR, "ffmpeg.exe")
EXIF   = os.path.join(TOOLS_DIR, "exiftool.exe")


# ==================================================
# GEO
# ==================================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def sta_name(m):
    km = int(m // 1000)
    mm = int(m % 1000)
    return f"STA_{km}+{mm:03d}.jpg"

# ==================================================
# FRAME + EXIF
# ==================================================
def save_frame(video, ts, out, lat, lon, sta_m):
    subprocess.run(
        [FFMPEG, "-y", "-ss", f"{ts:.3f}", "-i", video, "-frames:v", "1", out],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    sta_txt = f"STA {int(sta_m)//1000}+{int(sta_m%1000):03d}"

    subprocess.run(
        [
            EXIF,
            "-overwrite_original",
            f"-GPSLatitude={lat}",
            f"-GPSLongitude={lon}",
            "-GPSLatitudeRef=N" if lat >= 0 else "-GPSLatitudeRef=S",
            "-GPSLongitudeRef=E" if lon >= 0 else "-GPSLongitudeRef=W",
            f"-ImageDescription={sta_txt}",
            out
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# ==================================================
# READ GPX
# ==================================================
def read_gpx(gpx_file):
    """
    Returns list of:
    (abs_time, rel_sec, lat, lon, speed_kmh)
    """
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    tree = ET.parse(gpx_file)
    root = tree.getroot()

    pts = []
    t0 = None

    for trkpt in root.findall(".//gpx:trkpt", ns):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])

        time_el = trkpt.find("gpx:time", ns)
        if time_el is None:
            continue

        abs_t = datetime.fromisoformat(
            time_el.text.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

        if t0 is None:
            t0 = abs_t

        rel = (abs_t - t0).total_seconds()

        # speed optional
        spd_el = trkpt.find("gpx:speed", ns)
        spd = float(spd_el.text) * 3.6 if spd_el is not None else 999.0

        pts.append((abs_t, rel, lat, lon, spd))

    return pts

# ==================================================
# UI
# ==================================================
root = tk.Tk()
root.withdraw()

video_dir = filedialog.askdirectory(
    title="Select folder with VIRB MP4 videos"
)
if not video_dir:
    sys.exit("No video folder selected.")

gpx_dir = filedialog.askdirectory(
    title="Select folder with GPX files"
)
if not gpx_dir:
    sys.exit("No GPX folder selected.")

out_dir = filedialog.askdirectory(
    title="Select output folder"
)
if not out_dir:
    sys.exit("No output folder selected.")

# ==================================================
# LOAD FILE PAIRS
# ==================================================
videos = sorted(
    f for f in os.listdir(video_dir)
    if f.lower().endswith(".mp4")
)

if not videos:
    sys.exit("No MP4 files found.")

pairs = []
for v in videos:
    gpx1 = os.path.join(gpx_dir, v + ".gpx")      # name.mp4.gpx
    gpx2 = os.path.join(gpx_dir, os.path.splitext(v)[0] + ".gpx")  # name.gpx

    if os.path.exists(gpx1):
        pairs.append((os.path.join(video_dir, v), gpx1))
    elif os.path.exists(gpx2):
        pairs.append((os.path.join(video_dir, v), gpx2))
    else:
        print(f"⚠ GPX missing for {v}")


if not pairs:
    sys.exit("No MP4–GPX pairs found.")

# ==================================================
# LOAD GPS FROM GPX
# ==================================================
gps_all = []
video_map = []

for video, gpx in pairs:
    pts = read_gpx(gpx)
    print(f"{os.path.basename(video)} ← {len(pts)} GPX points")
    for p in pts:
        gps_all.append((*p, video))

if len(gps_all) < 2:
    sys.exit("Not enough GPX data.")

gps_all.sort(key=lambda x: x[0])

# ==================================================
# STA EXTRACTION
# ==================================================
total = 0.0
next_sta = STEP_M
last = None

# STA 0+000
abs_t, t, lat, lon, spd, video = gps_all[0]
out0 = os.path.join(out_dir, "STA_0+000.jpg")
save_frame(video, t, out0, lat, lon, 0)
print("📸 STA_0+000")

for abs_t, t, lat, lon, spd, video in gps_all:
    if last:
        _, lt, llat, llon, lspd, lvid = last

        if spd < MIN_SPEED_KMH and lspd < MIN_SPEED_KMH:
            last = (abs_t, t, lat, lon, spd, video)
            continue

        d = haversine(llat, llon, lat, lon)

        while total + d >= next_sta:
            r = (next_sta - total) / d

            ts = lt + r * (t - lt)
            ilat = llat + r * (lat - llat)
            ilon = llon + r * (lon - llon)

            out = os.path.join(out_dir, sta_name(next_sta))
            print("📸", os.path.basename(out))
            save_frame(video, ts, out, ilat, ilon, next_sta)

            next_sta += STEP_M

        total += d

    last = (abs_t, t, lat, lon, spd, video)

# FINAL STA
out_end = os.path.join(out_dir, sta_name(int(total)))
abs_t, t, lat, lon, spd, video = gps_all[-1]
save_frame(video, t, out_end, lat, lon, total)
print("📸", os.path.basename(out_end))

print(f"\nDONE. Total length ≈ {total:.1f} m")
