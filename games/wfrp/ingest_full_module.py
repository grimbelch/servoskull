#!/usr/bin/env python3
"""Complete re-extraction of Rough Nights & Hard Days from PDF to database.

Reads the PDF directly with PyMuPDF, extracts:
- 5 chapters with location descriptions
- ~35 plot threads (7 per chapter)
- ~100+ timed events with sort keys
- ~80+ NPCs with full stat blocks, skills, talents, trappings
- ~138 artwork images with transparency and NPC linkage

Usage: python3 -m games.wfrp.ingest_full_module
"""
import fitz
import json
import os
import re
import sqlite3
import sys

# ─── Configuration ────────────────────────────────────────────────────────────

PDF_PATH = os.path.join(os.path.dirname(__file__), "rules", "modules",
                        "[WFRP][4E] - Rough Nights and Hard Days.pdf")
IMG_DIR = os.path.join(os.path.dirname(__file__), "rules",
                       "wfrp-4e-rough-nights-and-hard-days", "images")
DB_PATH = os.path.expanduser("~/.config/omega7/campaigns/skull_campaigns.db")

MODULE_SLUG = "rough-nights-and-hard-days"
MODULE_TITLE = "Rough Nights and Hard Days"
MODULE_DESC = "Five grim and perilous scenarios by Graeme Davis."

# Chapter definitions: (chapter_number, title, location_name, location_description, book_page_start, book_page_end)
CHAPTERS = [
    (1, "A Rough Night at the Three Feathers", "The Three Feathers Inn",
     "A large coaching inn on the River Reik between Altdorf and Kemperbad, featuring a main bar, dormitory, private rooms, and a riverside dock.",
     8, 23),
    (2, "A Day at the Trials", "Kemperbad Courthouse",
     "A grand courthouse and town square in the free town of Kemperbad, featuring a temporary arena for trial by combat and holding cells.",
     24, 37),
    (3, "A Night at the Opera", "Staatsoper Theatre, Nuln",
     "A lavish opera house in the wealthy Altestadt district of Nuln, featuring a grand lobby, upper gallery, and exclusive ducal boxes.",
     38, 55),
    (4, "Nastassia's Wedding", "Schloss Grauenberg",
     "An aging but well-fortified castle perched high above the River Bögen in central Reikland, featuring a formal garden, solar tower, and multiple wings.",
     56, 69),
    (5, "Lord of Ubersreik", "Niederstadt Haus",
     "A modest 3-storey dressed stone mansion in the Morgenseite district of Ubersreik, serving as the venue for an opulent masquerade ball.",
     70, 87),
]

KNOWN_EXTRA_PREFIXES = ("Skills:", "Talents:", "Traits:", "Trappings:", "Spells:", "Miracles:", "Blessings:")

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def clear_module(conn, module_id):
    """Remove all existing data for this module."""
    c = conn.cursor()
    c.execute("DELETE FROM module_images WHERE module_id = ?", (module_id,))
    c.execute("DELETE FROM module_npcs WHERE module_id = ?", (module_id,))
    c.execute("DELETE FROM module_events WHERE chapter_id IN (SELECT id FROM module_chapters WHERE module_id = ?)", (module_id,))
    c.execute("DELETE FROM module_plots WHERE chapter_id IN (SELECT id FROM module_chapters WHERE module_id = ?)", (module_id,))
    c.execute("DELETE FROM module_chapters WHERE module_id = ?", (module_id,))
    c.execute("DELETE FROM module_catalog WHERE id = ?", (module_id,))
    conn.commit()


# ─── Text Extraction ─────────────────────────────────────────────────────────

def get_chapter_text(doc, book_start, book_end):
    """Extract all text for a chapter's page range."""
    texts = []
    for book_page in range(book_start, book_end + 1):
        pdf_page = book_page - 1  # PDF is 0-indexed
        if 0 <= pdf_page < len(doc):
            page = doc[pdf_page]
            texts.append(page.get_text("text"))
    return "\n".join(texts)


# ─── Plot Parsing ─────────────────────────────────────────────────────────────

