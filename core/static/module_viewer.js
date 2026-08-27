/* module_viewer.js — the Adventure Module Viewer.
 *
 * Reads a module straight out of /api/modules/<slug> and lays it out the way
 * the book lays itself out: a chapter at a time, two columns of justified
 * Caslon, stat blocks and tables in their printed form, and each chapter
 * carrying the accent colour of its own torn paper tab.
 *
 * The one thing deliberately not copied from print is the map key. In the book
 * the key is a panel of tiny numbers beside the plan; here the key is a live
 * list next to the map, so a GM can read a room description without hunting
 * for the number.
 */

(function () {
  "use strict";

  var slug = decodeURIComponent(
    (location.pathname.match(/\/module\/([^/?#]+)/) || [])[1] || ""
  );

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

  function esc(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /* Assets are stored in the database as repository-relative paths so the
   * database can be built on a workstation and served from the Pi. */
  function assetUrl(path) {
    if (!path) return "";
    if (/^https?:/.test(path)) return path;
    return "/asset/" + String(path).replace(/^\/+/, "");
  }

  function romanise(n) {
    var table = [[1000, "M"], [900, "CM"], [500, "D"], [400, "CD"], [100, "C"],
                 [90, "XC"], [50, "L"], [40, "XL"], [10, "X"], [9, "IX"],
                 [5, "V"], [4, "IV"], [1, "I"]];
    var out = "";
    table.forEach(function (pair) {
      while (n >= pair[0]) { out += pair[1]; n -= pair[0]; }
    });
    return out;
  }

  function parseList(value) {
    if (Array.isArray(value)) return value;
    if (!value) return [];
    try { return JSON.parse(value) || []; } catch (e) { return []; }
  }

  function traitText(entries) {
    return entries
      .map(function (entry) {
        return entry.value === null || entry.value === undefined
          ? entry.name
          : entry.name + " " + entry.value;
      })
      .join(", ");
  }

  // ------------------------------------------------------------ the model ---

  var M = null;          // the module payload
  var bySection = {};    // section id -> { assets, tables, npcs }
  var sectionById = {};
  var rootOf = {};       // section id -> its top-level root
  var roots = [];
  var view = "read";
  var currentRootId = null;
  var query = "";

  function index() {
    roots = M.sections || [];

    (function walk(list, root) {
      list.forEach(function (section) {
        sectionById[section.id] = section;
        rootOf[section.id] = root || section;
        walk(section.children || [], root || section);
      });
    })(roots, null);

    function bucket(id) {
      if (!bySection[id]) bySection[id] = { assets: [], tables: [], npcs: [] };
      return bySection[id];
    }

    (M.assets || []).forEach(function (asset) {
      if (asset.section_id) bucket(asset.section_id).assets.push(asset);
    });
    (M.tables || []).forEach(function (table) {
      if (table.section_id) bucket(table.section_id).tables.push(table);
    });
    (M.npcs || []).forEach(function (npc) {
      if (npc.section_id) bucket(npc.section_id).npcs.push(npc);
    });

    var firstChapter = roots.filter(function (r) { return r.kind === "chapter"; })[0];
    currentRootId = (firstChapter || roots[0] || {}).id || null;
  }

  function accentOf(section) {
    var root = section && rootOf[section.id];
    return (section && section.accent) || (root && root.accent) || "#7a1717";
  }

  // ------------------------------------------------------ prose rendering ---

  /* Bodies are stored as plain paragraphs separated by blank lines. A handful
   * carry the book's own run-in labels ("Skills:", "Trappings:"), which read
   * far better set as their own line than folded into the prose. */
  var RUNIN = /^(Skills|Talents|Traits|Trappings|Spells|Optional|Note|Special):/;

  function prose(body, opts) {
    var paragraphs = String(body || "")
      .split(/\n\s*\n/)
      .map(function (p) { return p.trim(); })
      .filter(Boolean);
    if (!paragraphs.length) return null;

    var wrap = el("div", {
      class: "prose" + (opts && opts.columns && paragraphs.length > 2 ? " two-column" : "")
    });

    paragraphs.forEach(function (text) {
      var match = text.match(RUNIN);
      if (match) {
        wrap.appendChild(
          el("p", {
            class: "trait-line",
            html: "<b>" + esc(match[1]) + ":</b>" + esc(text.slice(match[0].length))
          })
        );
      } else {
        wrap.appendChild(el("p", { html: highlight(text) }));
      }
    });
    return wrap;
  }

  function highlight(text) {
    var safe = esc(text);
    if (view !== "search" || !query) return safe;
    try {
      var re = new RegExp("(" + query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      return safe.replace(re, "<mark>$1</mark>");
    } catch (e) { return safe; }
  }

  // --------------------------------------------------------- stat  blocks ---

  var CHARS = [
    ["m", "M"], ["ws", "WS"], ["bs", "BS"], ["s", "S"], ["t", "T"], ["i", "I"],
    ["ag", "Ag"], ["dex", "Dex"], ["intl", "Int"], ["wp", "WP"], ["fel", "Fel"],
    ["w", "W"]
  ];

  function profileTable(profile) {
    var head = el("tr");
    var body = el("tr");
    CHARS.forEach(function (pair) {
      head.appendChild(el("th", { text: pair[1] }));
      var value = profile[pair[0]];
      body.appendChild(el("td", { text: value === null || value === undefined ? "\u2013" : value }));
    });
    return el("div", { class: "char-scroll" },
      el("table", { class: "char-table" },
        el("thead", null, head),
        el("tbody", null, body)));
  }

  function statblock(npc) {
    var block = el("div", { class: "statblock", id: "npc-" + npc.id });
    var portrait = (M.assets || []).filter(function (a) {
      return a.npc_id === npc.id && a.kind === "portrait";
    })[0];

    if (portrait) {
      block.appendChild(el("img", {
        class: "portrait-inline",
        src: assetUrl(portrait.path),
        alt: npc.name,
        loading: "lazy",
        onclick: function () { lightbox(portrait); }
      }));
    }

    block.appendChild(el("header", null,
      el("h3", { html: highlight(npc.name) }),
      npc.title ? el("div", { class: "npc-title", text: npc.title }) : null,
      npc.faction ? el("div", { class: "tiny muted", text: npc.faction }) : null));

    if (npc.description) block.appendChild(prose(npc.description));

    (npc.profiles || []).forEach(function (profile) {
      if ((npc.profiles || []).length > 1 && profile.label && profile.label !== "main") {
        block.appendChild(el("div", { class: "h-run", text: profile.label }));
      }
      block.appendChild(profileTable(profile));
      [["skills", "Skills"], ["talents", "Talents"], ["traits", "Traits"],
       ["trappings", "Trappings"], ["spells", "Spells"]].forEach(function (pair) {
        var entries = parseList(profile[pair[0]] || profile[pair[0] + "_json"]);
        if (!entries.length) return;
        block.appendChild(el("p", {
          class: "trait-line",
          html: "<b>" + pair[1] + ":</b> " + esc(traitText(entries))
        }));
      });
    });

    if (npc.page) block.appendChild(el("div", { class: "tiny muted", text: "p. " + npc.page }));
    return block;
  }

  // -------------------------------------------------------------- tables ---

  function bookTable(table) {
    var columns = table.columns || [];
    var rows = table.rows || [];
    var node = el("table", { class: "book-table" });
    if (table.title) node.appendChild(el("caption", { text: table.title }));
    if (columns.length) {
      node.appendChild(el("thead", null,
        el("tr", null, columns.map(function (c) { return el("th", { text: c }); }))));
    }
    node.appendChild(el("tbody", null, rows.map(function (row) {
      return el("tr", null, (row || []).map(function (cell) {
        return el("td", { text: cell === null || cell === undefined ? "" : cell });
      }));
    })));
    return node;
  }

  // ---------------------------------------------------------------- maps ---

  function lightbox(asset) {
    var box = el("div", { class: "lightbox", onclick: function () { box.remove(); } },
      el("img", { src: assetUrl(asset.path), alt: asset.caption || "" }));
    document.body.appendChild(box);
  }

  function mapPlate(asset) {
    var keys = asset.keys || [];
    var plate = el("div", { class: "map-plate", onclick: function () { lightbox(asset); } },
      el("img", { src: assetUrl(asset.path), alt: asset.caption || "Map", loading: "lazy" }));

    if (!keys.length) {
      return el("figure", { class: "plate" }, plate,
        asset.caption ? el("figcaption", { text: asset.caption }) : null);
    }

    var list = el("ul", { class: "key-list" });
    keys.forEach(function (key) {
      var item = el("li", null,
        el("span", { class: "num", text: key.key_label }),
        el("span", { class: "label", html: highlight(key.label || "") }),
        key.detail ? el("span", { class: "detail", html: highlight(key.detail) }) : null);
      item.onmouseenter = function () { item.classList.add("active"); };
      item.onmouseleave = function () { item.classList.remove("active"); };
      list.appendChild(item);
    });

    return el("div", { class: "map-layout" },
      el("figure", { class: "plate" }, plate,
        el("figcaption", { text: (asset.caption || "Map") + " \u2014 click to enlarge" })),
      el("div", null,
        el("div", { class: "h-run", text: "Key" }),
        list));
  }

  // ------------------------------------------------------- section render ---

  function headingFor(section) {
    var level = section.level || 2;
    var cls = level <= 2 ? "h-section" : level === 3 ? "h-sub" : "h-run";
    return el("h" + Math.min(level + 1, 6), {
      class: cls,
      id: "sec-" + section.id,
      html: highlight(section.title || "")
    });
  }

  function renderSection(section, out) {
    var extras = bySection[section.id] || { assets: [], tables: [], npcs: [] };

    if (section.level > 1) out.appendChild(headingFor(section));

    var maps = extras.assets.filter(function (a) { return a.kind === "map"; });
    var art = extras.assets.filter(function (a) { return a.kind === "art"; });

    var body = prose(section.body_md);
    if (body) out.appendChild(body);

    maps.forEach(function (asset) { out.appendChild(mapPlate(asset)); });

    art.forEach(function (asset) {
      out.appendChild(el("figure", { class: "plate" },
        el("img", {
          src: assetUrl(asset.path),
          alt: asset.caption || "",
          loading: "lazy",
          onclick: function () { lightbox(asset); }
        }),
        asset.caption ? el("figcaption", { text: asset.caption }) : null));
    });

    extras.tables.forEach(function (table) { out.appendChild(bookTable(table)); });
    extras.npcs.forEach(function (npc) { out.appendChild(statblock(npc)); });

    (section.children || []).forEach(function (child) { renderSection(child, out); });
  }

  // ----------------------------------------------------------- the views ---

  function chapterOpener(root, ordinal) {
    return el("div", { class: "chapter-opener" },
      el("div", { class: "numeral", text: romanise(ordinal) }),
      el("h1", { text: root.title || "" }),
      el("div", { class: "medallion", text: "\u2620" }),
      el("div", { class: "tiny muted", style: "margin-top:.9rem" },
        "pages " + root.page_start + "\u2013" + root.page_end));
  }

  function readView(sheet) {
    var root = sectionById[currentRootId];
    if (!root) return;
    var ordinal = roots.indexOf(root) + 1;

    sheet.appendChild(el("div", { class: "tab-strip" },
      el("span", { class: "chapter-tab", text: romanise(ordinal) })));
    sheet.appendChild(el("div", { class: "running-head", text: M.title }));
    sheet.appendChild(chapterOpener(root, ordinal));

    var body = el("div");
    var extras = bySection[root.id] || { assets: [], tables: [], npcs: [] };
    var intro = prose(root.body_md);
    if (intro) body.appendChild(intro);
    extras.assets.filter(function (a) { return a.kind === "map"; })
      .forEach(function (a) { body.appendChild(mapPlate(a)); });
    extras.tables.forEach(function (t) { body.appendChild(bookTable(t)); });
    extras.npcs.forEach(function (n) { body.appendChild(statblock(n)); });

    (root.children || []).forEach(function (child) { renderSection(child, body); });
    sheet.appendChild(body);
    sheet.appendChild(el("div", { class: "folio", text: root.page_end }));
  }

  function galleryView(sheet, kind, title) {
    sheet.appendChild(el("div", { class: "running-head", text: title }));
    sheet.appendChild(el("h2", { class: "h-section", text: title }));

    if (kind === "map") {
      (M.maps || []).forEach(function (asset) {
        var owner = sectionById[asset.section_id];
        var section = el("section", { style: "--accent:" + accentOf(owner || {}) });
        section.appendChild(el("h3", {
          class: "h-sub",
          text: asset.caption || ("Map, p. " + asset.page)
        }));
        section.appendChild(mapPlate(asset));
        sheet.appendChild(section);
      });
      return;
    }

    if (kind === "table") {
      (M.tables || []).forEach(function (table) {
        var owner = sectionById[table.section_id];
        sheet.appendChild(el("section", { style: "--accent:" + accentOf(owner || {}) },
          bookTable(table)));
      });
      return;
    }

    // NPCs, grouped by the chapter they belong to, in the book's own order.
    var grouped = {};
    (M.npcs || []).forEach(function (npc) {
      var root = rootOf[npc.section_id];
      var key = root ? root.id : "elsewhere";
      if (!grouped[key]) {
        grouped[key] = { title: root ? root.title : "Elsewhere", root: root, npcs: [] };
      }
      grouped[key].npcs.push(npc);
    });

    roots.concat([{ id: "elsewhere" }]).forEach(function (root) {
      var group = grouped[root.id];
      if (!group) return;
      var section = el("section", { style: "--accent:" + accentOf(group.root || {}) });
      section.appendChild(el("h3", { class: "h-sub", text: group.title }));
      section.appendChild(el("div", { class: "npc-grid" },
        group.npcs.map(function (npc) { return statblock(npc); })));
      sheet.appendChild(section);
    });
  }

  function searchView(sheet) {
    sheet.appendChild(el("div", { class: "running-head", text: "Search" }));
    if (!query) {
      sheet.appendChild(el("p", { class: "muted", text: "Type to search the module." }));
      return;
    }

    var needle = query.toLowerCase();
    var hits = [];

    Object.keys(sectionById).forEach(function (id) {
      var section = sectionById[id];
      var haystack = ((section.title || "") + " " + (section.body_md || "")).toLowerCase();
      if (haystack.indexOf(needle) === -1) return;
      var at = (section.body_md || "").toLowerCase().indexOf(needle);
      hits.push({
        title: section.title,
        where: (rootOf[section.id] || {}).title || "",
        page: section.page_start,
        excerpt: at === -1 ? (section.body_md || "").slice(0, 180)
                           : (section.body_md || "").slice(Math.max(0, at - 90), at + 130),
        go: function () { goTo(section); }
      });
    });

    (M.npcs || []).forEach(function (npc) {
      var haystack = ((npc.name || "") + " " + (npc.title || "") + " " + (npc.description || "")).toLowerCase();
      if (haystack.indexOf(needle) === -1) return;
      hits.push({
        title: npc.name,
        where: "NPC \u00b7 " + ((rootOf[npc.section_id] || {}).title || ""),
        page: npc.page,
        excerpt: (npc.description || "").slice(0, 200),
        go: function () { goTo(sectionById[npc.section_id], "npc-" + npc.id); }
      });
    });

    sheet.appendChild(el("h2", { class: "h-section", text: hits.length + " result" + (hits.length === 1 ? "" : "s") }));

    hits.slice(0, 120).forEach(function (hit) {
      sheet.appendChild(el("button", { class: "hit", onclick: hit.go },
        el("div", { class: "where", text: hit.where + (hit.page ? " \u00b7 p. " + hit.page : "") }),
        el("div", { class: "title", html: highlight(hit.title || "") }),
        el("div", { class: "tiny muted", html: "\u2026" + highlight(hit.excerpt) + "\u2026" })));
    });
  }

  function goTo(section, anchor) {
    if (!section) return;
    var root = rootOf[section.id];
    view = "read";
    query = "";
    currentRootId = root ? root.id : section.id;
    render();
    requestAnimationFrame(function () {
      var target = document.getElementById(anchor || ("sec-" + section.id));
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  // --------------------------------------------------------------- chrome ---

  function rail() {
    var nav = el("nav", { class: "rail" });

    roots.forEach(function (root, i) {
      var isCurrent = root.id === currentRootId && view === "read";
      nav.appendChild(el("button", {
        class: "chapter-head" + (isCurrent ? " current" : ""),
        style: "--chapter-accent:" + accentOf(root),
        onclick: function () { view = "read"; currentRootId = root.id; render(); }
      },
        el("span", { text: romanise(i + 1) + ". " + (root.title || "") }),
        el("span", { class: "pages", text: root.page_start + "\u2013" + root.page_end })));

      if (!isCurrent) return;

      var tree = el("div", { class: "tree", style: "--chapter-accent:" + accentOf(root) });
      (function walk(list, depth) {
        list.forEach(function (section) {
          if (depth > 3) return;
          tree.appendChild(el("button", {
            class: "lv" + depth,
            text: section.title || "",
            onclick: function () {
              var target = document.getElementById("sec-" + section.id);
              if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
          }));
          walk(section.children || [], depth + 1);
        });
      })(root.children || [], 2);
      nav.appendChild(tree);
    });

    return nav;
  }

  function masthead() {
    var tabs = [["read", "Read"], ["npcs", "NPCs"], ["maps", "Maps"],
                ["tables", "Tables"], ["search", "Search"]];

    var field = el("input", {
      type: "search",
      placeholder: "Search the module\u2026",
      value: query,
      oninput: function (e) {
        query = e.target.value.trim();
        view = "search";
        // Re-rendering the masthead here would steal focus mid-keystroke, so
        // only the tab state and the page below are refreshed.
        Array.prototype.forEach.call(
          field.parentNode.querySelectorAll(".tabs button"),
          function (button, i) {
            button.setAttribute("aria-selected", tabs[i][0] === "search" ? "true" : "false");
          }
        );
        renderPage();
        writeHash();
      }
    });

    return el("header", { class: "masthead" },
      el("div", { class: "brand" },
        el("small", { text: M.system || "WFRP 4E" }),
        M.title || "Adventure Module"),
      el("div", { class: "tabs" }, tabs.map(function (pair) {
        return el("button", {
          "aria-selected": view === pair[0] ? "true" : "false",
          onclick: function () { view = pair[0]; render(); }
        }, pair[1]);
      })),
      field);
  }

  var pageScroll = null;

  function renderPage() {
    if (!pageScroll) return;
    var root = sectionById[currentRootId];
    pageScroll.innerHTML = "";
    var sheet = el("div", { class: "sheet paper" });
    sheet.style.setProperty("--accent", accentOf(root || {}));

    if (view === "read") readView(sheet);
    else if (view === "npcs") galleryView(sheet, "npc", "Dramatis Personae");
    else if (view === "maps") galleryView(sheet, "map", "Maps & Plans");
    else if (view === "tables") galleryView(sheet, "table", "Tables");
    else searchView(sheet);

    pageScroll.appendChild(sheet);
    pageScroll.scrollTop = 0;
  }

  // -------------------------------------------------------------- routing ---

  /* The view lives in the URL so a GM can bookmark a chapter, or keep the maps
   * open in a second window while reading the text in the first. */
  var settingHash = false;

  function writeHash() {
    var hash = view === "read" ? "#read/" + currentRootId
             : view === "search" ? "#search/" + encodeURIComponent(query)
             : "#" + view;
    if (location.hash === hash) return;
    settingHash = true;
    location.hash = hash;
    setTimeout(function () { settingHash = false; }, 0);
  }

  function readHash() {
    var parts = location.hash.replace(/^#/, "").split("/");
    var name = parts[0];
    if (name === "read") {
      var id = parseInt(parts[1], 10);
      view = "read";
      if (sectionById[id]) currentRootId = id;
    } else if (name === "search") {
      view = "search";
      query = decodeURIComponent(parts.slice(1).join("/") || "");
    } else if (name === "npcs" || name === "maps" || name === "tables") {
      view = name;
    }
  }

  function render() {
    var root = sectionById[currentRootId];
    app.className = "viewer";
    app.style.setProperty("--accent", accentOf(root || {}));
    app.innerHTML = "";
    app.appendChild(masthead());
    app.appendChild(rail());
    pageScroll = el("div", { class: "page-scroll" });
    app.appendChild(pageScroll);
    renderPage();
    writeHash();
  }

  // ----------------------------------------------------------------- boot ---

  function applyTheme(theme) {
    if (!theme) return;
    var root = document.documentElement;
    if (theme.background_recto) {
      root.style.setProperty("--paper-texture", "url('" + assetUrl(theme.background_recto) + "')");
    }
    if (theme.background_verso) {
      root.style.setProperty("--paper-texture-verso", "url('" + assetUrl(theme.background_verso) + "')");
    }
    if (theme.rule) {
      root.style.setProperty("--ink-rule", "url('" + assetUrl(theme.rule) + "')");
    }
  }

  fetch("/api/modules/" + encodeURIComponent(slug))
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(function (payload) {
      M = payload && payload.module ? payload.module : payload;
      if (!M || !M.sections) throw new Error("This module has no extracted content.");
      document.title = (M.title || "Adventure Module") + " \u2014 Omega7";
      applyTheme(M.theme);
      index();
      readHash();
      render();
      window.addEventListener("hashchange", function () {
        if (settingHash) return;
        readHash();
        render();
      });
    })
    .catch(function (error) {
      app.className = "loading";
      app.textContent = "Could not open the module: " + error.message;
    });
})();
