// Minimal reproduction: jsonwebtoken@9.0.3 HS256 verify with a string secret.
// Run:  npm i jsonwebtoken@9.0.3 && node repro.js
const crypto = require('crypto');
const jwt = require('jsonwebtoken');

const SECRET = 'a-shared-secret-of-reasonable-length';
const KEYOBJ = crypto.createSecretKey(Buffer.from(SECRET));
const token = jwt.sign({ sub: 'u' }, SECRET, { algorithm: 'HS256', expiresIn: '1h' });
const N = 20000;

function bench(label, fn) {
  for (let i = 0; i < N; i++) fn();              // warm
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < N; i++) fn();
  const us = Number(process.hrtime.bigint() - t0) / 1000 / N;
  console.log(`${label.padEnd(34)} ${us.toFixed(2).padStart(8)} us/call`);
}

console.log(`node ${process.version}  openssl ${process.versions.openssl}  jsonwebtoken ${require('jsonwebtoken/package.json').version}\n`);
bench('jwt.verify, string secret', () => jwt.verify(token, SECRET, { algorithms: ['HS256'] }));
bench('jwt.verify, KeyObject secret', () => jwt.verify(token, KEYOBJ, { algorithms: ['HS256'] }));
bench('createPublicKey(secret) [throws]', () => { try { crypto.createPublicKey(SECRET); } catch (_) {} });
bench('createSecretKey(Buffer.from(s))', () => crypto.createSecretKey(Buffer.from(SECRET)));
