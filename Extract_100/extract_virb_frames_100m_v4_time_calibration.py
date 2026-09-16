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

# ------------------------------------------------------------
# TIME SYNC CALIBRATION
# A FIXED offset (same number of seconds everywhere) only makes sense
# if the GPX logger and camera started at slightly different moments.
# That does NOT match what you're seeing: a small error at 4.7km and
# a much bigger one at 12.7km. An error that GROWS with distance/time
# means the two clocks are running at slightly different RATES (e.g.
# the camera's internal clock or frame timing drifting a fraction of
# a percent from real/GPS time) - not a one-time startup delay.
#
# So instead of one constant, this uses an affine correction:
#   corrected_time = raw_video_elapsed_time * TIME_SYNC_SCALE - TIME_SYNC_OFFSET_SEC
#
# HOW TO CALIBRATE (need 2 reference points, as far apart as possible):
# 1. Run once with SCALE=1.0, OFFSET=0.0. Note the printed "seek=" time
#    for two STAs that are far apart (e.g. one near the start, one near
#    the end - the further apart the better, for accuracy).
# 2. For each of those two STAs, scrub the video manually to find the
#    TRUE timestamp where that real-world location actually appears.
# 3. You now have two (raw_seek, true_time) pairs in seconds:
#       (raw1, true1) and (raw2, true2)
# 4. Compute:
#       TIME_SYNC_SCALE      = (true2 - true1) / (raw2 - raw1)
#       TIME_SYNC_OFFSET_SEC = raw1 * TIME_SYNC_SCALE - true1
# 5. Plug those two numbers in below and re-run. This single
#    calibration should hold for the whole video, since it's now
#    modeling a constant clock RATE difference, not a fixed lag.
# ------------------------------------------------------------
TIME_SYNC_SCALE = 0.97
TIME_SYNC_OFFSET_SEC = 0

FFMPEG = r"D:\DEV\tools\ffmpeg.exe"
EXIFTOOL = r"D:\DEV\tools\exiftool.exe"

# ==============================
# UTILS
# ==============================
def haversine(lat1, lon1, lat2, lon2):
    """
    WGS84 ellipsoidal distance (Vincenty inverse formula).
    Kept the name 'haversine' so no other call sites need changing,
    but this is no longer the spherical approximation.

    Spherical haversine (R=6371000 mean radius) has a systematic bias
    of roughly 0.1-0.5% depending on latitude/bearing because the Earth
    is an oblate spheroid, not a sphere. That bias is what was causing
    the consistent ~0.2% distance drift. Vincenty uses the actual WGS84
    ellipsoid (same model GPS coordinates are based on), which removes
    that systematic error.
    """
    a = 6378137.0            # WGS84 semi-major axis (m)
    f = 1 / 298.257223563    # WGS84 flattening
    b = (1 - f) * a

    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    L = radians(lon2 - lon1)
    U1 = atan2((1 - f) * sin(radians(lat1)), cos(radians(lat1)))
    U2 = atan2((1 - f) * sin(radians(lat2)), cos(radians(lat2)))
    sinU1, cosU1 = sin(U1), cos(U1)
    sinU2, cosU2 = sin(U2), cos(U2)

    lam = L
    for _ in range(200):
        sinLam, cosLam = sin(lam), cos(lam)
        sinSigma = sqrt((cosU2 * sinLam) ** 2 +
                         (cosU1 * sinU2 - sinU1 * cosU2 * cosLam) ** 2)
        if sinSigma == 0:
            return 0.0  # coincident points
        cosSigma = sinU1 * sinU2 + cosU1 * cosU2 * cosLam
        sigma = atan2(sinSigma, cosSigma)
        sinAlpha = cosU1 * cosU2 * sinLam / sinSigma
        cosSqAlpha = 1 - sinAlpha ** 2
        cos2SigmaM = cosSigma - 2 * sinU1 * sinU2 / cosSqAlpha if cosSqAlpha != 0 else 0
        C = f / 16 * cosSqAlpha * (4 + f * (4 - 3 * cosSqAlpha))
        lamPrev = lam
        lam = L + (1 - C) * f * sinAlpha * (
            sigma + C * sinSigma * (cos2SigmaM + C * cosSigma *
                                     (-1 + 2 * cos2SigmaM ** 2))
        )
        if abs(lam - lamPrev) < 1e-12:
            break

    uSq = cosSqAlpha * (a ** 2 - b ** 2) / (b ** 2)
    A = 1 + uSq / 16384 * (4096 + uSq * (-768 + uSq * (320 - 175 * uSq)))
    B = uSq / 1024 * (256 + uSq * (-128 + uSq * (74 - 47 * uSq)))
    deltaSigma = B * sinSigma * (cos2SigmaM + B / 4 * (
        cosSigma * (-1 + 2 * cos2SigmaM ** 2) -
        B / 6 * cos2SigmaM * (-3 + 4 * sinSigma ** 2) * (-3 + 4 * cos2SigmaM ** 2)
    ))

    return b * A * (sigma - deltaSigma)

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

def calibrated(v_time):
    corrected_sec = v_time.total_seconds() * TIME_SYNC_SCALE - TIME_SYNC_OFFSET_SEC
    if corrected_sec < 0:
        corrected_sec = 0.0
    return timedelta(seconds=corrected_sec)

# STA 0+000
out = os.path.join(out_dir, sta_name(0))
seek_ts = ffmpeg_ts(calibrated(last[3]))
print("📸", sta_name(0), " seek=", seek_ts)
save_frame(
    video,
    seek_ts,
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
            seek_ts = ffmpeg_ts(calibrated(v_sta))

            out = os.path.join(out_dir, sta_name(next_sta))
            print("📸", os.path.basename(out), " seek=", seek_ts)

            save_frame(
                video,
                seek_ts,
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
    seek_ts = ffmpeg_ts(calibrated(end_v))
    print("📸", os.path.basename(out), "(end of track, -{:.1f}s) seek=".format(END_OFFSET_SEC), seek_ts)

    save_frame(
        video,
        seek_ts,
        out,
        final_lat,
        final_lon,
        f"STA {int(final_dist)//1000}+{int(final_dist%1000):03d} (END)"
    )

print(f"\nDONE. Total distance ≈ {final_dist:.1f} m")
print(f"Total video-elapsed time used ≈ {video_elapsed}")
print(f"Source video: {os.path.basename(video)}")