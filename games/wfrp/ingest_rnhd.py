import os
import re
import json
import sqlite3
import sys

# Add parent directory to path to import db
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wfrp.db import get_connection

def parse_markdown():
    manifest_path = os.path.join(os.path.dirname(__file__), "rules", "wfrp-4e-rough-nights-and-hard-days", "manifest.json")
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM module_catalog WHERE slug = 'rough-nights-and-hard-days'")
    row = c.fetchone()
    if not row:
        print("Module not found")
        return
    module_id = row['id']

    c.execute("SELECT id, title FROM module_chapters WHERE module_id = ?", (module_id,))
    chapter_id_map = {r['title']: r['id'] for r in c.fetchall()}
    
    c.execute("DELETE FROM module_plots WHERE chapter_id IN (SELECT id FROM module_chapters WHERE module_id = ?)", (module_id,))
    c.execute("DELETE FROM module_events WHERE chapter_id IN (SELECT id FROM module_chapters WHERE module_id = ?)", (module_id,))
    c.execute("DELETE FROM module_npcs WHERE module_id = ?", (module_id,))
    
    current_chapter_id = None
    current_plot_title = None
    current_plot_desc = []
    
    current_event_label = None
    current_event_desc = []
    
    current_npc_name = None
    current_npc_stats = None
    current_npc_desc = []
    
    plots_inserted = 0
    events_inserted = 0
    npcs_inserted = 0
    
    def flush_plot():
        nonlocal plots_inserted, current_plot_title, current_plot_desc
        if current_plot_title and current_chapter_id:
            desc = '\n'.join(current_plot_desc).strip()
            c.execute("INSERT INTO module_plots (chapter_id, title, description) VALUES (?, ?, ?)", 
                      (current_chapter_id, current_plot_title, desc))
            plots_inserted += 1
        current_plot_title = None
        current_plot_desc = []

    def flush_event():
        nonlocal events_inserted, current_event_label, current_event_desc
        if current_event_label and current_chapter_id:
            desc = '\n'.join(current_event_desc).strip()
            # Try to assign a simple sort key based on parsing the time label or just incrementing
            c.execute("INSERT INTO module_events (chapter_id, time_label, time_sort_key, description, related_plot_ids_json) VALUES (?, ?, ?, ?, ?)", 
                      (current_chapter_id, current_event_label, events_inserted, desc, "[]"))
            events_inserted += 1
        current_event_label = None
        current_event_desc = []

    def flush_npc():
        nonlocal npcs_inserted, current_npc_name, current_npc_desc, current_npc_stats
        if current_npc_name:
            desc = '\n'.join(current_npc_desc).strip()
            stats_str = json.dumps(current_npc_stats) if current_npc_stats else "{}"
            c.execute("INSERT INTO module_npcs (module_id, name, description, stats_json) VALUES (?, ?, ?, ?)", 
                      (module_id, current_npc_name, desc, stats_str))
            npcs_inserted += 1
        current_npc_name = None
        current_npc_desc = []
        current_npc_stats = None

    # Helper regex
    plot_re = re.compile(r'^(?:#|\*\*)\s*(Plot\s+\d+\s*[-–]\s*.*?)(?:\*\*|$)')
    time_re = re.compile(r'^(?:#|\*\*)\s*(\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)|Midnight|\d{1,2}\s*midnight|Noon|Angestag.*?|Two Rounds Later.*?|Festag Morning.*?)(?:\*\*|$)')
    npc_name_re = re.compile(r'^(?:#|\*\*)\s*(.*?)(?:\*\*|$)')
    stat_header_re = re.compile(r'^\|?\s*M\s*\|\s*WS\s*\|\s*BS\s*\|\s*S\s*\|\s*T\s*\|\s*I\s*\|\s*Agi\s*\|\s*Dex\s*\|\s*Int\s*\|\s*WP\s*\|\s*Fel\s*\|\s*W\s*\|?')
    
    parsing_mode = "general" # 'plot', 'event', 'npc'
    
    for item in manifest:
        chapter_name = item.get('chapter')
        if chapter_name not in chapter_id_map:
            continue
            
        new_chapter_id = chapter_id_map[chapter_name]
        if new_chapter_id != current_chapter_id:
            flush_plot()
            flush_event()
            flush_npc()
            current_chapter_id = new_chapter_id
            
        md_path = os.path.join(os.path.dirname(__file__), "rules", item['file'])
        if not os.path.exists(md_path):
            continue
            
        with open(md_path, 'r') as f:
            lines = f.readlines()
            
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            # Skip blockquotes (source indicators)
            if line.startswith('> Source:') or line.startswith('> Section:'):
                continue
                
            # Check for plot
            plot_match = plot_re.match(line)
            if plot_match:
                flush_plot()
                flush_event()
                flush_npc()
                current_plot_title = plot_match.group(1).strip()
                parsing_mode = "plot"
                continue
                
            # Check for event
            time_match = time_re.match(line)
            if time_match:
                flush_plot()
                flush_event()
                flush_npc()
                current_event_label = time_match.group(1).strip()
                parsing_mode = "event"
                continue
                
            # Check for NPC Stats Table
            if stat_header_re.match(line):
                # We found a stat block! Let's get the values from 2 lines down.
                try:
                    if i + 2 < len(lines):
                        val_line = lines[i+2].strip()
                        if val_line.startswith('|'):
                            parts = [p.strip() for p in val_line.split('|') if p.strip()]
                            if len(parts) >= 12:
                                flush_plot()
                                flush_event()
                                # We need the NPC name. It is either the heading directly before, or directly after.
                                possible_name = ""
                                if i > 0 and npc_name_re.match(lines[i-1].strip()):
                                    possible_name = npc_name_re.match(lines[i-1].strip()).group(1)
                                elif i + 4 < len(lines) and npc_name_re.match(lines[i+4].strip()):
                                    possible_name = npc_name_re.match(lines[i+4].strip()).group(1)
                                elif i + 3 < len(lines) and npc_name_re.match(lines[i+3].strip()):
                                    possible_name = npc_name_re.match(lines[i+3].strip()).group(1)
                                
                                if not possible_name:
                                    possible_name = f"Unknown NPC (Page {item['page']})"
                                    
                                # If we were already building this NPC, don't flush if it's the same
                                if current_npc_name != possible_name:
                                    flush_npc()
                                    current_npc_name = possible_name
                                
                                current_npc_stats = {
                                    'M': parts[0], 'WS': parts[1], 'BS': parts[2], 'S': parts[3], 
                                    'T': parts[4], 'I': parts[5], 'Ag': parts[6], 'Dex': parts[7], 
                                    'Int': parts[8], 'WP': parts[9], 'Fel': parts[10], 'W': parts[11]
                                }
                                parsing_mode = "npc"
                                continue
                except Exception as e:
                    pass

            # Append content to current mode
            if parsing_mode == "plot" and current_plot_title:
                current_plot_desc.append(line)
            elif parsing_mode == "event" and current_event_label:
                current_event_desc.append(line)
            elif parsing_mode == "npc" and current_npc_name:
                if not line.startswith('|'):
                    current_npc_desc.append(line)

    flush_plot()
    flush_event()
    flush_npc()
    
    # Finally, assign captions and chapter_ids to images based on the page number
    # Image path: /images/modules/rough-nights-and-hard-days/page_X_img_Y.jpeg
    c.execute("SELECT id, image_path FROM module_images WHERE module_id = ?", (module_id,))
    for row in c.fetchall():
        img_id = row['id']
        path = row['image_path']
        m = re.search(r'page_(\d+)_', path)
        if m:
            page_num = int(m.group(1)) # 0-indexed in PDF!
            # Find which chapter this page belongs to
            # The manifest page is 1-indexed (p03 -> page=3)
            # PDF page 0 is page 1 in book. Wait, pymupdf is 0-indexed, so page_0 = cover = p01.
            # So pdf page_num + 1 = book page num.
            book_page_num = page_num + 1
            matching_chapter = None
            for item in manifest:
                if item.get('page') == book_page_num:
                    ch = item.get('chapter')
                    if ch in chapter_id_map:
                        matching_chapter = chapter_id_map[ch]
                        break
            if matching_chapter:
                c.execute("UPDATE module_images SET chapter_id = ? WHERE id = ?", (matching_chapter, img_id))

    conn.commit()
    conn.close()
    print(f"Inserted {plots_inserted} plots, {events_inserted} events, {npcs_inserted} NPCs.")
    print("Updated images with chapter IDs.")

if __name__ == '__main__':
    parse_markdown()
