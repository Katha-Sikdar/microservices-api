# Where the cost of JWT verification actually goes

Measurement, control and analysis code for a study of JSON Web Token
verification cost in Kubernetes microservices under Istio, with the service
under layered enforcement: edge TLS, mutual TLS between workloads, and
application-level token validation.

The manuscript it supports is
[`psao-artifact/paper/key-resolution-cost.tex`](psao-artifact/paper/key-resolution-cost.tex).
Every numeric value in that paper is a generated macro read from a file under
`psao-artifact/data/runs/` or `psao-artifact/survey/`; none is typed by hand.
The figures quoted below come from the same place —
`psao-artifact/paper/keypath_macros.tex`, which the manuscript `\input`s.

---

## The finding

**It is not the cryptography.** Measured inside the running service on the host,
one HS256 validation costs **29.92 µs**. The HMAC primitive itself — the actual
signature check — costs **2.21 µs**.

**Nor is it key conversion**, which is what an earlier version of this work
concluded. Converting the secret from a string into a key object costs
**0.583 µs**. It is too small to explain anything.

**The dominant cost is a discarded exception.** When the caller supplies a shared
secret as a string, `jsonwebtoken` resolves it by attempting to parse it as an
*asymmetric* key first, and falls back to the symmetric constructor only after
that attempt throws. For an HMAC secret the first call cannot succeed. Every
validation therefore constructs and throws away an OpenSSL parse failure, at
**18.04 µs** — **60%** of the entire call, and the largest single component of
it. That discarded failure, not the conversion it falls back to, is why the
key-conversion attribution did not survive contact with direct measurement.

Passing a pre-parsed `KeyObject` instead of a string removes **23.92 µs** per
validation on the host. The effect is far larger on the runtime the service
actually deployed on: under Node **18.20.8** with OpenSSL **3.0.16**, the
discarded probe alone costs **373.79 µs** against a whole-call cost of
**394.71 µs**.

**The magnitude is a property of the runtime, not of the deployment.** Across the
container runtimes measured, the discarded probe spans **25.36×** while the rest
of the validation path spans at most **1.26×**. What varies is the OpenSSL
version the base image pins.

**Almost nobody avoids it.** In a sample of **327** call sites across **247**
public repositories, **0** pass a pre-parsed key. Across four combinations of
language and import form, no cell exceeds **0.0303%** of files importing the
library. A search built specifically to find the avoiding pattern located it at
**7** call sites across **6** projects — rare, not absent.

## A claim this repository previously made, and withdraws

An earlier version of this repository supported a manuscript arguing that
layered Zero Trust enforcement drives a Node.js service toward **event-loop
saturation**, and proposed relocating token verification into the Envoy sidecar
before that saturation point is reached. **Direct in-situ measurement did not
reproduce the saturation behaviour that claim rested on, and the claim is
withdrawn.**

The manuscript that replaced it made a second error, which is also withdrawn.
It reported that the dominant per-request cost was key material re-converted
from a string on every call. That is wrong: the conversion costs **0.583 µs**.
The cost it measured was real, but its attribution was not — the dominant term
is the discarded asymmetric-parse failure described above, at **18.04 µs**. That
manuscript further compared a host microbenchmark against an in-container
measurement and attributed the difference to deployment, when the two
environments differed by two OpenSSL major series; and it stated a runtime
version for the system under test that was read from the host rather than from
the container, and was wrong.

Both superseded manuscripts remain in `psao-artifact/paper/` under
`SUPERSEDED.md`, together with the runs behind them. They are kept deliberately:
the corrections are traceable only if what was corrected is still there.

## The security finding

Relocating verification into the service mesh does not work the way it appears
to, and the way that makes it work opens a bypass.

- Applying an Istio `RequestAuthentication` policy causes the sidecar to
  validate the token **in addition to** the application, not instead of it.
  Verification is **duplicated**, not relocated, and no work leaves the event
  loop.
- Making relocation effective therefore requires the application to trust
  something the sidecar tells it — in this testbed, a header carrying the
  verified claims — and to skip its own signature check when that header is
  present.
- That trust is the vulnerability. The sidecar overwrites the header only while
  a policy is applied. In any other state nothing sanitises it, and a request
  carrying a **forged `x-psao-jwt-payload` with no credential at all returned
  200 with the protected payload** — a complete authentication bypass.
- The fix is an **always-applied `EnvoyFilter` using `INSERT_FIRST`**, which
  strips any client-supplied copy of the header on entry to the pod, before any
  validation filter runs. It is matched on the connection manager rather than on
  the validation filter, because in the state that needs protection no
  validation filter exists.

