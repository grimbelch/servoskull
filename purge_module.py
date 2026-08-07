import sqlite3
import shutil
import os
from pathlib import Path

def purge_db(db_path):
    if not os.path.exists(db_path):
        print(f"Database {db_path} does not exist, skipping.")
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    tables = ["module_catalog", "module_chapters", "module_plots", "module_events", "module_npcs", "module_images", "campaign_module_state"]
    for t in tables:
        try:
            cur.execute(f"DELETE FROM {t};")
            print(f"Cleared table {t} in {db_path}")
        except Exception as e:
            print(f"Could not clear table {t} in {db_path}: {e}")
            
    conn.commit()
    conn.close()

# Purge local DBs
local_db1 = Path.home() / ".config" / "omega7" / "campaigns" / "skull_campaigns.db"
purge_db(str(local_db1))

local_db2 = Path("/Users/sean/Desktop/Servoskull/games/games.db")
purge_db(str(local_db2))

# Purge ripped images
images_dir = Path("/Users/sean/Desktop/Servoskull/games/images/modules")
if images_dir.exists():
    shutil.rmtree(images_dir)
    print(f"Removed images directory {images_dir}")

# List of temporary ingestion scripts to delete
scripts_to_remove = [
    "/Users/sean/Desktop/Servoskull/populate_module_data.py",
    "/Users/sean/Desktop/Servoskull/rip_correct_module_images.py",
    "/Users/sean/Desktop/Servoskull/clip_perfect_images.py",
    "/Users/sean/Desktop/Servoskull/extract_full_module_text.py",
    "/Users/sean/Desktop/Servoskull/clip_full_module_images.py",
    "/Users/sean/Desktop/Servoskull/ingest_full_module.py",
    "/Users/sean/Desktop/Servoskull/clip_true_portraits.py",
    "/Users/sean/Desktop/Servoskull/run_20_spot_checks.py"
]

for s in scripts_to_remove:
    if os.path.exists(s):
        os.remove(s)
        print(f"Removed script {s}")

print("Local module purge complete!")
