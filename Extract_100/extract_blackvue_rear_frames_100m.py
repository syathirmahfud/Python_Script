import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from math import radians, sin, cos, atan2, sqrt
import tkinter as tk
from tkinter import filedialog

# ==================================================
# EXE-SAFE RESOURCE PATH
# ==================================================
def resource_path(rel_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.abspath(rel_path)

FFMPEG = r"D:\DEV\tools\ffmpeg.exe"
EXIF = r"D:\DEV\tools\exiftool.exe"

STEP_M = 100.0
MIN_SPEED_KMH = 3.0

# ==================================================
# UTILITIES
# ==================================================
def embed_gps_to_photo(jpg, lat, lon, sta_text):
    subprocess.run(
        [
            EXIF,
            "-overwrite_original",
            f"-GPSLatitude={lat}",
            f"-GPSLongitude={lon}",
            f"-ImageDescription={sta_text}",
            jpg
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def parse_user_time(prompt):
    while True:
        s = input(prompt).strip()
        try:
            if "." in s:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")
            else:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            print("❌ Invalid format.")
            print("   Use: YYYY-MM-DD HH:MM:SS or YYYY-MM-DD HH:MM:SS.sss")

def sta_name(meters):
    km = int(meters // 1000)
    m  = int(meters % 1000)
    return f"STA_{km}+{m:03d}.jpg"

def sta_name1(meters):
    km = int(meters // 1000)
    m  = int(meters % 1000)
    return f"STA_{km}+{m:03d}"

def save_sta_frame(video, ts, out_path, lat, lon, sta_meters):
    subprocess.run(
        [FFMPEG, "-y", "-ss", f"{ts:.2f}", "-i", video, "-frames:v", "1", out_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    sta_txt = f"STA {int(sta_meters)//1000}+{int(sta_meters%1000):03d}"
    embed_gps_to_photo(out_path, lat, lon, sta_txt)

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
        "-p", "$SampleTime,$GPSLatitude,$GPSLongitude,$GPSSpeed",
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
            t, lat, lon, spd = line.split(",")
            abs_t = start + timedelta(seconds=float(t))
            pts.append((abs_t, float(t), float(lat), float(lon), float(spd), video))
        except:
            pass

    return pts

# ==================================================
# SELECT FOLDERS (WINDOWS DIALOG)
# ==================================================
root = tk.Tk()
root.withdraw()

video_dir = filedialog.askdirectory(
    title="Select folder containing BlackVue FRONT videos (EF / NF)"
)
if not video_dir:
    sys.exit("No video folder selected.")

out_dir = filedialog.askdirectory(
    title="Select folder to save STA screenshots"
)
if not out_dir:
    sys.exit("No output folder selected.")

# ==================================================
# LOAD FRONT CAMERA VIDEOS
# ==================================================
videos = sorted(
    os.path.join(video_dir, f)
    for f in os.listdir(video_dir)
    if f.lower().endswith(".mp4") and ("_ER" in f or "_NR" in f)
)

print(f"\nUsing {len(videos)} front-camera videos")

all_pts = []
for v in videos:
    gps = read_gps(v)
    print(f"{os.path.basename(v)}: {len(gps)} GPS samples")
    all_pts.extend(gps)

if not all_pts:
    sys.exit("No GPS data found.")

# ==================================================
# SORT & DEDUPLICATE (1 SECOND)
# ==================================================
all_pts.sort(key=lambda x: x[0])

gps = []
for p in all_pts:
    if not gps or (p[0] - gps[-1][0]).total_seconds() > 1:
        gps.append(p)

print("\nAVAILABLE TIME RANGE")
print("Start:", gps[0][0])
print("End  :", gps[-1][0])

# ==================================================
# USER-DEFINED ROAD SECTION
# ==================================================
t0 = parse_user_time("\nEnter STA 0+000 time: ")
t1 = parse_user_time("Enter END time      : ")

section = [p for p in gps if t0 <= p[0] <= t1]
if len(section) < 2:
    sys.exit("Selected section too short.")

print(f"\nUsing {len(section)} GPS points")

# ==================================================
# STA 0+000
# ==================================================
abs_t, t, lat, lon, spd, video = section[0]
out0 = os.path.join(out_dir, "STA_0+000_NR.jpg")
save_sta_frame(video, t, out0, lat, lon, 0)
print("📸 STA_0+000_NR")

# ==================================================
# POLYLINE STA SCREENSHOTS
# ==================================================
total = 0.0
next_sta = STEP_M
last = None

for abs_t, t, lat, lon, spd, video in section:
    if last:
        la, lt, llat, llon, lspd, lvid = last

        if spd < MIN_SPEED_KMH and lspd < MIN_SPEED_KMH:
            last = (abs_t, t, lat, lon, spd, video)
            continue

        d = haversine(llat, llon, lat, lon)

        while total + d >= next_sta:
            ratio = (next_sta - total) / d
            ts = lt + ratio * (t - lt)

            base = os.path.join(out_dir, sta_name1(next_sta))
            out = base + "_NR.jpg"
            print("📸", os.path.basename(out))
            save_sta_frame(video, ts, out, lat, lon, next_sta)

            next_sta += STEP_M

        total += d

    last = (abs_t, t, lat, lon, spd, video)

# ==================================================
# FINAL STA
# ==================================================
end_img = os.path.join(out_dir, sta_name1(int(total))) + "_NR.jpg"

abs_t, t, lat, lon, spd, video = section[-1]

save_sta_frame(video, t, end_img, lat, lon, total)
print("📸", os.path.basename(end_img))
print(f"\nDONE. Total length ≈ {total:.1f} m")