def extract_plots(chapter_text):
    """Extract plot summaries from chapter text."""
    plots = []
    plot_pattern = re.compile(
        r'Plot\s+(\d+)\s*[–\-—]\s*(.+?)(?:\n|$)',
        re.IGNORECASE
    )
    matches = list(plot_pattern.finditer(chapter_text))
    
    for i, match in enumerate(matches):
        plot_num = match.group(1)
        plot_title = match.group(2).strip()
        title = f"Plot {plot_num} – {plot_title}"
        
        start = match.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            events_match = re.search(r'\n(?:Events|Timeline|\d{1,2}[:\.]?\d{0,2}\s*(?:a\.m\.|p\.m\.|AM|PM))', chapter_text[start:])
            if events_match:
                end = start + events_match.start()
            else:
                end = start + 800
        
        desc = chapter_text[start:end].strip()
        desc = re.sub(r'\n\d+\n', '\n', desc)
        desc = re.sub(r'\nWARHAMMER FANTASY ROLEPL\s*AY\n', '\n', desc)
        desc = re.sub(r'\nA ROUGH NIGHT AT THE THREE FEATHERS\n', '\n', desc)
        desc = re.sub(r'\nA DAY AT THE TRIALS\n', '\n', desc)
        desc = re.sub(r'\nA NIGHT AT THE OPERA\n', '\n', desc)
        desc = re.sub(r"\nNASTASSIA'S WEDDING\n", '\n', desc)
        desc = re.sub(r'\nLORD OF UBERSREIK\n', '\n', desc)
        desc = re.sub(r'\n[IVXLCDM]+\n', '\n', desc)
        desc = desc.strip()
        
        if len(desc) > 1200:
            cut = desc[:1200].rfind('.')
            if cut > 400:
                desc = desc[:cut+1]
        
        plots.append({"title": title, "description": desc})
    
    seen_titles = set()
    unique_plots = []
    for p in plots:
        norm = re.sub(r'\s+', ' ', p['title'].lower().strip())
        if norm not in seen_titles:
            seen_titles.add(norm)
            unique_plots.append(p)
    
    return unique_plots


# ─── Event Parsing ────────────────────────────────────────────────────────────

TIME_PATTERNS = [
    re.compile(r'^(\d{1,2}[:\.]?\d{0,2}\s*(?:a\.m\.|p\.m\.|am|pm))\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^(Midnight|Noon)\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^((?:Angestag|Festag|Wellentag|Aubentag|Marktag|Backertag|Bezahltag|Konistag)\s+(?:Morning|Afternoon|Evening|Night))\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^(Two Rounds Later[…\.]*)\s*$', re.IGNORECASE | re.MULTILINE),
]

def time_to_sort_key(time_label):
    label = time_label.strip().lower()
    day_periods = {
        'angestag afternoon': 800,
        'angestag evening': 1080,
        'festag morning': 1800,
    }
    for key, val in day_periods.items():
        if key in label:
            return val
    
    if 'midnight' in label:
        return 1440
    if 'noon' in label:
        return 720
    if 'two rounds later' in label:
        return -1
    
    m = re.match(r'(\d{1,2})[:\.]?(\d{0,2})\s*(a\.?m\.?|p\.?m\.?)', label)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        period = m.group(3).replace('.', '').lower()
        
        if period == 'pm' and hour != 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0
        
        total = hour * 60 + minute
        if total < 360:
            total += 1440
        return total
    
    return 0


def extract_events(chapter_text):
    """Extract timed events from chapter text."""
    events = []
    all_matches = []
    for pattern in TIME_PATTERNS:
        for m in pattern.finditer(chapter_text):
            all_matches.append((m.start(), m.end(), m.group(1).strip()))
    
    all_matches.sort(key=lambda x: x[0])
    
    deduped = []
    for match in all_matches:
        if not deduped or match[0] - deduped[-1][0] > 5:
            deduped.append(match)
    
    for i, (start, end, time_label) in enumerate(deduped):
        desc_start = end
        if i + 1 < len(deduped):
            desc_end = deduped[i + 1][0]
        else:
            desc_end = desc_start + 2000
        
        desc = chapter_text[desc_start:desc_end].strip()
        desc = re.sub(r'\n\d+\n', '\n', desc)
        desc = re.sub(r'\nWARHAMMER FANTASY ROLEPL\s*AY\n', '\n', desc)
        desc = re.sub(r'\nA ROUGH NIGHT AT THE THREE FEATHERS\n', '\n', desc)
        desc = re.sub(r'\nA DAY AT THE TRIALS\n', '\n', desc)
        desc = re.sub(r'\nA NIGHT AT THE OPERA\n', '\n', desc)
        desc = re.sub(r"\nNASTASSIA'S WEDDING\n", '\n', desc)
        desc = re.sub(r'\nLORD OF UBERSREIK\n', '\n', desc)
        desc = re.sub(r'\n[IVXLCDM]+\n', '\n', desc)
        
        npc_break = re.search(r'\nNon-Player Characters\n|\nNPCs?\n', desc, re.IGNORECASE)
        if npc_break:
            desc = desc[:npc_break.start()]
        
        desc = desc.strip()
        if len(desc) > 3000:
            cut = desc[:3000].rfind('.')
            if cut > 500:
                desc = desc[:cut+1]
        
        sort_key = time_to_sort_key(time_label)
        events.append({
            "time_label": time_label,
            "time_sort_key": sort_key,
            "description": desc,
        })
    
    return events


