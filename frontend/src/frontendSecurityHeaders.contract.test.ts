/// <reference types="node" />

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  MAX_REQUEST_BODY_SIZE_MIB,
  MAX_UPLOAD_REQUEST_SIZE_MIB,
} from './config/uploadLimits.ts'

type VercelHeader = {
  key: string
  value: string
}

type VercelHeaderRule = {
  source: string
  headers: VercelHeader[]
}

type VercelConfig = {
  rewrites: Array<{
    source: string
    destination: string
  }>
  headers: VercelHeaderRule[]
}

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const vercelConfig = JSON.parse(read('../vercel.json')) as VercelConfig
const securityTxtPath = fileURLToPath(new URL('../public/.well-known/security.txt', import.meta.url))
const frontendRouteHeaders = vercelConfig.headers.find((rule) => rule.source === '/(.*)')
const apiRouteHeaders = vercelConfig.headers.find((rule) => rule.source === '/api/v1/:path*')
const headerValue = (rule: VercelHeaderRule | undefined, key: string) =>
  rule?.headers.find((header) => header.key.toLowerCase() === key.toLowerCase())?.value

test('the external API rewrite precedes the SPA fallback', () => {
  assert.deepEqual(vercelConfig.rewrites[0], {
    source: '/api/v1/:path*',
    destination: 'https://mata-backend.vercel.app/api/v1/:path*',
  })
  assert.deepEqual(vercelConfig.rewrites[1], {
    source: '/(.*)',
    destination: '/index.html',
  })
})

test('proxied API responses opt out of browser and CDN caching', () => {
  assert.equal(
    headerValue(apiRouteHeaders, 'Cache-Control'),
    'private, no-store, max-age=0',
  )
  assert.equal(headerValue(apiRouteHeaders, 'CDN-Cache-Control'), 'no-store')
  assert.equal(headerValue(apiRouteHeaders, 'Vercel-CDN-Cache-Control'), 'no-store')
})

test('the frontend applies the complete transport and browser header contract', () => {
  assert.ok(frontendRouteHeaders)
  assert.equal(
    headerValue(frontendRouteHeaders, 'Strict-Transport-Security'),
    'max-age=63072000; includeSubDomains; preload',
  )
  assert.equal(headerValue(frontendRouteHeaders, 'X-Frame-Options'), 'DENY')
  assert.equal(headerValue(frontendRouteHeaders, 'X-Content-Type-Options'), 'nosniff')
  assert.equal(headerValue(frontendRouteHeaders, 'Referrer-Policy'), 'no-referrer')
  assert.ok(headerValue(frontendRouteHeaders, 'Permissions-Policy'))
  assert.equal(headerValue(frontendRouteHeaders, 'Cross-Origin-Opener-Policy'), 'same-origin')
  assert.equal(headerValue(frontendRouteHeaders, 'Cross-Origin-Resource-Policy'), 'same-origin')
  assert.equal(headerValue(frontendRouteHeaders, 'X-Permitted-Cross-Domain-Policies'), 'none')
  assert.equal(headerValue(frontendRouteHeaders, 'Access-Control-Allow-Origin'), undefined)
})

test('CSP is same-origin, non-frameable, and has no inline script escape hatch', () => {
  const policy = headerValue(frontendRouteHeaders, 'Content-Security-Policy')
  assert.ok(policy)

  const directives = new Map(
    policy.split(';').map((directive) => {
      const [name, ...values] = directive.trim().split(/\s+/)
      return [name, values]
    }),
  )
  assert.deepEqual(directives.get('connect-src'), ["'self'"])
  assert.deepEqual(directives.get('script-src'), ["'self'"])
  assert.equal(directives.get('script-src')?.includes("'unsafe-inline'"), false)
  assert.deepEqual(directives.get('object-src'), ["'none'"])
  assert.deepEqual(directives.get('base-uri'), ["'none'"])
  assert.deepEqual(directives.get('form-action'), ["'self'"])
  assert.deepEqual(directives.get('frame-ancestors'), ["'none'"])
  assert.equal(policy.includes('mata-backend.vercel.app'), false)
  assert.equal(policy.includes('supabase.co'), false)
})

test('external font loading is removed and Nginx mirrors the core policy', () => {
  const css = read('./index.css')
  const nginx = read('../nginx.conf')
  assert.equal(css.includes('fonts.googleapis.com'), false)
  assert.match(nginx, /add_header Strict-Transport-Security/)
  assert.match(nginx, /connect-src 'self'/)
  assert.match(nginx, /script-src 'self';/)
  assert.doesNotMatch(nginx, /script-src[^;]*unsafe-inline/)
  assert.match(nginx, /X-Permitted-Cross-Domain-Policies "none"/)
  assert.match(nginx, /proxy_set_header X-Forwarded-Host \$host/)
  assert.match(nginx, /proxy_no_cache 1/)
})

test('Nginx bounds request bodies before proxying upload streams', () => {
  const nginx = read('../nginx.conf')
  const firstLocationIndex = nginx.indexOf('location ')
  const uploadLocationMatch = nginx.match(
    /location \^~ \/api\/v1\/admin\/upload\/ \{([^{}]*)\}/,
  )

  assert.notEqual(firstLocationIndex, -1)
  const serverDirectives = nginx.slice(0, firstLocationIndex)
  assert.match(
    serverDirectives,
    new RegExp(`client_max_body_size\\s+${MAX_REQUEST_BODY_SIZE_MIB}m;`),
  )
  assert.ok(uploadLocationMatch)
  const uploadLocation = uploadLocationMatch[1]
  assert.match(
    uploadLocation,
    new RegExp(`client_max_body_size\\s+${MAX_UPLOAD_REQUEST_SIZE_MIB}m;`),
  )
  assert.match(uploadLocation, /proxy_request_buffering off;/)
  assert.match(uploadLocation, /proxy_http_version 1\.1;/)
  assert.match(
    uploadLocation,
    /proxy_pass http:\/\/backend:8000\/api\/v1\/admin\/upload\/;/,
  )
})

test('the standard security contact file remains published', () => {
  assert.equal(existsSync(securityTxtPath), true)
})
