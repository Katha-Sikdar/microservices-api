/**
 * keypath-profile.js -- independent confirmation of where the string-key time
 * goes, by sampling profiler rather than by instrumented timers.
 *
 * The timing harness reaches its conclusion by differencing conditions. That is
 * exactly the inference style this work criticises elsewhere, so the conclusion
 * should not rest on it alone. V8's sampling profiler attributes self-time to
 * frames without any arithmetic on our part: if the failed createPublicKey
 * probe is what costs, it appears here by name.
 *
 * Usage:
 *   node --cpu-prof --cpu-prof-dir <dir> --cpu-prof-name <name>.cpuprofile \
 *        bench/keypath-profile.js --condition jwt_hs_string --iterations 200000
 *   node bench/keypath-profile.js --summarize <dir>/<name>.cpuprofile
 */
'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const patch = require('./keypath-patch.js');

const argv = process.argv.slice(2);
const flag = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? dflt : argv[i + 1];
};

// --- summarize mode ----------------------------------------------------------
if (argv.includes('--summarize')) {
  const profile = JSON.parse(fs.readFileSync(flag('summarize'), 'utf8'));
  const byId = new Map(profile.nodes.map((n) => [n.id, n]));
  const self = new Map();
  // timeDeltas[i] is the interval that ENDED at samples[i], so it is charged to
  // that sample's frame.
  for (let i = 0; i < profile.samples.length; i += 1) {
    const id = profile.samples[i];
    self.set(id, (self.get(id) || 0) + (profile.timeDeltas[i] || 0));
  }
  const rows = [];
  let total = 0;
  for (const [id, us] of self) {
    const n = byId.get(id);
    if (!n) continue;
    const cf = n.callFrame;
    const where = cf.url ? cf.url.replace(/.*\/node_modules\//, '') : '(native)';
    rows.push({ fn: cf.functionName || '(anonymous)', where, us });
    total += us;
  }
  const agg = new Map();
  for (const r of rows) {
    const k = `${r.fn}\t${r.where}`;
    agg.set(k, (agg.get(k) || 0) + r.us);
  }
  const sorted = [...agg.entries()].sort((a, b) => b[1] - a[1]).slice(0, 25);
  console.log('self_pct,self_ms,function,location');
  for (const [k, us] of sorted) {
    const [fn, where] = k.split('\t');
    console.log(`${(100 * us / total).toFixed(2)},${(us / 1000).toFixed(1)},${fn},${where}`);
  }
  console.error(`total sampled: ${(total / 1000).toFixed(1)} ms`);
  process.exit(0);
}

// --- profile mode ------------------------------------------------------------
const condition = flag('condition', 'jwt_hs_string');
const iterations = Number(flag('iterations', 200000));
const jwt = require(condition.endsWith('_safe') ? patch.build('safe') : patch.PKG);
const SECRET = 'your-super-secret-key-that-is-long';
const KEYOBJ = crypto.createSecretKey(Buffer.from(SECRET));
const token = jwt.sign({ sub: 'user0', name: 'Load User 0' }, SECRET,
  { algorithm: 'HS256', expiresIn: '24h' });

const key = condition === 'jwt_hs_preparsed' ? KEYOBJ : SECRET;
for (let i = 0; i < 20000; i += 1) jwt.verify(token, key, { algorithms: ['HS256'] });
for (let i = 0; i < iterations; i += 1) jwt.verify(token, key, { algorithms: ['HS256'] });
console.error(`profiled ${condition}: ${iterations} iterations`);