# ─── Robust NPC Parsing (Block-Based) ──────────────────────────────────────────

def extract_npcs_from_page(doc, pdf_page_num):
    """Extract NPCs from a single PDF page using PyMuPDF block layout."""
    page = doc[pdf_page_num]
    blocks = page.get_text("blocks")
    
    # Separate and sort into columns
    col1 = []
    col2 = []
    for b in blocks:
        text = b[4].strip()
        if not text or text.isdigit() or text in ["III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII"]:
            continue
        if text.upper() in ["WARHAMMER FANTASY ROLEPLAY", "WARHAMMER FANTASY ROLEPL AY",
                            "A ROUGH NIGHT AT THE THREE FEATHERS", "A DAY AT THE TRIALS",
                            "A NIGHT AT THE OPERA", "NASTASSIA'S WEDDING", "LORD OF UBERSREIK",
                            "NON-PLAYER CHARACTERS", "NON-PLAYER", "CHARACTERS"]:
            continue
        x0, y0, x1, y1 = b[:4]
        if x0 < 290:
            col1.append((y0, b))
        else:
            col2.append((y0, b))
            
    col1.sort(key=lambda x: x[0])
    col2.sort(key=lambda x: x[0])
    ordered_blocks = [b for _, b in col1] + [b for _, b in col2]
    
    npcs = []
    
    for idx, b in enumerate(ordered_blocks):
        text = b[4].strip()
        if "M WS BS" in text or (text.startswith("M") and "WS" in text and "BS" in text):
            # 1. Parse 12 stat values
            stats = {}
            val_block_idx = None
            for j in range(idx + 1, min(len(ordered_blocks), idx + 3)):
                v_text = ordered_blocks[j][4].strip()
                tokens = [t for t in v_text.split() if t.isdigit()]
                if len(tokens) == 12:
                    keys = ["M", "WS", "BS", "S", "T", "I", "Ag", "Dex", "Int", "WP", "Fel", "W"]
                    for k, val in zip(keys, tokens):
                        stats[k] = int(val)
                    val_block_idx = j
                    break
                    
            if not stats:
                continue
                
            # 2. Find NPC name block(s) before the stat header
            raw_name_parts = []
            name_idx = idx - 1
            
            for j in range(idx - 1, max(-1, idx - 4), -1):
                t = ordered_blocks[j][4].strip()
                if re.search(r'\((?:BRASS|SILVER|GOLD)\s*\d*\)', t, re.I) or "–" in t or "—" in t or t.isupper():
                    raw_name_parts.insert(0, t)
                    name_idx = j
                    # If this block was only a tier like "(SILVER 5)", grab the preceding line too
                    if re.match(r'^\((?:BRASS|SILVER|GOLD)\s*\d*\)$', t, re.I) and j > 0:
                        prev_t = ordered_blocks[j-1][4].strip()
                        raw_name_parts.insert(0, prev_t)
                        name_idx = j - 1
                    break
                    
            full_name_line = " ".join(" ".join(raw_name_parts).split())
            npc_name = ""
            career = ""
            tier = ""
            
            if full_name_line:
                t_match = re.search(r'\((BRASS|SILVER|GOLD)\s*(\d*)\)', full_name_line, re.I)
                if t_match:
                    tier = f"{t_match.group(1).title()} {t_match.group(2)}".strip()
                    full_name_line = full_name_line[:t_match.start()].strip()
                
                dash_match = re.search(r'(?:\s+[–—]\s*|\s+\-\s+)(.+)$', full_name_line)
                if dash_match:
                    career = dash_match.group(1).strip().title()
                    npc_name = full_name_line[:dash_match.start()].strip().title()
                else:
                    npc_name = full_name_line.strip().title()
            else:
                npc_name = f"NPC (page {pdf_page_num+1})"
                
            if career:
                stats["Career"] = career
            if tier:
                stats["Tier"] = tier
                
            # 3. Parse Narrative Description
            desc_text = ""
            if name_idx > 0:
                prev_block = ordered_blocks[name_idx - 1]
                prev_text = prev_block[4].strip()
                if not any(prev_text.startswith(k) for k in KNOWN_EXTRA_PREFIXES) and "M WS BS" not in prev_text and not re.search(r'\((?:BRASS|SILVER|GOLD)\s*\d*\)', prev_text, re.I):
                    desc_text = " ".join(prev_text.split())
                    
            # 4. Parse Extras (Skills, Talents, Traits, Trappings)
            if val_block_idx is not None:
                for j in range(val_block_idx + 1, min(len(ordered_blocks), val_block_idx + 4)):
                    e_text = ordered_blocks[j][4].strip()
                    if any(e_text.startswith(k) for k in KNOWN_EXTRA_PREFIXES) or "Skills:" in e_text or "Traits:" in e_text or "Talents:" in e_text or "Trappings:" in e_text:
                        for sect in ['Skills', 'Talents', 'Traits', 'Trappings', 'Spells', 'Miracles', 'Blessings']:
                            pat = re.compile(rf'{sect}:\s*(.+?)(?=(?:Skills|Talents|Traits|Trappings|Spells|Miracles|Blessings):|$)', re.DOTALL)
                            m = pat.search(e_text)
                            if m:
                                val_str = " ".join(m.group(1).strip().split())
                                stats[sect] = val_str
                                
            npcs.append({
                "name": npc_name,
                "description": desc_text,
                "stats_json": json.dumps(stats),
                "page": pdf_page_num,
            })
            
    return npcs


