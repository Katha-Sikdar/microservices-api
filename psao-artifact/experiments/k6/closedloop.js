/**
 * closedloop.js — closed-loop scenario run (S1..S9).
 *
 * This reproduces the manuscript's original load profile (a fixed VU pool with
 * think time) so that the new scenarios S6..S9 are directly comparable with the
 * previously reported S1..S5. It is deliberately NOT the ramp: a closed-loop
 * test measures what the system does at a given concurrency, not where it
 * saturates. Both belong in the paper, and they answer different questions.
 *
 * Two things are added relative to the original load-tests/test-jwt.js:
 *
 *   1. A steady-state window. The first `PSAO_WARMUP` of the run is tagged
 *      `phase:warmup` and the rest `phase:steady`, so the analysis can report
 *      throughput over the steady window AND over the full profile. Which of
 *      the two the manuscript used for its amortised-CPU number is currently
 *      ambiguous; analysis/amortized_cpu.py computes both, and this tagging is
 *      what makes that possible.
 *   2. Per-request latency samples are written out (--out csv) so the paper can
 *      show distributions rather than only means.
 *
 * Env:
 *   PSAO_SCENARIO     S1..S9 (written into the CSV)
 *   PSAO_ENVIRONMENT  local | eks
 *   PSAO_RUN          run index, e.g. 1
 *   PSAO_VUS          virtual users            (default 100)
 *   PSAO_WARMUP       ramp-up duration         (default 20s)
 *   PSAO_STEADY       steady duration          (default 1m)
 *   PSAO_RAMPDOWN     ramp-down duration       (default 10s)
 *   PSAO_SLEEP        per-iteration think time in seconds (default 1)
 *   PSAO_OUT_DIR      directory for k6_scenario.csv (default .)
 *   plus everything in lib/auth.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { TARGET_URL, requestParams } from './lib/auth.js';

const SCENARIO = __ENV.PSAO_SCENARIO || 'unknown';
const ENVIRONMENT = __ENV.PSAO_ENVIRONMENT || 'local';
const RUN = __ENV.PSAO_RUN || '1';
const VUS = Number(__ENV.PSAO_VUS || 100);
const WARMUP = __ENV.PSAO_WARMUP || '20s';
const STEADY = __ENV.PSAO_STEADY || '1m';
const RAMPDOWN = __ENV.PSAO_RAMPDOWN || '10s';
const THINK_S = Number(__ENV.PSAO_SLEEP || 1);
const OUT_DIR = __ENV.PSAO_OUT_DIR || '.';

function parseDurationSeconds(text) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m|h)$/.exec(String(text).trim());
  if (!m) throw new Error(`cannot parse duration: ${text}`);
  return Number(m[1]) * { ms: 0.001, s: 1, m: 60, h: 3600 }[m[2]];
}

const WARMUP_S = parseDurationSeconds(WARMUP);
const STEADY_S = parseDurationSeconds(STEADY);
const FULL_S = WARMUP_S + STEADY_S + parseDurationSeconds(RAMPDOWN);

export const options = {
  insecureSkipTLSVerify: true,
  stages: [
    { duration: WARMUP, target: VUS },
    { duration: STEADY, target: VUS },
    { duration: RAMPDOWN, target: 0 },
  ],
  thresholds: {
    // Always-true thresholds: they exist so k6 emits the phase-tagged
    // sub-metrics in the summary. See openloop-ramp.js for the same idiom.
    'http_req_duration{phase:steady}': ['p(99)>=0'],
    'http_reqs{phase:steady}': ['count>=0'],
    'http_req_duration{phase:warmup}': ['p(99)>=0'],
    'http_reqs{phase:warmup}': ['count>=0'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
};

export default function closedLoopRequest() {
  // exec.instance.currentTestRunDuration is milliseconds since test start, so
  // the phase tag is decided by wall-clock position in the profile rather than
  // by iteration count (which would drift as latency changes).
  const elapsedS = exec.instance.currentTestRunDuration / 1000;
  const phase = elapsedS < WARMUP_S ? 'warmup'
    : (elapsedS < WARMUP_S + STEADY_S ? 'steady' : 'rampdown');

  const params = requestParams(exec.scenario.iterationInTest, {
    phase,
    psao_scenario: SCENARIO,
    run: RUN,
  });
  const res = http.get(TARGET_URL, params);
  check(res, { 'status is 200': (r) => r.status === 200 });
  if (THINK_S > 0) sleep(THINK_S);
}

/**
 * Fixed precision, and an empty cell for anything k6 did not produce. See the
 * same helper in openloop-ramp.js: four decimals on a millisecond is already
 * finer than anything here resolves.
 */
function val(metric, key) {
  const value = metric && metric.values[key];
  return Number.isFinite(value) ? value.toFixed(4) : '';
}

export function handleSummary(data) {
  const header = [
    'scenario', 'environment', 'run', 'throughput_rps', 'throughput_window',
    'latency_mean_ms', 'latency_p50_ms', 'latency_p90_ms', 'latency_p95_ms',
    'latency_p99_ms', 'latency_stdev_ms',
  ].join(',');

  const rows = [];
  const windows = [
    ['steady', data.metrics['http_req_duration{phase:steady}'],
      data.metrics['http_reqs{phase:steady}'], STEADY_S],
    ['full', data.metrics.http_req_duration, data.metrics.http_reqs, FULL_S],
  ];

  for (const [windowName, duration, reqs, seconds] of windows) {
    if (!duration || !reqs) continue;
    const count = reqs.values.count || 0;
    rows.push([
      SCENARIO, ENVIRONMENT, RUN,
      (count / seconds).toFixed(3), windowName,
      val(duration, 'avg'), val(duration, 'med'), val(duration, 'p(90)'),
      val(duration, 'p(95)'), val(duration, 'p(99)'),
      // k6 does not expose a standard deviation. Leaving it blank is correct:
      // the runner recomputes it from the per-request CSV samples, and an
      // invented value here would silently become a published number.
      '',
    ].join(','));
  }

  const out = {};
  out[`${OUT_DIR}/k6_scenario.csv`] = `${[header].concat(rows).join('\n')}\n`;
  out[`${OUT_DIR}/k6_summary.json`] = JSON.stringify(data, null, 2);
  out.stdout = `\nclosed-loop ${SCENARIO} run ${RUN}: ${VUS} VUs, think ${THINK_S}s\n`
    + `wrote ${OUT_DIR}/k6_scenario.csv (steady + full windows)\n`
    + 'latency_stdev_ms and the CPU columns are filled in by run_closedloop_scenario.sh\n';
  return out;
}
