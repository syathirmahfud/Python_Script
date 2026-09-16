import gpxpy
import datetime
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import os
import sys

def parse_datetime_input(dt_str):
    """
    Parse common datetime formats. Returns a datetime object or None if parsing fails.
    Accepted examples:
      - 2025-11-26 15:30:00
      - 2025-11-26T15:30:00
      - 2025/11/26 15:30
      - 2025-11-26
      - 15:30:00  (will use today's date)
    """
    if not dt_str:
        return None
    dt_str = dt_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%H:%M:%S",
        "%H:%M",
    ]
    for fmt in formats:
        try:
            parsed = datetime.datetime.strptime(dt_str, fmt)
            # If format was time-only, add today's date
            if fmt in ("%H:%M:%S", "%H:%M"):
                today = datetime.date.today()
                return datetime.datetime.combine(today, parsed.time())
            return parsed
        except ValueError:
            continue
    return None

def modify_gpx_timestamps(input_path, output_path, start_time=None, interval_seconds=2):
    with open(input_path, "r", encoding="utf-8") as fh:
        gpx = gpxpy.parse(fh)

    # Determine fallback start_time from first available track point time
    fallback = None
    for track in gpx.tracks:
        for seg in track.segments:
            if seg.points:
                fallback = seg.points[0].time
                break
        if fallback:
            break

    if start_time is None:
        # If no provided start_time, use fallback or now
        if fallback:
            start_time = fallback
        else:
            start_time = datetime.datetime.now()

    # Make sure start_time is timezone-naive like existing GPX times (or keep tzinfo)
    for track in gpx.tracks:
        for seg in track.segments:
            for i, pt in enumerate(seg.points):
                pt.time = start_time + datetime.timedelta(seconds=i * interval_seconds)

    # Also consider waypoints (optional): update their times if present and you want them changed.
    # For now we leave waypoints unchanged.

    # Write output
    with open(output_path, "w", encoding="utf-8") as out_f:
        out_f.write(gpx.to_xml())

def main():
    root = tk.Tk()
    root.withdraw()  # hide main window

    messagebox.showinfo("GPX timestamp editor", "Select the input GPX file to modify.")
    input_path = filedialog.askopenfilename(
        title="Open GPX file",
        filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")],
    )
    if not input_path:
        messagebox.showinfo("Cancelled", "No input file selected. Exiting.")
        return

    # Try to read the GPX to find an existing first timestamp (for display)
    first_time_hint = ""
    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            gpx = gpxpy.parse(fh)
        hint = None
        for track in gpx.tracks:
            for seg in track.segments:
                if seg.points:
                    hint = seg.points[0].time
                    break
            if hint:
                break
        if hint:
            # Format hint without timezone for display
            first_time_hint = hint.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        first_time_hint = ""

    prompt = "Enter starting date & time (e.g. 2025-11-26 15:30:00).\nLeave blank to use the GPX's first point time or current time."
    if first_time_hint:
        prompt += f"\nDetected first point time: {first_time_hint}"

    user_input = simpledialog.askstring("Start date/time", prompt, initialvalue=first_time_hint or "")
    parsed_dt = parse_datetime_input(user_input)

    if user_input and parsed_dt is None:
        # invalid format — ask user if they'd like to retry or cancel
        retry = messagebox.askretrycancel("Invalid datetime", "Couldn't parse the date/time you entered. Retry?")
        if retry:
            # naive approach: restart main
            root.destroy()
            return main()
        else:
            messagebox.showinfo("Using fallback", "Will use GPX's first point time or current time as fallback.")
            parsed_dt = None

    # Choose output file
    default_name = os.path.splitext(os.path.basename(input_path))[0] + "_modified.gpx"
    output_path = filedialog.asksaveasfilename(
        title="Save modified GPX as",
        defaultextension=".gpx",
        initialfile=default_name,
        filetypes=[("GPX files", "*.gpx"), ("All files", "*.*")],
    )
    if not output_path:
        messagebox.showinfo("Cancelled", "No output file selected. Exiting.")
        return

    try:
        modify_gpx_timestamps(input_path, output_path, start_time=parsed_dt, interval_seconds=2)
        messagebox.showinfo("Success", f"Modified GPX saved to:\n{output_path}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to process GPX:\n{e}")
    finally:
        root.destroy()

if __name__ == "__main__":
    main()
