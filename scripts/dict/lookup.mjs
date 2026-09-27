// Reference client for data/dict/: finds the article(s) for a word, loading
// one shard at a time. Works in Node 18+, browsers and extension workers (only
// needs fetch). Copy it into a consumer or import it from a pinned tag.
//
//   import { createDictionary } from "./lookup.mjs";
//   const dict = createDictionary("https://raw.githubusercontent.com/cestmoi111/russian-language-data/v6.2/data/dict");
//   await dict.lookup("ru-fr", "девушки", ["девушка"]);   // lemmas from your morphology
//   await dict.lookup("en-ru", "ran");                    // forms are resolved by the data

// FNV-1a 32-bit over UTF-16 code units; must match fnv1a() in build.py.
export function fnv1a(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

// Key of a Russian word: no stress marks, ё and й kept, lowercase.
export function keyRu(s) {
  return String(s || "")
    .replace(/ё/g, "\u0001").replace(/Ё/g, "\u0002").replace(/й/g, "\u0003").replace(/Й/g, "\u0004")
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/\u0001/g, "ё").replace(/\u0002/g, "Ё").replace(/\u0003/g, "й").replace(/\u0004/g, "Й")
    .normalize("NFC").toLowerCase().trim();
}

export function keyX(s) {
  return String(s || "").trim().normalize("NFC").toLowerCase();
}

// French and Italian elisions as tokenisers leave them: l' qu' dell'
const ELISION = { c: "ce", l: "le", j: "je", d: "de", qu: "que", n: "ne", t: "te", m: "me",
  s: "se", quelqu: "quelque", jusqu: "jusque", lorsqu: "lorsque", puisqu: "puisque", dell: "dello" };

export function createDictionary(base, { fetchJson } = {}) {
  const load = fetchJson || (async (url) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  });
  const manifests = new Map();
  const shards = new Map();

  async function manifest(pair) {
    if (!manifests.has(pair)) manifests.set(pair, load(`${base}/${pair}/manifest.json`));
    return manifests.get(pair);
  }

  async function shard(pair, key) {
    const m = await manifest(pair);
    const i = fnv1a(key) % m.buckets;
    const id = `${pair}/${i}`;
    if (!shards.has(id)) shards.set(id, load(`${base}/${id}.json`));
    return shards.get(id);
  }

  async function articles(pair, key) {
    const own = (await shard(pair, key)).e[key] || [];
    const lemmas = (await shard(pair, key)).f[key] || [];
    const out = own.filter((a) => a.t || a.s);
    for (const l of lemmas) {
      if (l === key) continue;
      for (const a of (await shard(pair, l)).e[l] || []) out.push({ ...a, from: key });
    }
    return out;
  }

  // pair: "ru-fr" or "fr-ru". lemmas: extra dictionary forms to try (for
  // Russian, the normal forms your morphology gives; the data has no Russian
  // inflection table of its own).
  async function lookup(pair, word, lemmas = []) {
    const ru = pair.startsWith("ru-");
    const norm = ru ? keyRu : keyX;
    let key = norm(word);
    if (!ru && /['’]$/.test(key)) key = ELISION[key.slice(0, -1)] || key.slice(0, -1);
    const tried = new Set();
    const out = [];
    for (const k of [key, ...lemmas.map(norm)]) {
      if (!k || tried.has(k)) continue;
      tried.add(k);
      out.push(...(await articles(pair, k)));
    }
    // avez-vous, dis-moi, allons-y: the verb carries the meaning.
    if (!out.length && !ru && key.includes("-")) return lookup(pair, key.split("-")[0]);
    // Serbian in Latin script shares most words with Croatian.
    if (!out.length && pair === "sr-ru" && /[a-z]/.test(key)) return lookup("hr-ru", key);
    return out;
  }

  return { lookup, manifest };
}