# ─── Image Extraction & Spatial Linking ────────────────────────────────────────

def extract_images(doc, module_id, conn):
    """Extract artwork images from the PDF with proper transparency."""
    os.makedirs(IMG_DIR, exist_ok=True)
    
    for f in os.listdir(IMG_DIR):
        if f.endswith(('.png', '.jpg', '.jpeg')):
            os.remove(os.path.join(IMG_DIR, f))
    
    c = conn.cursor()
    c.execute("DELETE FROM module_images WHERE module_id = ?", (module_id,))
    
    images_inserted = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        imgs = page.get_image_info(xrefs=True)
        i = 0
        
        for img in imgs:
            xref = img['xref']
            try:
                base_img = doc.extract_image(xref)
            except Exception:
                continue
            if not base_img:
                continue
            
            w, h = base_img['width'], base_img['height']
            
            # Filter out backgrounds and UI textures
            if w < 100 or h < 100:
                continue
            if w > 1500 and h > 2000:
                continue
            if w in (736, 728, 726, 725, 743):
                continue
            
            try:
                pix = fitz.Pixmap(doc, xref)
                smask_xref = base_img.get('smask', 0)
                
                if not pix.alpha and smask_xref > 0:
                    mask = fitz.Pixmap(doc, smask_xref)
                    pix = fitz.Pixmap(pix, mask)
                    mask = None
                
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                
                filename = f"page_{page_num}_img_{i}.png"
                filepath = os.path.join(IMG_DIR, filename)
                pix.save(filepath)
                pix = None
            except Exception as e:
                print(f"  Warning: Failed to process image xref={xref} on page {page_num}: {e}")
                continue
            
            db_img_path = f"wfrp-4e-rough-nights-and-hard-days/images/{filename}"
            
            book_page = page_num + 1
            chapter_id = None
            for ch_num, ch_title, _, _, ch_start, ch_end in CHAPTERS:
                if ch_start <= book_page <= ch_end:
                    c2 = conn.execute("SELECT id FROM module_chapters WHERE module_id = ? AND chapter_number = ?",
                                     (module_id, ch_num))
                    row = c2.fetchone()
                    if row:
                        chapter_id = row[0]
                    break
            
            c.execute("INSERT INTO module_images (module_id, chapter_id, image_path) VALUES (?, ?, ?)",
                      (module_id, chapter_id, db_img_path))
            images_inserted += 1
            i += 1
    
    conn.commit()
    return images_inserted


