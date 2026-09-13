# PSAO — Predictive Security-Aware Offloading of JWT Verification

> **The current work lives in [`psao-artifact/`](psao-artifact/).** Start there.
> It contains the controller, the experiment runners, the analysis pipeline and
> the figure code for *predictive security-aware offloading* (PSAO).
>
> The rest of this repository — `service-a/`, `service-b/`, `kubernetes/`,
> `load-tests/` and `results/` — is the **earlier study** that PSAO builds on.
> See [Relationship to the earlier study](#relationship-to-the-earlier-study).

## What PSAO is

A Node.js service under layered Zero Trust enforcement saturates on **one thread**.
As Edge TLS, Istio mTLS and application-level JWT validation are layered on, the
cost that actually matters is not encryption — it is the per-request work landing
on the **event loop**. Past a threshold, event-loop delay climbs sharply and
latency follows.

PSAO models the service as a single-server queue (**M/M/1** and **M/D/1**), watches
the utilisation ρ = λ/μ against a trigger, and relocates token verification into
the Envoy sidecar *before* the saturation point is reached — then reverts, with
hysteresis and a dwell timer, when load falls back.

Three things make that claim testable rather than rhetorical:

- **Open-loop load.** Arrival rate λ is an independent variable, so there is an
  x-axis to put a queueing model on. A closed-loop generator slows down when the
  service does and can never find a saturation point.
- **The offload must RELOCATE verification, not duplicate it.** Istio writes the
  verified claims into a header and the handler reads them instead of re-running
  `jwt.verify()`. Without that the cost stays on the event loop. This moves the
  trust boundary — read the security notes in the artifact README before citing
  any offload result.
- **HS256 vs RS256 matter differently.** RS256 is the deployable path: the sidecar
  fetches public keys and no secret leaves the issuer. HS256 requires handing the
  shared secret to every sidecar as an inline `oct` JWKS.

## Repository layout

```
microservices-api/
├── psao-artifact/              <-- THE CURRENT WORK
│   ├── controller/             PSAO policy as running code + the Istio objects
│   ├── experiments/            open-loop runners, k6 scripts, posture control
│   ├── instrumentation/        event-loop delay + verification-only histograms
│   ├── scenarios/              S8 token cache, S9 node:cluster, + deploy manifests
│   ├── bench/                  jwt.verify() decomposed into four stages
│   ├── analysis/               queueing fits, tests, LaTeX macro generation
│   ├── figures/                figure code, watermarks synthetic input
│   └── data/                   run output (see its README on what is committed)
│
├── service-a/                  product endpoint; PSAO_AUTH_MODE selects handler
├── service-b/                  review endpoint
├── kubernetes/                 deployment, service, ingress, mTLS manifests
├── load-tests/                 CLOSED-LOOP k6 scripts from the earlier study
├── tls-cert/                   certificate only — see "Test certificate" below
└── results/                    raw logs from the EARLIER study
```

## Relationship to the earlier study

`results/`, `load-tests/` and the root manifests belong to the earlier paper,
*"Quantifying the Performance Cost of API Security in Cloud-Native
Microservices"*, which measured TLS, mTLS and JWT validation with a **closed-loop**
generator (100 VUs, `sleep(1)`, ≈83 rps).

**Those results are kept for provenance and are not the PSAO results.** They are
superseded in three specific ways, each documented with measurements in
`psao-artifact/`:

1. Their reported throughput (≈82.9 rps in every scenario, within 0.2%) is the
   generator's fixed rate, not a property of the service.
2. Their CPU figures come from `kubectl top`, whose ~15 s averaging window and
   millicore rounding are too coarse for a per-step measurement.
3. At ≈83 rps no scenario is near saturation, so they cannot speak to behaviour
   at the elbow — which is the regime PSAO is about.

Do not cite numbers from `results/` as PSAO results.

## Quick start

```sh
git clone https://github.com/Katha-Sikdar/microservices-api.git
cd microservices-api/psao-artifact
make setup
make example-data && make analysis && make figures   # laptop path, no cluster
```

Everything produced by the laptop path is built from clearly-labelled synthetic
data and is watermarked accordingly. See `psao-artifact/README.md` for the
measurement path, which needs a cluster.

## Prerequisites

- Docker Desktop with Kubernetes enabled
- `kubectl`
- Istio **1.28.0** — installed via `istioctl`, not vendored (see below)
- k6
- Node.js ≥ 18
- Python ≥ 3.9 (analysis pipeline)

### Installing Istio

The `istioctl` binary is **not** committed to this repository. Install it pinned
to the version the experiments used:

```sh
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.28.0 sh -
cd istio-1.28.0
export PATH="$PWD/bin:$PATH"
istioctl install --set profile=demo -y
kubectl label namespace default istio-injection=enabled
```

Prometheus is required for the controller:

```sh
kubectl apply -f samples/addons/prometheus.yaml
```

## Test certificate

**The certificate in `tls-cert/` is expired** (`CN=localhost`, valid
2025-11-17 → 2025-12-17), and its private key is not in this repository. Generate
a fresh self-signed pair before running any TLS scenario:

```sh
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
  -keyout tls-cert/tls.key -out tls-cert/tls.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth"
```

`subjectAltName` is required: modern clients ignore `CN` for hostname
verification, so a cert without it fails even though the subject looks right.

Then create the secret the Ingress refers to:

```sh
kubectl create secret tls tls-secret \
  --cert=tls-cert/tls.crt --key=tls-cert/tls.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

`tls.key` is ignored by `.gitignore` (`*.key`). **Do not commit it.** A previous
revision of this repository committed a private key whose modulus matched the
committed certificate; treat any key that was ever pushed as compromised and
regenerate rather than reuse.

## Deploying the services

```sh
kubectl apply -f kubernetes/service-a-deployment.yaml
kubectl apply -f kubernetes/service-a-service.yaml
kubectl apply -f kubernetes/service-b-deployment.yaml
kubectl apply -f kubernetes/service-b-service.yaml
kubectl apply -f kubernetes/ingress.yaml
```

For the mTLS scenarios:

```sh
kubectl apply -f kubernetes/mtls-policy.yaml        # PeerAuthentication STRICT
kubectl apply -f kubernetes/destination-rule.yaml   # ISTIO_MUTUAL
```

There are cluster preconditions that will otherwise cost you a day — the ingress
must be in the mesh, and it needs `service-upstream`. They are documented, with
the symptoms each produces, in `psao-artifact/README.md`.

## Running the experiments

Use the artifact's runners, not the closed-loop scripts in `load-tests/`:

```sh
cd psao-artifact
make tokens                                  # tokens expire; re-mint per session
experiments/run_scenario_ramp.sh --scenario S5
experiments/run_scenario_ramp.sh --scenario S1     # tears down + restores mTLS
experiments/run_scenario_service.sh --scenario S8
make analysis DATA=data/runs/<run dir>
make figures  DATA=data/runs/<run dir>
```

`load-tests/*.js` are the earlier study's closed-loop scripts. They are kept so
that study can be reproduced; they cannot produce a saturation curve.

## Key configuration

- **mTLS:** `kubernetes/mtls-policy.yaml`, `mode: STRICT`
- **JWT algorithm:** HS256 for S4–S5 and S7–S9; RS256 for S6 and the microbenchmark
- **Auth mode:** `PSAO_AUTH_MODE=jwt|none` on `service-a`, resolved at startup, so
  S1–S3 and S4–S9 run on **one image and one digest**
- **Load profile (PSAO):** open-loop constant-arrival-rate steps
- **Load profile (earlier study):** 100 VUs with a 1 s sleep — closed loop

## License

MIT. See `LICENSE`.
