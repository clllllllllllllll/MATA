/// <reference types="node" />

import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

type VercelHeader = {
  key: string
  value: string
}

type VercelHeaderRule = {
  source: string
  headers: VercelHeader[]
}

type VercelConfig = {
  rewrites?: Array<{
    source: string
    destination: string
  }>
  headers?: VercelHeaderRule[]
}

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

function assert(condition: unknown, label: string): asserts condition {
  if (!condition) {
    throw new Error(label)
  }
}

const vercelConfig = JSON.parse(read('../vercel.json')) as VercelConfig
const securityTxtPath = fileURLToPath(new URL('../public/.well-known/security.txt', import.meta.url))

const frontendRouteHeaders = vercelConfig.headers?.find((rule) => rule.source === '/(.*)')
const headerValue = (key: string) =>
  frontendRouteHeaders?.headers.find((header) => header.key.toLowerCase() === key.toLowerCase())?.value

assert(
  vercelConfig.rewrites?.some((rewrite) => rewrite.source === '/(.*)' && rewrite.destination === '/index.html') === true,
  'Vercel frontend config preserves the SPA rewrite to index.html',
)
assert(frontendRouteHeaders !== undefined, 'Vercel frontend config applies headers to all frontend routes')

const contentSecurityPolicy = headerValue('Content-Security-Policy')
assert(contentSecurityPolicy !== undefined, 'Content-Security-Policy is configured')
assert(
  contentSecurityPolicy.includes('connect-src') &&
    contentSecurityPolicy.includes('https://mata-backend.vercel.app') &&
    contentSecurityPolicy.includes('https://*.supabase.co'),
  'CSP connect-src allows only the MATA backend and Supabase hosts required by the frontend',
)
assert(!contentSecurityPolicy.includes('default-src *'), 'CSP does not wildcard default-src')
assert(!contentSecurityPolicy.includes('connect-src *'), 'CSP does not wildcard connect-src')
assert(!contentSecurityPolicy.includes('unsafe-eval'), 'CSP does not allow unsafe-eval')

assert(headerValue('X-Frame-Options') === 'DENY', 'X-Frame-Options denies framing')
assert(headerValue('X-Content-Type-Options') === 'nosniff', 'X-Content-Type-Options disables MIME sniffing')
assert(headerValue('Referrer-Policy') !== undefined, 'Referrer-Policy is configured')
assert(headerValue('Permissions-Policy') !== undefined, 'Permissions-Policy is configured')
assert(headerValue('Cross-Origin-Opener-Policy') !== undefined, 'Cross-Origin-Opener-Policy is configured')
assert(headerValue('Cross-Origin-Resource-Policy') !== undefined, 'Cross-Origin-Resource-Policy is configured')
assert(
  headerValue('X-Permitted-Cross-Domain-Policies') === 'none',
  'X-Permitted-Cross-Domain-Policies disables cross-domain policy files',
)
assert(headerValue('Cross-Origin-Embedder-Policy') === undefined, 'COEP is not configured for the Vercel frontend')
assert(existsSync(securityTxtPath), 'frontend security.txt exists in the public .well-known directory')
