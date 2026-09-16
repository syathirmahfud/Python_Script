#!/usr/bin/env python3
"""
Extract screenshots from Garmin VIRB video at 100-meter GPS intervals.
Requires: ffmpeg, gpxpy (pip install gpxpy)
"""

import subprocess
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import json
import math
import tkinter as tk
from tkinter import filedialog, messagebox

# ============================================================
# CONFIGURATION - Update this path to your ffmpeg location
# ============================================================
FFMPEG_PATH = r"D:\DEV\tools\ffmpeg.exe"
# ============================================================

# ============================================================
# ANCHOR POINTS - Sync points between video time and GPS time
# Format: (video_time, gps_time) where time is "HH:MM:SS"
# ============================================================
ANCHOR = [
    ("00:00:00", "00:00:00"),
    ("00:17:32", "00:17:35"),
    ("00:35:13", "00:35:15"),
    ("00:47:26", "00:56:02"),
    ("01:05:07", "01:13:42"),
    ("01:22:48", "01:31:24"),
    ("01:40:29", "01:49:27"),
]
# ============================================================

try:
    import gpxpy
    import gpxpy.gpx
except ImportError:
    print("Error: gpxpy not installed. Run: pip install gpxpy")
    sys.exit(1)


def time_str_to_seconds(time_str):
    """Convert HH:MM:SS string to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def gps_time_to_video_time(gps_offset_seconds, gps_start_time, anchor_points):
    """
    Convert GPS time offset to video time using anchor points.
    Uses piecewise linear interpolation between anchor points.
    """
    # Convert anchor points to seconds
    anchors = []
    for video_time_str, gps_time_str in anchor_points:
        video_sec = time_str_to_seconds(video_time_str)
        gps_sec = time_str_to_seconds(gps_time_str)
        anchors.append((gps_sec, video_sec))
    
    # Sort by GPS time
    anchors.sort(key=lambda x: x[0])
    
    # Find which segment this GPS time falls into
    for i in range(len(anchors) - 1):
        gps1, vid1 = anchors[i]
        gps2, vid2 = anchors[i + 1]
        
        if gps1 <= gps_offset_seconds <= gps2:
            # Linear interpolation within this segment
            gps_segment_duration = gps2 - gps1
            video_segment_duration = vid2 - vid1
            
            if gps_segment_duration == 0:
                return vid1
            
            # How far through this GPS segment are we?
            progress = (gps_offset_seconds - gps1) / gps_segment_duration
            
            # Apply same progress to video segment
            video_time = vid1 + (progress * video_segment_duration)
            
            return video_time
    
    # If before first anchor
    if gps_offset_seconds < anchors[0][0]:
        # Use first segment's ratio
        gps1, vid1 = anchors[0]
        gps2, vid2 = anchors[1]
        ratio = (vid2 - vid1) / (gps2 - gps1) if (gps2 - gps1) > 0 else 1.0
        video_time = vid1 + (gps_offset_seconds - gps1) * ratio
        return max(0, video_time)
    
    # If after last anchor
    if gps_offset_seconds > anchors[-1][0]:
        # Use last segment's ratio
        gps1, vid1 = anchors[-2]
        gps2, vid2 = anchors[-1]
        ratio = (vid2 - vid1) / (gps2 - gps1) if (gps2 - gps1) > 0 else 1.0
        video_time = vid2 + (gps_offset_seconds - gps2) * ratio
        return video_time
    
    return None


def select_video_file():
    """Open file dialog to select video file."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    video_path = filedialog.askopenfilename(
        title="Select Garmin VIRB Video File",
        filetypes=[
            ("Video files", "*.mp4 *.MP4 *.mov *.MOV *.avi *.AVI"),
            ("All files", "*.*")
        ]
    )
    
    root.destroy()
    return video_path


def select_gpx_file():
    """Open file dialog to select GPX file."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    gpx_path = filedialog.askopenfilename(
        title="Select GPX File",
        filetypes=[
            ("GPX files", "*.gpx *.GPX"),
            ("All files", "*.*")
        ]
    )
    
    root.destroy()
    return gpx_path


def select_output_directory():
    """Open directory dialog to select output folder."""
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    output_dir = filedialog.askdirectory(
        title="Select Output Directory for Screenshots"
    )
    
    root.destroy()
    return output_dir


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two GPS points in meters."""
    R = 6371000  # Earth radius in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


