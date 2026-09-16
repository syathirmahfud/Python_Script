import subprocess
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

GS_PATH = r"C:\Program Files\gs\gs10.06.0\bin\gswin64c.exe"

def run_compression(input_pdf, output_pdf, quality, progress, root):
    try:
        cmd = [
            GS_PATH,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS=/{quality}",
            "-dNOPAUSE",
            "-dBATCH",
            "-dQUIET",
            f"-sOutputFile={output_pdf}",
            input_pdf
        ]

        subprocess.run(cmd, check=True)

        root.after(0, lambda: messagebox.showinfo(
            "Done",
            "PDF compression completed successfully."
        ))

    except Exception as e:
        root.after(0, lambda: messagebox.showerror(
            "Error",
            f"Compression failed:\n{e}"
        ))

    finally:
        root.after(0, progress.stop)
        root.after(0, lambda: progress.pack_forget())


def start_compression():
    input_pdf = filedialog.askopenfilename(
        title="Select PDF to compress",
        filetypes=[("PDF files", "*.pdf")]
    )
    if not input_pdf:
        return

    output_pdf = filedialog.asksaveasfilename(
        title="Save compressed PDF as",
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")]
    )
    if not output_pdf:
        return

    quality = quality_var.get()

    progress.pack(pady=10)
    progress.start(10)

    t = threading.Thread(
        target=run_compression,
        args=(input_pdf, output_pdf, quality, progress, root),
        daemon=True
    )
    t.start()


# ================= UI =================
root = tk.Tk()
root.title("PDF Compressor (Ghostscript)")
root.geometry("420x200")
root.resizable(False, False)

tk.Label(root, text="Compression quality:").pack(pady=(15, 5))

quality_var = tk.StringVar(value="ebook")
quality_menu = ttk.Combobox(
    root,
    textvariable=quality_var,
    values=["screen", "ebook", "printer"],
    state="readonly",
    width=15
)
quality_menu.pack()

tk.Button(
    root,
    text="Select PDF and Compress",
    command=start_compression,
    height=2
).pack(pady=15)

progress = ttk.Progressbar(
    root,
    mode="determinate",
    length=300
)

root.mainloop()
