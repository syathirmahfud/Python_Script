import os
import subprocess
import sys
from math import radians, sin, cos, atan2, sqrt
from datetime import timedelta
import gpxpy
import tkinter as tk
from tkinter import filedialog

# ==============================
# CONFIG
# ==============================
STEP_M = 100.0
END_OFFSET_SEC = 0.1

FFMPEG = r"D:\DEV\tools\ffmpeg.exe"
EXIFTOOL = r"D:\DEV\tools\exiftool.exe"

# ==============================
# UTILS
# ==============================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def ffmpeg_ts(td):
    total = td.total_seconds()
    if total < 0:
        total = 0.0
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def sta_name(m):
    km = int(m // 1000)
    mm = int(m % 1000)
    return f"STA_{km}+{mm:03d}.jpg"

def save_frame(video, ts, out, lat, lon, sta_txt):
    subprocess.run(
        [FFMPEG, "-y", "-ss", ts, "-i", video, "-frames:v", "1", out],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    subprocess.run(
        [
            EXIFTOOL,
            "-overwrite_original",
            f"-GPSLatitude={lat}",
            f"-GPSLongitude={lon}",
            f"-ImageDescription={sta_txt}",
            out
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# ==============================
# LOAD FILES
# ==============================
root = tk.Tk()
root.withdraw()

video = filedialog.askopenfilename(
    title="Select rendered VIRB video",
    filetypes=[("MP4 files", "*.mp4")]
)
if not video:
    sys.exit("No video selected.")

gpx_file = filedialog.askopenfilename(
    title="Select GPX file",
    filetypes=[("GPX files", "*.gpx")]
)
if not gpx_file:
    sys.exit("No GPX selected.")

video_dir = os.path.dirname(video)
dir_name = os.path.basename(video_dir)  # e.g. "Ruas_01"

out_dir = os.path.join(video_dir, f"{dir_name}_ScreenShot")
os.makedirs(out_dir, exist_ok=True)

# ==============================
# PARSE GPX
# Each <trkseg> is treated as one continuous recording clip.
# Time gaps BETWEEN segments (paused tracking) are assumed to have
# been excised from the rendered/exported video, so they contribute
# ZERO video duration. This is the key fix vs. the original script,
# which assumed GPX wall-clock time == video elapsed time throughout.
# ==============================
with open(gpx_file, "r", encoding="utf-8") as f:
    gpx = gpxpy.parse(f)

# points: (lat, lon, real_time, video_time_elapsed)
points = []
video_elapsed = timedelta(0)
seg_index = 0

for trk in gpx.tracks:
    for seg in trk.segments:
        seg_points = [p for p in seg.points if p.time]
        if not seg_points:
            continue

        seg_index += 1
        seg_start_real = seg_points[0].time

        if points:
            gap = seg_start_real - points[-1][2]
            if gap.total_seconds() > 1.0:
                print(f"⏸  Pause detected before segment {seg_index}: "
                      f"{gap.total_seconds():.1f}s of GPX time excluded from video timeline.")

        for i, p in enumerate(seg_points):
            if i == 0:
                v_time = video_elapsed
            else:
                dt = p.time - seg_points[i-1].time
                v_time = points[-1][3] + dt
            points.append((p.latitude, p.longitude, p.time, v_time))

        video_elapsed = points[-1][3]

if len(points) < 2:
    sys.exit("Not enough GPX points.")

# ==============================
# DISTANCE-DRIVEN STA EXTRACTION
# (distance logic unchanged — it was never the problem)
# ==============================
cum_dist = 0.0
next_sta = 0.0
last = points[0]  # (lat, lon, real_time, video_time)

# STA 0+000
out = os.path.join(out_dir, sta_name(0))
print("📸", sta_name(0))
save_frame(
    video,
    ffmpeg_ts(last[3]),
    out,
    last[0],
    last[1],
    f"STA {0}+{0:03d}"
)
next_sta += STEP_M

for lat, lon, t, v_time in points[1:]:
    d = haversine(last[0], last[1], lat, lon)

    if d > 0:
        while cum_dist + d >= next_sta:
            ratio = (next_sta - cum_dist) / d
            # Interpolate video time using video-elapsed values, not raw GPX time.
            # If this interval crosses a paused segment boundary, video_time still
            # interpolates correctly because both endpoints are already expressed
            # on the same "video clock".
            v_sta = last[3] + (v_time - last[3]) * ratio

            out = os.path.join(out_dir, sta_name(next_sta))
            print("📸", os.path.basename(out))

            save_frame(
                video,
                ffmpeg_ts(v_sta),
                out,
                lat,
                lon,
                f"STA {int(next_sta)//1000}+{int(next_sta%1000):03d}"
            )
            next_sta += STEP_M

        cum_dist += d

    last = (lat, lon, t, v_time)

# ==============================
# FINAL FRAME AT TRUE END OF TRACK
# ==============================
final_dist = cum_dist
final_lat, final_lon, final_t, final_v = last

if final_dist > (next_sta - STEP_M) + 0.5:
    end_v = final_v - timedelta(seconds=END_OFFSET_SEC)
    if end_v.total_seconds() < 0:
        end_v = timedelta(seconds=0)

    out = os.path.join(out_dir, sta_name(final_dist))
    print("📸", os.path.basename(out), "(end of track, -{:.1f}s)".format(END_OFFSET_SEC))

    save_frame(
        video,
        ffmpeg_ts(end_v),
        out,
        final_lat,
        final_lon,
        f"STA {int(final_dist)//1000}+{int(final_dist%1000):03d} (END)"
    )

print(f"\nDONE. Total distance ≈ {final_dist:.1f} m")
print(f"Total video-elapsed time used ≈ {video_elapsed}")
print(f"Source video: {os.path.basename(video)}")