import gpxpy
import datetime

def modify_gpx_timestamps(input_file, output_file):
    """
    Modifies the timestamps in a GPX file to have a 2-second interval.

    Args:
        input_file: The path to the input GPX file.
        output_file: The path to the output GPX file.
    """

    gpx = gpxpy.parse(open(input_file, 'r'))

    # Calculate the start time from the first track point
    start_time = gpx.tracks[0].segments[0].points[0].time

    # Iterate over all track points and modify their timestamps
    for track in gpx.tracks:
        for segment in track.segments:
            for i, point in enumerate(segment.points):
                point.time = start_time + datetime.timedelta(seconds=i * 2)

    # Write the modified GPX data to the output file
    with open(output_file, 'w') as f:
        f.write(gpx.to_xml())

# Example usage
input_file = "D:\\15.02. MERANGIN\\2026\\FILE VIDEO RENDER\\15.02.21.001 Jalan Simpang Sumber Agung - Batas Tebo.mp4.gpx"
output_file = "D:\\15.02. MERANGIN\\2026\\FILE VIDEO RENDER\\15.02.21.001 Jalan Simpang Sumber Agung - Batas Tebo.mp4--00.gpx"
modify_gpx_timestamps(input_file, output_file)