def link_images_to_npcs(doc, module_id, conn):
    """Link extracted images to NPCs by spatial proximity analysis."""
    c = conn.cursor()
    c.execute("SELECT id, name FROM module_npcs WHERE module_id = ?", (module_id,))
    npcs = [{"id": r[0], "name": r[1], "first_name": r[1].split()[0] if r[1] else ""} for r in c.fetchall()]
    
    c.execute("SELECT id, image_path FROM module_images WHERE module_id = ?", (module_id,))
    images = [dict(r) for r in c.fetchall()]
    
    linked = 0
    for img_row in images:
        img_path = img_row['image_path']
        m = re.search(r'page_(\d+)_img_', img_path)
        if not m:
            continue
        page_num = int(m.group(1))
        if page_num >= len(doc):
            continue
        
        page = doc[page_num]
        text_blocks = page.get_text("blocks")
        page_imgs = page.get_image_info(xrefs=True)
        
        img_idx_match = re.search(r'img_(\d+)', img_path)
        if not img_idx_match:
            continue
        target_idx = int(img_idx_match.group(1))
        
        valid_imgs = []
        for pimg in page_imgs:
            try:
                base = doc.extract_image(pimg['xref'])
                if not base:
                    continue
                w, h = base['width'], base['height']
                if w < 100 or h < 100 or (w > 1500 and h > 2000) or w in (736, 728, 726, 725, 743):
                    continue
                valid_imgs.append(pimg)
            except Exception:
                continue
        
        if target_idx >= len(valid_imgs):
            continue
        
        r = fitz.Rect(valid_imgs[target_idx]['bbox'])
        
        closest_text = ""
        for tb in text_blocks:
            tb_rect = fitz.Rect(tb[:4])
            text_content = tb[4].strip()
            
            if tb_rect.y0 >= r.y1 - 25 and tb_rect.y0 <= r.y1 + 220:
                if max(r.x0, tb_rect.x0) < min(r.x1, tb_rect.x1):
                    closest_text += " " + text_content
            if tb_rect.y1 <= r.y0 + 25 and tb_rect.y1 >= r.y0 - 120:
                if max(r.x0, tb_rect.x0) < min(r.x1, tb_rect.x1):
                    closest_text += " " + text_content
        
        for npc in npcs:
            if not npc['name'] or "NPC" in npc['name']:
                continue
            if npc['name'].lower() in closest_text.lower():
                c.execute("UPDATE module_npcs SET image_path = ? WHERE id = ?",
                          (img_path, npc['id']))
                linked += 1
                break
            elif len(npc['first_name']) > 4 and npc['first_name'].lower() in closest_text.lower():
                c.execute("UPDATE module_npcs SET image_path = ? WHERE id = ?",
                          (img_path, npc['id']))
                linked += 1
                break
    
    conn.commit()
    return linked


