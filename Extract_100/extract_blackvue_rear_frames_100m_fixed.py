import os
import sys
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from math import radians, sin, cos, atan2, sqrt

import tkinter as tk
from tkinter import filedialog


# ==================================================
# CONFIG
# ==================================================

FFMPEG = os.environ.get("FFMPEG_PATH", r"D:\DEV\tools\ffmpeg.exe")
EXIF = os.environ.get("EXIFTOOL_PATH", r"D:\DEV\tools\exiftool.exe")

STEP_M = 100.0
MIN_SPEED_KMH = 3.0

# Your original rear script used "_NR" as the output suffix.
# If you later prefer "_RR", "_REAR", or "_ER", change it here.
OUTPUT_SUFFIX = "_NR"


def resolve_tool(path, fallback_name):
    """
    Use the configured path if it exists.
    Otherwise, try to find the tool in PATH.
    """
    if os.path.exists(path):
        return path

    found = shutil.which(fallback_name)
    if found:
        return found

    return path


FFMPEG = resolve_tool(FFMPEG, "ffmpeg")
EXIF = resolve_tool(EXIF, "exiftool")


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
            jpg,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2.0) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2.0) ** 2
    )

    return 2.0 * R * atan2(sqrt(a), sqrt(1.0 - a))


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
            print("Invalid format.")
            print("Use: YYYY-MM-DD HH:MM:SS or YYYY-MM-DD HH:MM:SS.sss")


def sta_filename(meters, suffix=OUTPUT_SUFFIX):
    meters = int(meters)
    km = meters // 1000
    m = meters % 1000
    return f"STA_{km}+{m:03d}{suffix}.jpg"


def relative_time_for(point, target_abs):
    """
    Convert an absolute UTC time into a relative second value
    for the video file that owns this GPS point.
    """
    rel = (target_abs - point["start"]).total_seconds()
    duration = (point["end"] - point["start"]).total_seconds()

    if rel < 0.0:
        rel = 0.0

    if duration > 0.0 and rel > duration:
        rel = duration

    return rel


def choose_video_and_rel(prev, curr, target_abs):
    """
    Choose the correct video file for an interpolated STA time.

    This is important when the 100 m STA point falls near the boundary
    between two BlackVue video files.
    """
    if prev["video"] == curr["video"]:
        return prev["video"], relative_time_for(prev, target_abs)

    if prev["start"] <= target_abs <= prev["end"]:
        return prev["video"], relative_time_for(prev, target_abs)

    if curr["start"] <= target_abs <= curr["end"]:
        return curr["video"], relative_time_for(curr, target_abs)

    prev_end = prev.get("end", prev["abs"])
    curr_start = curr.get("start", curr["abs"])

    if abs((target_abs - prev_end).total_seconds()) <= abs(
        (target_abs - curr_start).total_seconds()
    ):
        return prev["video"], relative_time_for(prev, target_abs)

    return curr["video"], relative_time_for(curr, target_abs)


def save_sta_frame(video, ts, out_path, lat, lon, sta_meters):
    if ts < 0.0:
        ts = 0.0

    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{ts:.2f}",
            "-i",
            video,
            "-frames:v",
            "1",
            out_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    if proc.returncode != 0 or not os.path.exists(out_path):
        print(f"WARNING: failed to save {out_path}")
        return False

    sta_txt = f"STA {int(sta_meters) // 1000}+{int(sta_meters % 1000):03d}"
    embed_gps_to_photo(out_path, lat, lon, sta_txt)
    return True


# ==================================================
# READ GPS FROM ONE VIDEO
# ==================================================

