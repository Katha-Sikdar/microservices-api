# Experiments that still need the authors (JSS revision)

Every item below needs hardware, a cluster or a person the revision could not
use. Each lists the exact command, the environment, the output it writes, and
the sentences, tables or figures in the paper that change when it is run.
Nothing in the paper was estimated in their place: the current text either
reports what exists or says what is missing.

Reviewer comment IDs (M1-M7, minor 1-16) refer to `JSS_reviewer_report.md`.

---

## 1. M5: re-run the host decomposition with the OpenSSL version recorded

**Why.** Table 2 (the headline numbers) comes from
`data/runs/2026-09-17T08-42-17Z-keypath-mechanism`, which predates the per-row
`openssl_version` column. The version (3.6.3, the Homebrew `openssl@3` that
Homebrew's Node 26.6.0 links dynamically) is inferred from
`data/runs/HOST-OPENSSL-DRIFT-2026-09-17.md`, not recorded. The host has since
moved to 3.6.4 and `openssl@3` is pinned.

**Environment.** The authors' Apple-silicon Mac (macOS 26.5.2, arm64), the same
Homebrew Node. Close other applications; do not install software during the run.

**Command.**
```sh
node -p 'process.versions'            # record; expect openssl 3.6.4 (pinned)
experiments/run_keypath_mechanism.sh --environment "host-openssl$(node -p process.versions.openssl)"
python3 -m analysis.keypath_stats --run data/runs/<new>-keypath-mechanism
```
`bench/keypath-mechanism.js` already writes `openssl_version` on every row.

**Output.** `data/runs/<ts>-keypath-mechanism/keypath_mechanism.csv` with the
OpenSSL version on every row; `keypath_stats.json`.

**Paper changes.** Table 2 (and every `\Host*` macro: abstract, Sections 4, 5,
8, 9, conclusion) if the authors choose to make the new run the headline;
otherwise add it as a second host row in Table 4 and replace the dagger note in
Table 4 and the sentence in Section 3.1 ("inferred from the run record") with
the recorded version. To switch the headline, point `MECH` in
`analysis/make_keypath_macros.py` at the new run and regenerate.

---

## 2. M3: the in-situ A/B as alternating windows

**Why.** Table 5 is one enabled and one disabled window, consecutive, at
different host load, with k6 on the same machine.

**Environment.** The Kubernetes testbed in `testbed/` (Docker Desktop
single-node Kubernetes v1.32.2, Istio, NGINX ingress), service-a on
`node:18-alpine` as in the paper. Run k6 on another machine (`--base-url`) or
pin it with `--k6-cpus` to a core the cluster does not use.

**Command.**
```sh
node experiments/mint_tokens.js --count 64 --ttl 24h
experiments/run_ab_alternating.sh --pairs 5 --rps 200 --duration 3m --seed 20261001 --k6-cpus 3
python3 -m analysis.ab_alternating --run data/runs/<ts>-ab-alternating
```

**Output.** `data/runs/<ts>-ab-alternating/{order.csv, window-NN-<arm>/, ab_alternating.json}`:
median within-pair difference in CPU per request with a 95% bootstrap interval
over pairs, per-pair values, validation's share of CPU per request, host load
per window.

**Paper changes.** Section 6.2 (replace "one pair of consecutive windows ... no
interval" with the median difference and interval), Table 5 (add a row or a
companion table for the alternating design), Table 8 RQ3 row, Section 10
(Internal), abstract if the share changes materially.

---

## 3. M2: the in-situ A/B on supported base images

**Why.** The containerised service runs `node:18-alpine` (Node 18 is
end-of-life).

**Environment.** The same testbed.

**Command.**
```sh
cd testbed/service-a
docker build -f Dockerfile.ubuntu24.04 -t service-a:ubuntu24.04 .   # system OpenSSL 3.0 (Ubuntu's Node 18.19.1)
docker build -f Dockerfile.node24      -t service-a:node24 .         # bundled OpenSSL 3.5
# for each image: point testbed/kubernetes/service-a-deployment.yaml at it,
# kubectl apply, then run item 2's command
```

**Output.** Two further `*-ab-alternating` runs.

**Paper changes.** Section 6.2 and Table 5 (a column per image), Table 8 RQ3
row, Section 10 (External: "the service runs an end-of-life image").

---

## 4. M2: Debian 12 distribution-packaged Node.js

**Why.** Ubuntu 24.04 was measured in this revision
(`data/runs/2026-09-30T08-09-10Z-keypath-runtime-matrix`). The Debian mirror
was not reachable from the environment used for the revision.

**Environment.** Any x86_64 Linux host with Docker and access to deb.debian.org.
For comparability use the same machine for all three images below.

**Command.**
```sh
docker build -t psao/distro-node:debian12 -f experiments/distro/Dockerfile.debian12 experiments/distro
experiments/run_keypath_container.sh --rounds 10 --iterations 20000 --warmup 10000 \
  --images "psao/distro-node:debian12 psao/distro-node:ubuntu24.04 node:18.20.8-alpine node:26.6.0-alpine" \
  --conditions "jwt_hs_string jwt_hs_preparsed jwt_hs_string_safe probe_throws probe_succeeds"
python3 -m analysis.keypath_stats --run data/runs/<ts>-keypath-runtime-matrix
python3 -m analysis.make_review_macros --out macros/review_macros.tex
```

**Paper changes.** Section 5.3 (distribution-packaged Node.js) and Table 6
(new Debian row), Table 8 RQ2 row.

---

## 5. M6: second rater for the survey

**Why.** The call-site buckets are assigned by rules (`survey/classify.py`) and
the counter-search was adjudicated by one person.

**Who.** Two authors, independently.

**Command.**
```sh
# rater_1 and rater_2 each fill their own column, following survey/second_rater/CODEBOOK.md
open survey/second_rater/sheet_callsites.csv     # 110 call sites, stratified, seed 20261001
open survey/second_rater/sheet_adjudicated.csv   # 13 counter-search call sites (second rater only)
python3 survey/second_rater/kappa.py
```

**Output.** Cohen's kappa between the raters, agreement of each with the
rule-based classifier, and agreement on the counter-search.

**Paper changes.** Section 6.3 (add kappa and the resolution procedure),
Section 10 (Reliability: replace "one rater"), Figure 6 caption if the
resolved labels change a bucket count.

---

## 6. M1: the library survey outside npm, and confirmation of the npm adjudication

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

## 7. Optional: forged tokens on the arm64 host and in the service

**Why.** The revision measured rejected-token cost with `bench/forged-token.js`
on an x86_64 cloud VM (`data/runs/*-forged-tokens`). The reviewer suggested CPU
per rejected request in the running service.

**Command.**
```sh
experiments/run_forged_tokens.sh --rounds 10                       # on the Mac
# in-service: mint forged RS256 tokens (see bench/forged-token.js FORGED_RS)
# into a token pool and run item 2 with --token-pool pointing at them
```

**Paper changes.** Section 8.4 and Table 7 (add the host column).

---

## 8. Minor 12: upstream status

Before resubmission, check auth0/node-jsonwebtoken issues 966 and 1046 and the
pull request against 1046 for maintainer comments, and update the sentence in
Section 8.5 marked `TODO(minor 12)`. On 30 September 2026 the pull request was
unmerged, no release after 9.0.3 existed, and the main branch was unchanged
since June 2026; comments could not be read from the revision environment.
