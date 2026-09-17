/**
 * keypath-security-check.js -- does removing the failed asymmetric probe
 * reintroduce algorithm confusion?
 *
 * The classic attack: a service is configured with an RSA PUBLIC KEY and
 * expects RS256. An attacker sends a token with alg:HS256, HMAC'd using that
 * public key -- which is public, so the attacker has it -- as the shared
 * secret. A library that dispatches on the token's own alg header will validate
 * it. CVE-2015-9235 and the family after it.
 *
 * jsonwebtoken@9.0.3 survives this partly by accident of the probe order:
 * createPublicKey(pem) SUCCEEDS, producing a KeyObject of type 'public', and
 * the later guard rejects HS* against a non-secret key. Any patch that skips
 * the probe for HS* must not lose that.
 *
 * Exit status is non-zero if any expectation fails.
 */
'use strict';
const crypto = require('node:crypto');
const patch = require('./keypath-patch.js');

const RSA = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const PUBLIC_PEM = RSA.publicKey.export({ type: 'spki', format: 'pem' });
const PRIVATE_PEM = RSA.privateKey.export({ type: 'pkcs8', format: 'pem' });
const HMAC_SECRET = 'your-super-secret-key-that-is-long';

function b64url(buf) {
  return Buffer.from(buf).toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** A token claiming alg:HS256, signed with `key` as the HMAC secret. */
function forgeHs256(key) {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = b64url(JSON.stringify({ sub: 'attacker', admin: true }));
  const signingInput = `${header}.${payload}`;
  const sig = crypto.createHmac('sha256', key).update(signingInput).digest();
  return `${signingInput}.${b64url(sig)}`;
}

const VARIANTS = {
  stock: patch.PKG,
  naive: patch.build('naive'),
  safe: patch.build('safe'),
};

// Expectations are stated PER VARIANT, because the interesting result is that
// they differ. `naive` is expected to ACCEPT the forged token: that is the
// regression being demonstrated, not a failure of this script. The script exits
// non-zero only when a variant departs from what is documented here -- so it
// also fails if `naive` were ever to stop being vulnerable, which would mean
// the demonstration had gone stale.
//
// [name, secret the SERVER is configured with, token, algorithms, {variant: expected}]
function cases(jwt) {
  return [
    ['confusion_attack__rsa_public_pem_as_secret',
      PUBLIC_PEM, forgeHs256(PUBLIC_PEM), undefined,
      { stock: 'reject', naive: 'accept', safe: 'reject' }],
    // Pinning `algorithms` defends this independently of the key path, in every
    // variant. The service in our earlier study passed no `algorithms` option,
    // which is the configuration the row above models.
    ['confusion_attack__algorithms_pinned_rs256',
      PUBLIC_PEM, forgeHs256(PUBLIC_PEM), ['RS256'],
      { stock: 'reject', naive: 'reject', safe: 'reject' }],
    ['legitimate_hs256_string_secret',
      HMAC_SECRET, jwt.sign({ sub: 'u' }, HMAC_SECRET, { algorithm: 'HS256' }), ['HS256'],
      { stock: 'accept', naive: 'accept', safe: 'accept' }],
    ['legitimate_rs256_pem',
      PUBLIC_PEM, jwt.sign({ sub: 'u' }, PRIVATE_PEM, { algorithm: 'RS256' }), ['RS256'],
      { stock: 'accept', naive: 'accept', safe: 'accept' }],
    ['legitimate_hs256_keyobject',
      crypto.createSecretKey(Buffer.from(HMAC_SECRET)),
      jwt.sign({ sub: 'u' }, HMAC_SECRET, { algorithm: 'HS256' }), ['HS256'],
      { stock: 'accept', naive: 'accept', safe: 'accept' }],
  ];
}

let failures = 0;
console.log('variant,case,expected,observed,detail');
for (const [variant, modPath] of Object.entries(VARIANTS)) {
  const jwt = require(modPath);
  for (const [name, secret, token, algorithms, expectations] of cases(jwt)) {
    const expected = expectations[variant];
    let observed, detail = '';
    try {
      jwt.verify(token, secret, algorithms ? { algorithms } : undefined);
      observed = 'accept';
    } catch (err) {
      observed = 'reject';
      detail = err.message.replace(/,/g, ';');
    }
    if (observed !== expected) failures += 1;
    console.log([variant, name, expected, observed,
      (observed === expected ? 'ok' : 'MISMATCH') + (detail ? ' | ' + detail : '')].join(','));
  }
}
console.error(failures === 0
  ? '\nall variants behaved as documented (including naive, which is vulnerable by design)'
  : `\n${failures} variant(s) departed from documented behaviour`);
process.exit(failures === 0 ? 0 : 1);
