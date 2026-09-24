// Bilingual dictionary entries for the languages OpenRussian does not cover.
//
// OpenRussian ships hand-written glosses for English and German only
// (build-language-db.mjs turns those into data/translations/{en,de}.json). The
// other priority languages — French, Dutch, Italian, Spanish, Chinese — come
// from WikDict, which distils Wiktionary's own translation tables (via DBnary)
// into per-pair dictionaries with a confidence score. Same idea as OpenRussian:
// entries written by people, not machine output.
//
//   node scripts/build-translations.mjs            # fr nl it es zh
//   node scripts/build-translations.mjs fr zh      # only these
//   node scripts/build-translations.mjs --merge-en # also top up en/de
//
// Writes data/translations/<lang>.json, the same shape the OpenRussian step
// writes: bare lowercase headword -> { t: [glosses], pos?, g?, a? }.
//
// Sources: WikDict (CC BY-SA 3.0, from Wiktionary/DBnary), see NOTICE.

import { writeFile, readFile, mkdir, rm } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";
import { DatabaseSync } from "node:sqlite";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(ROOT, "data", "translations");
// Keep in sync with the release WikDict currently publishes.
const WIKDICT = "https://download.wikdict.com/dictionaries/sqlite/2_2026-06";
const DEFAULT_LANGS = ["fr", "nl", "it", "es", "zh"];
const MAX_GLOSSES = 6;
// WikDict scores a pair by how many Wiktionary editions attest it. Low scores
// are mostly one-off or automatic imports, so they are dropped.
const MIN_SCORE = 20;

const protectYo = (s) => s.replace(/[ёЁËë]/g, "").replace(/[йЙ]/g, "");
const restoreYo = (s) => s.replaceAll("", "ё").replaceAll("", "й");

// Same key convention as the other databases: no stress marks, ё and й kept,
// lowercased. Mirrors bareLemma() in build-language-db.mjs.
const bareLemma = (s) =>
  restoreYo(
    protectYo(String(s || ""))
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/['`]/g, ""),
  )
    .toLowerCase()
    .trim();

const isWord = (s) => /^[а-яё]{2,}(-[а-яё]+)*$/i.test(s || "");

async function download(lang) {
  const url = `${WIKDICT}/ru-${lang}.sqlite3`;
  const file = join(tmpdir(), `wikdict-ru-${lang}.sqlite3`);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download ru-${lang}: ${res.status}`);
  await pipeline(Readable.fromWeb(res.body), createWriteStream(file));
  return file;
}

function extract(file) {
  const db = new DatabaseSync(file, { readOnly: true });
  const rows = db
    .prepare(
      "SELECT written_rep, trans_list, max_score FROM simple_translation WHERE max_score >= ? ORDER BY written_rep",
    )
    .all(MIN_SCORE);
  const out = {};
  for (const row of rows) {
    const key = bareLemma(row.written_rep);
    if (!isWord(key)) continue; // фразы, латиница, имена собственные не берём
    const glosses = String(row.trans_list || "")
      .split("|")
      .map((x) => x.trim())
      .filter(Boolean)
      .slice(0, MAX_GLOSSES);
    if (!glosses.length) continue;
    const prev = out[key];
    if (!prev) {
      out[key] = { t: glosses };
      continue;
    }
    for (const g of glosses) if (prev.t.length < MAX_GLOSSES && !prev.t.includes(g)) prev.t.push(g);
  }
  db.close();
  return out;
}

// Для en и de словарь OpenRussian остаётся главным: значения WikDict только
// дописываются в конец и только тем словам, что уже есть.
async function mergeInto(lang, extra) {
  const path = join(OUT_DIR, `${lang}.json`);
  let base = {};
  try {
    base = JSON.parse(await readFile(path, "utf8"));
  } catch {
    base = {};
  }
  let added = 0;
  for (const [key, rec] of Object.entries(extra)) {
    const cur = base[key];
    if (!cur) {
      base[key] = rec;
      added++;
      continue;
    }
    for (const g of rec.t) {
      if (cur.t.length >= MAX_GLOSSES) break;
      if (!cur.t.some((x) => x.toLowerCase() === g.toLowerCase())) {
        cur.t.push(g);
        added++;
      }
    }
  }
  await writeFile(path, JSON.stringify(base), "utf8");
  return { total: Object.keys(base).length, added };
}

async function main() {
  const args = process.argv.slice(2);
  const mergeEn = args.includes("--merge-en");
  const langs = args.filter((a) => !a.startsWith("--"));
  const list = langs.length ? langs : DEFAULT_LANGS;
  await mkdir(OUT_DIR, { recursive: true });

  for (const lang of [...list, ...(mergeEn ? ["en", "de"] : [])]) {
    const file = await download(lang);
    const entries = extract(file);
    await rm(file, { force: true });
    if (lang === "en" || lang === "de") {
      const { total, added } = await mergeInto(lang, entries);
      console.log(`translations/${lang}.json:    ${total} headwords (+${added} from WikDict)`);
    } else {
      await writeFile(join(OUT_DIR, `${lang}.json`), JSON.stringify(entries), "utf8");
      console.log(`translations/${lang}.json:    ${Object.keys(entries).length} headwords`);
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
