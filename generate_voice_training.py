#!/usr/bin/env python3
"""
Generate a Piper TTS training corpus from your configured ElevenLabs voice.

Synthesizes ~500 phonetically diverse sentences at 22050 Hz and writes them
in LJSpeech format, ready for the Piper training pipeline.

Output:
    voice_training/
        wavs/           22050 Hz mono 16-bit WAV files
        metadata.csv    pipe-delimited transcript (LJSpeech format)

Usage:
    python generate_voice_training.py             # generate all, resume by default
    python generate_voice_training.py --fresh     # ignore existing WAVs, regenerate
    python generate_voice_training.py --delay 1.0 # slower API calls (rate-limit safe)

After generation, train with Piper:
    See: https://github.com/rhasspy/piper/blob/master/TRAINING.md
    Quick start (requires piper-train + GPU recommended):
        python -m piper_train.preprocess \\
            --language en-us \\
            --input-dir voice_training/ \\
            --output-dir voice_training/preprocessed/
        python -m piper_train \\
            --dataset-dir voice_training/preprocessed/ \\
            --accelerator gpu --devices 1 \\
            --quality medium --max_epochs 6000
        python -m piper_train.export_onnx \\
            --checkpoint voice_training/preprocessed/lightning_logs/.../last.ckpt \\
            --output models/omega7.onnx
    Then set PIPER_MODEL_PATH=models/omega7.onnx in .env
"""

from __future__ import annotations
import argparse
import io
import os
import pathlib
import time
import wave

from dotenv import load_dotenv
load_dotenv()

API_KEY  = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID = os.environ["ELEVENLABS_VOICE_ID"]
MODEL_ID = "eleven_turbo_v2"

SAMPLE_RATE = 22050   # Hz — Piper's required input rate
CHANNELS    = 1
SAMPWIDTH   = 2       # 16-bit

# ── Phonetically diverse training corpus ──────────────────────────────────────
# Covers all English phonemes, prosodic patterns, sentence lengths, and stress
# positions. Harvard IEEE sentences anchor phonetic coverage; the rest extend it.

