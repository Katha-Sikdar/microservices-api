#!/usr/bin/env node
'use strict';
/**
 * s8-token-cache.js — Scenario S8: HS256 validation with an LRU cache of
 * already-verified tokens.
 *
 * S8 is the cheap alternative that a reviewer will raise against PSAO: "why
 * relocate verification to the sidecar when you could just cache the result?"
 * The artifact must therefore *measure* the cache rather than argue about it,
 * which is what this file exists for. It is the unmodified S5 handler with one
 * change: a verified token is remembered, keyed by SHA-256 of the token string.
 *
 * ---------------------------------------------------------------------------
 * SECURITY: THE TTL IS A SECURITY PARAMETER, NOT A TUNING KNOB
 * ---------------------------------------------------------------------------
 * Caching a verification result weakens revocation. Between the moment a token
 * is revoked (logout, credential compromise, session invalidation, a rotated
 * signing key) and the moment its cache entry is dropped, this service will
 * accept a token it should have rejected. The cache TTL is exactly that window.
 *
 * Two mitigations are built in, and neither eliminates the exposure:
 *
 *   1. Entry lifetime is min(configured TTL, remaining time on the token's own
 *      `exp` claim). A cached entry can therefore never outlive the token it
 *      describes -- caching never *extends* a token's validity. This bounds the
 *      damage but does not address revocation before `exp`.
 *
 *   2. Only successful verifications are cached. Failures are re-verified every
 *      time, so an attacker cannot pin a negative result, and a token that
 *      becomes valid (clock skew around `nbf`) is not stuck as invalid.
 *
 * What remains: a token revoked at time t is still accepted until
 * t + min(TTL, remaining exp). With the default TTL of 30 s that is a 30-second
 * revocation gap. In a Zero Trust deployment -- which is the setting of this
 * paper -- that gap is a policy decision belonging to the security owner, not a
 * performance tuning decision. It is reported alongside the throughput number
 * for exactly that reason: S8's speedup is bought with revocation latency,
 * whereas PSAO's (S7) is not.
 *
 * The cache is also keyed by the *whole token string*, hashed. Keying by `jti`
 * or `sub` would let one token's verification result authorise a different
 * token; SHA-256 of the full compact serialisation makes the key
 * collision-resistant and means any change to any byte is a different entry.
 * The hash also keeps raw bearer tokens out of process memory as map keys and
 * out of heap dumps.
 *
 * Usage:  node scenarios/s8-token-cache.js
 * Env:    PORT, METRICS_PORT, JWT_SECRET, CACHE_TTL_MS, CACHE_MAX_ENTRIES
 */

const crypto = require('node:crypto');
const express = require('express');
const jwt = require('jsonwebtoken');
const { createEventLoopMetrics } = require('../instrumentation/eventloop-metrics');

const PORT = Number(process.env.PORT || 3000);
const METRICS_PORT = Number(process.env.METRICS_PORT || 9464);
const JWT_SECRET = process.env.JWT_SECRET || 'your-super-secret-key-that-is-long';
// 30 s default: short enough that the revocation gap is comparable to a typical
// session-invalidation propagation delay, long enough that at 200 rps with a
// small token population the cache actually does something measurable.
const CACHE_TTL_MS = Number(process.env.CACHE_TTL_MS || 30000);
// Bounded so the cache cannot become a memory-exhaustion vector: an attacker
// presenting a stream of distinct (invalid) tokens must not be able to grow it.
// Only successful verifications are inserted, which already blocks that path;
// the bound is the second line of defence.
const CACHE_MAX_ENTRIES = Number(process.env.CACHE_MAX_ENTRIES || 10000);

// ---------------------------------------------------------------------------
// LRU with per-entry expiry
// ---------------------------------------------------------------------------

/**
 * Map preserves insertion order, so "delete then set" moves an entry to the
 * most-recently-used end and `keys().next()` yields the least-recently-used
 * one. That gives O(1) LRU without a dependency, which matters here: an
 * external LRU package would put its own allocation behaviour inside the
 * measurement.
 */
class TokenCache {
  constructor({ maxEntries, ttlMs, counters }) {
    this.map = new Map();
    this.maxEntries = maxEntries;
    this.ttlMs = ttlMs;
    this.counters = counters;
  }

