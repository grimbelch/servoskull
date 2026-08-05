# WFRP 4E AI Combat Mechanics & Algorithm Cheat Sheet

**CRITICAL INSTRUCTION FOR LLM GM**: Do not guess combat outcomes based on prose. Follow this strict algorithm for resolving combat. Use the `whfrp_resolve_attack` tool to do the math for you, or compute it exactly as shown below.

## Combat Resolution Algorithm (Opposed Test)

1. **Attacker Rolls to Hit**: Attacker rolls a d100 against their Weapon Skill (Melee) or Ballistic Skill (Ranged).
2. **Calculate Attacker SL (Success Level)**: 
   `Attacker SL = (Stat Tens Digit) - (Roll Tens Digit)`. 
   *(Example: WS 45, Roll 23 -> SL = 4 - 2 = 2)*
3. **Determine Hit Location**: Reverse the attacker's d100 roll to get the hit location.
   *(Example: Roll 23 -> Hit Location 32).*
   - 01-09: Head
   - 10-24: Left Arm
   - 25-44: Right Arm
   - 45-79: Body
   - 80-89: Left Leg
   - 90-00: Right Leg
4. **Defender Rolls to Evade/Parry**: Defender rolls d100 against Dodge or Melee (Parry).
5. **Calculate Defender SL**: 
   `Defender SL = (Stat Tens Digit) - (Roll Tens Digit)`.
6. **Compare SLs (Opposed Test)**:
   - If Attacker SL > Defender SL: **HIT!** 
   - `Net SL = Attacker SL - Defender SL`
   - If Attacker SL <= Defender SL: **MISS!** (Defender won the opposed test).
7. **Calculate Damage**:
   - Base Damage = Weapon Damage + (Attacker Strength Bonus *if melee*).
   - `Total Damage = Net SL + Base Damage`
8. **Apply Mitigation & Determine Wounds**:
   - `Mitigation = Defender Toughness Bonus (TB) + Armour Points (AP) on the Hit Location`.
   - `Wounds Suffered = Total Damage - Mitigation`.
   - **Minimum Damage Rule**: A successful hit *always* deals a minimum of 1 Wound, regardless of Mitigation, unless a specific Creature Trait or Talent says otherwise.

## Advantage
- **Gaining Advantage**: +1 Advantage when you win an Opposed Test, assess the situation, or charge.
- **Using Advantage**: Each point of Advantage gives +10 to Attack/Defend rolls.
- **Losing Advantage**: If a combatant suffers 1 or more Wounds, their Advantage immediately resets to 0.

## Critical Hits (Fumbles & Crits)
- **Critical Hit**: Roll doubles that are a success (e.g., 11, 22, 33, 44 on a stat of 45+). Causes an immediate roll on the Critical Hit table for the specific body part.
- **Fumble**: Roll doubles that are a failure (e.g., 55, 66, 77, 88, 99 on a stat of 45-). Causes an immediate roll on the Fumble table.