def read_gps(video):
    try:
        start_raw = subprocess.check_output(
            [
                EXIF,
                "-api",
                "QuickTimeUTC=1",
                "-StartTime",
                "-s3",
                video,
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return []

    if not start_raw:
        return []

    try:
        start = datetime.strptime(
            start_raw.split(".")[0],
            "%Y:%m:%d %H:%M:%S",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return []

    cmd = [
        EXIF,
        "-ee",
        "-n",
        "-p",
        "$SampleTime,$GPSLatitude,$GPSLongitude,$GPSSpeed",
        video,
    ]

    try:
        out = subprocess.check_output(
            cmd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []

    pts = []

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")
        if len(parts) < 4:
            continue

        try:
            rel = float(parts[0])
            lat = float(parts[1])
            lon = float(parts[2])
            spd = float(parts[3])
        except ValueError:
            continue

        if not (-90.0 <= lat <= 90.0):
            continue

        if not (-180.0 <= lon <= 180.0):
            continue

        if lat == 0.0 and lon == 0.0:
            continue

        abs_t = start + timedelta(seconds=rel)

        pts.append(
            {
                "abs": abs_t,
                "rel": rel,
                "lat": lat,
                "lon": lon,
                "spd": spd,
                "video": video,
                "start": start,
                "end": start,
            }
        )

    if pts:
        file_end = max(p["abs"] for p in pts)
        for p in pts:
            p["end"] = file_end

    return pts


# ==================================================
# MAIN
# ==================================================

def main():
    if not os.path.exists(FFMPEG):
        sys.exit(f"FFmpeg not found: {FFMPEG}")

    if not os.path.exists(EXIF):
        sys.exit(f"ExifTool not found: {EXIF}")

    root = tk.Tk()
    root.withdraw()

    video_dir = filedialog.askdirectory(
        title="Select folder containing BlackVue REAR videos (ER / NR)"
    )

    if not video_dir:
        sys.exit("No video folder selected.")

    out_dir = filedialog.askdirectory(
        title="Select folder to save rear STA screenshots"
    )

    if not out_dir:
        sys.exit("No output folder selected.")

    root.destroy()

    os.makedirs(out_dir, exist_ok=True)

    # --------------------------------------------------
    # LOAD REAR CAMERA VIDEOS
    # --------------------------------------------------

    videos = []

    for f in os.listdir(video_dir):
        name = f.upper()
        if name.endswith(".MP4") and ("_ER" in name or "_NR" in name):
            videos.append(os.path.join(video_dir, f))

    videos.sort()

    if not videos:
        sys.exit("No rear-camera MP4 files found.")

    print(f"\nUsing {len(videos)} rear-camera videos")

    all_pts = []

    for v in videos:
        gps = read_gps(v)
        print(f"{os.path.basename(v)}: {len(gps)} GPS samples")
        all_pts.extend(gps)

    if not all_pts:
        sys.exit("No GPS data found.")

    # --------------------------------------------------
    # SORT & DEDUPLICATE
    # --------------------------------------------------

    all_pts.sort(key=lambda x: x["abs"])

    gps = []
    for p in all_pts:
        if not gps or (p["abs"] - gps[-1]["abs"]).total_seconds() > 1.0:
            gps.append(p)

    print("\nAVAILABLE TIME RANGE")
    print("Start:", gps[0]["abs"])
    print("End  :", gps[-1]["abs"])

    # --------------------------------------------------
    # USER-DEFINED ROAD SECTION
    # --------------------------------------------------

    t0 = parse_user_time("\nEnter STA 0+000 time: ")
    t1 = parse_user_time("Enter END time      : ")

    if t1 <= t0:
        sys.exit("END time must be after STA 0+000 time.")

    section = [p for p in gps if t0 <= p["abs"] <= t1]

    if len(section) < 2:
        sys.exit("Selected section too short.")

    print(f"\nUsing {len(section)} GPS points")

    # --------------------------------------------------
    # SAVE STA 0+000
    # --------------------------------------------------

    first = section[0]
    out0 = os.path.join(out_dir, sta_filename(0))

    print("Saving", os.path.basename(out0))
    save_sta_frame(
        first["video"],
        first["rel"],
        out0,
        first["lat"],
        first["lon"],
        0,
    )

    saved_sta = {0}

    # --------------------------------------------------
    # POLYLINE STA SCREENSHOTS
    # --------------------------------------------------

    total = 0.0
    next_sta = STEP_M
    last = None

    for point in section:
        if last is None:
            last = point
            continue

        if point["spd"] < MIN_SPEED_KMH and last["spd"] < MIN_SPEED_KMH:
            last = point
            continue

        d = haversine(
            last["lat"],
            last["lon"],
            point["lat"],
            point["lon"],
        )

        if d <= 0.0:
            last = point
            continue

        while total + d >= next_sta:
            ratio = (next_sta - total) / d

            if ratio < 0.0:
                ratio = 0.0
            if ratio > 1.0:
                ratio = 1.0

            segment_seconds = (point["abs"] - last["abs"]).total_seconds()
            target_abs = last["abs"] + timedelta(seconds=segment_seconds * ratio)

            target_lat = last["lat"] + ratio * (point["lat"] - last["lat"])
            target_lon = last["lon"] + ratio * (point["lon"] - last["lon"])

            target_video, target_rel = choose_video_and_rel(
                last,
                point,
                target_abs,
            )

            out = os.path.join(out_dir, sta_filename(next_sta))
            print("Saving", os.path.basename(out))

            if save_sta_frame(
                target_video,
                target_rel,
                out,
                target_lat,
                target_lon,
                next_sta,
            ):
                saved_sta.add(int(next_sta))

            next_sta += STEP_M

        total += d
        last = point

    # --------------------------------------------------
    # FINAL STA
    # --------------------------------------------------

    final_m = int(total)

    if final_m > 0 and final_m not in saved_sta:
        end_img = os.path.join(out_dir, sta_filename(final_m))
        final_point = section[-1]

        print("Saving", os.path.basename(end_img))
        save_sta_frame(
            final_point["video"],
            final_point["rel"],
            end_img,
            final_point["lat"],
            final_point["lon"],
            final_m,
        )

    print(f"\nDONE. Total length ≈ {total:.1f} m")


if __name__ == "__main__":
    main()