def extract_gpx_from_video(video_path):
    """Extract GPX data embedded in VIRB video metadata."""
    print(f"Extracting GPX data from {video_path}...")
    
    # Try to extract GPX from video metadata using ffmpeg
    cmd = [
        FFMPEG_PATH,
        '-i', video_path,
        '-f', 'ffmetadata',
        '-'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Check output for GPX data
        if 'gpx' in result.stdout.lower() or 'gpx' in result.stderr.lower():
            return result.stdout
    except subprocess.CalledProcessError:
        pass
    
    return None


def parse_gpx_file(gpx_path):
    """Parse GPX file and return list of (timestamp, lat, lon) tuples."""
    print(f"Parsing GPX file: {gpx_path}")
    
    with open(gpx_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
    
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.time:
                    points.append((point.time, point.latitude, point.longitude))
    
    points.sort(key=lambda x: x[0])  # Sort by timestamp
    print(f"Found {len(points)} GPS points")
    return points


def get_video_start_time(video_path):
    """Get video creation time from metadata."""
    cmd = [
        FFMPEG_PATH,
        '-i', video_path,
        '-f', 'ffmetadata',
        '-'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr
        
        # Look for creation_time or date in metadata
        import re
        time_patterns = [
            r'creation_time\s*:\s*(\S+)',
            r'date\s*:\s*(\S+)',
            r'DateTime\s*:\s*(\S+)'
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                try:
                    # Parse ISO format
                    return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                except:
                    pass
    except Exception as e:
        print(f"Warning: Could not extract video start time: {e}")
    
    return None


def get_video_duration(video_path):
    """Get video duration in seconds."""
    cmd = [
        FFMPEG_PATH,
        '-i', video_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr
        
        # Look for Duration in ffmpeg output
        # Format: Duration: 00:10:25.38
        import re
        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.?\d*)', output)
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = float(duration_match.group(3))
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
    except Exception as e:
        print(f"Warning: Could not extract video duration: {e}")
    
    return None


def find_100m_intervals(gps_points):
    """Find GPS points at approximately 100-meter intervals."""
    if not gps_points:
        return []
    
    intervals = []
    cumulative_distance = 0
    next_interval_distance = 0  # Target distance for next interval
    
    # Always include first point
    intervals.append(gps_points[0])
    
    for i in range(1, len(gps_points)):
        prev_point = gps_points[i-1]
        curr_point = gps_points[i]
        
        # Calculate distance from previous point
        segment_dist = haversine_distance(
            prev_point[1], prev_point[2],
            curr_point[1], curr_point[2]
        )
        
        cumulative_distance += segment_dist
        
        # Check if we've passed the next interval mark
        while cumulative_distance >= next_interval_distance + 100:
            next_interval_distance += 100
            # Use the current point as it's the closest to this 100m mark
            if len(intervals) == 0 or intervals[-1] != curr_point:
                intervals.append(curr_point)
    
    print(f"Found {len(intervals)} intervals at 100m spacing")
    print(f"Total distance: {cumulative_distance:.2f} meters ({cumulative_distance/1000:.2f} km)")
    print(f"Expected intervals: ~{int(cumulative_distance/100)}")
    return intervals


def take_screenshot(video_path, timestamp_seconds, output_path):
    """Take screenshot at specific timestamp using ffmpeg."""
    cmd = [
        FFMPEG_PATH,
        '-y',  # Overwrite output file
        '-ss', str(timestamp_seconds),
        '-i', video_path,
        '-frames:v', '1',
        '-q:v', '2',  # High quality
        output_path
    ]
    
    subprocess.run(cmd, capture_output=True, check=True)


def main():
    print("=" * 60)
    print("Garmin VIRB Screenshot Extractor - 100m GPS Intervals")
    print("=" * 60)
    
    # Validate ffmpeg path
    if not os.path.exists(FFMPEG_PATH):
        error_msg = f"ERROR: ffmpeg not found at: {FFMPEG_PATH}\n\n"
        error_msg += "Please update FFMPEG_PATH at the top of this script."
        print(error_msg)
        messagebox.showerror("FFmpeg Not Found", error_msg)
        sys.exit(1)
    
    print(f"Using ffmpeg: {FFMPEG_PATH}\n")
    
    # If command line arguments provided, use those
    if len(sys.argv) >= 2:
        video_path = sys.argv[1]
        gpx_path = sys.argv[2] if len(sys.argv) > 2 else None
        output_dir = sys.argv[3] if len(sys.argv) > 3 else None
    else:
        # Use GUI file dialogs
        print("\nPlease select the video file...")
        video_path = select_video_file()
        
        if not video_path:
            print("No video file selected. Exiting.")
            return
    
    if not os.path.exists(video_path):
        messagebox.showerror("Error", f"Video file not found: {video_path}")
        sys.exit(1)
    
    print(f"\nVideo: {video_path}")
    
    # Get GPX file
    gps_points = None
    gpx_path_used = None
    
    if 'gpx_path' not in locals() or gpx_path is None:
        # Try to find GPX file automatically
        video_base = Path(video_path).stem
        video_dir = Path(video_path).parent
        
        # Try common GPX file naming patterns
        for pattern in [f"{video_base}.gpx", f"{video_base}.GPX"]:
            potential_gpx = video_dir / pattern
            if potential_gpx.exists():
                print(f"Found GPX file: {potential_gpx}")
                gpx_path_used = str(potential_gpx)
                gps_points = parse_gpx_file(str(potential_gpx))
                break
        
        if not gps_points:
            print("\nNo GPX file found automatically. Please select GPX file...")
            gpx_path = select_gpx_file()
            
            if not gpx_path:
                messagebox.showerror("Error", "No GPX file selected. Cannot continue.")
                sys.exit(1)
            
            if not os.path.exists(gpx_path):
                messagebox.showerror("Error", f"GPX file not found: {gpx_path}")
                sys.exit(1)
            
            gpx_path_used = gpx_path
            gps_points = parse_gpx_file(gpx_path)
    else:
        if os.path.exists(gpx_path):
            gpx_path_used = gpx_path
            gps_points = parse_gpx_file(gpx_path)
        else:
            messagebox.showerror("Error", f"GPX file not found: {gpx_path}")
            sys.exit(1)
    
    if not gps_points:
        messagebox.showerror("Error", "No GPS data available")
        sys.exit(1)
    
    print(f"GPX: {gpx_path_used}")
    
    # Get output directory
    if 'output_dir' not in locals() or output_dir is None:
        print("\nPlease select output directory for screenshots...")
        output_dir = select_output_directory()
        
        if not output_dir:
            # Default to same location as video
            output_dir = str(Path(video_path).parent / (Path(video_path).stem + "_screenshots"))
            print(f"No directory selected. Using default: {output_dir}")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output: {output_dir}/")
    
    # Get video info
    video_start_time = get_video_start_time(video_path)
    video_duration = get_video_duration(video_path)
    
    if not video_start_time:
        print("Warning: Could not determine video start time from metadata.")
        print("Using first GPS point time as video start.")
        video_start_time = gps_points[0][0]
    
    print(f"\nVideo duration: {video_duration:.2f} seconds ({video_duration/60:.2f} minutes)")
    print(f"GPS first point time: {gps_points[0][0]}")
    print(f"GPS last point time: {gps_points[-1][0]}")
    gps_duration = (gps_points[-1][0] - gps_points[0][0]).total_seconds()
    print(f"GPS duration: {gps_duration:.2f} seconds ({gps_duration/60:.2f} minutes)")
    
    # Use anchor points for sync
    print("\n" + "=" * 60)
    print("SYNC MODE: Anchor-based interpolation")
    print("=" * 60)
    print(f"Using {len(ANCHOR)} anchor points for accurate sync:")
    for vid_time, gps_time in ANCHOR:
        print(f"  Video {vid_time} <-> GPS {gps_time}")
    
    # Find 100m intervals
    intervals = find_100m_intervals(gps_points)
    
    # Take screenshots using anchor-based mapping
    print(f"\nTaking screenshots...")
    screenshots_taken = 0
    skipped = 0
    
    for i, (timestamp, lat, lon) in enumerate(intervals):
        # Calculate GPS time offset from start
        gps_offset = (timestamp - gps_points[0][0]).total_seconds()
        
        # Convert to video time using anchor points
        video_time = gps_time_to_video_time(gps_offset, gps_points[0][0], ANCHOR)
        
        if video_time is None:
            skipped += 1
            continue
        
        # Debug output for first 10 and every 50th interval
        if i < 10 or i % 50 == 0:
            gps_time_str = str(timedelta(seconds=int(gps_offset)))
            vid_time_str = str(timedelta(seconds=int(video_time)))
            print(f"  [{i:3d}] GPS {gps_time_str} -> Video {vid_time_str} ({int(i*100)}m / {int(i*100/1000)}.{int((i*100)%1000):03d}km)")
        
        # Skip if outside video duration
        if video_time < 0 or video_time > video_duration:
            skipped += 1
            if i < 10:
                print(f"    SKIPPED: video_time={video_time:.2f}s out of range [0, {video_duration:.2f}]")
            continue
        
        # Generate output filename in format STA_XX+XXX.jpg
        distance_meters = int(i * 100)
        kilometers = distance_meters // 1000
        meters = distance_meters % 1000
        output_file = os.path.join(
            output_dir,
            f"STA_{kilometers:02d}+{meters:03d}.jpg"
        )
        
        try:
            take_screenshot(video_path, video_time, output_file)
            screenshots_taken += 1
            if screenshots_taken <= 5 or screenshots_taken % 50 == 0:
                print(f"  [{screenshots_taken}/{len(intervals)}] {Path(output_file).name} (video: {video_time:.2f}s, {int(i*100)}m)")
        except subprocess.CalledProcessError as e:
            print(f"  Error taking screenshot at {video_time:.2f}s: {e}")
    
    print(f"\n" + "=" * 60)
    print(f"Complete! Took {screenshots_taken} screenshots")
    print(f"Skipped: {skipped} intervals (outside video range)")
    print(f"Total intervals found: {len(intervals)}")
    print(f"Output: {output_dir}/")
    print("=" * 60)
    
    if screenshots_taken == 0:
        warning_msg = f"WARNING: No screenshots were taken!\n\n"
        warning_msg += f"Video duration: {video_duration:.2f}s ({video_duration/60:.2f} min)\n"
        warning_msg += f"GPS duration: {gps_duration:.2f}s ({gps_duration/60:.2f} min)\n"
        print(warning_msg)
        messagebox.showwarning("No Screenshots", warning_msg)
    else:
        # Show completion message
        messagebox.showinfo(
            "Complete",
            f"Successfully extracted {screenshots_taken} screenshots!\n\nSaved to:\n{output_dir}"
        )


if __name__ == "__main__":
    main()