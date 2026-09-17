// Regenerates the two offline language databases the site relies on:
//
//   lib/content/data/stress-db.json        bare form -> stress-marked form
//   lib/content/data/aspect-pairs-db.json  imperfective/perfective pairs
//
// Source: the OpenRussian dataset (Badestrand/russian-dictionary, CC-BY-SA
// 4.0). We pull the four CSV tables straight from GitHub raw so the build is
// reproducible from a clean checkout with no vendored data:
//
//   node scripts/build-language-db.mjs
//
// OpenRussian marks stress with an apostrophe placed AFTER the stressed vowel
// ("сказа'ть"). The rest of the codebase (lib/content/stress.ts) marks stress
// with the combining acute U+0301 sitting right after the vowel, so we convert
// on the way in — that way lookupStress() output plugs straight into
// stripStress()/toSpeechKitStress() without a second convention to reconcile.

import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const COMBINING_ACUTE = "́";
const RAW = "https://raw.githubusercontent.com/Badestrand/russian-dictionary/master";
const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "data");

// Normalize an accented headword to the project's convention: a single
// combining acute (U+0301) right after the stressed vowel. The source marks
// stress with an apostrophe, but a minority of rows use a grave or a
// pre-composed accented Latin vowel instead, so fold those to the acute too,
// and repair the Latin-"ë"-for-"ё" mis-encoding while we're here.
const toAcute = (s) =>
  (s || "")
    .replace(/[ёЁËë]/g, "")
    .normalize("NFD")
    .replace(/['`̀́]/g, COMBINING_ACUTE) // apostrophe/grave -> acute
    .replace(/[̂-ͯ]/g, "") // drop any other stray combining marks
    .replaceAll("", "ё")
    .trim();

// OpenRussian uses "-" / "_" as placeholder headwords for a handful of rows
// (defective verbs whose only real member is the partner). Guard against them
// so those placeholders never leak into either database as if they were words.
const isWord = (s) => /^[а-яё]{2,}(-[а-яё]+)*$/i.test(s || "");

// A bare, lookup-ready lemma: no stress marks of any kind (apostrophe, or any
// combining diacritic — the source mixes acute/grave/dot marks), Latin "ë"
// folded to "ё", lowercased. Aspect lookups key on this so a marked or noisy
// partner form still matches. Callers gate the result through isWord(), which
// rejects anything with leftover Latin letters.
const bareLemma = (s) =>
  (s || "")
    // Protect ё before NFD (which would split it into е + combining diaeresis
    // and then lose the dots to the strip below). Latin "ë" is the source's
    // frequent mis-encoding of ё, so fold it in here too.
    .replace(/[ёЁËë]/g, "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // strip acute/grave/dot stress marks
    .replace(/['`]/g, "")
    .replaceAll("", "ё")
    .toLowerCase()
    .trim();

// Both the headword and partner cells are sometimes a list of alternatives
// joined by "," or ";", and some entries are the "-" placeholder. Take the
// first real word.
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

async function main() {
  const [nouns, verbs, adjectives, others] = await Promise.all(
    ["nouns", "verbs", "adjectives", "others"].map(fetchTable)
  );

  // ---- stress-db: bare (lowercase) -> accented form(s) --------------------
  // Homographs with different stress (за́мок / замо́к) genuinely have two
  // answers, so the value is a string OR an array of strings. A single answer
  // stays a plain string to keep the file small and lookups trivial.
  const stress = new Map();
  const addStress = (bare, accented) => {
    const key = bareLemma(bare);
    if (!isWord(key)) return;
    const val = toAcute(accented);
    // Keep a form only if it actually pins the stress: either an explicit acute
    // mark, or a "ё" (always stressed, so it needs no mark). Unmarked
    // monosyllables carry no useful stress info and are skipped.
    if (!val || (!val.includes(COMBINING_ACUTE) && !val.includes("ё"))) return;
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
  // Each verb row carries its own aspect and the bare form of its partner.
  // We resolve a pair from whichever side we're on, dedupe by impf|perf, and
  // take the English gloss from the imperfective member when we have it.
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
    if (!isWord(impf) || !isWord(perf)) continue; // skip placeholder headwords
    const key = `${impf}|${perf}`;
    if (pairs.has(key)) continue;
    const impfRow = byBare.get(impf);
    const gloss = ((impfRow?.translations_en) || v.translations_en || "")
      .split(",")[0]
      .trim();
    pairs.set(key, { impf, perf, gloss });
  }
  const pairsArr = [...pairs.values()].sort((a, b) => a.impf.localeCompare(b.impf, "ru"));

  await writeFile(join(OUT_DIR, "stress-db.json"), JSON.stringify(stressObj), "utf8");
  await writeFile(join(OUT_DIR, "aspect-pairs-db.json"), JSON.stringify(pairsArr), "utf8");

  console.log(`stress-db.json:        ${Object.keys(stressObj).length} headwords`);
  console.log(`aspect-pairs-db.json:  ${pairsArr.length} pairs`);
}

main().catch((e) => { console.error(e); process.exit(1); });
