// Regenerates the language databases from the OpenRussian dataset
// (Badestrand/russian-dictionary, CC BY-SA 4.0). We pull the four CSV tables
// straight from GitHub raw so the build is reproducible from a clean checkout
// with no vendored source data:
//
//   node scripts/build-language-db.mjs
//
// Outputs (data/):
//   stress-db.json        headword       -> stress-marked form(s)
//   aspect-pairs-db.json  [{ impf, perf, gloss }]
//   stress-forms-db.json  lemma          -> { inflected form -> accented form }
//   forms/<letter>.json   stress-forms-db sharded by the lemma's first letter,
//                         so a consumer can fetch just one shard at runtime
//                         instead of the whole ~27 MB paradigm map.
//
// OpenRussian marks stress with an apostrophe after the stressed vowel
// ("сказа'ть"); we convert it to the combining acute U+0301 used across the
// consuming app, so a value plugs straight into stripStress()/toSpeechKitStress().

import { writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const COMBINING_ACUTE = "́";
const RAW = "https://raw.githubusercontent.com/Badestrand/russian-dictionary/master";
const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "data");

// ё and й both DECOMPOSE under NFD (ё -> е + U+0308, й -> и + U+0306), and the
// diacritic-stripping below would then silently turn them into е / и. So we
// swap them out for private placeholders before NFD and swap them back after.
// Latin "ë" is the source's frequent mis-encoding of ё, folded in here too.
const protectYo = (s) => s.replace(/[ёЁËë]/g, "").replace(/[йЙ]/g, "");
const restoreYo = (s) => s.replaceAll("", "ё").replaceAll("", "й");

