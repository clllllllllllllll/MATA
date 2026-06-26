/// <reference types="node" />

import { readFileSync } from 'node:fs'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const pageHeroSource = readFileSync(new URL('./PageHero.tsx', import.meta.url), 'utf8')

assertEqual(
  pageHeroSource.includes('className="hero-meta"'),
  false,
  'PageHero does not render top-right informational meta text',
)
assertEqual(
  /metaInline\.map|meta\.map/.test(pageHeroSource),
  false,
  'PageHero does not render meta or metaInline arrays',
)
assertEqual(
  pageHeroSource.includes('className="hero-actions"'),
  true,
  'PageHero still renders useful action buttons',
)
assertEqual(
  /actions\s*\?\s*\([\s\S]*className="page-hero-right"/.test(pageHeroSource),
  true,
  'PageHero only renders the right-side hero column when actions exist',
)