SENTENCES: list[str] = [

    # ── Harvard IEEE Lists 1–10 (standard TTS evaluation corpus) ──────────────
    "The birch canoe slid on the smooth planks.",
    "Glue the sheet to the dark blue background.",
    "It's easy to tell the depth of a well.",
    "These days a chicken leg is a rare dish.",
    "Rice is often served in round bowls.",
    "The juice of lemons makes fine punch.",
    "The box was thrown beside the parked truck.",
    "The hogs were fed chopped corn and garbage.",
    "Four hours of steady work faced us.",
    "Large size in stockings is hard to sell.",
    "The boy was there when the sun rose.",
    "A rod is used to catch pink salmon.",
    "The source of the huge river is the clear mountain spring.",
    "Kick the ball straight and follow through.",
    "Help the woman get back to her feet.",
    "A pot of tea helps to pass the evening.",
    "Smoky fires lack flame and heat.",
    "The soft cushion broke the man's fall.",
    "The salt breeze came across from the sea.",
    "The girl at the booth sold fifty bonds.",
    "The small pup gnawed a hole in the sock.",
    "The fish twisted and turned on the bent hook.",
    "Press the pants and sew a button on the vest.",
    "The swan on the lake attracted much attention.",
    "The beauty of the view stunned the young boy.",
    "Two blue fish swam in the tank.",
    "Her well-trained cat sat beside her.",
    "Rock the boat gently with your oar.",
    "Hoist the load to your left shoulder.",
    "Take the winding path to reach the lake.",
    "Note closely the size of the gas tank.",
    "Wipe the grease off his dirty face.",
    "Mend the coat before you go out.",
    "The wrist band was of bright red leather.",
    "The stray cat gave birth to kittens.",
    "The young girl gave no clear response.",
    "The meal was cooked before the bell rang.",
    "What joy there is in living.",
    "A king ruled the state in the early days.",
    "The ship was torn apart on the sharp reef.",
    "Sickness kept him home the third week.",
    "The wide road shimmered in the hot sun.",
    "The lazy cow lay in the cool grass.",
    "Lift the square stone over the fence.",
    "The rope will bind the seven books at once.",
    "Hop over the fence and plunge in.",
    "The friendly gang left the drug store.",
    "Mesh wire keeps the cheese fresh.",
    "The wolf roamed the hills on dark nights.",
    "The dune rose from the sands below.",
    "Crouch before you jump or miss the mark.",
    "The faint smell of oil was in the air.",
    "The pleasant hours fly by quickly.",
    "A tall stranger stood at the door.",
    "She had her dark hair tied in a knot.",
    "The old oak tree turned leaves in fall.",
    "The gold ring fits only a pierced ear.",
    "The sharp knife cut through the coarse twine.",
    "Bad weather will bring floods next spring.",
    "The school was built on land donated by the city.",
    "A large red deer came bounding over the hill.",
    "He picked up the old can from the trash.",
    "The steel was cut to the right length.",
    "The colt reared and threw the tall rider.",
    "It snowed, rained, and hailed the same morning.",
    "Read verse out loud for pleasure.",
    "Heed the words of the wise man.",
    "The square peg will not fit in the round hole.",
    "A horde of old junk filled the attic.",
    "Waste not, want not, is a maxim I would teach.",
    "Cut the pie into large parts.",
    "Men strive but seldom get rich.",
    "Always close the barn door tight.",
    "He lay prone and hardly moved a limb.",
    "The slush lay deep along the street.",
    "A wisp of cloud hung in the blue air.",
    "Strike a match and light the camp fire.",
    "It was done before the boy could see it.",
    "Both brothers wear the same sized shirt.",
    "The round hills were covered in snow.",
    "Flood the entire field with water.",
    "The whole team went ahead of the leader.",
    "A blue crane flew past the marshland.",
    "He sent the boy on a short errand.",
    "It takes a good eye to gauge distance.",
    "The sink is the thing in which we let dishes soak.",
    "The stem of the tall plant was weak.",
    "The clean breeze felt fresh on his face.",
    "The coat was clean and pressed and neat.",
    "Pour the stew from the pot into the plate.",
    "The thaw came early and the hills turned green.",
    "Those words were the cue for the actor to leave.",
    "The wires shifted in the wind and went slack.",
    "In the end the whole town was devastated.",
    "Pack the box with five dozen liquor jugs.",
    "The bronze doorknocker needs a good polish.",
    "Her purse was full of useless trash.",

    # ── Everyday conversational sentences ─────────────────────────────────────
    "Good morning. The coffee is ready on the counter.",
    "Have you seen my keys? I left them by the door.",
    "The weather forecast calls for rain this afternoon.",
    "She reminded him to pick up groceries on the way home.",
    "Could you please pass the salt?",
    "The meeting starts in about fifteen minutes.",
    "I'll be back before dinner time, I promise.",
    "Would you like anything to drink with that?",
    "The traffic on the bridge was backed up for miles.",
    "He forgot his umbrella and got soaked in the rain.",
    "Let's take a walk after we finish eating.",
    "She checked the time and realized she was late.",
    "The package arrived three days earlier than expected.",
    "Turn left at the corner, then go straight for two blocks.",
    "Is there anything else I can help you with today?",
    "I need to charge my phone before we leave.",
    "The kids are already asleep upstairs.",
    "Can you turn the volume down just a little?",
    "There's a great restaurant around the corner from here.",
    "He thanked her and walked out into the cool evening air.",
    "The library closes at nine o'clock on weekdays.",
    "Please leave a message and I will call you back.",
    "The store was out of the brand she usually bought.",
    "We should probably head home before it gets dark.",
    "She laughed and shook her head in disbelief.",
    "The dog barked at every car that drove past the house.",
    "Could you hold the door open for just a moment?",
    "I almost forgot to mention the change in schedule.",
    "He made coffee while she read the morning news.",
    "The neighbors were playing music late into the night.",

    # ── Descriptive and narrative sentences ───────────────────────────────────
    "The ancient forest stretched for miles in every direction.",
    "Sunlight filtered through the dense canopy of leaves above.",
    "A narrow stone path wound its way up the steep hillside.",
    "The river carved a deep channel through the soft limestone.",
    "Stars filled the sky from horizon to horizon without a cloud.",
    "The old lighthouse stood alone at the edge of the rocky cliff.",
    "Waves crashed rhythmically against the weathered sea wall.",
    "The meadow was alive with the sound of insects in summer.",
    "A thin layer of frost covered the grass on winter mornings.",
    "The mountains shimmered purple and gold in the fading light.",
    "Thick fog rolled in from the bay and swallowed the city.",
    "The cathedral rose from the cobblestones in solemn grandeur.",
    "Autumn leaves drifted silently down from the tall maples.",
    "The abandoned house stood at the end of a long dirt road.",
    "Fireflies blinked in the warm darkness of the summer night.",
    "A single candle burned on the table in the empty room.",
    "The harbor was busy with fishing boats in the early dawn.",
    "Mud clung to their boots as they crossed the flooded field.",
    "The old clock tower chimed twelve times across the square.",
    "A hawk circled lazily high above the golden wheat fields.",
    "The road disappeared into the distance without a curve.",
    "Ice formed on the inside of the windows by midnight.",
    "The vineyard rows ran in perfect lines across the valley.",
    "A sudden wind scattered the fallen leaves across the yard.",
    "The valley below was patchwork green and gold in the light.",
    "Rain hammered the tin roof all through the long night.",
    "The bridge swayed slightly under the weight of heavy traffic.",
    "Embers glowed orange in the hearth as the fire died down.",
    "The garden was overgrown but still full of wild color.",
    "Mist clung to the low places in the field at dawn.",

    # ── Questions and dialogue ─────────────────────────────────────────────────
    "What time does the next train arrive at the station?",
    "Have you ever visited the mountains in the winter?",
    "Why didn't you call when you said you would?",
    "Do you think the weather will clear up by tomorrow?",
    "How long have you been living in this neighborhood?",
    "Where did you say you were going after the meeting?",
    "Would you prefer to sit inside or out on the patio?",
    "Has anyone seen the report that was on my desk?",
    "When did you last speak to someone about this problem?",
    "Are you sure that's the right direction to take?",
    "Which of these options do you think is most practical?",
    "Did you remember to lock the back door before you left?",
    "How do you manage to stay so calm under pressure?",
    "Is there enough time to finish before the deadline?",
    "What exactly did he say when you told him the news?",
    "Can you explain what happened after the lights went out?",
    "Who was the last person to use the car this morning?",
    "Should we wait here or move on and meet them later?",
    "Don't you think we should take a break soon?",
    "Isn't it strange how quickly the weeks seem to pass?",
    "You remember what happened last time, don't you?",
    "That was a longer journey than we expected, wasn't it?",
    "Why not just tell them the truth and be done with it?",
    "Couldn't we find a simpler solution than that?",
    "Isn't there another way to approach this problem?",

    # ── Complex and compound sentences ────────────────────────────────────────
    "Although the forecast predicted rain, the day turned out to be bright and clear.",
    "She had been waiting for nearly an hour when the bus finally appeared.",
    "The project was finished on time despite the many obstacles the team encountered.",
    "He realized, only after he had left, that he forgot his wallet on the counter.",
    "The results were surprising, not because they were unexpected, but because of their scale.",
    "By the time she arrived at the station, the last train had already departed.",
    "The company had to revise its entire strategy after the market shifted so quickly.",
    "Even though they were exhausted, they pushed on until they reached the summit.",
    "If you look carefully at the map, you can see the shortcut through the woods.",
    "While some people prefer the city, others find peace in the quiet countryside.",
    "The old manuscript, which had been lost for centuries, was found in a monastery.",
    "She smiled when she saw him, though she had not expected him to be there at all.",
    "The decision, once made, could not easily be reversed without serious consequences.",
    "As the crowd grew larger, it became harder to hear anything above the noise.",
    "The report concluded that further investigation would be necessary before any action.",
    "Whether or not the plan succeeds will depend on the cooperation of the whole group.",
    "He had traveled to many countries but had never seen anything quite like this.",
    "The bridge, completed after decades of construction, opened to great celebration.",
    "Not all questions have easy answers, and this one was no exception to that rule.",
    "The storm, which had been building offshore for days, finally reached the coast.",

    # ── Short punchy sentences with varied stress ──────────────────────────────
    "Stop. Think. Then act.",
    "It's done.",
    "Are you certain?",
    "I heard you.",
    "That's enough.",
    "Try again.",
    "Not yet.",
    "Well done.",
    "Come in.",
    "Stand back.",
    "It works.",
    "Look out!",
    "Hold on.",
    "Not bad.",
    "Move along.",
    "Fair enough.",
    "Speak up.",
    "Sit down.",
    "Step aside.",
    "Pay attention.",
    "Eyes front.",
    "At ease.",
    "Never mind.",
    "Carry on.",
    "As you were.",

    # ── Numbers, time, measurement ─────────────────────────────────────────────
    "The meeting is scheduled for three fifteen in the afternoon.",
    "He ran the full distance in just under twenty-two minutes.",
    "The temperature dropped to minus five overnight.",
    "She ordered two dozen eggs and a pound of butter.",
    "The delivery is expected between nine and eleven in the morning.",
    "The building stands at four hundred and forty feet tall.",
    "They live about thirty miles north of the city center.",
    "The package weighs approximately three and a half kilograms.",
    "The event starts at seven thirty and ends around midnight.",
    "He scored ninety-four points out of a possible one hundred.",
    "The old bridge was built in eighteen ninety-three.",
    "She called at half past six to say she was running late.",
    "The recipe calls for two cups of flour and one of sugar.",
    "The train leaves platform seven at quarter to eight.",
    "Interest rates have risen by half a percent this quarter.",

    # ── Technical and procedural language ─────────────────────────────────────
    "First, ensure that all connections are properly secured before powering on.",
    "The software requires at least eight gigabytes of available memory.",
    "Calibrate the sensor by holding it level for ten seconds.",
    "The error log showed a pattern of failures occurring after midnight.",
    "All data must be encrypted before transmission across the network.",
    "The firmware update should complete within approximately three minutes.",
    "Press and hold the reset button for five seconds until the light flashes.",
    "The output signal should measure between three and five volts.",
    "System diagnostics showed no anomalies across all primary subsystems.",
    "The backup process runs automatically every night at two in the morning.",
    "Configure the network settings before attempting to connect the device.",
    "The process completed successfully with no errors or warnings reported.",
    "Verify that the input file matches the expected format before proceeding.",
    "The algorithm processes each request in under fifty milliseconds.",
    "Restart the service after making any changes to the configuration file.",

    # ── Emotion and emphasis ───────────────────────────────────────────────────
    "I can't believe how quickly everything changed.",
    "That is absolutely not what I said.",
    "You have no idea how important this is.",
    "This is extraordinary. I have never seen anything like it.",
    "He was furious, and rightfully so.",
    "She was genuinely moved by the kindness of the gesture.",
    "That's the most ridiculous thing I have ever heard.",
    "I'm not worried. I'm terrified.",
    "We did it. Against all odds, we actually did it.",
    "I want you to know that I am truly grateful.",
    "This changes everything. Everything.",
    "He looked at her and, for a moment, said nothing.",
    "Something about this doesn't feel right.",
    "I knew from the start that it would come to this.",
    "There's no turning back now. We've come too far.",

    # ── Phoneme-targeted coverage sentences ───────────────────────────────────
    # Fricatives and affricates
    "The chef chose a fresh fish for the chowder.",
    "She sells seashells by the seashore every summer.",
    "The thin thread stretched through the thick cloth.",
    "His vision of the future was sharp and vivid.",
    "The azure sky above the azure sea seemed infinite.",
    # Plosives
    "Peter picked a peck of pickled peppers.",
    "The black dog bit the big brown bear.",
    "Tom tied ten tight twine knots together.",
    "Kate quickly caught the kitten before it could escape.",
    "Barbara bought a bag of big rubber balls.",
    # Nasals and liquids
    "Nine nimble fingers knit a narrow knot.",
    "The main rail line ran along the mountain lane.",
    "Around and around the rugged rock the ragged rascal ran.",
    "Nolan knew the narrow road ran near the river.",
    "A million men marched in the moonlit night.",
    # Vowel variety
    "Beets, bates, bites, boats, boots are all food.",
    "The cat sat on a mat with a flat cap.",
    "He ate eight oranges in a row.",
    "The pool by the school is cool and full.",
    "Bright light might frighten the night bird.",
    # Consonant clusters
    "Strength through struggle builds character.",
    "The sphinx scratched at the rough stone threshold.",
    "Split the crisp strips into three equal lengths.",
    "The text was compressed into a strict format.",
    "She glimpsed the world through the frosted glass.",
    # Unstressed syllables and schwa
    "The computer on the table belongs to the professor.",
    "A collection of photographs covered the entire wall.",
    "The government announced a series of new regulations.",
    "Numerous animals inhabit the surrounding wilderness.",
    "The particular problem requires a specific solution.",

    # ── Varied prosody and rhythm ──────────────────────────────────────────────
    "One, two, three. Ready? Go.",
    "It was a dark and stormy night.",
    "The best is yet to come.",
    "Easy come, easy go.",
    "All's well that ends well.",
    "Better late than never.",
    "Time flies when you're having fun.",
    "The early bird catches the worm.",
    "Actions speak louder than words.",
    "Every cloud has a silver lining.",
    "Look before you leap.",
    "You can't judge a book by its cover.",
    "Where there's a will, there's a way.",
    "The proof is in the pudding.",
    "Two heads are better than one.",

    # ── Additional coverage sentences ─────────────────────────────────────────
    "The morning light came in at a low angle through the blinds.",
    "She opened the window and breathed in the cold November air.",
    "The children lined up quietly and filed into the classroom.",
    "He checked the map one last time before setting out.",
    "The bookshelf was filled from floor to ceiling with paperbacks.",
    "A crow sat on the fence post and watched the yard.",
    "The candle flickered as the wind crept under the door.",
    "He pulled his collar up against the biting winter wind.",
    "The smell of pine needles filled the car on the drive home.",
    "She placed the letter in the envelope and sealed it shut.",
    "The kettle began to whistle from the back of the stove.",
    "He nodded slowly and looked out across the empty field.",
    "The trail narrowed as it entered the shadow of the ridge.",
    "She wiped her hands on the cloth and looked at her work.",
    "The engine ticked quietly as it cooled in the night air.",
    "He sat for a while without speaking, just listening.",
    "The drawer was stuck and it took both hands to open it.",
    "She turned the page and found the note tucked inside.",
    "The cat stretched and settled back into a tight curl.",
    "He waited until he was sure, then made his move.",
    "The rope frayed at the end where it rubbed the cleat.",
    "She spread the map across the table and studied it carefully.",
    "The fire had burned down to coals by the time he arrived.",
    "He kept his voice low and steady through the whole exchange.",
    "The road ran straight and flat all the way to the horizon.",
    "She stacked the plates and carried them through to the kitchen.",
    "The glass door slid open with a soft mechanical hiss.",
    "He rested his hand on the railing and looked down.",
    "The last of the light faded from the sky to the west.",
    "She folded the cloth carefully and put it away in the drawer.",
    "The lock clicked and the door swung silently inward.",
    "He found the key exactly where she said it would be.",
    "The ground was soft and dark from two days of steady rain.",
    "She set the alarm for six and turned off the lamp.",
    "The old radio crackled to life with static, then music.",
    "He traced the outline on the paper with a steady hand.",
    "The fog lifted slowly as the morning sun climbed higher.",
    "She pulled the curtain aside and looked out at the street.",
    "The sand was warm and dry between her fingers.",
    "He closed the book and set it face down on the arm of the chair.",
    "The ship's horn sounded twice before it left the dock.",
    "She pressed her ear to the wall and heard nothing.",
    "The jar was tightly sealed and he could not get it open.",
    "He stepped off the path to let the others pass.",
    "The creek was shallow enough to cross without getting wet.",
    "She wrote her name at the top of the form in careful letters.",
    "The gate latch was stiff from years of salt air and rust.",
    "He took a deep breath and knocked on the door.",
    "The shelf above the desk held a row of framed photographs.",
    "She glanced at the clock and decided there was still time.",

    # ── Extended narrative passages ────────────────────────────────────────────
    "The old man sat on the porch every evening watching the road.",
    "She kept a journal and wrote in it every night before sleeping.",
    "The clock on the wall had not been wound in years.",
    "He found the letter hidden inside the spine of a old book.",
    "The dog slept near the fire and twitched in his dream.",
    "She packed everything she owned into two canvas bags.",
    "The lighthouse keeper had not seen another person in weeks.",
    "He drew the curtains and sat down in the dark room.",
    "The well at the edge of the property had run dry in July.",
    "She learned to read by the light of a single bare bulb.",
    "The old truck barely made it over the top of the hill.",
    "He built the fence himself over the course of one long summer.",
    "The train station at night was quiet and strangely beautiful.",
    "She kept the photograph in a small wooden box under the bed.",
    "The garden had gone wild after three seasons of neglect.",
    "He watched the clouds pile up to the west before the storm.",
    "The path through the woods was marked with orange paint on the trees.",
    "She never told anyone what she saw that night by the river.",
    "The pier extended far out into the grey and choppy water.",
    "He folded his coat and placed it on the back of the chair.",
    "The smell of sawdust and oil filled the old workshop.",
    "She tied the boat to the dock and climbed out carefully.",
    "The field mice nested in the walls and rustled all night.",
    "He spread the tarpaulin over the woodpile before the rain came.",
    "The window above the sink looked out over the back alley.",
    "She scraped the frost from the windshield with a credit card.",
    "The chimney sweep left grey footprints across the white carpet.",
    "He pressed the clay into the mold with both thumbs.",
    "The radio tower blinked red against the darkening sky.",
    "She noticed the small detail that everyone else had overlooked.",
    "The old photographs showed a town that no longer existed.",
    "He sharpened the pencil and began to write on a fresh page.",
    "The broken tile had been there since before she moved in.",
    "She walked to the end of the dock and looked down into the water.",
    "The argument faded and the house went quiet again.",
    "He wrapped the glass in newspaper and packed it in the box.",
    "The tide came in faster than they had expected.",
    "She remembered the smell of the kitchen in her grandmother's house.",
    "The wind knocked the chairs off the deck during the night.",
    "He found a way through when every obvious path was blocked.",

    # ── Occupations and activity sentences ────────────────────────────────────
    "The carpenter measured twice before cutting the board.",
    "The nurse checked the chart and made a quiet note.",
    "The chef reduced the sauce until it was thick and glossy.",
    "The teacher wrote the assignment on the board in careful letters.",
    "The diver checked her tank and rolled backward off the boat.",
    "The mechanic wiped his hands and slid out from under the car.",
    "The baker arrived before dawn to start the first batch of bread.",
    "The pilot announced the cruising altitude over the intercom.",
    "The farmer checked the sky and decided to cut the field today.",
    "The surgeon scrubbed her hands for exactly the right amount of time.",
    "The librarian replaced the books in strict alphabetical order.",
    "The firefighter climbed the ladder without hesitation.",
    "The pianist played the same phrase until it felt exactly right.",
    "The geologist cracked the rock open to see what was inside.",
    "The tailor pinned the hem and stepped back to look.",
    "The sailor tied off the line and secured the fenders.",
    "The ranger led the group along the ridge as the sun rose.",
    "The archaeologist brushed the soil away from the fragment carefully.",
    "The glassblower shaped the molten material with practiced breath.",
    "The astronomer adjusted the telescope and held her breath.",

    # ── Science, nature, and observation ──────────────────────────────────────
    "Carbon dioxide is absorbed by plants during photosynthesis.",
    "The moon's gravity is responsible for the rise and fall of tides.",
    "Crystals form when atoms arrange themselves in repeating structures.",
    "Sound travels faster through water than it does through air.",
    "The magnetic field of the earth protects us from solar wind.",
    "Volcanoes form where tectonic plates meet or pull apart.",
    "A single lightning bolt can reach temperatures of thirty thousand kelvin.",
    "Bees navigate by sensing polarized light from the sky.",
    "The human eye can distinguish about ten million distinct colors.",
    "Glaciers move imperceptibly slowly but reshape entire landscapes.",
    "Migratory birds use the earth's magnetic field as a compass.",
    "The deepest part of the ocean lies in the western Pacific.",
    "Trees communicate through networks of fungi in the soil.",
    "The speed of light in a vacuum is constant regardless of the observer.",
    "Clouds form when warm moist air rises and cools rapidly.",

    # ── Instruction and procedure ──────────────────────────────────────────────
    "Remove the cover by pressing the two tabs on either side.",
    "Allow the mixture to cool completely before adding the final ingredient.",
    "Ensure that all power sources are disconnected before servicing.",
    "Thread the needle from left to right, pulling through evenly.",
    "Apply a thin coat and let it dry for at least four hours.",
    "Place the pieces face down and align them carefully before pressing.",
    "Loosen the four bolts before attempting to lift the panel.",
    "Stir constantly over medium heat until the mixture thickens.",
    "Check the seal for any gaps or bubbles before continuing.",
    "Back up your data before making any changes to the system.",
    "Gently fold the egg whites into the batter until just combined.",
    "Turn the key counterclockwise a quarter turn to unlock the mechanism.",
    "Apply even pressure across the entire surface for best adhesion.",
    "Allow twelve hours before exposing the repair to moisture.",
    "Read all instructions thoroughly before beginning the assembly.",

    # ── History and place ──────────────────────────────────────────────────────
    "The Roman road ran straight from one end of the province to the other.",
    "The city was founded on a small promontory overlooking the bay.",
    "The old bridge has stood at the crossing for over three centuries.",
    "The dialect of the island preserved sounds lost elsewhere.",
    "The trade route connected the eastern highlands to the coastal ports.",
    "The castle was built on the only high ground for many miles.",
    "The original settlement grew up around a freshwater spring.",
    "The canal was dug by hand over a period of twelve years.",
    "The map showed the territory as it was a hundred years ago.",
    "The border shifted three times before the current line was drawn.",
    "The archive held documents going back to the earliest settlement.",
    "The old market square has been the heart of the town for generations.",
    "The expedition followed the river upstream for thirty days.",
    "The cliff face was carved into during the long occupation of the valley.",
    "The ruins were found by accident during the construction of the road.",

    # ── Contrast and comparison ────────────────────────────────────────────────
    "Some days are harder than others, but none are truly hopeless.",
    "The silence after the storm felt louder than the storm itself.",
    "What seemed impossible in the morning was finished by evening.",
    "The younger of the two was clearly the more experienced.",
    "A small mistake early on had large consequences much later.",
    "The new building was taller, but the old one was better made.",
    "Her approach was cautious; his was bold to the point of recklessness.",
    "The plan looked simple on paper and proved complex in practice.",
    "The difference between the two samples was subtle but significant.",
    "Short-term discomfort often leads to long-term advantage.",
    "The cost of doing nothing can exceed the cost of acting.",
    "What was rare in the past is now common; what was common is now rare.",
    "The slow path and the fast path both arrived at the same place.",
    "Logic pointed one way; intuition pointed the other.",
    "The gains were modest, but they were real and they were lasting.",

    # ── Reflection and philosophy ──────────────────────────────────────────────
    "A person who never makes a mistake has never tried anything new.",
    "The measure of a day is not its length but what is done within it.",
    "Memory is not a record of the past but a reconstruction of it.",
    "The most difficult conversations are often the most necessary ones.",
    "A question asked at the right moment can change everything.",
    "We understand things differently depending on where we stand.",
    "The simplest explanation is often, though not always, the correct one.",
    "Patience is not passive waiting but active endurance.",
    "A small habit, sustained long enough, becomes part of who you are.",
    "The right word spoken at the wrong moment changes its meaning entirely.",
    "What we choose not to say reveals as much as what we do say.",
    "Experience does not automatically produce wisdom.",
    "Familiarity makes it hard to see what strangers notice at once.",
    "The value of a tool is determined by the work it enables.",
    "Progress rarely looks like progress when you are in the middle of it.",

    # ── Longer varied sentences ────────────────────────────────────────────────
    "The morning fog had not yet lifted when they set out across the valley.",
    "She had asked the same question three times and received three different answers.",
    "The repairs took longer than anyone had anticipated, but the result was worth it.",
    "He could not recall whether he had locked the door or simply thought about it.",
    "The sound of footsteps on the gravel announced her return before she appeared.",
    "They had planned to leave at dawn but did not manage it until well after sunrise.",
    "The conversation drifted from one subject to another without ever reaching a conclusion.",
    "He stood at the top of the stairs for a long moment before deciding to go back down.",
    "The record had not been broken in forty years, and few expected it to be broken now.",
    "She recognized the handwriting before she had read a single word of the letter.",
    "The structure had been damaged in the flood, but the foundations remained solid.",
    "He had the distinct feeling of having been in this exact situation before.",
    "The meeting ended without a decision, which was itself a kind of decision.",
    "She finished the last sentence of the chapter and closed the book with a sigh.",
    "The light in the room changed as the clouds moved across the afternoon sun.",
    "He had not expected to find anyone there, and the discovery unsettled him.",
    "The children ran ahead and were out of sight before the adults had started.",
    "She noticed that the chair had been moved slightly from where it usually stood.",
    "The answer was simpler than he had made it by thinking about it too long.",
    "The last guests left just before midnight, leaving the house quiet at last.",
]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPWIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Piper TTS training corpus from ElevenLabs voice")
    parser.add_argument("--out",   default="voice_training", help="Output directory (default: voice_training)")
    parser.add_argument("--fresh", action="store_true",      help="Regenerate all files, ignoring existing WAVs")
    parser.add_argument("--delay", type=float, default=0.5,  help="Seconds between API calls (default: 0.5)")
    args = parser.parse_args()

    out_dir  = pathlib.Path(args.out)
    wavs_dir = out_dir / "wavs"
    wavs_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "metadata.csv"

    from elevenlabs.client import ElevenLabs
    client = ElevenLabs(api_key=API_KEY)

    total     = len(SENTENCES)
    generated = 0
    skipped   = 0
    errors    = 0
    meta_lines: list[str] = []

    print(f"Corpus: {total} sentences")
    print(f"Output: {out_dir}/")
    print(f"Voice:  {VOICE_ID}  |  Model: {MODEL_ID}  |  Rate: {SAMPLE_RATE} Hz")
    if not args.fresh:
        print("Resume mode: existing WAV files will be skipped (--fresh to override)")
    print()

    for idx, sentence in enumerate(SENTENCES, start=1):
        stem     = f"omega7_{idx:04d}"
        wav_path = wavs_dir / f"{stem}.wav"

        if not args.fresh and wav_path.exists():
            skipped += 1
            meta_lines.append(f"{stem}|{sentence}|{sentence}")
            continue

        preview = sentence[:70] + ("…" if len(sentence) > 70 else "")
        print(f"[{idx:>3}/{total}] {preview}")

        try:
            audio_iter = client.text_to_speech.convert(
                voice_id=VOICE_ID,
                text=sentence,
                model_id=MODEL_ID,
                output_format="pcm_22050",
            )
            pcm = b"".join(audio_iter)
            wav_path.write_bytes(_pcm_to_wav(pcm))
            meta_lines.append(f"{stem}|{sentence}|{sentence}")
            generated += 1
        except Exception as exc:
            print(f"         ERROR: {exc}")
            errors += 1

        time.sleep(args.delay)

    # Write metadata even if some files errored — only include successful entries
    meta_path.write_text("\n".join(meta_lines) + "\n", encoding="utf-8")

    print()
    print("=" * 60)
    print(f"Generated : {generated}")
    print(f"Skipped   : {skipped}")
    print(f"Errors    : {errors}")
    print(f"Metadata  : {meta_path}")
    print()
    print("Next steps — train the Piper voice model:")
    print()
    print("  1. Install piper-train (on a machine with a GPU or Apple Silicon):")
    print("       pip install piper-train")
    print()
    print("  2. Preprocess the dataset:")
    print(f"       python -m piper_train.preprocess \\")
    print(f"           --language en-us \\")
    print(f"           --input-dir {out_dir}/ \\")
    print(f"           --output-dir {out_dir}/preprocessed/")
    print()
    print("  3. Train (adjust --devices and --batch-size for your hardware):")
    print(f"       python -m piper_train \\")
    print(f"           --dataset-dir {out_dir}/preprocessed/ \\")
    print(f"           --accelerator gpu --devices 1 \\")
    print(f"           --quality medium --max_epochs 6000")
    print()
    print("  4. Export the trained checkpoint to ONNX:")
    print(f"       python -m piper_train.export_onnx \\")
    print(f"           --checkpoint {out_dir}/preprocessed/lightning_logs/version_0/checkpoints/last.ckpt \\")
    print(f"           --output models/omega7.onnx")
    print()
    print("  5. Set in .env:")
    print("       PIPER_MODEL_PATH=models/omega7.onnx")
    print("       TTS_BACKEND=piper")


if __name__ == "__main__":
    main()