// Normalize an accented form to the app's convention: a single combining acute
// right after the stressed vowel. The source marks stress with an apostrophe,
// but a minority of rows use a grave or a pre-composed accented vowel, so fold
// those to the acute too.
const toAcute = (s) =>
  restoreYo(
    protectYo(s || "")
      .normalize("NFD")
      .replace(/['`̀́]/g, COMBINING_ACUTE) // apostrophe/grave -> acute
      .replace(/[̂-ͯ]/g, "") // drop any other stray combining marks
  ).trim();

// OpenRussian uses "-" / "_" as placeholder headwords for a handful of rows
// (defective verbs whose only real member is the partner). Guard against them.
const isWord = (s) => /^[а-яё]{2,}(-[а-яё]+)*$/i.test(s || "");

// A bare, lookup-ready form: no stress marks of any kind, "ё"/"й" preserved,
// lowercased. Callers gate the result through isWord(), which rejects anything
// with leftover Latin letters or placeholder junk.
const bareLemma = (s) =>
  restoreYo(
    protectYo(s || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/['`]/g, "")
  )
    .toLowerCase()
    .trim();

// Both the headword and partner cells are sometimes a list of alternatives
// joined by "," or ";", some entries being the "-" placeholder. Take the first
// real word.
const firstForm = (cell) =>
  (cell || "").split(/[,;]/).map(bareLemma).find(isWord) || "";

// Tab-separated, first row is the header. Values never contain tabs here.
function parseTsv(text) {
  const [head, ...rows] = text.trim().split("\n");
  const cols = head.split("\t");
  return rows.map((line) => {
    const cells = line.split("\t");
    const rec = {};
    cols.forEach((c, i) => (rec[c] = cells[i] ?? ""));
    return rec;
  });
}

async function fetchTable(name) {
  const res = await fetch(`${RAW}/${name}.csv`);
  if (!res.ok) throw new Error(`fetch ${name}: ${res.status}`);
  return parseTsv(await res.text());
}

// Keep only a stress-bearing form: an explicit acute, or a "ё" (always stressed
// so it needs no mark). Unmarked monosyllables carry no useful stress info.
const marksStress = (val) => !!val && (val.includes(COMBINING_ACUTE) || val.includes("ё"));

async function main() {
  const [nouns, verbs, adjectives, others] = await Promise.all(
    ["nouns", "verbs", "adjectives", "others"].map(fetchTable)
  );

  // ---- stress-db: headword (lowercase) -> accented form(s) ----------------
  // Heterographs with different stress (за́мок / замо́к) map to an array; a
  // single answer stays a plain string to keep the file small.
  const stress = new Map();
  const addStress = (bare, accented) => {
    const key = bareLemma(bare);
    if (!isWord(key)) return;
    const val = toAcute(accented);
    if (!marksStress(val)) return;
    const cur = stress.get(key);
    if (cur === undefined) stress.set(key, val);
    else if (Array.isArray(cur)) { if (!cur.includes(val)) cur.push(val); }
    else if (cur !== val) stress.set(key, [cur, val]);
  };
  for (const t of [nouns, verbs, adjectives, others])
    for (const r of t) addStress(r.bare, r.accented);

  const stressObj = {};
  for (const [k, v] of [...stress.entries()].sort((a, b) => a[0].localeCompare(b[0], "ru")))
    stressObj[k] = v;

  // ---- aspect-pairs-db: {impf, perf, gloss} -------------------------------
  const byBare = new Map(verbs.map((v) => [firstForm(v.bare), v]));
  const pairs = new Map();
  for (const v of verbs) {
    const self = firstForm(v.bare);
    const partner = firstForm(v.partner);
    if (!partner) continue;
    let impf, perf;
    if (v.aspect === "imperfective") { impf = self; perf = partner; }
    else if (v.aspect === "perfective") { impf = partner; perf = self; }
    else continue; // biaspectual / unknown -> no clean pair
    if (!isWord(impf) || !isWord(perf)) continue;
    const key = `${impf}|${perf}`;
    if (pairs.has(key)) continue;
    const impfRow = byBare.get(impf);
    const gloss = ((impfRow?.translations_en) || v.translations_en || "").split(",")[0].trim();
    pairs.set(key, { impf, perf, gloss });
  }
  const pairsArr = [...pairs.values()].sort((a, b) => a.impf.localeCompare(b.impf, "ru"));

  // ---- translations-db: lemma -> curated dictionary entry ----------------
  // OpenRussian carries hand-written translations (translations_en /
  // translations_de) alongside every headword. That is lexicographer data, the
  // same kind ABBYY Lingvo is built on, and it is what makes a word lookup
  // read like a dictionary entry instead of a machine-translation guess.
  // Shape: bare lemma -> { pos, accented, en: [...], de: [...] }
  const splitGlosses = (cell) =>
    String(cell || "")
      .split(/[,;]/)
      .map((x) => x.trim())
      .filter(Boolean)
      .slice(0, 6);

  const translations = {};
  const addTranslation = (row, pos) => {
    const key = bareLemma(firstForm(row.bare));
    if (!isWord(key)) return;
    const en = splitGlosses(row.translations_en);
    const de = splitGlosses(row.translations_de);
    if (!en.length && !de.length) return;
    const prev = translations[key];
    if (prev) {
      // одна и та же форма у разных частей речи: копим, не затираем
      for (const g of en) if (!prev.en.includes(g)) prev.en.push(g);
      for (const g of de) if (!prev.de.includes(g)) prev.de.push(g);
      return;
    }
    const entry = { pos, en, de };
    if (pos === "noun" && row.gender) entry.gender = row.gender;
    if (pos === "verb" && row.aspect) entry.aspect = row.aspect;
    translations[key] = entry;
  };
  for (const r of nouns) addTranslation(r, "noun");
  for (const r of verbs) addTranslation(r, "verb");
  for (const r of adjectives) addTranslation(r, "adjective");
  for (const r of others) addTranslation(r, "other");

  // Формат статьи: { t: [значения], pos, g: род, a: вид }. Короткие ключи —
  // файл читает сервер, а не человек, и каждый байт здесь умножается на 55k.
  const byLang = { en: {}, de: {} };
  for (const k of Object.keys(translations).sort((a, b) => a.localeCompare(b, "ru"))) {
    const e = translations[k];
    for (const lang of ["en", "de"]) {
      const list = e[lang];
      if (!list.length) continue;
      const rec = { t: list, pos: e.pos };
      if (e.gender) rec.g = e.gender;
      if (e.aspect) rec.a = e.aspect;
      byLang[lang][k] = rec;
    }
  }

  // ---- stress-forms-db: lemma -> { inflected bare form -> accented } -------
  // The flat stress-db is keyed by headword only, so it cannot stress an
  // inflected word (челове́ку, сказа́л, но́вого) — and a flat inflected map would
  // mis-stress cross-lemma heterographs (стекла́ vs стёкла). This paradigm map
  // is keyed BY LEMMA, so a page that already knows the lemma (declension /
  // conjugation) gets the correct stress for every one of its own forms. Every
  // non-metadata column is an inflected form; cells may list comma-separated
  // variants (e.g. an animate/inanimate accusative).
  const NOUN_META = new Set(["bare","accented","translations_en","translations_de","gender","partner","animate","indeclinable","sg_only","pl_only"]);
  const VERB_META = new Set(["bare","accented","translations_en","translations_de","aspect","partner"]);
  const ADJ_META = new Set(["bare","accented","translations_en","translations_de"]);

  const forms = {}; // lemma -> { formBare: accented }
  const addForms = (table, meta) => {
    for (const r of table) {
      const lemma = firstForm(r.bare);
      if (!isWord(lemma)) continue;
      const map = forms[lemma] || (forms[lemma] = {});
      const cells = [r.accented, ...Object.entries(r).filter(([c]) => !meta.has(c)).map(([, v]) => v)];
      for (const cell of cells) {
        for (const variant of (cell || "").split(",")) {
          const b = bareLemma(variant);
          const acc = toAcute(variant);
          if (!isWord(b) || !marksStress(acc)) continue;
          if (map[b] === undefined) map[b] = acc; // first attested wins
        }
      }
      if (Object.keys(map).length === 0) delete forms[lemma];
    }
  };
  addForms(nouns, NOUN_META);
  addForms(verbs, VERB_META);
  addForms(adjectives, ADJ_META);

  const formsObj = {};
  for (const k of Object.keys(forms).sort((a, b) => a.localeCompare(b, "ru"))) formsObj[k] = forms[k];

  // Shard the paradigm map by the lemma's first letter so consumers can fetch
  // one ~1 MB slice at runtime instead of the whole file.
  const shardKey = (lemma) => {
    const c = lemma[0];
    return /[а-яё]/.test(c) ? c : "_";
  };
  const shards = {};
  for (const [lemma, map] of Object.entries(formsObj)) {
    const k = shardKey(lemma);
    (shards[k] || (shards[k] = {}))[lemma] = map;
  }

  await mkdir(join(OUT_DIR, "forms"), { recursive: true });
  await writeFile(join(OUT_DIR, "stress-db.json"), JSON.stringify(stressObj), "utf8");
  await writeFile(join(OUT_DIR, "aspect-pairs-db.json"), JSON.stringify(pairsArr), "utf8");
  console.log(`translations/en.json:    ${Object.keys(byLang.en).length} headwords`);
  console.log(`translations/de.json:    ${Object.keys(byLang.de).length} headwords`);
  await mkdir(join(OUT_DIR, "translations"), { recursive: true });
  for (const [lang, obj] of Object.entries(byLang))
    await writeFile(join(OUT_DIR, "translations", `${lang}.json`), JSON.stringify(obj), "utf8");
  await writeFile(join(OUT_DIR, "stress-forms-db.json"), JSON.stringify(formsObj), "utf8");
  for (const [k, map] of Object.entries(shards))
    await writeFile(join(OUT_DIR, "forms", `${k}.json`), JSON.stringify(map), "utf8");

  const formCount = Object.values(formsObj).reduce((n, m) => n + Object.keys(m).length, 0);
  console.log(`stress-db.json:        ${Object.keys(stressObj).length} headwords`);
  console.log(`aspect-pairs-db.json:  ${pairsArr.length} pairs`);
  console.log(`stress-forms-db.json:  ${Object.keys(formsObj).length} lemmas, ${formCount} forms`);
  console.log(`forms/ shards:         ${Object.keys(shards).length}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
