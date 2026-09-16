import cv2
import gpxpy
import haversine as hs
from tqdm import tqdm

def capture_screenshots_at_distance(video_path, gpx_file_path, distance_interval=0.2):
    """
    Captures screenshots from a video at specific distance intervals based on a GPX file.

    Args:
        video_path: Path to the video file.
        gpx_file_path: Path to the GPX file containing GPS data.
        distance_interval: Distance interval (in kilometers) at which to capture screenshots.

    Returns:
        None
    """

    # Parse the GPX file
    with open(gpx_file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    # Open video file
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return

    # Get video frame rate and total number of frames
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Initialize variables
    prev_point = None
    total_distance = 0
    frame_count = 0

    # Create progress bar
    with tqdm(total=total_frames, desc="Processing video", unit="frame") as pbar:
        while cap.isOpened():
            ret, frame = cap.read()

            if not ret:
                break

            # Get the closest GPX point for the current frame
            curr_point = min(gpx.tracks[0].segments[0].points,
                             key=lambda p: abs(p.time - frame_count / fps))

            if prev_point:
                distance = hs.haversine((prev_point.latitude, prev_point.longitude),
                                        (curr_point.latitude, curr_point.longitude))
                total_distance += distance

                if total_distance >= distance_interval:
                    screenshot_filename = f"screenshot_{frame_count}.jpg"
                    cv2.imwrite(screenshot_filename, frame)
                    print(f"Captured screenshot: {screenshot_filename} at distance {total_distance:.2f} km")
                    total_distance = 0

            prev_point = curr_point
            pbar.update(1)
            frame_count += 1

    cap.release()
    cv2.destroyAllWindows()

# Example usage
video_path = "D:\\FILE SYATHIR\\PY\\screenshooter\\226.mp4" 
gpx_file_path = "D:\\FILE SYATHIR\\PY\\screenshooter\\226.mp4.gpx"
capture_screenshots_at_distance(video_path, gpx_file_path)