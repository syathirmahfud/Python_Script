from pathlib import Path
import tkinter as tk
from tkinter import filedialog

# ---- ask for folder ----
root = tk.Tk()
root.withdraw()

txt_folder = filedialog.askdirectory(title="Select folder containing MapSource TXT files")
if not txt_folder:
    raise RuntimeError("No folder selected")

TXT_FOLDER = Path(txt_folder)
OUT_FILE = TXT_FOLDER / "COMBINED.txt"

txt_files = sorted(TXT_FOLDER.glob("*.txt"))
if not txt_files:
    raise RuntimeError("No TXT files found")

combined_lines = []
first_file = True

for txt in txt_files:
    print(f"Reading: {txt.name}")
    lines = txt.read_text(encoding="cp1252").splitlines()

    if first_file:
        # keep everything from first file
        combined_lines.extend(lines)
        first_file = False
    else:
        for line in lines:
            # skip repeated headers
            if line.startswith("Grid\t"):
                continue
            if line.startswith("Datum\t"):
                continue
            if line.startswith("Header\t"):
                continue

            combined_lines.append(line)

# ---- write combined file ----
OUT_FILE.write_text("\n".join(combined_lines), encoding="cp1252")
print(f"✅ Combined file written to: {OUT_FILE}")
