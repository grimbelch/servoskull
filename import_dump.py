import sqlite3
import sys

db_path = "/home/sspeer/.config/omega7/campaigns/skull_campaigns.db"
sql_file = "/home/sspeer/skull/modules_data.sql"

try:
    with open(sql_file, "r") as f:
        sql = f.read()
    
    conn = sqlite3.connect(db_path)
    
    # Optional: Delete existing module records to avoid unique constraint errors during import
    conn.executescript("""
    DELETE FROM module_images;
    DELETE FROM module_npcs;
    DELETE FROM module_events;
    DELETE FROM module_plots;
    DELETE FROM module_chapters;
    DELETE FROM module_catalog;
    """)
    
    conn.executescript(sql)
    conn.commit()
    conn.close()
    print("Import successful.")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
