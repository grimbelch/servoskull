from . import db

def list_modules():
    conn = db.get_connection()
    cur = conn.execute("SELECT * FROM module_catalog ORDER BY title")
    modules = [dict(row) for row in cur.fetchall()]
    conn.close()
    return modules

def get_module(slug):
    conn = db.get_connection()
    cur = conn.execute("SELECT * FROM module_catalog WHERE slug=?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    module = dict(row)
    module_id = module["id"]
    
    # chapters
    cur = conn.execute("SELECT * FROM module_chapters WHERE module_id=? ORDER BY chapter_number", (module_id,))
    chapters = [dict(r) for r in cur.fetchall()]
    for chap in chapters:
        cid = chap["id"]
        # plots
        cur2 = conn.execute("SELECT * FROM module_plots WHERE chapter_id=?", (cid,))
        chap["plots"] = [dict(r) for r in cur2.fetchall()]
        # events
        cur2 = conn.execute("SELECT * FROM module_events WHERE chapter_id=? ORDER BY time_sort_key", (cid,))
        events = []
        for r in cur2.fetchall():
            e = dict(r)
            e["related_plot_ids"] = [] # would parse JSON
            events.append(e)
        chap["events"] = events
        
    module["chapters"] = chapters
    
    # npcs
    cur = conn.execute("SELECT * FROM module_npcs WHERE module_id=?", (module_id,))
    module["npcs"] = [dict(r) for r in cur.fetchall()]
    
    # images
    cur = conn.execute("SELECT * FROM module_images WHERE module_id=?", (module_id,))
    module["images"] = [dict(r) for r in cur.fetchall()]
    
    conn.close()
    return module

def get_module_with_campaign_state(slug, campaign_id):
    module = get_module(slug)
    if not module:
        return None
        
    conn = db.get_connection()
    
    # Fetch states
    cur = conn.execute("SELECT entity_type, entity_id, status, gm_notes FROM campaign_module_state WHERE campaign_id=?", (campaign_id,))
    states = {}
    for r in cur.fetchall():
        key = f"{r['entity_type']}_{r['entity_id']}"
        states[key] = {"status": r["status"], "gm_notes": r["gm_notes"]}
        
    # Apply states to chapters
    for chap in module["chapters"]:
        ckey = f"chapter_{chap['id']}"
        if ckey in states:
            chap["campaign_state"] = states[ckey]
        else:
            chap["campaign_state"] = {"status": "Not Started", "gm_notes": ""}
            
        for plot in chap.get("plots", []):
            pkey = f"plot_{plot['id']}"
            if pkey in states:
                plot["campaign_state"] = states[pkey]
            else:
                plot["campaign_state"] = {"status": "Not Started", "gm_notes": ""}
                
        for event in chap.get("events", []):
            ekey = f"event_{event['id']}"
            if ekey in states:
                event["campaign_state"] = states[ekey]
            else:
                event["campaign_state"] = {"status": "Not Started", "gm_notes": ""}
                
    # Fetch overridden NPCs for the campaign
    cur = conn.execute("SELECT module_npc_id, id as campaign_npc_id, name, role_career FROM npcs WHERE campaign_id=? AND module_npc_id IS NOT NULL", (campaign_id,))
    campaign_npcs = {r["module_npc_id"]: dict(r) for r in cur.fetchall()}
    
    for npc in module.get("npcs", []):
        if npc["id"] in campaign_npcs:
            npc["campaign_override"] = campaign_npcs[npc["id"]]
            
    conn.close()
    return module

def update_module_state(campaign_id, entity_type, entity_id, status, gm_notes):
    conn = db.get_connection()
    conn.execute("""
        INSERT INTO campaign_module_state (campaign_id, entity_type, entity_id, status, gm_notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, entity_type, entity_id) DO UPDATE SET
            status=excluded.status,
            gm_notes=excluded.gm_notes
    """, (campaign_id, entity_type, entity_id, status, gm_notes))
    conn.commit()
    conn.close()
