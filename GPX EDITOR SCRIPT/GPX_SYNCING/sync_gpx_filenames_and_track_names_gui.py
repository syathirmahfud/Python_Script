import os
import re
import glob
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

INVALID_FILENAME_CHARS = r'<>:"/\|?*'


def sanitize_filename(name):
    for ch in INVALID_FILENAME_CHARS:
        name = name.replace(ch, "_")
    return name.strip()


def get_gpx_name(filepath):
    """Read the <name> tag from a GPX file. Returns (name_text, error_message)."""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        ns = {"gpx": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

        if ns:
            name_elem = root.find("gpx:name", ns)
            if name_elem is None:
                name_elem = root.find(".//gpx:trk/gpx:name", ns)
        else:
            name_elem = root.find("name")
            if name_elem is None:
                name_elem = root.find(".//trk/name")

        if name_elem is None or not name_elem.text:
            return None, None
        return name_elem.text.strip(), None

    except ET.ParseError as e:
        return None, f"Parse error: {e}"


class GpxCheckerApp:
    def __init__(self, root):
        self.root = root
        root.title("GPX Filename Checker")
        root.geometry("900x550")

        top = tk.Frame(root)
        top.pack(fill="x", padx=10, pady=10)

        self.folder_var = tk.StringVar()
        tk.Entry(top, textvariable=self.folder_var).pack(side="left", fill="x", expand=True)
        tk.Button(top, text="Browse...", command=self.browse_folder).pack(side="left", padx=5)
        tk.Button(top, text="Scan", command=self.scan_folder).pack(side="left")

        columns = ("filename", "gpx_name", "status")
        self.tree = ttk.Treeview(root, columns=columns, show="headings")
        self.tree.heading("filename", text="Filename")
        self.tree.heading("gpx_name", text="Name inside GPX")
        self.tree.heading("status", text="Status")
        self.tree.column("filename", width=320)
        self.tree.column("gpx_name", width=320)
        self.tree.column("status", width=180)
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Color tags for quick visual scanning
        self.tree.tag_configure("match", foreground="#2e7d32")
        self.tree.tag_configure("mismatch", foreground="#c62828")
        self.tree.tag_configure("noname", foreground="#f9a825")
        self.tree.tag_configure("error", foreground="#8e24aa")

        bottom = tk.Frame(root)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        self.summary_label = tk.Label(bottom, text="No scan yet.")
        self.summary_label.pack(side="left")
        tk.Button(bottom, text="Export mismatches to .txt", command=self.export_mismatches).pack(side="right")

        actions = tk.Frame(root)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(
            actions, text="Rename FILES to match GPX <name>", bg="#ffe0b2",
            command=self.rename_files_to_gpx_name
        ).pack(side="left", padx=(0, 10))
        tk.Button(
            actions, text="Rewrite GPX <name> to match FILENAME", bg="#ffe0b2",
            command=self.update_gpx_name_to_filename
        ).pack(side="left")

        self.results = []       # store (filename, gpx_name, status_text)
        self.filepaths = []     # parallel list of full paths, same order as self.results

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_var.set(folder)

    def scan_folder(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please choose a valid folder first.")
            return

        for row in self.tree.get_children():
            self.tree.delete(row)
        self.results.clear()
        self.filepaths.clear()

        gpx_files = sorted(glob.glob(os.path.join(folder, "*.gpx")))
        if not gpx_files:
            messagebox.showinfo("No files", "No .gpx files found in that folder.")
            return

        match_count = 0
        mismatch_count = 0
        noname_count = 0
        error_count = 0

        for filepath in gpx_files:
            filename = os.path.splitext(os.path.basename(filepath))[0]
            gpx_name, err = get_gpx_name(filepath)

            if err:
                status, tag = "PARSE ERROR", "error"
                error_count += 1
            elif gpx_name is None:
                status, tag = "NO NAME TAG", "noname"
                noname_count += 1
            elif gpx_name == filename:
                status, tag = "OK", "match"
                match_count += 1
            else:
                status, tag = "MISMATCH", "mismatch"
                mismatch_count += 1

            display_gpx_name = gpx_name if gpx_name else (err if err else "-")
            self.tree.insert("", "end", values=(filename + ".gpx", display_gpx_name, status), tags=(tag,))
            self.results.append((filename + ".gpx", display_gpx_name, status))
            self.filepaths.append(filepath)

        total = len(gpx_files)
        self.summary_label.config(
            text=f"Total: {total}   |   OK: {match_count}   Mismatch: {mismatch_count}   "
                 f"No name tag: {noname_count}   Errors: {error_count}"
        )

    def export_mismatches(self):
        if not self.results:
            messagebox.showinfo("Nothing to export", "Run a scan first.")
            return

        problems = [r for r in self.results if r[2] != "OK"]
        if not problems:
            messagebox.showinfo("Nothing to export", "No mismatches found — everything matches.")
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile="gpx_mismatches.txt",
            filetypes=[("Text file", "*.txt")],
        )
        if not save_path:
            return

        with open(save_path, "w", encoding="utf-8") as f:
            for filename, gpx_name, status in problems:
                f.write(f"[{status}] {filename}  -->  {gpx_name}\n")

        messagebox.showinfo("Exported", f"Saved {len(problems)} entries to:\n{save_path}")

    def _mismatched_indices(self):
        """Indices of rows that are MISMATCH (skips OK, NO NAME TAG, PARSE ERROR)."""
        return [i for i, r in enumerate(self.results) if r[2] == "MISMATCH"]

    def rename_files_to_gpx_name(self):
        if not self.results:
            messagebox.showinfo("Nothing to do", "Run a scan first.")
            return

        idxs = self._mismatched_indices()
        if not idxs:
            messagebox.showinfo("Nothing to do", "No mismatches found.")
            return

        preview = "\n".join(
            f"{self.results[i][0]}  -->  {self.results[i][1]}.gpx" for i in idxs[:10]
        )
        more = f"\n...and {len(idxs) - 10} more" if len(idxs) > 10 else ""
        if not messagebox.askyesno(
            "Confirm rename",
            f"This will rename {len(idxs)} file(s) on disk to match the name "
            f"inside each GPX. This cannot be undone.\n\nBack up the folder first "
            f"if you haven't already.\n\nPreview:\n{preview}{more}\n\nProceed?",
        ):
            return

        renamed, skipped_dupe, failed = 0, 0, 0
        for i in idxs:
            old_path = self.filepaths[i]
            folder = os.path.dirname(old_path)
            new_base = sanitize_filename(self.results[i][1])
            new_path = os.path.join(folder, new_base + ".gpx")

            if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(old_path):
                skipped_dupe += 1
                continue
            try:
                os.rename(old_path, new_path)
                renamed += 1
            except OSError:
                failed += 1

        messagebox.showinfo(
            "Done",
            f"Renamed: {renamed}\nSkipped (target name already exists): {skipped_dupe}\nFailed: {failed}",
        )
        self.scan_folder()

    def update_gpx_name_to_filename(self):
        if not self.results:
            messagebox.showinfo("Nothing to do", "Run a scan first.")
            return

        idxs = self._mismatched_indices()
        if not idxs:
            messagebox.showinfo("Nothing to do", "No mismatches found.")
            return

        preview = "\n".join(
            f"{self.results[i][0]}: '{self.results[i][1]}' --> '{os.path.splitext(self.results[i][0])[0]}'"
            for i in idxs[:10]
        )
        more = f"\n...and {len(idxs) - 10} more" if len(idxs) > 10 else ""
        if not messagebox.askyesno(
            "Confirm rewrite",
            f"This will edit {len(idxs)} .gpx file(s) in place, changing only the "
            f"text inside the first <name>...</name> tag to match the filename. "
            f"Everything else in each file stays untouched. This cannot be undone.\n\n"
            f"Back up the folder first if you haven't already.\n\nPreview:\n{preview}{more}\n\nProceed?",
        ):
            return

        updated, failed = 0, 0
        for i in idxs:
            filepath = self.filepaths[i]
            new_name = os.path.splitext(os.path.basename(filepath))[0]
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()

                escaped_new_name = (
                    new_name.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                # Replace only the first <name>...</name> occurrence's inner text,
                # leaving every other byte of the file (tags, attributes, whitespace) untouched.
                new_content, count = re.subn(
                    r"(<name>).*?(</name>)",
                    lambda m: m.group(1) + escaped_new_name + m.group(2),
                    content,
                    count=1,
                    flags=re.DOTALL,
                )

                if count == 0:
                    failed += 1
                    continue

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                updated += 1
            except OSError:
                failed += 1

        messagebox.showinfo("Done", f"Updated: {updated}\nFailed / no <name> tag found: {failed}")
        self.scan_folder()


if __name__ == "__main__":
    root = tk.Tk()
    app = GpxCheckerApp(root)
    root.mainloop()