  /** @returns {object|undefined} the cached claims, or undefined. */
  get(key, nowMs) {
    const entry = this.map.get(key);
    if (entry === undefined) {
      this.counters.miss.inc();
      return undefined;
    }
    if (entry.expiresAtMs <= nowMs) {
      // Lazy expiry: we do not run a sweeper timer, because a periodic sweep is
      // itself event-loop work and would contaminate the very metric this
      // testbed measures.
      this.map.delete(key);
      this.counters.expiry.inc();
      this.counters.miss.inc();
      return undefined;
    }
    this.map.delete(key);
    this.map.set(key, entry); // refresh recency
    this.counters.hit.inc();
    return entry.claims;
  }

  set(key, claims, nowMs) {
    // Entry lifetime is bounded by BOTH the configured TTL and the token's own
    // expiry. See the security note at the top of this file.
    const tokenExpiryMs = typeof claims.exp === 'number' ? claims.exp * 1000 : Infinity;
    const expiresAtMs = Math.min(nowMs + this.ttlMs, tokenExpiryMs);
    if (expiresAtMs <= nowMs) return; // already expired; nothing worth storing

    if (this.map.has(key)) this.map.delete(key);
    this.map.set(key, { claims, expiresAtMs });

    while (this.map.size > this.maxEntries) {
      const lruKey = this.map.keys().next().value;
      this.map.delete(lruKey);
      this.counters.eviction.inc();
    }
  }

  get size() { return this.map.size; }
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

function build() {
  const m = createEventLoopMetrics({
    port: METRICS_PORT,
    defaultLabels: { scenario: 'S8' },
  });

  const counters = {};
  for (const [name, help] of [
    ['hit', 'Token cache hits (verification skipped).'],
    ['miss', 'Token cache misses (full verification performed).'],
    ['eviction', 'Entries evicted because the cache reached its size bound.'],
    ['expiry', 'Entries dropped because their lifetime elapsed. This counter is the revocation-gap audit trail.'],
  ]) {
    counters[name] = new m.client.Counter({
      name: `psao_token_cache_${name}_total`,
      help,
      registers: [m.register],
    });
  }

  const cache = new TokenCache({
    maxEntries: CACHE_MAX_ENTRIES,
    ttlMs: CACHE_TTL_MS,
    counters,
  });

  new m.client.Gauge({
    name: 'psao_token_cache_entries',
    help: 'Current number of cached verification results.',
    registers: [m.register],
    collect() { this.set(cache.size); },
  });
  new m.client.Gauge({
    name: 'psao_token_cache_ttl_seconds',
    help: 'Configured cache TTL. This is the maximum revocation gap in seconds and is a SECURITY parameter.',
    registers: [m.register],
  }).set(CACHE_TTL_MS / 1000);

  const products = [
    { id: 1, name: 'Laptop' },
    { id: 2, name: 'Keyboard' },
    { id: 3, name: 'Mouse' },
  ];

  const app = express();
  app.use(m.middleware);

  app.get('/products', (req, res) => {
    const authHeader = req.headers.authorization;
    const token = authHeader && authHeader.split(' ')[1];
    if (!token) return res.sendStatus(401);

    const now = Date.now();
    // SHA-256 of the full compact serialisation: see the keying note above.
    const key = crypto.createHash('sha256').update(token).digest('base64');

    let claims = cache.get(key, now);
    if (claims === undefined) {
      try {
        // timeVerify() keeps the S8 verify histogram directly comparable with
        // S5's: the same wrapper, the same buckets, just called less often.
        claims = m.timeVerify('HS256', () => jwt.verify(token, JWT_SECRET, { algorithms: ['HS256'] }));
      } catch (err) {
        return res.sendStatus(403);
      }
      cache.set(key, claims, now);
    }
    return res.json(products);
  });

  return { app, m, cache };
}

if (require.main === module) {
  const { app, m } = build();
  m.startMetricsServer();
  const server = app.listen(PORT, () => {
    console.log(`[S8] token-cache service on :${PORT} `
      + `(TTL ${CACHE_TTL_MS} ms = max revocation gap, max ${CACHE_MAX_ENTRIES} entries)`);
  });
  const shutdown = () => {
    server.close();
    m.stop();
    process.exit(0);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

module.exports = { build, TokenCache };
