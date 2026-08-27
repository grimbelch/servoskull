/* campaign.js — the campaign manager.
 *
 * A standalone front end over the /api/campaign endpoints, styled with the
 * same book.css as the module viewer so the whole campaign side of the app
 * reads as one printed volume rather than two unrelated screens.
 *
 * The bias throughout is towards the things a GM touches mid-session: wound
 * and fate trackers sit on the roster where they can be adjusted without
 * opening anything, and every list is editable in place.
 */

(function () {
  "use strict";

  var app = document.getElementById("app");

  // ------------------------------------------------------------ utilities ---

  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "html") node.innerHTML = value;
        else if (key.slice(0, 2) === "on") node[key.toLowerCase()] = value;
        else node.setAttribute(key, value);
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      if (Array.isArray(child)) child.forEach(function (c) { if (c) node.appendChild(c); });
      else if (typeof child === "string") node.appendChild(document.createTextNode(child));
      else node.appendChild(child);
    }
    return node;
  }

  function api(path, body) {
    var options = { headers: { "Content-Type": "application/json" } };
    if (body !== undefined) {
      options.method = "POST";
      options.body = JSON.stringify(body);
    }
    return fetch(path, options)
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        if (payload && payload.ok === false) throw new Error(payload.error || "Request failed");
        return payload;
      });
  }

  var noticeTimer = null;
  function notice(message, bad) {
    var existing = document.querySelector(".notice");
    if (existing) existing.remove();
    var node = el("div", { class: "notice" + (bad ? " bad" : ""), text: message });
    document.body.appendChild(node);
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(function () { node.remove(); }, bad ? 6000 : 2200);
  }

  function num(value, fallback) {
    var parsed = parseInt(value, 10);
    return isNaN(parsed) ? (fallback === undefined ? 0 : fallback) : parsed;
  }

  // ---------------------------------------------------------------- state ---

  var C = null;          // the active campaign
  var campaigns = [];
  var view = "campaign";
  var openChar = null;   // index into C.characters when a sheet is open
  var draft = null;      // the character being edited
  var dirty = false;

  var CHARS = ["WS", "BS", "S", "T", "I", "Ag", "Dex", "Int", "WP", "Fel"];
  var RACES = [
    ["human", "Human (Reiklander)"], ["dwarf", "Dwarf"], ["halfling", "Halfling"],
    ["high_elf", "High Elf"], ["wood_elf", "Wood Elf"]
  ];

  function refresh() {
    return api("/api/campaign").then(function (payload) {
      setCampaign(payload.active_campaign);
      campaigns = payload.campaigns || [];
    });
  }

  /* The API accepts resilience/resolve as nested objects but hands them back
   * flattened, so reshape them on the way in to keep one shape in the UI. */
  function setCampaign(campaign) {
    C = campaign;
    (C && C.characters ? C.characters : []).forEach(normaliseCharacter);
    return C;
  }

  function normaliseCharacter(character) {
    if (typeof character.resilience !== "object" || character.resilience === null) {
      character.resilience = { total: character.resilience_tot || 0 };
    }
    if (typeof character.resolve !== "object" || character.resolve === null) {
      character.resolve = { current: character.resolve_curr || 0 };
    }
    return character;
  }

  // --------------------------------------------------------------- fields ---

  /* Campaign-level fields save themselves when they lose focus; there is no
   * form to submit, so there is nothing to forget to press. */
  function field(label, value, onSave, opts) {
    opts = opts || {};
    var wrap = el("div", { class: "field" });
    if (label) wrap.appendChild(el("label", { text: label }));

    var input = el(opts.rows ? "textarea" : "input", {
      value: value === null || value === undefined ? "" : value,
      type: opts.type || "text",
      rows: opts.rows,
      placeholder: opts.placeholder
    });
    if (opts.rows) input.value = value || "";

    input.onblur = function () {
      if (String(input.value) === String(value === null || value === undefined ? "" : value)) return;
      Promise.resolve(onSave(input.value)).then(function () {
        wrap.classList.add("saved");
        setTimeout(function () { wrap.classList.remove("saved"); }, 900);
      }).catch(function (error) { notice(error.message, true); });
    };
    wrap.appendChild(input);
    return wrap;
  }

  function selectField(label, value, choices, onSave) {
    var wrap = el("div", { class: "field" });
    if (label) wrap.appendChild(el("label", { text: label }));

    /* Records written by Omega7 or an older build can hold values outside our
     * list. Carry them as an extra option so opening the editor never quietly
     * rewrites a field the user did not touch. */
    var list = choices.slice();
    var known = list.some(function (choice) {
      var pair = Array.isArray(choice) ? choice : [choice, choice];
      return String(pair[0]) === String(value);
    });
    if (!known && value !== null && value !== undefined && String(value) !== "") {
      list.unshift([value, String(value)]);
    }

    var select = el("select", null, list.map(function (choice) {
      var pair = Array.isArray(choice) ? choice : [choice, choice];
      return el("option", { value: pair[0], selected: String(pair[0]) === String(value) }, pair[1]);
    }));
    select.onchange = function () {
      Promise.resolve(onSave(select.value)).catch(function (e) { notice(e.message, true); });
    };
    wrap.appendChild(select);
    return wrap;
  }

  /* Sheet fields edit the local draft; the draft is saved as a whole. */
  function draftField(label, path, opts) {
    opts = opts || {};
    var wrap = el("div", { class: "field" });
    if (label) wrap.appendChild(el("label", { text: label }));
    var input = el(opts.rows ? "textarea" : "input", {
      type: opts.type || "text",
      rows: opts.rows,
      placeholder: opts.placeholder
    });
    input.value = readPath(draft, path);
    input.oninput = function () {
      writePath(draft, path, opts.type === "number" ? num(input.value) : input.value);
      markDirty();
    };
    wrap.appendChild(input);
    return wrap;
  }

  function readPath(object, path) {
    var value = path.split(".").reduce(function (acc, key) {
      return acc === null || acc === undefined ? acc : acc[key];
    }, object);
    return value === null || value === undefined ? "" : value;
  }

  function writePath(object, path, value) {
    var keys = path.split(".");
    var last = keys.pop();
    var target = keys.reduce(function (acc, key) {
      if (!acc[key] || typeof acc[key] !== "object") acc[key] = {};
      return acc[key];
    }, object);
    target[last] = value;
  }

  function markDirty() {
    if (dirty) return;
    dirty = true;
    var bar = document.getElementById("save-bar");
    if (bar) bar.style.visibility = "visible";
  }

  // --------------------------------------------------------- campaign view ---

  function updateField(key, value) {
    var patch = {};
    patch[key] = value;
    return api("/api/campaign/update", patch).then(function (payload) {
      setCampaign(payload.active_campaign);
    });
  }

  function campaignView(sheet) {
    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: "The Campaign" })));

    sheet.appendChild(el("div", { class: "grid-2" },
      field("Name", C.name, function (v) { return updateField("name", v); }),
      field("Adventure", C.adventure, function (v) { return updateField("adventure", v); })));

    sheet.appendChild(el("div", { class: "grid-2" },
      field("Current location", C.current_location, function (v) { return updateField("current_location", v); }),
      field("Current scene", C.current_scene, function (v) { return updateField("current_scene", v); })));

    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: "Party Ambitions" })));
    sheet.appendChild(el("div", { class: "grid-2" },
      field("Short term", C.party_ambition_short, function (v) { return updateField("party_ambition_short", v); }),
      field("Long term", C.party_ambition_long, function (v) { return updateField("party_ambition_long", v); })));

    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: "Gamemaster Notes" })));
    sheet.appendChild(field(null, C.notes, function (v) { return updateField("notes", v); }, { rows: 10 }));

    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: "Campaigns" })));
    sheet.appendChild(el("div", { class: "rows" }, campaigns.map(function (entry) {
      var key = entry.slug || entry.name;
      var active = key === (C && C.slug);
      return el("div", { class: "row" },
        el("div", null,
          el("div", { class: "title", text: entry.name || key }),
          el("div", { class: "meta", text: [
            entry.adventure,
            (entry.character_count || 0) + (entry.character_count === 1 ? " adventurer" : " adventurers"),
            entry.current_location
          ].filter(Boolean).join(" \u00b7 ") })),
        active
          ? el("span", { class: "pill", text: "Active" })
          : el("button", {
              class: "btn quiet",
              onclick: function () {
                api("/api/campaign/load", { name: key })
                  .then(refresh)
                  .then(function () { notice("Campaign loaded."); render(); })
                  .catch(function (e) { notice(e.message, true); });
              }
            }, "Open"));
    })));

    var name = el("input", { class: "chronicle-input wide", placeholder: "New campaign name" });
    var adventure = el("input", { class: "chronicle-input", placeholder: "Adventure (optional)" });
    sheet.appendChild(el("div", { class: "row-actions", style: "margin-top:1rem" },
      name, adventure,
      el("button", {
        class: "btn solid",
        onclick: function () {
          if (!name.value.trim()) return notice("A campaign needs a name.", true);
          api("/api/campaign/new", { name: name.value.trim(), adventure: adventure.value.trim() })
            .then(function () { return refresh(); })
            .then(function () { notice("Campaign created."); render(); })
            .catch(function (e) { notice(e.message, true); });
        }
      }, "Begin a new campaign")));
  }

  // ------------------------------------------------------------ party view ---

  function saveCharacter(character, quiet) {
    /* The server stores `total` verbatim, so derive it here rather than trust
     * whatever the record was last saved with. */
    CHARS.forEach(function (stat) {
      var block = (character.characteristics || {})[stat];
      if (block && typeof block === "object") {
        block.total = num(block.initial) + num(block.advances);
      }
    });
    return api("/api/campaign/character/upsert", character).then(function (payload) {
      setCampaign(payload.active_campaign);
      if (!quiet) notice("Saved.");
    });
  }

  /* A tracker is a current/max pair with the two buttons a GM reaches for
   * most: one damage, one heal. Each nudge saves immediately. */
  function tracker(character, label, currentPath, maxPath) {
    var current = num(readPath(character, currentPath));
    var max = num(readPath(character, maxPath));
    var value = el("span", { class: "value", text: max ? current + " / " + max : String(current) });
    var fill = el("span", { style: "width:" + (max ? Math.max(0, Math.min(100, (current / max) * 100)) : 0) + "%" });
    var bar = el("div", { class: "bar" + (max && current / max <= 0.34 ? " low" : "") }, fill);

    function nudge(delta) {
      var next = Math.max(0, num(readPath(character, currentPath)) + delta);
      if (max) next = Math.min(next, max);
      writePath(character, currentPath, next);
      value.textContent = max ? next + " / " + max : String(next);
      fill.style.width = (max ? Math.max(0, Math.min(100, (next / max) * 100)) : 0) + "%";
      bar.className = "bar" + (max && next / max <= 0.34 ? " low" : "");
      saveCharacter(character, true).catch(function (e) { notice(e.message, true); });
    }

    return el("div", { class: "tracker" },
      el("span", { class: "name", text: label }),
      el("button", { onclick: function () { nudge(-1); }, title: "Spend or lose one" }, "\u2212"),
      el("div", null, value, bar),
      el("button", { onclick: function () { nudge(1); }, title: "Recover one" }, "+"));
  }

  function partyView(sheet) {
    var characters = C.characters || [];

    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: "The Party" }),
      el("span", { class: "muted tiny", text: characters.length + " adventurer" + (characters.length === 1 ? "" : "s") }),
      el("span", { class: "spacer" }),
      el("div", { class: "row-actions" },
        el("select", { id: "roll-race" }, RACES.map(function (pair) {
          return el("option", { value: pair[0] }, pair[1]);
        })),
        el("button", { class: "btn", onclick: rollNewCharacter }, "Roll an adventurer"),
        el("button", { class: "btn quiet", onclick: blankCharacter }, "Blank sheet"))));

    if (!characters.length) {
      sheet.appendChild(el("div", { class: "empty" },
        "No one has answered the call yet. Roll an adventurer to begin."));
      return;
    }

    sheet.appendChild(el("div", { class: "roster" }, characters.map(function (character, index) {
      var career = [character.race || character.species, character.career].filter(Boolean).join(" \u00b7 ");
      return el("div", { class: "pc" },
        el("h3", { text: character.name || "Unnamed", onclick: function () { openSheet(index); } }),
        career ? el("div", { class: "who", text: career }) : null,
        tracker(character, "Wounds", "wounds.current", "wounds.max"),
        tracker(character, "Fate", "fate.current", "fate.total"),
        tracker(character, "Fortune", "fortune.current", "fortune.total"),
        tracker(character, "Corrupt.", "corruption.current", "corruption.max"),
        el("div", { class: "row-actions", style: "margin-top:.8rem" },
          el("button", { class: "btn", onclick: function () { openSheet(index); } }, "Open sheet"),
          el("button", {
            class: "btn danger",
            onclick: function () {
              if (!confirm("Remove " + (character.name || "this character") + " from the party?")) return;
              api("/api/campaign/character/delete", { id: character.id, name: character.name })
                .then(refresh).then(function () { notice("Removed."); render(); })
                .catch(function (e) { notice(e.message, true); });
            }
          }, "Remove")));
    })));
  }

  function rollNewCharacter() {
    var select = document.getElementById("roll-race");
    var race = select ? select.value : "human";
    api("/api/campaign/roll_char", { race: race }).then(function (payload) {
      var block = payload.characteristics || {};
      var characteristics = {};
      CHARS.forEach(function (key) {
        var value = (block.characteristics || {})[key] || 30;
        characteristics[key] = { initial: value, advances: 0, total: value };
      });
      return saveCharacter({
        name: "New Adventurer",
        race: block.race_display || race,
        characteristics: characteristics,
        wounds: { max: block.wounds_max || 10, current: block.wounds_current || 10 },
        fate: { total: block.fate || 0, current: block.fate || 0 },
        fortune: { total: block.fortune || 0, current: block.fortune || 0 },
        resilience: { total: block.resilience || 0, current: block.resilience || 0 },
        resolve: { total: block.resolve || 0, current: block.resolve || 0 },
        move: { walk: block.move || 4, run: (block.move || 4) * 2 },
        xp: { total: block.xp_bonus || 0, spent: 0, current: block.xp_bonus || 0 }
      }, true);
    }).then(refresh).then(function () {
      notice("Adventurer rolled.");
      openSheet((C.characters || []).length - 1);
    }).catch(function (e) { notice(e.message, true); });
  }

  function blankCharacter() {
    saveCharacter({ name: "New Adventurer" }, true)
      .then(refresh)
      .then(function () { openSheet((C.characters || []).length - 1); })
      .catch(function (e) { notice(e.message, true); });
  }

  // ------------------------------------------------------- character sheet ---

  function charIndexById(id) {
    var list = C.characters || [];
    for (var i = 0; i < list.length; i++) {
      if (String(list[i].id) === String(id)) return i;
    }
    return -1;
  }

  function openSheet(index) {
    if (index < 0 || !(C.characters || [])[index]) return;
    openChar = index;
    draft = JSON.parse(JSON.stringify(C.characters[index]));
    dirty = false;
    view = "sheet";
    render();
  }

  function entryList(list, columns, placeholders) {
    var wrap = el("div", { class: "entries" });

    function row(entry, index) {
      var inputs = columns.map(function (key, position) {
        var input = el("input", {
          value: entry[key] === null || entry[key] === undefined ? "" : entry[key],
          placeholder: placeholders[position]
        });
        input.oninput = function () {
          entry[key] = input.value;
          markDirty();
        };
        return input;
      });
      var node = el("div", { class: "entry " + (columns.length === 2 ? "two" : "three") },
        inputs,
        el("button", {
          class: "drop",
          title: "Remove",
          onclick: function () {
            list.splice(index, 1);
            markDirty();
            rebuild();
          }
        }, "\u00d7"));
      return node;
    }

    function rebuild() {
      wrap.innerHTML = "";
      list.forEach(function (entry, index) { wrap.appendChild(row(entry, index)); });
      wrap.appendChild(el("div", { class: "row-actions", style: "margin-top:.5rem" },
        el("button", {
          class: "btn quiet",
          onclick: function () {
            var blank = {};
            columns.forEach(function (key) { blank[key] = ""; });
            list.push(blank);
            markDirty();
            rebuild();
          }
        }, "Add")));
    }

    rebuild();
    return wrap;
  }

  function characteristicsTable() {
    var head = el("tr", null, el("th", { text: "" }),
      CHARS.map(function (key) { return el("th", { text: key }); }));

    function line(label, key, editable) {
      var cells = CHARS.map(function (stat) {
        if (!draft.characteristics[stat] || typeof draft.characteristics[stat] !== "object") {
          draft.characteristics[stat] = { initial: 30, advances: 0, total: 30 };
        }
        var block = draft.characteristics[stat];
        if (!editable) {
          return el("td", { class: "derived", id: "total-" + stat, text: num(block.initial) + num(block.advances) });
        }
        var input = el("input", { value: num(block[key]), inputmode: "numeric" });
        input.oninput = function () {
          block[key] = num(input.value);
          block.total = num(block.initial) + num(block.advances);
          var total = document.getElementById("total-" + stat);
          if (total) total.textContent = block.total;
          markDirty();
        };
        return el("td", null, input);
      });
      return el("tr", null, el("th", { text: label }), cells);
    }

    return el("div", { class: "char-scroll" },
      el("table", { class: "char-edit" },
        el("thead", null, head),
        el("tbody", null,
          line("Initial", "initial", true),
          line("Advances", "advances", true),
          line("Total", "total", false))));
  }

  function sheetView(sheet) {
    if (!draft) { view = "party"; return partyView(sheet); }

    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: draft.name || "Unnamed Adventurer" }),
      el("span", { class: "spacer" }),
      el("div", { class: "row-actions" },
        el("button", { class: "btn quiet", onclick: function () { view = "party"; draft = null; render(); } }, "Back to party"),
        el("button", {
          class: "btn solid", id: "save-bar",
          style: "visibility:" + (dirty ? "visible" : "hidden"),
          onclick: function () {
            saveCharacter(draft).then(refresh).then(function () {
              dirty = false;
              draft = JSON.parse(JSON.stringify(C.characters[openChar] || draft));
              render();
            }).catch(function (e) { notice(e.message, true); });
          }
        }, "Save character"))));

    sheet.appendChild(el("div", { class: "grid-3" },
      draftField("Name", "name"),
      draftField("Species", "race"),
      draftField("Class", "class")));

    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Career", "career"),
      draftField("Career level", "career_level"),
      draftField("Career path", "career_path"),
      draftField("Status", "status")));

    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Age", "age"),
      draftField("Height", "height"),
      draftField("Hair", "hair"),
      draftField("Eyes", "eyes")));

    sheet.appendChild(el("div", { class: "grid-3" },
      draftField("Star sign", "star_sign"),
      draftField("Doomed", "doomed"),
      draftField("Motivation", "motivation")));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Characteristics" })));
    sheet.appendChild(characteristicsTable());

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Fate & Resilience" })));
    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Wounds", "wounds.current", { type: "number" }),
      draftField("Wounds max", "wounds.max", { type: "number" }),
      draftField("Fate", "fate.current", { type: "number" }),
      draftField("Fate total", "fate.total", { type: "number" })));
    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Fortune", "fortune.current", { type: "number" }),
      draftField("Fortune total", "fortune.total", { type: "number" }),
      draftField("Resilience", "resilience.total", { type: "number" }),
      draftField("Resolve", "resolve.current", { type: "number" })));
    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Movement", "move.walk", { type: "number" }),
      draftField("Run", "move.run", { type: "number" }),
      draftField("Corruption", "corruption.current", { type: "number" }),
      draftField("Sin", "sin", { type: "number" })));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Experience" })));
    sheet.appendChild(el("div", { class: "grid-3" },
      draftField("Current", "xp.current", { type: "number" }),
      draftField("Spent", "xp.spent", { type: "number" }),
      draftField("Total", "xp.total", { type: "number" })));

    var lists = el("div", { class: "sheet-grid split" });

    lists.appendChild(el("div", null,
      el("div", { class: "section-head" }, el("h2", { text: "Skills" })),
      entryList(draft.skills = draft.skills || [], ["name", "advances"], ["Skill", "Adv"])));

    lists.appendChild(el("div", null,
      el("div", { class: "section-head" }, el("h2", { text: "Talents" })),
      entryList(draft.talents = draft.talents || [], ["name", "times"], ["Talent", "Times"])));

    lists.appendChild(el("div", null,
      el("div", { class: "section-head" }, el("h2", { text: "Weapons" })),
      entryList(draft.weapons = draft.weapons || [], ["name", "damage", "qualities"],
        ["Weapon", "Damage", "Qualities"])));

    lists.appendChild(el("div", null,
      el("div", { class: "section-head" }, el("h2", { text: "Trappings" })),
      entryList(draft.trappings = draft.trappings || [], ["name", "encumbrance"], ["Trapping", "Enc"])));

    sheet.appendChild(lists);

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Armour" })));
    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Head", "armour.head", { type: "number" }),
      draftField("Body", "armour.body", { type: "number" }),
      draftField("Left arm", "armour.l_arm", { type: "number" }),
      draftField("Right arm", "armour.r_arm", { type: "number" })));
    sheet.appendChild(el("div", { class: "grid-4" },
      draftField("Left leg", "armour.l_leg", { type: "number" }),
      draftField("Right leg", "armour.r_leg", { type: "number" }),
      draftField("Encumbrance", "encumbrance.current", { type: "number" }),
      draftField("Enc. max", "encumbrance.max", { type: "number" })));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Wealth" })));
    sheet.appendChild(el("div", { class: "grid-3" },
      draftField("Gold crowns", "money.gc", { type: "number" }),
      draftField("Silver shillings", "money.ss", { type: "number" }),
      draftField("Brass pennies", "money.bp", { type: "number" })));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Ambitions" })));
    sheet.appendChild(el("div", { class: "grid-2" },
      draftField("Short term", "ambitions.short"),
      draftField("Long term", "ambitions.long")));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Psychology" })));
    sheet.appendChild(el("div", { class: "grid-2" },
      draftField("Mutations", "psychology.mutations"),
      draftField("Notes", "psychology.notes")));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "The Ten Questions" })));
    var questions = [
      ["origin", "Where are you from?"], ["family", "What is your family like?"],
      ["childhood", "What was your childhood like?"], ["why_leave", "Why did you leave home?"],
      ["friends", "Who are your friends and enemies?"], ["desire", "What do you value most?"],
      ["memories", "Who are your closest companions?"], ["religion", "What are your religious beliefs?"],
      ["loyalty", "To whom are you loyal?"], ["secret", "What is your secret?"]
    ];
    var grid = el("div", { class: "grid-2" });
    questions.forEach(function (pair) {
      grid.appendChild(draftField(pair[1], "ten_questions." + pair[0]));
    });
    sheet.appendChild(grid);
  }

  // ------------------------------------------------------ record  sections ---

  /* NPCs, locations and quests are all "a list of records with a few fields",
   * so they share one editor rather than three near-identical ones. */
  function recordSection(sheet, config) {
    var records = C[config.source] || [];

    sheet.appendChild(el("div", { class: "section-head" },
      el("h2", { text: config.title }),
      el("span", { class: "muted tiny", text: records.length + " " + (records.length === 1 ? config.noun : config.plural) }),
      el("span", { class: "spacer" }),
      el("button", {
        class: "btn solid",
        onclick: function () { editRecord(config, {}); }
      }, "Add " + config.noun)));

    if (!records.length) {
      sheet.appendChild(el("div", { class: "empty", text: config.empty }));
      return;
    }

    sheet.appendChild(el("div", { class: "rows" }, records.map(function (record) {
      var meta = config.meta(record).filter(Boolean);
      return el("div", { class: "row" },
        el("div", null,
          el("div", { class: "title", text: record[config.label] || "Untitled" }),
          meta.length ? el("div", { style: "margin:.25rem 0" }, meta.map(function (pair) {
            return el("span", { class: "pill " + (pair[1] || ""), text: pair[0] });
          })) : null,
          config.body(record) ? el("p", { text: config.body(record) }) : null),
        el("div", { class: "row-actions" },
          el("button", { class: "btn quiet", onclick: function () { editRecord(config, record); } }, "Edit"),
          el("button", {
            class: "btn danger",
            onclick: function () {
              if (!confirm("Delete \u201c" + (record[config.label] || "this") + "\u201d?")) return;
              api(config.deleteUrl, { id: record.id })
                .then(refresh).then(function () { notice("Deleted."); render(); })
                .catch(function (e) { notice(e.message, true); });
            }
          }, "Delete")));
    })));
  }

  function editRecord(config, record) {
    var working = JSON.parse(JSON.stringify(record || {}));
    var host = el("div", { class: "sheet paper overlay-card" });
    var overlay = el("div", { class: "overlay" }, host);

    host.appendChild(el("div", { class: "section-head" },
      el("h2", { text: (record && record.id ? "Edit " : "New ") + config.noun })));

    config.fields.forEach(function (spec) {
      if (spec.choices) {
        host.appendChild(selectField(spec.label, working[spec.key] || spec.choices[0], spec.choices,
          function (value) { working[spec.key] = value; }));
      } else {
        var wrap = el("div", { class: "field" }, el("label", { text: spec.label }));
        var input = el(spec.rows ? "textarea" : "input", { rows: spec.rows });
        input.value = working[spec.key] || "";
        input.oninput = function () { working[spec.key] = input.value; };
        wrap.appendChild(input);
        host.appendChild(wrap);
      }
    });

    host.appendChild(el("div", { class: "row-actions", style: "margin-top:1.2rem" },
      el("button", {
        class: "btn solid",
        onclick: function () {
          api(config.upsertUrl, working)
            .then(refresh)
            .then(function () { overlay.remove(); notice("Saved."); render(); })
            .catch(function (e) { notice(e.message, true); });
        }
      }, "Save"),
      el("button", { class: "btn quiet", onclick: function () { overlay.remove(); } }, "Cancel")));

    document.body.appendChild(overlay);
  }

  var NPC_CONFIG = {
    title: "Non-Player Characters", noun: "NPC", plural: "NPCs", source: "npcs",
    label: "name", empty: "No one of note yet.",
    upsertUrl: "/api/campaign/npc/upsert", deleteUrl: "/api/campaign/npc/delete",
    meta: function (r) {
      return [
        r.role_career && [r.role_career, ""],
        r.species && [r.species, ""],
        r.disposition && [r.disposition, /friend|ally|help/i.test(r.disposition) ? "good"
          : /hostile|enem|foe/i.test(r.disposition) ? "bad" : ""],
        r.status && [r.status, /dead|slain/i.test(r.status) ? "bad" : ""]
      ];
    },
    body: function (r) { return r.notes || r.motivations_goals || r.secrets_lore || ""; },
    fields: [
      { key: "name", label: "Name" },
      { key: "role_career", label: "Role or career" },
      { key: "species", label: "Species" },
      { key: "disposition", label: "Disposition", choices: ["Friendly", "Neutral", "Wary", "Hostile"] },
      { key: "status", label: "Status", choices: ["Alive", "Missing", "Dead"] },
      { key: "motivations_goals", label: "Motivations and goals", rows: 3 },
      { key: "secrets_lore", label: "Secrets the party does not know", rows: 3 },
      { key: "notes", label: "Notes", rows: 3 }
    ]
  };

  var LOCATION_CONFIG = {
    title: "Locations", noun: "location", plural: "locations", source: "locations",
    label: "name", empty: "The map is still blank.",
    upsertUrl: "/api/campaign/location/upsert", deleteUrl: "/api/campaign/location/delete",
    meta: function (r) {
      return [
        r.type && [r.type, ""],
        r.region && [r.region, ""],
        r.danger_level && [r.danger_level + " danger",
          /high|deadly/i.test(r.danger_level) ? "bad" : /low/i.test(r.danger_level) ? "good" : ""],
        [r.visited ? "Visited" : "Unvisited", r.visited ? "good" : ""]
      ];
    },
    body: function (r) { return r.description || r.history || ""; },
    fields: [
      { key: "name", label: "Name" },
      { key: "type", label: "Type", choices: ["City", "Town", "Village", "Inn", "Wilderness", "Ruin", "Stronghold"] },
      { key: "region", label: "Region" },
      { key: "controlling_faction", label: "Controlling faction" },
      { key: "danger_level", label: "Danger", choices: ["Low", "Moderate", "High", "Deadly"] },
      { key: "description", label: "Description", rows: 4 },
      { key: "history", label: "History", rows: 3 }
    ]
  };

  var QUEST_CONFIG = {
    title: "Quests & Encounters", noun: "quest", plural: "quests", source: "quests",
    label: "title", empty: "Nothing is afoot. Yet.",
    upsertUrl: "/api/campaign/quest/upsert", deleteUrl: "/api/campaign/quest/delete",
    meta: function (r) {
      return [
        r.type && [r.type, ""],
        r.status && [r.status, /complete|done/i.test(r.status) ? "good"
          : /failed|abandon/i.test(r.status) ? "bad" : ""],
        r.reward && ["Reward: " + r.reward, ""]
      ];
    },
    body: function (r) { return r.objective || r.notes || ""; },
    fields: [
      { key: "title", label: "Title" },
      { key: "type", label: "Type", choices: ["Main Quest", "Side Quest", "Encounter", "Rumour"] },
      { key: "status", label: "Status", choices: ["Active", "Completed", "Failed", "Abandoned"] },
      { key: "objective", label: "Objective", rows: 3 },
      { key: "reward", label: "Reward" },
      { key: "notes", label: "Notes", rows: 3 }
    ]
  };

  // -------------------------------------------------------------- timeline ---

  function timelineView(sheet) {
    var entries = C.timeline || [];

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Add to the Chronicle" })));
    var date = el("input", { class: "chronicle-input", placeholder: "In-game date" });
    var summary = el("input", { class: "chronicle-input wide", placeholder: "What happened" });
    sheet.appendChild(el("div", { class: "row-actions", style: "margin-top:.8rem" },
      date, summary,
      el("button", {
        class: "btn solid",
        onclick: function () {
          if (!summary.value.trim()) return notice("Describe what happened.", true);
          api("/api/campaign/timeline/add", {
            event_summary: summary.value.trim(), in_game_date: date.value.trim()
          }).then(refresh).then(function () { notice("Recorded."); render(); })
            .catch(function (e) { notice(e.message, true); });
        }
      }, "Record")));

    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "The Chronicle" })));
    if (!entries.length) {
      sheet.appendChild(el("div", { class: "empty", text: "Nothing has happened yet." }));
      return;
    }
    sheet.appendChild(el("div", { class: "rows" }, entries.slice().reverse().map(function (entry) {
      return el("div", { class: "row" },
        el("div", null,
          entry.in_game_date ? el("div", { class: "meta", text: entry.in_game_date }) : null,
          el("p", { text: entry.event_summary || entry.summary || "" })),
        el("div"));
    })));
  }

  // --------------------------------------------------------------- modules ---

  function modulesView(sheet) {
    sheet.appendChild(el("div", { class: "section-head" }, el("h2", { text: "Adventure Modules" })));
    var host = el("div", { class: "rows" });
    sheet.appendChild(host);

    api("/api/modules").then(function (payload) {
      var modules = payload.modules || [];
      if (!modules.length) {
        host.appendChild(el("div", { class: "empty", text: "No modules have been extracted yet." }));
        return;
      }
      modules.forEach(function (module) {
        host.appendChild(el("div", { class: "row" },
          el("div", null,
            el("div", { class: "title", text: module.title }),
            el("div", { style: "margin:.25rem 0" },
              el("span", { class: "pill", text: module.system || "WFRP 4E" }),
              el("span", { class: "pill", text: (module.chapter_count || 0) + " chapters" }),
              el("span", { class: "pill", text: (module.npc_count || 0) + " NPCs" }),
              el("span", { class: "pill", text: (module.page_count || 0) + " pages" }))),
          el("div", { class: "row-actions" },
            el("a", { class: "btn solid", href: "/module/" + module.slug, target: "_blank" }, "Open"))));
      });
    }).catch(function (e) {
      host.appendChild(el("div", { class: "empty", text: e.message }));
    });
  }

  // ---------------------------------------------------------------- chrome ---

  function masthead() {
    var tabs = [["campaign", "Campaign"], ["party", "Party"], ["npcs", "NPCs"],
                ["locations", "Locations"], ["quests", "Quests"],
                ["timeline", "Chronicle"], ["modules", "Modules"]];

    var switcher = el("select", null, campaigns.map(function (entry) {
      return el("option", {
        value: entry.name || entry.slug,
        selected: (entry.slug || entry.name) === (C && C.slug)
      }, entry.name || entry.slug);
    }));
    switcher.onchange = function () {
      api("/api/campaign/load", { name: switcher.value })
        .then(refresh).then(function () { view = "campaign"; render(); })
        .catch(function (e) { notice(e.message, true); });
    };

    return el("header", { class: "masthead" },
      el("div", { class: "brand" },
        el("small", { text: "Omega7 \u00b7 WFRP 4E" }),
        (C && C.name) || "No campaign"),
      campaigns.length > 1 ? switcher : null,
      el("div", { class: "tabs" }, tabs.map(function (pair) {
        return el("button", {
          "aria-selected": (view === pair[0] || (view === "sheet" && pair[0] === "party")) ? "true" : "false",
          onclick: function () {
            if (dirty && !confirm("This character has unsaved changes. Leave anyway?")) return;
            view = pair[0];
            draft = null;
            dirty = false;
            render();
          }
        }, pair[1]);
      })),
      el("a", { class: "btn quiet", href: "/", style: "text-decoration:none" }, "Terminal"));
  }

  function render() {
    app.className = "shell";
    app.innerHTML = "";
    app.appendChild(masthead());

    var scroll = el("div", { class: "page-scroll" });
    var sheet = el("div", { class: "sheet paper" });

    if (!C) {
      sheet.appendChild(el("div", { class: "empty" }, "No campaign is loaded."));
      campaignView(sheet);
    } else if (view === "campaign") campaignView(sheet);
    else if (view === "party") partyView(sheet);
    else if (view === "sheet") sheetView(sheet);
    else if (view === "npcs") recordSection(sheet, NPC_CONFIG);
    else if (view === "locations") recordSection(sheet, LOCATION_CONFIG);
    else if (view === "quests") recordSection(sheet, QUEST_CONFIG);
    else if (view === "timeline") timelineView(sheet);
    else if (view === "modules") modulesView(sheet);

    scroll.appendChild(sheet);
    app.appendChild(scroll);
    if (currentHash() !== hashFor()) {
      history.replaceState(null, "", "#" + hashFor());
    }
  }

  /* Deep links: every view is addressable, and an open sheet carries the
   * character's id so a reload lands back on the same adventurer. */
  function hashFor() {
    if (view === "sheet" && draft && draft.id != null) return "sheet/" + draft.id;
    return view;
  }

  function currentHash() {
    return location.hash.replace(/^#/, "");
  }

  var VIEWS = ["campaign", "party", "sheet", "npcs", "locations", "quests", "timeline", "modules"];

  function applyHash() {
    var raw = currentHash();
    var parts = raw.split("/");
    var name = parts[0] || "campaign";
    if (VIEWS.indexOf(name) === -1) name = "campaign";

    if (name === "sheet") {
      var index = parts[1] != null ? charIndexById(parts[1]) : openChar;
      if (index == null || index < 0 || !(C.characters || [])[index]) {
        view = "party";
        draft = null;
        openChar = null;
        return;
      }
      if (openChar !== index || !draft) {
        openChar = index;
        draft = JSON.parse(JSON.stringify(C.characters[index]));
        dirty = false;
      }
      view = "sheet";
      return;
    }

    view = name;
  }

  // ------------------------------------------------------------------ boot ---

  /* The campaign pages borrow the module's extracted paper so both halves of
   * the app are printed on the same stock. */
  function applyTheme() {
    return api("/api/modules").then(function (payload) {
      var first = (payload.modules || [])[0];
      if (!first) return;
      return api("/api/modules/" + first.slug).then(function (response) {
        var theme = (response.module || {}).theme;
        if (!theme) return;
        var root = document.documentElement;
        if (theme.background_recto) {
          root.style.setProperty("--paper-texture", "url('/asset/" + theme.background_recto + "')");
        }
        if (theme.rule) {
          root.style.setProperty("--ink-rule", "url('/asset/" + theme.rule + "')");
        }
      });
    }).catch(function () { /* the paper is decoration; carry on without it */ });
  }

  refresh()
    .then(applyTheme)
    .then(function () {
      applyHash();
      render();
      window.addEventListener("hashchange", function () {
        if (currentHash() === hashFor()) return;
        applyHash();
        render();
      });
    })
    .catch(function (error) {
      app.className = "loading";
      app.textContent = "Could not reach the campaign archives: " + error.message;
    });

  window.addEventListener("beforeunload", function (event) {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
