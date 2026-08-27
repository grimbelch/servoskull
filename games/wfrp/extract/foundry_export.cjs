#!/usr/bin/env node
/**
 * Export a Foundry VTT adventure module's compendium packs to a single JSON file.
 *
 * Foundry stores compendium packs as LevelDB directories, which Python cannot
 * read without pulling in a native dependency. Node can, and Node is already a
 * requirement for the MCP bridge, so the export runs here and the ingester
 * (games/wfrp/extract/foundry_module.py) consumes plain JSON.
 *
 * Run this on the machine hosting Foundry, where classic-level already ships
 * inside the application:
 *
 *   node foundry_export.cjs \
 *     --module /path/to/Data/modules/wfrp4e-rnhd \
 *     --out    /tmp/wfrp4e-rnhd.json
 *
 * Documents inside a pack are stored flat, with embedded documents held under
 * their own keys rather than nested in the parent:
 *
 *   !journal!<id>                  a JournalEntry
 *   !journal.pages!<id>.<pageId>   one of its pages
 *   !actors!<id>                   an Actor
 *   !actors.items!<id>.<itemId>    an item owned by that Actor
 *
 * The parent only carries an array of child ids, so this script rejoins them.
 * Packs are opened read-only against a copy when --copy is given, because
 * LevelDB takes an exclusive lock and a running Foundry already holds it.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const PACKS = ['journals', 'actors', 'items', 'tables', 'scenes'];

// Where classic-level lives inside a Foundry install, relative to the app root.
const CLASSIC_LEVEL_CANDIDATES = [
  '/foundry/fvtt/resources/app/node_modules/classic-level',
  '/opt/foundryvtt/resources/app/node_modules/classic-level',
  'classic-level',
];

function parseArgs(argv) {
  const args = { module: '', out: '', classicLevel: '', copy: true };
  for (let i = 2; i < argv.length; i++) {
    const key = argv[i];
    const next = () => argv[++i];
    if (key === '--module') args.module = next();
    else if (key === '--out') args.out = next();
    else if (key === '--classic-level') args.classicLevel = next();
    else if (key === '--no-copy') args.copy = false;
    else if (key === '--help' || key === '-h') args.help = true;
    else throw new Error(`unknown argument: ${key}`);
  }
  return args;
}

function loadClassicLevel(explicit) {
  const candidates = explicit ? [explicit, ...CLASSIC_LEVEL_CANDIDATES] : CLASSIC_LEVEL_CANDIDATES;
  const failures = [];
  for (const candidate of candidates) {
    try {
      return require(candidate).ClassicLevel;
    } catch (err) {
      failures.push(`  ${candidate}: ${err.message}`);
    }
  }
  throw new Error(
    'could not load classic-level. Pass --classic-level <path> pointing at the ' +
    'copy inside your Foundry install.\nTried:\n' + failures.join('\n')
  );
}

/** Split a pack key into its namespace and id: `!actors.items!a.b` -> [`actors.items`, `a.b`]. */
function splitKey(key) {
  const parts = key.split('!');
  return [parts[1] || '', parts.slice(2).join('!')];
}

/**
 * Read every document in one pack, grouped by namespace.
 *
 * The namespace inside a pack does not always match its directory name — the
 * `journals` pack stores `!journal!<id>` — so primary documents are identified
 * structurally: a namespace containing a dot is an embedded collection, and
 * anything else is a top-level document. Folders are metadata and are skipped.
 *
 * Returns { primary: [doc], embedded: { 'actors.items': { '<parentId>': [doc] } } }.
 */
async function readPack(ClassicLevel, dir) {
  const db = new ClassicLevel(dir, { valueEncoding: 'json' });
  await db.open();
  const primary = [];
  const embedded = {};
  try {
    for await (const [key, value] of db.iterator()) {
      const [namespace, id] = splitKey(key);
      if (!namespace || namespace === 'folders') continue;
      if (!namespace.includes('.')) {
        primary.push(value);
        continue;
      }
      // Embedded ids are `<parentId>.<childId>`; group by parent.
      const parentId = id.split('.')[0];
      const bucket = (embedded[namespace] = embedded[namespace] || {});
      (bucket[parentId] = bucket[parentId] || []).push(value);
    }
  } finally {
    await db.close();
  }
  return { primary, embedded };
}

/** Keep the fields the ingester needs; a full actor carries ~40 KB of UI cruft. */
function trimItem(item) {
  return {
    _id: item._id,
    name: item.name,
    type: item.type,
    img: item.img || '',
    system: item.system || {},
  };
}

function buildJournals(pack) {
  const pages = pack.embedded['journal.pages'] || {};
  return pack.primary.map((entry) => {
    const owned = pages[entry._id] || [];
    const byId = new Map(owned.map((p) => [p._id, p]));
    // `entry.pages` holds ids in display order; fall back to whatever we found.
    const ordered = (entry.pages || []).map((id) => byId.get(id)).filter(Boolean);
    const resolved = ordered.length ? ordered : owned;
    return {
      _id: entry._id,
      name: entry.name,
      sort: entry.sort || 0,
      pages: resolved.map((page) => ({
        _id: page._id,
        name: page.name,
        type: page.type,
        sort: page.sort || 0,
        html: (page.text && page.text.content) || '',
        src: (page.src) || (page.image && page.image.src) || '',
      })),
    };
  });
}