# ─── Main Execution ───────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("WFRP Module Ingestion: Rough Nights & Hard Days")
    print("=" * 60)
    
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: PDF not found at {PDF_PATH}")
        sys.exit(1)
    
    doc = fitz.open(PDF_PATH)
    print(f"PDF loaded: {len(doc)} pages")
    
    conn = get_db()
    c = conn.cursor()
    
    # 1. Reset module
    c.execute("SELECT id FROM module_catalog WHERE slug = ?", (MODULE_SLUG,))
    row = c.fetchone()
    if row:
        module_id = row[0]
        print(f"Clearing existing module (id={module_id})...")
        clear_module(conn, module_id)
    
    c.execute("INSERT INTO module_catalog (slug, title, description, cover_image_path) VALUES (?, ?, ?, ?)",
              (MODULE_SLUG, MODULE_TITLE, MODULE_DESC, ""))
    module_id = c.lastrowid
    conn.commit()
    print(f"Module catalog created (id={module_id})")
    
    # 2. Insert chapters
    chapter_ids = {}
    for ch_num, ch_title, loc_name, loc_desc, _, _ in CHAPTERS:
        c.execute("""INSERT INTO module_chapters (module_id, chapter_number, title, location_name, location_description)
                     VALUES (?, ?, ?, ?, ?)""",
                  (module_id, ch_num, ch_title, loc_name, loc_desc))
        chapter_ids[ch_num] = c.lastrowid
    conn.commit()
    print(f"Inserted {len(CHAPTERS)} chapters")
    
    # 3. Extract plots
    total_plots = 0
    for ch_num, ch_title, _, _, ch_start, ch_end in CHAPTERS:
        chapter_text = get_chapter_text(doc, ch_start, ch_end)
        plots = extract_plots(chapter_text)
        ch_id = chapter_ids[ch_num]
        
        for plot in plots:
            c.execute("INSERT INTO module_plots (chapter_id, title, description) VALUES (?, ?, ?)",
                      (ch_id, plot['title'], plot['description']))
        
        print(f"  Chapter {ch_num} '{ch_title}': {len(plots)} plots")
        total_plots += len(plots)
    conn.commit()
    print(f"Total plots: {total_plots}")
    
    # 4. Extract events
    total_events = 0
    for ch_num, ch_title, _, _, ch_start, ch_end in CHAPTERS:
        chapter_text = get_chapter_text(doc, ch_start, ch_end)
        events = extract_events(chapter_text)
        ch_id = chapter_ids[ch_num]
        
        for event in events:
            c.execute("""INSERT INTO module_events (chapter_id, time_label, time_sort_key, description)
                         VALUES (?, ?, ?, ?)""",
                      (ch_id, event['time_label'], event['time_sort_key'], event['description']))
        
        print(f"  Chapter {ch_num} '{ch_title}': {len(events)} events")
        total_events += len(events)
    conn.commit()
    print(f"Total events: {total_events}")
    
    # 5. Extract NPCs
    total_npcs = 0
    seen_npc_names = set()
    
    for ch_num, ch_title, _, _, ch_start, ch_end in CHAPTERS:
        ch_npcs = 0
        for book_page in range(ch_start, ch_end + 1):
            pdf_page = book_page - 1
            if 0 <= pdf_page < len(doc):
                page_npcs = extract_npcs_from_page(doc, pdf_page)
                for npc in page_npcs:
                    name_key = npc['name'].lower().strip()
                    if not name_key or name_key in seen_npc_names:
                        continue
                    seen_npc_names.add(name_key)
                    
                    c.execute("""INSERT INTO module_npcs (module_id, name, description, stats_json, image_path)
                                 VALUES (?, ?, ?, ?, '')""",
                              (module_id, npc['name'], npc['description'], npc['stats_json']))
                    ch_npcs += 1
        
        print(f"  Chapter {ch_num} '{ch_title}': {ch_npcs} NPCs")
        total_npcs += ch_npcs
    conn.commit()
    print(f"Total NPCs: {total_npcs}")
    
    # 6. Extract images
    print("\nExtracting images...")
    images_count = extract_images(doc, module_id, conn)
    print(f"Extracted {images_count} artwork images")
    
    # 7. Link images to NPCs
    print("Linking images to NPCs...")
    linked_count = link_images_to_npcs(doc, module_id, conn)
    print(f"Linked {linked_count} images to NPCs")
    
    # 8. Set cover image
    c.execute("SELECT image_path FROM module_images WHERE module_id = ? ORDER BY id LIMIT 1", (module_id,))
    cover = c.fetchone()
    if cover:
        c.execute("UPDATE module_catalog SET cover_image_path = ? WHERE id = ?", (cover[0], module_id))
        conn.commit()
    
    # 9. Export JSON
    export_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "modules_export.json")
    tables = ["module_catalog", "module_chapters", "module_plots", "module_events", "module_npcs", "module_images"]
    data = {}
    for t in tables:
        cur = conn.execute(f"SELECT * FROM {t}")
        cols = [desc[0] for desc in cur.description]
        data[t] = [dict(zip(cols, row)) for row in cur.fetchall()]
    
    with open(export_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nExported database to {export_path}")
    
    conn.close()
    doc.close()
    
    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print(f"  Module:   {MODULE_TITLE}")
    print(f"  Chapters: {len(CHAPTERS)}")
    print(f"  Plots:    {total_plots}")
    print(f"  Events:   {total_events}")
    print(f"  NPCs:     {total_npcs}")
    print(f"  Images:   {images_count} ({linked_count} linked to NPCs)")
    print("=" * 60)

if __name__ == '__main__':
    main()
