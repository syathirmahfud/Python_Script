import os
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog

# ==================================================
# EXE-SAFE RESOURCE PATH
# ==================================================
def resource_path(rel_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.abspath(rel_path)

EXIF = resource_path("exiftool.exe")

# ==================================================
# PICK VIDEO FILE (POPUP)
# ==================================================
root = tk.Tk()
root.withdraw()

video_path = filedialog.askopenfilename(
    title="Select BlackVue 1-minute video (MP4)",
    filetypes=[("MP4 files", "*.mp4")]
)

if not video_path:
    sys.exit("No video selected.")

# ==================================================
# OUTPUT FILES (PROJECT DIRECTORY)
# ==================================================
script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
base = os.path.splitext(os.path.basename(video_path))[0]

meta_txt = os.path.join(script_dir, base + "_metadata.txt")
gpslog_txt = os.path.join(script_dir, base + "_GPSLog.txt")

# ==================================================
# 1️⃣ EXTRACT ALL METADATA (TEXT)
# ==================================================
print("📄 Extracting full metadata...")

cmd_meta = [
    EXIF,
    "-ee",
    "-G3",
    "-a",
    "-s",
    video_path
]

try:
    meta_out = subprocess.check_output(
        cmd_meta,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace"
    )
except subprocess.CalledProcessError as e:
    print("❌ ExifTool metadata extraction failed")
    print(e.output)
    sys.exit(1)

with open(meta_txt, "w", encoding="utf-8") as f:
    f.write(meta_out)

print("✅ Metadata saved to:")
print(meta_txt)

# ==================================================
# 2️⃣ EXTRACT GPSLOG BINARY (CORRECT WAY)
# ==================================================
print("\n📡 Extracting GPSLog (binary → text)...")

cmd_gpslog = [
    EXIF,
    "-ee",
    "-b",
    "-GPSLog",
    video_path
]

try:
    with open(gpslog_txt, "wb") as f:
        subprocess.run(
            cmd_gpslog,
            stdout=f,
            stderr=subprocess.DEVNULL,
            check=True
        )
except subprocess.CalledProcessError:
    print("⚠️ GPSLog extraction failed or not present")
    sys.exit(1)

print("✅ GPSLog saved to:")
print(gpslog_txt)

print("\nDONE.")
