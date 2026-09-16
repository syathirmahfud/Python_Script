import speedtest
import statistics
import time

N = 5
WAIT_BETWEEN = 2  # seconds

latencies = []
downloads = []
uploads = []

st = speedtest.Speedtest()
st.get_best_server()

for i in range(N):
    print(f"Run {i+1}/{N}")

    latency = st.results.ping
    download = st.download() / 1_000_000  # Mbps
    upload = st.upload() / 1_000_000      # Mbps

    latencies.append(latency)
    downloads.append(download)
    uploads.append(upload)

    time.sleep(WAIT_BETWEEN)

def trimmed_mean(data, trim=0.1):
    k = int(len(data) * trim)
    data_sorted = sorted(data)
    return statistics.mean(data_sorted[k:-k])

print("\n=== RESULTS ===")
print(f"Latency avg (ms): {trimmed_mean(latencies):.2f}")
print(f"Download avg (Mbps): {trimmed_mean(downloads):.2f}")
print(f"Upload avg (Mbps): {trimmed_mean(uploads):.2f}")
