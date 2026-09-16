import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import subprocess
import os

FFMPEG_PATH = r"D:\DEV\tools\ffmpeg.exe"

# ---------- Core Logic ----------

def run_ffmpeg(cmd, logbox):
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    while True:
        line = process.stderr.readline()
        if not line:
            break
        logbox.insert(tk.END, line)
        logbox.see(tk.END)
        logbox.update()

    return process.wait()

def is_video_corrupt(path, logbox):
    logbox.insert(tk.END, "=== Checking video integrity ===\n")
    cmd = [
        FFMPEG_PATH,
        "-v", "error",
        "-i", path,
        "-f", "null",
        "-"
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.stderr.strip():
        logbox.insert(tk.END, result.stderr + "\n")
        return True
    else:
        logbox.insert(tk.END, "No decode errors found.\n")
        return False

def repair_video(path, logbox):
    folder = os.path.dirname(path)
    name, ext = os.path.splitext(os.path.basename(path))
    fixed_path = os.path.join(folder, f"{name}_FIXED{ext}")

    logbox.insert(tk.END, "\n=== Attempting repair (remux) ===\n")

    cmd = [
        FFMPEG_PATH,
        "-err_detect", "ignore_err",
        "-i", path,
        "-c", "copy",
        "-movflags", "+faststart",
        fixed_path
    ]

    code = run_ffmpeg(cmd, logbox)

    if code == 0 and os.path.exists(fixed_path):
        logbox.insert(tk.END, f"\nRepair successful:\n{fixed_path}\n")
        messagebox.showinfo("Repair Complete", f"Fixed file created:\n{fixed_path}")
    else:
        logbox.insert(tk.END, "\nRepair failed.\n")
        messagebox.showerror("Repair Failed", "FFmpeg could not repair this file.")

# ---------- UI ----------

def pick_and_check():
    file_path = filedialog.askopenfilename(
        title="Select a video file",
        filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.avi *.webm"), ("All Files", "*.*")]
    )

    if not file_path:
        return

    logbox.delete("1.0", tk.END)
    logbox.insert(tk.END, f"Selected file:\n{file_path}\n\n")

    corrupt = is_video_corrupt(file_path, logbox)

    if corrupt:
        messagebox.showwarning("Result", "Decode errors detected.\nYou can try REPAIR.")
        repair_btn.config(state=tk.NORMAL)
    else:
        messagebox.showinfo("Result", "No corruption detected.\nIf duration is wrong, try REPAIR anyway.")
        repair_btn.config(state=tk.NORMAL)

    repair_btn.file_path = file_path

def repair_selected():
    if hasattr(repair_btn, "file_path"):
        repair_video(repair_btn.file_path, logbox)

root = tk.Tk()
root.title("Video Validator & Repair Tool")
root.geometry("700x400")

top_frame = tk.Frame(root)
top_frame.pack(pady=5)

tk.Button(top_frame, text="Select Video", command=pick_and_check, width=20).pack(side=tk.LEFT, padx=5)

repair_btn = tk.Button(top_frame, text="Repair Video", command=repair_selected, width=20, state=tk.DISABLED)
repair_btn.pack(side=tk.LEFT, padx=5)

logbox = scrolledtext.ScrolledText(root, wrap=tk.WORD)
logbox.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

root.mainloop()
