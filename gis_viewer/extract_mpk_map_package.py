import zipfile
import os
from pathlib import Path

def extract_mpk(mpk_file, output_folder=None):
    """
    Extract .mpk file (it's actually a ZIP archive)
    Returns list of found shapefiles and geodatabases
    """
    if not os.path.exists(mpk_file):
        print(f"Error: File not found: {mpk_file}")
        return None
    
    # Create output folder if not specified
    if output_folder is None:
        mpk_name = Path(mpk_file).stem
        output_folder = f"extracted_{mpk_name}"
    
    # Create output directory
    os.makedirs(output_folder, exist_ok=True)
    
    try:
        print(f"Attempting to extract: {mpk_file}")
        print(f"Output folder: {output_folder}\n")
        
        # Try to open as ZIP
        with zipfile.ZipFile(mpk_file, 'r') as zip_ref:
            # List contents
            print("Archive contents:")
            for name in zip_ref.namelist()[:10]:  # Show first 10 files
                print(f"  - {name}")
            if len(zip_ref.namelist()) > 10:
                print(f"  ... and {len(zip_ref.namelist()) - 10} more files\n")
            
            # Extract all
            print("Extracting files...")
            zip_ref.extractall(output_folder)
            print(f"✓ Extracted to: {output_folder}\n")
        
        # Search for GIS data
        shapefiles = []
        geodatabases = []
        
        print("Searching for GIS data...")
        for root, dirs, files in os.walk(output_folder):
            # Find shapefiles
            for file in files:
                if file.endswith('.shp'):
                    shp_path = os.path.join(root, file)
                    shapefiles.append(shp_path)
                    print(f"✓ Found shapefile: {shp_path}")
            
            # Find geodatabases
            for dir_name in dirs:
                if dir_name.endswith('.gdb'):
                    gdb_path = os.path.join(root, dir_name)
                    geodatabases.append(gdb_path)
                    print(f"✓ Found geodatabase: {gdb_path}")
        
        # Summary
        print(f"\n=== SUMMARY ===")
        print(f"Shapefiles found: {len(shapefiles)}")
        print(f"Geodatabases found: {len(geodatabases)}")
        
        if not shapefiles and not geodatabases:
            print("\n⚠ No shapefiles or geodatabases found in the archive.")
            print("The .mpk might contain other data formats or be encrypted.")
        
        return {
            'shapefiles': shapefiles,
            'geodatabases': geodatabases,
            'output_folder': output_folder
        }
        
    except zipfile.BadZipFile:
        print("Error: File is not a valid ZIP archive.")
        print("\nThis .mpk file might be:")
        print("  1. Encrypted or password-protected")
        print("  2. Using a newer ArcGIS format that's not a simple ZIP")
        print("  3. Corrupted")
        print("\nSuggestions:")
        print("  - Try opening it in ArcGIS Desktop/Pro")
        print("  - Check if the file is complete and not corrupted")
        print("  - Ask the file creator about the ArcGIS version used")
        return None
        
    except Exception as e:
        print(f"Error: {e}")
        return None


def extract_mpk_interactive():
    """Interactive version - asks for file path"""
    print("=== MPK File Extractor ===\n")
    
    mpk_file = input("Enter path to .mpk file: ").strip().strip('"')
    
    if not mpk_file:
        print("No file specified.")
        return
    
    if not os.path.exists(mpk_file):
        print(f"File not found: {mpk_file}")
        return
    
    output_folder = input("Enter output folder (press Enter for default): ").strip()
    if not output_folder:
        output_folder = None
    
    result = extract_mpk(mpk_file, output_folder)
    
    if result and (result['shapefiles'] or result['geodatabases']):
        print("\n=== Next Steps ===")
        print("You can now open these files in the GIS Viewer:")
        print("  python view_gis_layers_gui.py")
        print("\nOr use geopandas to read them:")
        if result['shapefiles']:
            print(f"  import geopandas as gpd")
            print(f"  gdf = gpd.read_file('{result['shapefiles'][0]}')")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        # Command line usage
        mpk_file = sys.argv[1]
        output_folder = sys.argv[2] if len(sys.argv) > 2 else None
        extract_mpk(mpk_file, output_folder)
    else:
        # Interactive mode
        extract_mpk_interactive()