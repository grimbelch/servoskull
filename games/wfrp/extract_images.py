import fitz
import sys
import os
import sqlite3
import json

def get_db():
    return sqlite3.connect(os.path.expanduser("~/.config/omega7/campaigns/skull_campaigns.db"))

def main():
    conn = get_db()
    c = conn.cursor()
    
    # Get module id
    c.execute("SELECT id FROM module_catalog WHERE slug = 'rough-nights-and-hard-days'")
    row = c.fetchone()
    if not row:
        print("Module not found")
        return
    module_id = row[0]
    
    # Load NPCs for matching
    c.execute("SELECT id, name FROM module_npcs WHERE module_id = ?", (module_id,))
    npcs = [{"id": r[0], "name": r[1], "first_name": r[1].split()[0] if r[1] else ""} for r in c.fetchall()]
    
    # Clear existing images
    c.execute("DELETE FROM module_images WHERE module_id = ?", (module_id,))
    # Clear image links from NPCs
    c.execute("UPDATE module_npcs SET image_path = '' WHERE module_id = ?", (module_id,))
    
    pdf_path = os.path.join(os.path.dirname(__file__), "rules", "modules", "[WFRP][4E] - Rough Nights and Hard Days.pdf")
    doc = fitz.open(pdf_path)
    
    out_dir = os.path.join(os.path.dirname(__file__), "rules", "wfrp-4e-rough-nights-and-hard-days", "images")
    os.makedirs(out_dir, exist_ok=True)
    
    # Remove old images in out_dir
    for f in os.listdir(out_dir):
        if f.endswith(".png") or f.endswith(".jpg") or f.endswith(".jpeg"):
            os.remove(os.path.join(out_dir, f))

    # Read manifest to match pages to chapter_id
    manifest_path = os.path.join(os.path.dirname(__file__), "rules", "wfrp-4e-rough-nights-and-hard-days", "manifest.json")
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
        
    c.execute("SELECT id, title FROM module_chapters WHERE module_id = ?", (module_id,))
    chapter_id_map = {r[1]: r[0] for r in c.fetchall()}
    
    images_inserted = 0
    npcs_linked = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # Match chapter_id for this page
        book_page_num = page_num + 1
        chapter_id = None
        for item in manifest:
            if item.get('page') == book_page_num:
                ch = item.get('chapter')
                if ch in chapter_id_map:
                    chapter_id = chapter_id_map[ch]
                    break
                    
        # Extract text blocks for matching
        text_blocks = page.get_text("blocks") 
        
        imgs = page.get_image_info(xrefs=True)
        i = 0
        for img in imgs:
            xref = img['xref']
            try:
                base_img = doc.extract_image(xref)
            except:
                continue
                
            if not base_img:
                continue
                
            w, h = base_img['width'], base_img['height']
            
            # Skip tiny UI elements and full page backgrounds
            if w < 100 or h < 100: continue
            if w > 1500 and h > 2000: continue
            
            # Skip stat block backgrounds
            if w in (736, 728, 726, 725, 743): continue
            
            try:
                pix = fitz.Pixmap(doc, xref)
                smask_xref = base_img.get('smask', 0)
                
                # Apply smask for transparency if needed
                if not pix.alpha and smask_xref > 0:
                    mask = fitz.Pixmap(doc, smask_xref)
                    pix = fitz.Pixmap(pix, mask)
                    mask = None
                    
                # Convert CMYK to RGB
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                    
                ext = "png" # We force PNG because we want to preserve transparency
                filename = f"page_{page_num}_img_{i}.{ext}"
                filepath = os.path.join(out_dir, filename)
                
                pix.save(filepath)
                pix = None
            except Exception as e:
                print(f"Failed to process image {xref} on page {page_num}: {e}")
                continue
                
            db_img_path = f"wfrp-4e-rough-nights-and-hard-days/images/{filename}"
            
            c.execute("INSERT INTO module_images (module_id, chapter_id, image_path) VALUES (?, ?, ?)",
                      (module_id, chapter_id, db_img_path))
            images_inserted += 1
            i += 1
            
            # Link to NPC
            r = fitz.Rect(img['bbox'])
            closest_text = ""
            for tb in text_blocks:
                tb_rect = fitz.Rect(tb[:4])
                text_content = tb[4].strip()
                
                # Check if it's below the image
                if tb_rect.y0 >= r.y1 - 15 and tb_rect.y0 <= r.y1 + 180:
                    # Check if it overlaps horizontally
                    if max(r.x0, tb_rect.x0) < min(r.x1, tb_rect.x1):
                        closest_text += " " + text_content
                        
            matched_npc = None
            for npc in npcs:
                if "Unknown NPC" in npc['name']: continue
                if npc['name'].lower() in closest_text.lower():
                    matched_npc = npc['id']
                    break
                if len(npc['first_name']) > 4 and npc['first_name'].lower() in closest_text.lower():
                    matched_npc = npc['id']
                    break
                    
            if matched_npc:
                c.execute("UPDATE module_npcs SET image_path = ? WHERE id = ?", (db_img_path, matched_npc))
                npcs_linked += 1

    conn.commit()
    conn.close()
    
    print(f"Extracted {images_inserted} raw artwork images with transparency.")
    print(f"Successfully linked {npcs_linked} images to NPCs.")

if __name__ == '__main__':
    main()
