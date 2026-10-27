#!/usr/bin/env node
// Checks every t()/tp() phrase in the TV app against the de and ro tables in
// web/src/shared/i18n.js. Exits 1 if any are missing.
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const root = new URL('../web/src/', import.meta.url).pathname
const files = [
  ...readdirSync(join(root, 'tv')).filter((f) => f.endsWith('.jsx') || f.endsWith('.js')).map((f) => join(root, 'tv', f)),
  // The player, which the TV shows too.
  ...readdirSync(join(root, 'shared')).filter((f) => /^Player.*\.jsx$/.test(f)).map((f) => join(root, 'shared', f)),
]
const source = readFileSync(join(root, 'shared/i18n.js'), 'utf8')
const tables = {}
for (const lang of ['de', 'ro']) {
  const start = source.indexOf(`  ${lang}: {`, source.indexOf('const DICT'))
  const end = source.indexOf('\n  },', start)
  tables[lang] = source.slice(start, end)
}
const has = (table, key) =>
  table.includes(`'${key.replace(/'/g, "\\'")}'`) || table.includes(`"${key}"`) || new RegExp(`[\\s{,]${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}:`).test(table)

const phrases = new Set()
for (const file of files) {
  const text = readFileSync(file, 'utf8')
  for (const m of text.matchAll(/\bt\(\s*(['"])((?:\\.|(?!\1).)+)\1/g)) phrases.add(m[2].replace(/\\'/g, "'"))
  for (const m of text.matchAll(/\btp\(\s*'([^']+)',\s*'([^']+)'/g)) phrases.add(`${m[1]}|${m[2]}`)
}
let missing = 0
for (const phrase of [...phrases].sort()) {
  for (const lang of ['de', 'ro']) {
    if (!has(tables[lang], phrase)) {
      console.log(`${lang}: ${phrase}`)
      missing += 1
    }
  }
}
console.log(`${phrases.size} phrases, ${missing} missing`)
process.exit(missing ? 1 : 0)
