/**
 * openloop-ramp.js — stepped open-loop arrival-rate ramp.
 *
 * WHY OPEN LOOP
 * -------------
 * Every measurement in the current manuscript came from a closed-loop test:
 * 100 VUs, each sleeping 1 s between requests. A closed-loop generator cannot
 * find a saturation point, because when the service slows down the generator
 * slows down with it -- offered load is not an independent variable, so there
 * is no arrival rate lambda to put on the x-axis of a queueing model. That is
 * the methodological hole behind the missing elbow figure.
 *
 * Here each step is a separate k6 `constant-arrival-rate` scenario: k6 starts
 * iterations at a fixed rate regardless of how long they take. Offered load is
 * therefore genuinely independent, and lambda is known exactly rather than
 * inferred from completed requests.
 *
 * WHY SEPARATE SCENARIOS PER STEP
 * -------------------------------
 * A single `ramping-arrival-rate` executor interpolates linearly between stage
 * targets, so the arrival rate is never actually constant and no point on the
 * curve corresponds to a single lambda. One constant-arrival-rate scenario per
 * step, offset by startTime, gives flat steps AND makes k6 tag every sample
 * with its step automatically, which is how the per-step rows are recovered.
 *
 * DROPPED ITERATIONS ARE THE SATURATION SIGNAL
 * --------------------------------------------
 * When the service can no longer keep up, k6 runs out of pre-allocated VUs and
 * reports `dropped_iterations`. A step with dropped iterations did NOT offer
 * the nominal rate, and the analysis must know that -- achieved_rps is written
 * to the CSV alongside target_rps for exactly this reason, and elbow_fit.py
 * fits only on the steps where the two agree.
 *
 * Env:
 *   PSAO_SCENARIO       scenario label written into the CSV (e.g. S5)
 *   PSAO_ENVIRONMENT    local | eks
 *   PSAO_MAX_RPS        top of the ramp            (default 400)
 *   PSAO_STEP_RPS       step size                  (default 20)
 *   PSAO_START_RPS      first step                 (default = PSAO_STEP_RPS)
 *   PSAO_STEP_DURATION  hold time per step         (default 30s)
 *   PSAO_SETTLE_S       gap between steps, seconds (default 0)
 *   PSAO_OUT_DIR        directory for k6_steps.csv (default .)
 *   plus everything in lib/auth.js
 */
import http from 'k6/http';
import { check } from 'k6';
import { TARGET_URL, requestParams } from './lib/auth.js';

const SCENARIO = __ENV.PSAO_SCENARIO || 'unknown';
const ENVIRONMENT = __ENV.PSAO_ENVIRONMENT || 'local';
const MAX_RPS = Number(__ENV.PSAO_MAX_RPS || 400);
const STEP_RPS = Number(__ENV.PSAO_STEP_RPS || 20);
const START_RPS = Number(__ENV.PSAO_START_RPS || STEP_RPS);
const STEP_DURATION = __ENV.PSAO_STEP_DURATION || '30s';
const SETTLE_S = Number(__ENV.PSAO_SETTLE_S || 0);
const OUT_DIR = __ENV.PSAO_OUT_DIR || '.';

function parseDurationSeconds(text) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m|h)$/.exec(String(text).trim());
  if (!m) throw new Error(`cannot parse duration: ${text}`);
  const value = Number(m[1]);
  return value * { ms: 0.001, s: 1, m: 60, h: 3600 }[m[2]];
}

const STEP_SECONDS = parseDurationSeconds(STEP_DURATION);

/** Zero-padded so scenario names sort lexicographically in k6 output. */
function stepName(rps) {
  return `step_${String(rps).padStart(5, '0')}`;
}

const STEP_RATES = [];
for (let r = START_RPS; r <= MAX_RPS; r += STEP_RPS) STEP_RATES.push(r);

const scenarios = {};
const thresholds = {};
STEP_RATES.forEach((rate, index) => {
  const name = stepName(rate);
  scenarios[name] = {
    executor: 'constant-arrival-rate',
    rate,
    timeUnit: '1s',
    duration: STEP_DURATION,
    startTime: `${index * (STEP_SECONDS + SETTLE_S)}s`,
    // Pre-allocating for a ~200 ms response gives headroom well past the elbow
    // without spawning tens of thousands of idle VUs; maxVUs allows k6 to grow
    // if the service degrades further, and any growth is itself reported.
    preAllocatedVUs: Math.max(20, Math.ceil(rate * 0.2)),
    maxVUs: Math.max(100, rate * 3),
    gracefulStop: '10s',
  };
  // A threshold on a tagged sub-metric is what makes k6 compute and emit that
  // sub-metric in handleSummary. The condition is deliberately always-true:
  // we want the statistics, not a pass/fail gate.
  thresholds[`http_req_duration{scenario:${name}}`] = ['p(99)>=0'];
  thresholds[`http_reqs{scenario:${name}}`] = ['count>=0'];
});

export const options = {
  insecureSkipTLSVerify: true, // self-signed Edge TLS certificate in the testbed
  discardResponseBodies: false, // the body is 3 small objects; parsing it is part of S1
  scenarios,
  thresholds,
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max', 'count'],
};

export default function openLoopRequest() {
  const params = requestParams(__ITER, { psao_scenario: SCENARIO });
  const res = http.get(TARGET_URL, params);
  check(res, { 'status is 200': (r) => r.status === 200 });
}

/**
 * Fixed precision, and an empty cell for anything k6 did not produce. Four
 * decimals on a millisecond is a tenth of a microsecond -- well past the
 * resolution of anything being measured, and past it is just float noise that
 * makes the CSV unreadable.
 */
function num(value, digits) {
  return Number.isFinite(value) ? value.toFixed(digits === undefined ? 4 : digits) : '';
}

export function handleSummary(data) {
  const header = [
    'scenario', 'environment', 'target_rps', 'achieved_rps',
    'latency_mean_ms', 'latency_p99_ms',
  ].join(',');

  const lines = [header];
  for (const rate of STEP_RATES) {
    const name = stepName(rate);
    const duration = data.metrics[`http_req_duration{scenario:${name}}`];
    const reqs = data.metrics[`http_reqs{scenario:${name}}`];
    if (!duration || !reqs) continue; // step never ran (test aborted early)
    const count = reqs.values.count || 0;
    // Computed against this step's own duration. k6's own `rate` field divides
    // by the WHOLE test duration, which for a 20-step ramp understates every
    // step by 20x.
    const achieved = count / STEP_SECONDS;
    lines.push([
      SCENARIO, ENVIRONMENT, rate, achieved.toFixed(3),
      num(duration.values.avg), num(duration.values['p(99)']),
    ].join(','));
  }

  const dropped = (data.metrics.dropped_iterations && data.metrics.dropped_iterations.values.count) || 0;
  const out = {};
  out[`${OUT_DIR}/k6_steps.csv`] = `${lines.join('\n')}\n`;
  out[`${OUT_DIR}/k6_summary.json`] = JSON.stringify(data, null, 2);
  out.stdout = `\nopen-loop ramp: ${STEP_RATES.length} steps, `
    + `${START_RPS}..${MAX_RPS} rps in ${STEP_RPS} rps steps of ${STEP_DURATION}\n`
    + `dropped_iterations = ${dropped}`
    + (dropped > 0 ? '  <-- offered load fell short of target on at least one step\n' : '\n')
    + `wrote ${OUT_DIR}/k6_steps.csv\n`;
  return out;
}
