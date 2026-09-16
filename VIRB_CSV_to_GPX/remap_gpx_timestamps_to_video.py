import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import sys
from pathlib import Path

TIME_FMT = "%H:%M:%S"

# =========================
# USER INPUT (EDIT THIS)
# =========================

ANCHORS = [
    ("00:00:00", "00:00:00"),
    ("00:17:32", "00:17:35"),
    ("00:35:13", "00:35:15"),
    ("00:47:26", "00:56:02"),
    ("01:05:07", "01:13:42"),
    ("01:22:48", "01:31:24"),
    ("01:40:29", "01:49:27"),
    # add more if needed
]

# =========================
# INTERNAL LOGIC
# =========================

def parse_hms(t):
    return datetime.strptime(t, TIME_FMT)

def build_segments(anchors):
    segments = []

    for i in range(len(anchors) - 1):
        v0, g0 = map(parse_hms, anchors[i])
        v1, g1 = map(parse_hms, anchors[i + 1])

        g_delta = (g1 - g0).total_seconds()
        v_delta = (v1 - v0).total_seconds()

        if g_delta <= 0:
            raise ValueError("GPX anchor times must be increasing")

        scale = v_delta / g_delta

        segments.append({
            "g_start": g0,
            "g_end": g1,
            "v_start": v0,
            "scale": scale
        })

    # last segment → extend using last scale
    last = segments[-1]
    segments.append({
        "g_start": last["g_end"],
        "g_end": None,
        "v_start": last["v_start"] + timedelta(
            seconds=(last["g_end"] - last["g_start"]).total_seconds() * last["scale"]
        ),
        "scale": last["scale"]
    })

    return segments

def remap_time(gpx_time, segments):
    for seg in segments:
        if seg["g_end"] is None or gpx_time < seg["g_end"]:
            dt = (gpx_time - seg["g_start"]).total_seconds()
            return seg["v_start"] + timedelta(seconds=dt * seg["scale"])
    return gpx_time

# =========================
# MAIN
# =========================

def main():
    if len(sys.argv) != 3:
        print("Usage: python remap_gpx_timestamps_to_video.py input.gpx output.gpx")
        sys.exit(1)

    in_gpx = Path(sys.argv[1])
    out_gpx = Path(sys.argv[2])

    tree = ET.parse(in_gpx)
    root = tree.getroot()

    ns = root.tag.split("}")[0].strip("{")
    NS = {"g": ns}

    segments = build_segments(ANCHORS)

    fixed = 0

    for time_el in root.findall(".//g:time", NS):
        gpx_time = datetime.fromisoformat(time_el.text.replace("Z", ""))
        new_time = remap_time(gpx_time, segments)
        time_el.text = new_time.isoformat() + "Z"
        fixed += 1

    tree.write(out_gpx, encoding="utf-8", xml_declaration=True)
    print(f"✔ GPX adjusted: {fixed} timestamps rewritten")
    print(f"✔ Output: {out_gpx}")

if __name__ == "__main__":
    main()
