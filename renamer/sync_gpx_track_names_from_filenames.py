import os
import re

FOLDER = r"D:\15.02. MERANGIN\2025\Bina Marga\SURVEY KONDISI JALAN\DATA GPX JALAN MERANGIN"

for file in os.listdir(FOLDER):
    if not file.lower().endswith(".gpx"):
        continue

    path = os.path.join(FOLDER, file)
    new_name = os.path.splitext(file)[0]

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace ONLY the first <name>...</name>
    new_content, count = re.subn(
        r"<name>.*?</name>",
        f"<name>{new_name}</name>",
        content,
        count=1,
        flags=re.DOTALL
    )

    if count == 1:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"UPDATED: {file}")
    else:
        print(f"SKIPPED (no <name>): {file}")
