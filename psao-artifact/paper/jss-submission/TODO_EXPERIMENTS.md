# Experiments that still need the authors (JSS revision)

Every item below needs hardware, a cluster or a person the revision could not
use. Each lists the exact command, the environment, the output it writes, and
the sentences, tables or figures in the paper that change when it is run.
Nothing in the paper was estimated in their place.

Reviewer comment IDs (M1-M7, minor 1-16) refer to `JSS_reviewer_report.md`;
"item N" refers to the second revision request.

---

# MUST COMPLETE BEFORE SUBMISSION

These three were dry-run end to end in the revision environment (on dummy data
where a cluster or a person is needed) and are ready to run.

## A. Alternating in-situ A/B (M3; supersedes the single pair in Table 6)

**Environment.** The Kubernetes testbed in `testbed/` on the authors' Mac.
k6 must not share cores with the service: either run it from a second machine
(`--base-url https://<mac-ip>`) or pin it with `--k6-cpus`.

**Dry run (no cluster; checks orchestration and analysis):**
```sh
experiments/run_ab_alternating.sh --dry-run --pairs 5
python3 -m analysis.ab_alternating --run "${TMPDIR:-/tmp}"/DRYRUN-*-ab-alternating   # prints "dummy_data": true
```
**Real run (>= 5 windows per arm, randomised order within each pair):**
```sh
node experiments/mint_tokens.js --count 64 --ttl 24h
experiments/run_ab_alternating.sh --pairs 5 --rps 200 --duration 3m --seed 20261001 --k6-cpus 3
python3 -m analysis.ab_alternating --run data/runs/<ts>-ab-alternating
```
**Output.** `ab_alternating.json`: median within-pair difference in CPU per
request with a 95% bootstrap interval over pairs (10,000 resamples), per-pair
values, validation's share of CPU per request, host load per window.

**Paper changes once it exists.** Abstract (the CPU-share sentence), §6.2
(replace "one pair of consecutive windows ... carries no interval" and the
"prepared ... but was not run" wording with the median difference and
interval), Table 6 (add the alternating result), §10 Internal (remove "an
alternating design ... is prepared in the replication package but was not
run"), Table 10 RQ3 row. Add the macros to `analysis/make_review_macros.py`
(read `data/runs/*-ab-alternating/ab_alternating.json`).

## B. Host decomposition re-run with process.versions recorded (M5)

**Environment.** The authors' Mac, same Homebrew Node 26.6.0 (OpenSSL now
pinned at 3.6.4). Close other applications.

