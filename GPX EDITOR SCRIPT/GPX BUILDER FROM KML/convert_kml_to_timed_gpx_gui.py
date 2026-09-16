#!/usr/bin/env python3
"""
Tkinter GUI to convert a KML track into a timestamped GPX file.

- Asks the user which KML file to open (file picker)
- Asks the user where to save the resulting GPX file (save dialog)
- Lets the user enter a start time (ISO 8601, any UTC offset) and
  an elapsed time (seconds, MM:SS, or HH:MM:SS)
- Timestamps are spaced evenly by point count across the elapsed time
"""
import re
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

KML_NS = "{http://www.opengis.net/kml/2.2}"


def parse_iso(ts: str) -> datetime:
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def parse_elapsed(elapsed_str: str) -> float:
    elapsed_str = elapsed_str.strip()
    if ":" in elapsed_str:
        parts = [float(p) for p in elapsed_str.split(":")]
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + p
        return seconds
    return float(elapsed_str)


def extract_coordinates(kml_path: str):
    tree = ET.parse(kml_path)
    root = tree.getroot()
    coords_text = None
    for coord_el in root.iter(f"{KML_NS}coordinates"):
        coords_text = coord_el.text
        break
    if coords_text is None:
        raise ValueError("No <coordinates> element found in KML.")

    points = []
    for token in re.split(r"\s+", coords_text.strip()):
        if not token:
            continue
        parts = token.split(",")
        lon, lat = float(parts[0]), float(parts[1])
        ele = float(parts[2]) if len(parts) > 2 else None
        points.append((lat, lon, ele))
    return points


def build_gpx(points, start_time: datetime, elapsed_seconds: float) -> str:
    n = len(points)
    if n == 0:
        raise ValueError("No coordinate points found.")

    interval = 0.0 if n == 1 else elapsed_seconds / (n - 1)

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        '<gpx version="1.1" creator="convert_kml_to_timed_gpx_gui.py" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
        'http://www.topografix.com/GPX/1/1/gpx.xsd">'
    )
    lines.append("  <trk>")
    lines.append("    <n>Converted Track</n>")
    lines.append("    <trkseg>")

    for i, (lat, lon, ele) in enumerate(points):
        t = start_time + timedelta(seconds=interval * i)
        t_str = t.isoformat()
        lines.append(f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}">')
        if ele is not None:
            lines.append(f"        <ele>{ele:.2f}</ele>")
        lines.append(f"        <time>{t_str}</time>")
        lines.append("      </trkpt>")

    lines.append("    </trkseg>")
    lines.append("  </trk>")
    lines.append("</gpx>")
    return "\n".join(lines)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("KML to GPX Converter")
        self.geometry("520x260")
        self.resizable(False, False)

        self.kml_path = tk.StringVar()
        self.gpx_path = tk.StringVar()
        self.start_time_str = tk.StringVar(value="2026-07-16T11:01:45+07:00")
        self.elapsed_str = tk.StringVar(value="1:48")

        pad = {"padx": 10, "pady": 6}

        # KML file row
        tk.Label(self, text="KML file:").grid(row=0, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.kml_path, width=45).grid(row=0, column=1, **pad)
        tk.Button(self, text="Browse...", command=self.choose_kml).grid(row=0, column=2, **pad)

        # GPX save row
        tk.Label(self, text="Save GPX as:").grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.gpx_path, width=45).grid(row=1, column=1, **pad)
        tk.Button(self, text="Browse...", command=self.choose_gpx).grid(row=1, column=2, **pad)

        # Start time row
        tk.Label(self, text="Start time (ISO 8601):").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.start_time_str, width=45).grid(row=2, column=1, columnspan=2, sticky="w", **pad)

        # Elapsed time row
        tk.Label(self, text="Elapsed time (sec or MM:SS):").grid(row=3, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.elapsed_str, width=45).grid(row=3, column=1, columnspan=2, sticky="w", **pad)

        # Convert button
        tk.Button(self, text="Convert", command=self.convert, bg="#4CAF50", fg="white",
                  font=("Arial", 11, "bold")).grid(row=4, column=0, columnspan=3, pady=20)

        # Status label
        self.status = tk.Label(self, text="", fg="blue", wraplength=480, justify="left")
        self.status.grid(row=5, column=0, columnspan=3, sticky="w", padx=10)

    def choose_kml(self):
        path = filedialog.askopenfilename(
            title="Select KML file",
            filetypes=[("KML files", "*.kml"), ("All files", "*.*")]
        )
        if path:
            self.kml_path.set(path)
            if not self.gpx_path.get():
                default_out = re.sub(r"\.kml$", ".gpx", path, flags=re.IGNORECASE)
                if default_out == path:
                    default_out = path + ".gpx"
                self.gpx_path.set(default_out)

    def choose_gpx(self):
        path = filedialog.asksaveasfilename(
            title="Save GPX file as",
            defaultextension=".gpx",
            filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")]
        )
        if path:
            self.gpx_path.set(path)

    def convert(self):
        kml_path = self.kml_path.get().strip()
        gpx_path = self.gpx_path.get().strip()

        if not kml_path:
            messagebox.showerror("Missing input", "Please choose a KML file.")
            return
        if not gpx_path:
            messagebox.showerror("Missing output", "Please choose where to save the GPX file.")
            return

        try:
            start_time = parse_iso(self.start_time_str.get())
        except Exception as e:
            messagebox.showerror("Invalid start time", f"Could not parse start time:\n{e}")
            return

        try:
            elapsed_seconds = parse_elapsed(self.elapsed_str.get())
        except Exception as e:
            messagebox.showerror("Invalid elapsed time", f"Could not parse elapsed time:\n{e}")
            return

        try:
            points = extract_coordinates(kml_path)
            gpx_str = build_gpx(points, start_time, elapsed_seconds)
            with open(gpx_path, "w", encoding="utf-8") as f:
                f.write(gpx_str)
        except Exception as e:
            messagebox.showerror("Conversion failed", str(e))
            return

        n = len(points)
        interval = 0.0 if n <= 1 else elapsed_seconds / (n - 1)
        self.status.config(
            text=(f"Done! Wrote {n} points to:\n{gpx_path}\n"
                  f"Start: {start_time.isoformat()}  |  Interval: {interval:.3f}s/point")
        )
        messagebox.showinfo("Success", f"GPX file saved:\n{gpx_path}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