function buildActors(pack) {
  const items = pack.embedded['actors.items'] || {};
  return pack.primary.map((actor) => ({
    _id: actor._id,
    name: actor.name,
    type: actor.type,
    img: actor.img || '',
    prototypeToken: { texture: { src: (actor.prototypeToken && actor.prototypeToken.texture && actor.prototypeToken.texture.src) || '' } },
    system: actor.system || {},
    items: (items[actor._id] || []).map(trimItem),
  }));
}

function buildTables(pack) {
  const results = pack.embedded['tables.results'] || {};
  return pack.primary.map((table) => ({
    _id: table._id,
    name: table.name,
    description: table.description || '',
    formula: table.formula || '',
    // The wfrp4e system stamps tables with a lookup key and species column
    // ("career"/"human"); the rules engine selects tables by these.
    flags: (table.flags && table.flags.wfrp4e) || {},
    results: (results[table._id] || []).map((r) => ({
      range: r.range || [],
      // Rulebook tables carry their result as an @UUID link in `description`,
      // adventure tables as plain `text`; keep whichever is present.
      text: r.text || r.name || '',
      description: r.description || '',
      documentUuid: r.documentUuid || '',
      type: r.type,
    })),
  }));
}

/** The module's English strings; rules text like condition effects lives here. */
function readLang(moduleDir) {
  const candidates = [path.join(moduleDir, 'lang', 'en.json')];
  for (const file of candidates) {
    if (fs.existsSync(file)) {
      try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* fall through */ }
    }
  }
  return {};
}

function buildScenes(pack) {
  return pack.primary.map((scene) => ({
    _id: scene._id,
    name: scene.name,
    width: scene.width || 0,
    height: scene.height || 0,
    background: (scene.background && scene.background.src) || scene.img || '',
    thumb: scene.thumb || '',
    tiles: (scene.tiles || [])
      .map((t) => (t.texture && t.texture.src) || t.img || '')
      .filter(Boolean),
    notes: (scene.notes || []).map((n) => ({
      text: n.text || '',
      entryId: n.entryId || '',
      pageId: n.pageId || '',
    })),
  }));
}

/** Every file under assets/, relative to the module directory. */
function listAssets(moduleDir) {
  const root = path.join(moduleDir, 'assets');
  if (!fs.existsSync(root)) return [];
  const out = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else out.push(path.relative(moduleDir, full));
    }
  };
  walk(root);
  return out.sort();
}

/**
 * LevelDB needs write access for its lock file even to read, and a running
 * Foundry holds that lock. Copy the packs somewhere temporary instead.
 */
function copyPacks(moduleDir) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'foundry-export-'));
  const source = path.join(moduleDir, 'packs');
  fs.cpSync(source, path.join(temp, 'packs'), { recursive: true });
  for (const pack of fs.readdirSync(path.join(temp, 'packs'))) {
    const lock = path.join(temp, 'packs', pack, 'LOCK');
    if (fs.existsSync(lock)) fs.rmSync(lock);
  }
  return temp;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help || !args.module || !args.out) {
    console.log(
      'Usage: node foundry_export.cjs --module <module dir> --out <file.json>\n' +
      '                              [--classic-level <path>] [--no-copy]'
    );
    return args.help ? 0 : 1;
  }

  const moduleDir = path.resolve(args.module);
  const manifestPath = path.join(moduleDir, 'module.json');
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`no module.json in ${moduleDir}`);
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const ClassicLevel = loadClassicLevel(args.classicLevel);

  const workDir = args.copy ? copyPacks(moduleDir) : moduleDir;
  const packsRoot = path.join(workDir, 'packs');
  const result = {
    module: {
      id: manifest.id,
      title: manifest.title,
      version: manifest.version,
      description: manifest.description || '',
    },
    journals: [],
    actors: [],
    items: [],
    tables: [],
    scenes: [],
    assets: listAssets(moduleDir),
    lang: readLang(moduleDir),
  };

  try {
    for (const packName of PACKS) {
      const dir = path.join(packsRoot, packName);
      if (!fs.existsSync(dir)) continue;
      const pack = await readPack(ClassicLevel, dir);
      if (packName === 'journals') result.journals = buildJournals(pack);
      else if (packName === 'actors') result.actors = buildActors(pack);
      else if (packName === 'items') result.items = pack.primary.map(trimItem);
      else if (packName === 'tables') result.tables = buildTables(pack);
      else if (packName === 'scenes') result.scenes = buildScenes(pack);
    }
  } finally {
    if (args.copy) fs.rmSync(workDir, { recursive: true, force: true });
  }

  fs.writeFileSync(args.out, JSON.stringify(result, null, 1));
  const pages = result.journals.reduce((n, j) => n + j.pages.length, 0);
  console.log(
    `Exported ${manifest.id} ${manifest.version} -> ${args.out}\n` +
    `  journals ${result.journals.length} (${pages} pages)\n` +
    `  actors   ${result.actors.length}\n` +
    `  tables   ${result.tables.length}\n` +
    `  scenes   ${result.scenes.length}\n` +
    `  assets   ${result.assets.length}`
  );
  return 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(`error: ${err.message}`);
    process.exit(1);
  }
);
