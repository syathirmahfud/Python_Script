# Renamed Python collection

All 50 Python source files (including one inside files.zip) and two notebooks have descriptive snake_case filenames. Existing directories are retained so relative data paths keep their locations. See RENAME_MAP.csv for every old/new path. Version variants remain separate; a higher version number is not a reliability endorsement.

## Validation

- All 50 Python sources parse successfully, including the empty placeholder.
- Executable AST structure matches the originals after accounting for renamed filename strings. No algorithms were changed.
- Existing script filename references were updated in usage messages, comments, docstrings and GPX creator strings. No imports between the renamed local scripts were found.
- 17 other files were verified byte-for-byte unchanged. The nested files.zip was rebuilt to rename its one Python source; its GPX data is preserved.
- Notebooks were renamed only; their contents were preserved.
- This is static verification, not a runtime certification. GUI workflows, external programs and data processing were not executed.

## Existing limitations

- retime_gpx_empty_placeholder.py is empty in the original archive and remains empty.
- Several scripts use fixed Windows paths, external tools (FFmpeg, ExifTool or Ghostscript), or specific input data. These still require the original environment or manual configuration.
- Shortcuts, scheduled tasks and commands outside this archive must be updated using RENAME_MAP.csv.
- Original variants and all supplied data remain included. This task does not verify engineering calculations, model accuracy, or dataset quality.

## Examples

- Extract_100/extract_blackvue_frames_100m.py
- build_pdf/generate_road_photo_report_inset_sarolangun_pdf.py
- KMZ JEMBATAN/enrich_bridge_kmz_from_pkrms_excel.py
- KMZ JEMBATAN/convert_bridge_kmz_to_shapefile_ready.py
- decompress/compress_pdf_ghostscript_gui.py

Run a script from its existing directory with your configured Python environment, using its new filename.