**Command** (the runner records `process.versions` to `process_versions.json`,
writes the OpenSSL version on every row, and labels the environment
`host-openssl<version>` so it cannot be pooled with the 3.6.3 run; it was run
end to end on the revision VM as `data/runs/2026-09-30T09-13-02Z-keypath-mechanism`):
```sh
experiments/run_keypath_mechanism.sh --rounds 15 --iterations 40000 --warmup 20000
experiments/run_keypath_mechanism.sh --rounds 15 --iterations 40000 --warmup 20000 \
  --conditions "jwt_hs_string jwt_hs_preparsed jwt_hs_string_safe jwt_hs_string_keyonly jwt_sign_string jwt_sign_preparsed"
python3 -m analysis.keypath_stats --run data/runs/<ts>-keypath-mechanism
```
**Paper changes once it exists.** §3.1 and Table 4 note (replace "inferred
from the run record" with the recorded version), §10 Internal (last sentence),
and, if the authors choose, Table 2 and every `\Host*` value (point `MECH` in
`analysis/make_keypath_macros.py` at the new run). The second command adds the
arm64 bars for the key-material-only fix to Figure 9 and arm64 `sign()` timing.

## C. Second rater and Cohen's kappa (M6)

**Who.** Two authors, independently, following `survey/second_rater/CODEBOOK.md`.

**Dry run (dummy ratings; the real sheets are not touched):**
```sh
python3 survey/second_rater/make_dummy_ratings.py --out /tmp/dummy_rating
python3 survey/second_rater/kappa.py --sheets /tmp/dummy_rating
```
**Real run.** Fill `rater_1`/`rater_2` in `survey/second_rater/sheet_callsites.csv`
(110 call sites) and `rater_2` in `sheet_adjudicated.csv` (13), then
`python3 survey/second_rater/kappa.py`.

**Paper changes once it exists.** §6.3 (kappa, resolution procedure), §10
"Reliability of the survey" (replace "the second rating has not yet been
done"), Figure 6 caption if a resolved label moves a count.

---

# Other open items
## 1. M2: the in-situ A/B on supported base images

**Why.** The containerised service runs `node:18-alpine` (Node 18 is
end-of-life).

**Environment.** The same testbed.

**Command.**
```sh
cd testbed/service-a
docker build -f Dockerfile.ubuntu24.04 -t service-a:ubuntu24.04 .   # system OpenSSL 3.0 (Ubuntu's Node 18.19.1)
docker build -f Dockerfile.node24      -t service-a:node24 .         # bundled OpenSSL 3.5
# for each image: point testbed/kubernetes/service-a-deployment.yaml at it,
# kubectl apply, then run item A's command
```

**Output.** Two further `*-ab-alternating` runs.

**Paper changes.** Section 6.2 and Table 5 (a column per image), Table 8 RQ3
row, Section 10 (External: "the service runs an end-of-life image").

---

## 2. M1: the library survey outside npm, and confirmation of the npm adjudication

**Why.** The revision ran the npm frames (`survey/libsurvey/`). PyPI, Go and
Maven have no download-count API reachable from the revision environment, and
the adjudication of the detector's npm hits
(`survey/libsurvey/data/adjudication_*.csv`) was done in the revision pass and
should be confirmed by an author.

**Command.** For npm, re-run and re-check:
```sh
python3 survey/libsurvey/collect.py --frame jwt --min-weekly 50000
python3 survey/libsurvey/collect.py --frame crypto --min-weekly 500000
node survey/libsurvey/scan.js --frame jwt
node survey/libsurvey/scan.js --frame crypto
# read every row of data/scan_*.csv and confirm or correct adjudication_*.csv
```
For PyPI/Go/Maven: define the frame (e.g. PyPI packages with "jwt"/"jose" in
name or classifiers and >= 100k monthly downloads from pypistats; Go modules
importing `crypto/x509`/`crypto/hmac` with >= 100 importers on pkg.go.dev;
Maven artifacts with "jwt"/"jose" in the artifactId), and extend `scan.js`'s
rule to `try: load_pem_*/…except: …` (Python), `x509.Parse*` error-as-type
fallbacks (Go) and `try { KeyFactory…generatePublic } catch` (Java).

**Paper changes.** Section 7.1 (library survey) and Table 1 note c.

---

## 3. Optional: forged tokens on the arm64 host and in the service

**Why.** The revision measured rejected-token cost with `bench/forged-token.js`
on an x86_64 cloud VM (`data/runs/*-forged-tokens`). The reviewer suggested CPU
per rejected request in the running service.

**Command.**
```sh
experiments/run_forged_tokens.sh --rounds 10                       # on the Mac
# in-service: mint forged RS256 tokens (see bench/forged-token.js FORGED_RS)
# into a token pool and run item A with --token-pool pointing at them
```

**Paper changes.** Section 8.4 and Table 7 (add the host column).

---

## 4. Minor 12: upstream status

Before resubmission, check auth0/node-jsonwebtoken issues 966 and 1046 and the
pull request against 1046 for maintainer comments, and update the sentence in
Section 8.5 marked `TODO(minor 12)`. On 30 September 2026 the pull request was
unmerged, no release after 9.0.3 existed, and the main branch was unchanged
since June 2026; comments could not be read from the revision environment.

---

## 5. Debian 12 packaged nodejs and its support status (item 5)

The Debian archive (deb.debian.org, security.debian.org, snapshot.debian.org
and the mirrors tried) was blocked by the revision environment's network
policy, so Debian 12 could not be built or measured and its package's support
status could not be read. On any host with Docker and access to deb.debian.org:
```sh
docker build -t psao/distro-node:debian12 -f experiments/distro/Dockerfile.debian12 experiments/distro
docker run --rm psao/distro-node:debian12 sh -c 'apt-get update -qq; apt-cache policy nodejs; apt-cache show nodejs | grep -E "^(Version|Section)"' \
  > data/runs/<date>-debian-nodejs-support/apt_nodejs.txt
experiments/run_keypath_container.sh --rounds 10 --iterations 20000 --warmup 10000 \
  --images "psao/distro-node:debian12 psao/distro-node:ubuntu24.04 node:18.20.8-alpine node:26.6.0-alpine" \
  --conditions "jwt_hs_string jwt_hs_preparsed jwt_hs_string_safe jwt_hs_string_keyonly probe_throws probe_succeeds jwt_sign_string jwt_sign_preparsed"
python3 -m analysis.keypath_stats --run data/runs/<ts>-keypath-runtime-matrix
```
Also record Debian's security-support statement for nodejs (package
`debian-security-support`, file `security-support-limited`). **Paper changes:**
Table 5 (Debian row; re-running all four images together keeps the rows on one
machine), §5.3 support-status sentence, Table 10 RQ2 row.

## 6. Verify every DOI (item 9)

doi.org, Crossref and publisher sites were unreachable from the revision
environment, so no DOI could be checked there. Run:
```sh
python3 - <<'PY'
import re, urllib.request
for doi in sorted(set(re.findall(r'doi\s*=\s*\{([^}]+)\}', open('paper/references.bib').read()))):
    try:
        r = urllib.request.urlopen(urllib.request.Request('https://doi.org/' + doi, method='HEAD'), timeout=30)
        print('OK ', doi, r.status)
    except Exception as e:
        print('BAD', doi, e)
PY
```
and fix or remove any entry that does not resolve. The candidate references
listed in CHANGES.md were not added for the same reason.
