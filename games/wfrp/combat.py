"""WFRP 4E Backend Combat Engine"""
import math
from . import db
from . import campaign

def start_combat(campaign_id: int, name: str, combatants_list: list) -> str:
    """Initializes a new combat encounter."""
    conn = db.get_connection()
    try:
        # End any active combat
        conn.execute("UPDATE combat_encounters SET is_active = 0 WHERE campaign_id = ?", (campaign_id,))
        
        # Create new combat
        cur = conn.execute(
            "INSERT INTO combat_encounters (campaign_id, name, round, current_turn_index, is_active) VALUES (?, ?, 1, 0, 1)",
            (campaign_id, name)
        )
        encounter_id = cur.lastrowid
        
        for c in combatants_list:
            c_name = c.get("name", "Unknown")
            init = int(c.get("initiative", 0))
            is_npc = int(c.get("is_npc", 1))
            wounds_max = int(c.get("wounds_max", 0))
            wounds_current = int(c.get("wounds_current", wounds_max))
            
            conn.execute(
                """INSERT INTO combatants (encounter_id, name, initiative, wounds_current, wounds_max, advantage, conditions, is_npc) 
                   VALUES (?, ?, ?, ?, ?, 0, '', ?)""",
                (encounter_id, c_name, init, wounds_current, wounds_max, is_npc)
            )
            
        conn.commit()
        return f"Combat '{name}' started. Encounter ID: {encounter_id}"
    finally:
        conn.close()

def get_combat_status(campaign_id: int) -> str:
    conn = db.get_connection()
    try:
        enc = conn.execute("SELECT * FROM combat_encounters WHERE campaign_id = ? AND is_active = 1", (campaign_id,)).fetchone()
        if not enc:
            return "No active combat."
            
        combatants = conn.execute(
            "SELECT * FROM combatants WHERE encounter_id = ? ORDER BY initiative DESC", 
            (enc['id'],)
        ).fetchall()
        
        lines = [f"COMBAT: {enc['name']} (Round {enc['round']})"]
        for i, c in enumerate(combatants):
            marker = ">> " if i == enc['current_turn_index'] else "   "
            hp = f"{c['wounds_current']}/{c['wounds_max']}" if c['wounds_max'] > 0 else f"{c['wounds_current']}"
            cond = f" [{c['conditions']}]" if c['conditions'] else ""
            lines.append(f"{marker}Init {c['initiative']:2} | {c['name']} (Adv: {c['advantage']}, Wounds: {hp}){cond}")
            
        return "\n".join(lines)
    finally:
        conn.close()

def update_combatant(campaign_id: int, combatant_name: str, wounds_change: int = 0, advantage_set: int = None, conditions: str = None) -> str:
    conn = db.get_connection()
    try:
        enc = conn.execute("SELECT id FROM combat_encounters WHERE campaign_id = ? AND is_active = 1", (campaign_id,)).fetchone()
        if not enc:
            return "No active combat."
            
        c = conn.execute("SELECT * FROM combatants WHERE encounter_id = ? AND name LIKE ?", (enc['id'], f"%{combatant_name}%")).fetchone()
        if not c:
            return f"Combatant {combatant_name} not found."
            
        new_wounds = max(0, c['wounds_current'] + wounds_change)
        new_adv = advantage_set if advantage_set is not None else c['advantage']
        new_cond = conditions if conditions is not None else c['conditions']
        
        conn.execute(
            "UPDATE combatants SET wounds_current = ?, advantage = ?, conditions = ? WHERE id = ?",
            (new_wounds, new_adv, new_cond, c['id'])
        )
        conn.commit()
        return f"Updated {c['name']}: Wounds {new_wounds}/{c['wounds_max']}, Adv {new_adv}, Cond: {new_cond}"
    finally:
        conn.close()

def next_turn(campaign_id: int) -> str:
    conn = db.get_connection()
    try:
        enc = conn.execute("SELECT * FROM combat_encounters WHERE campaign_id = ? AND is_active = 1", (campaign_id,)).fetchone()
        if not enc:
            return "No active combat."
            
        count = conn.execute("SELECT COUNT(*) as c FROM combatants WHERE encounter_id = ?", (enc['id'],)).fetchone()['c']
        if count == 0:
            return "No combatants in active combat."
            
        next_idx = enc['current_turn_index'] + 1
        new_round = enc['round']
        if next_idx >= count:
            next_idx = 0
            new_round += 1
            
        conn.execute(
            "UPDATE combat_encounters SET current_turn_index = ?, round = ? WHERE id = ?",
            (next_idx, new_round, enc['id'])
        )
        conn.commit()
        
        c = conn.execute("SELECT name FROM combatants WHERE encounter_id = ? ORDER BY initiative DESC LIMIT 1 OFFSET ?", (enc['id'], next_idx)).fetchone()
        return f"Turn advanced. Round {new_round}, Turn: {c['name']}."
    finally:
        conn.close()

def calculate_attack(attacker_sl: int, defender_sl: int, weapon_damage: int, attacker_sb: int, defender_tb: int, defender_ap: int, is_melee: bool = True) -> str:
    """Resolves an opposed test and calculates damage based on WFRP 4E core rules."""
    net_sl = attacker_sl - defender_sl
    if net_sl <= 0:
        return f"Attack Failed! (Net SL: {net_sl}). Defender wins the opposed test."
        
    base_damage = weapon_damage
    if is_melee:
        base_damage += attacker_sb
        
    damage_dealt = net_sl + base_damage - (defender_tb + defender_ap)
    damage_dealt = max(1, damage_dealt) # Minimum 1 damage on a successful hit unless specific talents/qualities apply
    
    return (
        f"Attack Successful! (Net SL: +{net_sl})\n"
        f"Calculation: Net SL ({net_sl}) + Weapon Dam ({weapon_damage}) "
        f"+ SB ({attacker_sb if is_melee else 0}) - TB ({defender_tb}) - AP ({defender_ap}) "
        f"= {damage_dealt} Wounds suffered."
    )
