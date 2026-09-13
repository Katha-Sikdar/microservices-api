/**
 * auth.js — token handling shared by the k6 scripts.
 *
 * Tokens are never generated inside k6. k6's JS runtime (goja) has no HS256 or
 * RS256 signing that matches the service's library, and more importantly a
 * token minted per iteration would make every request a cache miss in S8 and
 * would put signing cost inside the load generator. Tokens are minted once,
 * outside the run, and passed in through the environment. run_*.sh does this.
 *
 * Environment variables (all optional except the token source):
 *   PSAO_TOKEN        the bearer token to send
 *   PSAO_TOKEN_FILE   path to a file containing the token (preferred: keeps the
 *                     token out of the process table)
 *   PSAO_TOKEN_POOL   path to a newline-separated file of tokens. Used to
 *                     control the S8 cache hit rate: one token = 100% hits
 *                     after the first request, which would be a dishonest
 *                     best case, so the ramp scripts pass a pool.
 *   PSAO_BASE_URL     default https://localhost
 *   PSAO_PATH         default /products
 */
import { fail } from 'k6';

const TOKEN_ENV = __ENV.PSAO_TOKEN || '';
// open() is only callable during init, which is exactly where this module is
// evaluated. Reading in the default function would throw.
const TOKEN_FILE = __ENV.PSAO_TOKEN_FILE ? open(__ENV.PSAO_TOKEN_FILE).trim() : '';
const TOKEN_POOL_RAW = __ENV.PSAO_TOKEN_POOL ? open(__ENV.PSAO_TOKEN_POOL) : '';

const TOKEN_POOL = TOKEN_POOL_RAW
  .split('\n')
  .map((line) => line.trim())
  .filter((line) => line.length > 0);

export const BASE_URL = __ENV.PSAO_BASE_URL || 'https://localhost';
export const REQUEST_PATH = __ENV.PSAO_PATH || '/products';
export const TARGET_URL = `${BASE_URL}${REQUEST_PATH}`;

/** true when the scenario under test does not send a token at all (S1-S3). */
export const AUTH_REQUIRED = (__ENV.PSAO_AUTH || 'true') !== 'false';

if (AUTH_REQUIRED && TOKEN_POOL.length === 0 && !TOKEN_ENV && !TOKEN_FILE) {
  fail('no token: set PSAO_TOKEN, PSAO_TOKEN_FILE or PSAO_TOKEN_POOL '
    + '(or PSAO_AUTH=false for the unauthenticated scenarios)');
}

/**
 * Pick a token for this iteration. Round-robin over the pool keyed by the
 * global iteration counter, so the distribution across tokens is uniform and
 * reproducible rather than random -- a random draw would make the S8 hit rate
 * differ between runs and make S8 unreproducible.
 */
export function tokenForIteration(iteration) {
  if (TOKEN_POOL.length > 0) return TOKEN_POOL[iteration % TOKEN_POOL.length];
  return TOKEN_FILE || TOKEN_ENV;
}

/** Request params, including the Authorization header when the scenario uses one. */
export function requestParams(iteration, extraTags) {
  const params = {
    headers: {},
    tags: extraTags || {},
    // Named so k6 groups the URL under one metric even if the path gains a
    // query string later.
    responseCallback: undefined,
  };
  if (AUTH_REQUIRED) {
    params.headers.Authorization = `Bearer ${tokenForIteration(iteration)}`;
  }
  return params;
}

/** Number of distinct tokens in play; recorded in run_metadata.json. */
export const TOKEN_POOL_SIZE = TOKEN_POOL.length > 0 ? TOKEN_POOL.length : 1;
