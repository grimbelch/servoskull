# WFRP 4E AI Magic Mechanics & Algorithm Cheat Sheet

**CRITICAL INSTRUCTION FOR LLM GM**: Do not guess magic outcomes. Follow this strict algorithm.

## Magic Resolution Algorithm

1. **Check Ingredients**: Does the caster have the required ingredient?
   - **Yes**: Cast roll ignores Miscasts unless a Fumble (double failures) is rolled.
   - **No**: Any roll ending in an 8 (e.g. 18, 28, 38) OR double successes/failures causes a Miscast.

2. **Channelling (Optional)**: 
   - Test `Channelling (Wind)` vs CN (Casting Number) of the spell.
   - For every SL generated, the caster gains 1 Channelling SL towards the spell's CN.
   - If they fail the Channelling test, they lose all accumulated SL and must roll on the Minor Miscast table.
   - **Critical Channelling**: Roll doubles that succeed. Gains SL normally AND can cast the spell immediately without a Language (Magick) test. Must still roll Minor Miscast if they lack an ingredient.
   - **Fumble Channelling**: Roll doubles that fail. Roll on Major Miscast table.

3. **Casting**:
   - Test `Language (Magick)`.
   - `Casting SL = (Stat Tens) - (Roll Tens) + (Channelling SL accumulated)`.
   - If `Casting SL >= CN of the spell`: **SPELL CAST SUCCESSFULLY!**
   - If `Casting SL < CN of the spell`: **SPELL FAILS!**

4. **Overcasting**:
   - If the spell is cast successfully and `Casting SL > CN`, for every 2 SL above the CN, the caster may choose one Overcast effect:
     - Increase Range (by base increment).
     - Increase Duration (by base increment).
     - Increase Area of Effect (by base increment).
     - Increase Targets (by 1 additional target).
     - Increase Damage (by +1).

5. **Miscasts (The Winds of Magic are Fickle)**:
   - **Minor Miscast**: 
     - Caused by failing a Channelling roll.
     - Caused by a successful Cast roll ending in '8' (18, 28) without an ingredient.
   - **Major Miscast**: 
     - Caused by a Fumble (double failures, e.g. 88, 99) on any Channelling or Casting roll.
     - Caused by a Critical Cast (double successes, e.g. 11, 22) without an ingredient (the spell succeeds, but triggers a Major Miscast).

## Opposed Spells (Magic Missiles)
If the spell is a Magic Missile (e.g., Dart, Blast), the target may attempt to Dodge.
- Caster's SL is their `Casting SL - CN`.
- Target's SL is their `Dodge SL`.
- If Caster SL > Target SL, the spell hits. Damage is calculated normally (SL difference + Spell Damage + Willpower Bonus if applicable - TB - AP).
