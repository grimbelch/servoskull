# WFRP 4E AI Skill Tests & Mechanics Cheat Sheet

**CRITICAL INSTRUCTION FOR LLM GM**: Follow these strict rules when calling for or resolving skill and characteristic tests.

## 1. When to Call for a Test
- Do NOT call for a test for routine, everyday actions (walking, talking, buying a drink, noticing obvious things).
- Call for a test ONLY when there are dramatic consequences for failure (e.g., jumping a chasm, haggling with a suspicious merchant, spotting a hidden assassin).

## 2. Types of Tests

### Simple Tests
- Used when there is no active opposition and you just need a "Pass/Fail" result.
- **Roll**: d100.
- **Result**: If Roll <= Characteristic/Skill, it is a PASS. If Roll > Characteristic/Skill, it is a FAIL.
- **Do not** calculate Success Levels (SL) for Simple Tests unless the degree of success dictates a major narrative difference.

### Dramatic Tests
- Used when *how well* the character succeeds matters (e.g., picking a lock, performing a surgery, tracking footprints).
- **Roll**: d100 vs Characteristic/Skill.
- **Calculate SL**: `SL = (Stat Tens Digit) - (Roll Tens Digit)`.
  *(Example: Stat 45, Roll 23 -> SL = 4 - 2 = +2 SL)*
- **Outcome**:
  - SL +6 or more: Astounding Success
  - SL +4 to +5: Impressive Success
  - SL +2 to +3: Success
  - SL +0 to +1: Marginal Success
  - SL -0 to -1: Marginal Failure
  - SL -2 to -3: Failure
  - SL -4 to -5: Impressive Failure
  - SL -6 or less: Astounding Failure

### Opposed Tests
- Used when two characters compete (e.g., sneaking past a guard, arm wrestling, bargaining).
- **Procedure**:
  1. Both characters roll a Dramatic Test and calculate their SL.
  2. Compare the SLs. The character with the highest SL wins.
  3. If there is a tie, the character with the highest tested Characteristic/Skill wins. If still tied, re-roll.

## 3. Difficulty Modifiers
Apply these modifiers to the character's Base Characteristic/Skill before they roll, based on the situation:
- **Very Easy**: +60
- **Easy**: +40
- **Average**: +20
- **Challenging**: +0 (Standard)
- **Difficult**: -10
- **Hard**: -20
- **Very Hard**: -30

*Example: If a character with Agility 35 tries to pick a "Difficult" (-10) lock, their target number to roll under is 25.*

## 4. Automatic Successes and Failures
- A roll of **01 to 05** is ALWAYS a success, regardless of negative modifiers.
- A roll of **96 to 00** is ALWAYS a failure, regardless of positive modifiers.
- Rolls of **99** and **00** are Astounding Failures, often resulting in a Fumble or complication.

## 5. Group Tests & Assisting
- **Assisting**: One character can assist another if they have the relevant skill. This grants a **+10 modifier** to the primary actor's test.
- **Group Tests**: If the whole party must sneak or search, have the character with the highest skill roll first. Their SL serves as a modifier for the rest of the group (+10 for positive SL, -10 for negative SL).