A separate, library-level finding concerns the fix for the cost above. The
obvious optimisation — skip the asymmetric parse whenever the token declares an
HMAC algorithm — **reintroduces algorithm confusion**, because the success of
that parse on asymmetric material is what the library's key-type check depends
on. Against the library's own test suite: unmodified **511** passing, with the
narrow patch **511** passing, with the unrestricted form **2** failing, both in
the suite's `wrong_alg` tests. The upstream suite already guards this.

## Repository layout

```
service-a/            product endpoint; PSAO_AUTH_MODE and PSAO_JWT_KEYFORM
                      select the handler and key form at startup
service-b/            review endpoint
kubernetes/           deployment, service, ingress and mTLS manifests
load-tests/           closed-loop k6 scripts from the earliest study
results/              raw logs from that earliest study
tls-cert/             certificate only; see "Test certificate" below

psao-artifact/        the current work
  paper/              manuscript, bibliography, generated macros, provenance
  bench/              the measurement harness: one condition per process
  experiments/        runners for the host decomposition and runtime matrix
  analysis/           statistics and LaTeX macro generation
  survey/             prevalence survey, corpus manifest, adjudication
  upstream/           the patch, its tests, and the issue as filed
  instrumentation/    event-loop delay and verification-only histograms
  controller/         the sidecar-offload policy and Istio objects
  scenarios/          token-cache and cluster-mode variants
  data/runs/          every run, including the ones that failed
  docs/DATA_SCHEMA.md the schema for every CSV in the artifact
```

## Reproducing

**Prerequisites.** Node.js ≥ 18, Python ≥ 3.9, Docker. A Kubernetes cluster with
Istio 1.28.0 and k6 are needed only for the cluster scenarios; the measurements
behind the current finding do not require them.

```sh
cd psao-artifact
make setup                                    # venv + Python and Node deps

experiments/run_keypath_mechanism.sh          # host decomposition
                                              # 15 processes x 12 conditions
                                              # ~15 min

experiments/run_keypath_container.sh          # runtime matrix, 4 images
                                              # 10 processes x 10 conditions
                                              # ~20 min, needs Docker

python3 -m analysis.make_keypath_macros       # regenerate paper macros
cd paper && tectonic -X compile key-resolution-cost.tex
```

The survey is reproduced with `survey/collect.py`, `survey/classify.py` and
`survey/counterexamples.py`; it needs a GitHub token and takes roughly an hour,
most of it waiting on search rate limits.

`make help` lists the cluster-dependent targets.

## The run data

Everything measured lives under `psao-artifact/data/runs/`, one directory per
run, each with a `run_metadata.json` recording host state, versions and the
artifact's git commit. Fields that could not be determined are `null`, never
guessed.

**Read [`psao-artifact/data/runs/INDEX.md`](psao-artifact/data/runs/INDEX.md)
first.** It lists every run and says plainly what rests on it — including the
runs that failed, were contaminated, or were superseded, each with a marker file
explaining what went wrong. Those are kept on purpose: every one of them
produced a directory that looked finished.

**Every CSV is specified in
[`psao-artifact/docs/DATA_SCHEMA.md`](psao-artifact/docs/DATA_SCHEMA.md)**,
including what an empty cell means (not measured — never zero, never imputed)
and why three adjudication rows carry blank hashes.

The survey corpus itself is third-party source and is **not** redistributed.
`psao-artifact/survey/data/corpus_manifest.csv` stands in for it: repository,
path, git blob hash, SHA-256 of the exact bytes analysed, and verdict, for every
file examined.

## Test certificate

The certificate in `tls-cert/` is expired and its private key is **not** in this
repository. A private key whose modulus matched that certificate was committed in
an early revision and was reachable from the initial commit until it was removed
from history with `git filter-repo`. **Treat that key as compromised and
regenerate rather than reuse it.**

```sh
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
  -keyout tls-cert/tls.key -out tls-cert/tls.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

`subjectAltName` is required: modern clients ignore `CN` for hostname
verification.

## Citation

```bibtex
@misc{sikdar2026artifact,
  author       = {Sikdar, Katha},
  title        = {Replication package: key-resolution cost in token validation},
  year         = {2026},
  howpublished = {\url{https://github.com/Katha-Sikdar/microservices-api}},
  note         = {Measurements under psao-artifact/data/runs/}
}
```

## Licence

MIT. See [`LICENSE`](LICENSE).
