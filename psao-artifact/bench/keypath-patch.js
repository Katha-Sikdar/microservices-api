/**
 * keypath-patch.js -- build patched copies of jsonwebtoken for the mechanism
 * experiment, and refuse to build one if the source it expects has changed.
 *
 * jsonwebtoken@9.0.3 verify.js resolves a non-KeyObject secret by TRYING
 * createPublicKey() first and falling back to createSecretKey() in the catch.
 * For an HMAC string secret the first call always throws, so every verification
 * pays for a thrown-and-discarded OpenSSL parse failure.
 *
 * Two patches are built, because the obvious one is wrong:
 *
 *   naive  Take the symmetric path whenever header.alg is HS*. This removes the
 *          exception AND removes an algorithm-confusion defence: with an RSA
 *          PUBLIC KEY as the configured secret and an attacker-supplied
 *          alg:HS256 token HMAC'd with that public key, stock jsonwebtoken is
 *          saved by createPublicKey() SUCCEEDING -- the resulting KeyObject has
 *          type 'public', and the later check rejects it. Under this patch
 *          createSecretKey() is called on the PEM instead, yields type
 *          'secret', and the check passes. Built only so the regression can be
 *          demonstrated; it is NOT the proposed fix.
 *
 *   safe   Take the symmetric path only when alg is HS* AND the secret is a
 *          string that is not PEM and not JWK -- i.e. an ordinary shared
 *          secret, the case where createPublicKey() cannot succeed and the
 *          exception is therefore pure waste. Anything that could be asymmetric
 *          key material still goes down the original path, so the confusion
 *          defence is untouched.
 *
 * bench/keypath-security-check.js asserts both of those claims rather than
 * asserting the comment.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const PKG = path.join(__dirname, 'node_modules', 'jsonwebtoken');
const DEST_ROOT = path.join(__dirname, 'node_modules', '.keypath');

// Matched literally. If jsonwebtoken changes this block the patch must be
// re-derived, not silently applied to code it was never read against.
const ORIGINAL = `    if (secretOrPublicKey != null && !(secretOrPublicKey instanceof KeyObject)) {
      try {
        secretOrPublicKey = createPublicKey(secretOrPublicKey);
      } catch (_) {
        try {
          secretOrPublicKey = createSecretKey(typeof secretOrPublicKey === 'string' ? Buffer.from(secretOrPublicKey) : secretOrPublicKey);
        } catch (_) {
          return done(new JsonWebTokenError('secretOrPublicKey is not valid key material'))
        }
      }
    }`;

const SYMMETRIC_BRANCH = `        try {
          secretOrPublicKey = createSecretKey(typeof secretOrPublicKey === 'string' ? Buffer.from(secretOrPublicKey) : secretOrPublicKey);
        } catch (_) {
          return done(new JsonWebTokenError('secretOrPublicKey is not valid key material'))
        }`;

const ORIGINAL_BRANCH = `        try {
          secretOrPublicKey = createPublicKey(secretOrPublicKey);
        } catch (_) {
          try {
            secretOrPublicKey = createSecretKey(typeof secretOrPublicKey === 'string' ? Buffer.from(secretOrPublicKey) : secretOrPublicKey);
          } catch (_) {
            return done(new JsonWebTokenError('secretOrPublicKey is not valid key material'))
          }
        }`;

const PATCHES = {
  naive: `    if (secretOrPublicKey != null && !(secretOrPublicKey instanceof KeyObject)) {
      if (typeof header.alg === 'string' && header.alg.startsWith('HS')) {
${SYMMETRIC_BRANCH}
      } else {
${ORIGINAL_BRANCH}
      }
    }`,

  safe: `    if (secretOrPublicKey != null && !(secretOrPublicKey instanceof KeyObject)) {
      var __kpSymmetric = typeof header.alg === 'string'
        && header.alg.startsWith('HS')
        && typeof secretOrPublicKey === 'string'
        && secretOrPublicKey.indexOf('-----BEGIN') === -1
        && secretOrPublicKey.trim().charAt(0) !== '{';
      if (__kpSymmetric) {
${SYMMETRIC_BRANCH}
      } else {
${ORIGINAL_BRANCH}
      }
    }`,
};

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

/**
 * Build `variant` and return its require path. Placed under bench/node_modules/
 * so the copy's own require('jws') still resolves to the same dependency tree
 * the unpatched package uses -- a copy in /tmp would resolve differently or not
 * at all, and would not be measuring the same code.
 */
function build(variant) {
  if (!Object.prototype.hasOwnProperty.call(PATCHES, variant)) {
    throw new Error(`unknown patch variant: ${variant}`);
  }
  const verifySrc = fs.readFileSync(path.join(PKG, 'verify.js'), 'utf8');
  if (!verifySrc.includes(ORIGINAL)) {
    throw new Error(
      'jsonwebtoken/verify.js does not contain the block this patch was ' +
      'written against (expected the createPublicKey-then-createSecretKey ' +
      'try/catch of 9.0.3). Re-derive the patch; do not proceed.');
  }
  const dest = path.join(DEST_ROOT, variant, 'jsonwebtoken');
  fs.rmSync(path.join(DEST_ROOT, variant), { recursive: true, force: true });
  copyDir(PKG, dest);
  const patched = verifySrc.replace(ORIGINAL, PATCHES[variant]);
  if (patched === verifySrc) throw new Error(`patch ${variant} produced no change`);
  fs.writeFileSync(path.join(dest, 'verify.js'), patched);
  return dest;
}

module.exports = { build, variants: Object.keys(PATCHES), PKG };
