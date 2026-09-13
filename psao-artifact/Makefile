# Makefile -- PSAO reproducibility artifact.
#
# The laptop path (no cluster needed):
#     make setup && make example-data && make analysis && make figures
#
# The measurement path (needs a Kubernetes cluster with Istio, and k6):
#     make ramp                 # open-loop ramp -> the elbow figure's input
#     make controller-experiment
#     make microbench
#     make analysis DATA=data/runs/<timestamp>-.../
#
# DATA selects which directory the analysis and figures read. It defaults to the
# SYNTHETIC example data, which produces watermarked figures and \SYNTHVAL-wrapped
# LaTeX macros. Point it at a real run directory to produce publishable output.

DATA        ?= data/example
FIGDIR      ?= figures/output
ANALYSISDIR ?= analysis/output
MACROS      ?= paper/generated_macros.tex

PYTHON      ?= python3
VENV        ?= .venv
VENV_PY     := $(VENV)/bin/python
VENV_PIP    := $(VENV)/bin/pip

# Use the virtualenv interpreter once it exists, otherwise fall back to the
# system one so that a checkout without `make setup` still does something useful.
PY := $(shell [ -x "$(VENV_PY)" ] && echo "$(VENV_PY)" || echo "$(PYTHON)")

# Scenario runner defaults. Override on the command line, e.g.
#     make ramp SCENARIO=S3 MAX_RPS=600
SCENARIO    ?= S5
ENVIRONMENT ?= local
MAX_RPS     ?= 400
STEP_RPS    ?= 20
STEP_DUR    ?= 30s
ITERATIONS  ?= 1000000

.PHONY: setup example-data analysis figures all microbench ramp \
        controller-experiment controller-dry-run scenario-s8 scenario-s9 \
        tokens posture-s1 posture-full posture-verify offload-safety \
        clean clean-figures help

help:
	@echo "PSAO artifact targets (DATA=$(DATA)):"
	@echo "  setup                 create $(VENV) and install Python + Node dependencies"
	@echo "  example-data          regenerate the SYNTHETIC example data in data/example"
	@echo "  analysis              fits, tests, amortised CPU, and $(MACROS)"
	@echo "  figures               render all seven figures into $(FIGDIR)"
	@echo "  all                   example-data + analysis + figures"
	@echo "  microbench            run the JWT stage microbenchmark (no cluster needed)"
	@echo "  ramp                  open-loop arrival-rate ramp (needs cluster + k6)"
	@echo "  controller-experiment run PSAO against the cluster under load"
	@echo "  controller-dry-run    replay the example trace through the controller"
	@echo "  scenario-s8 / -s9     start the token-cache / cluster-mode services"
	@echo "  tokens                re-mint tokens/ (they expire; do this before a session)"
	@echo "  posture-s1            tear the mesh down to the S1 plain-HTTP baseline"
	@echo "  posture-full          restore mTLS + edge TLS, and VERIFY enforcement"
	@echo "  posture-verify        verify mTLS enforcement without changing anything"
	@echo "  offload-safety        regression-test the offload trust boundary"
	@echo "  clean                 remove generated output (never removes data/runs)"

# ---------------------------------------------------------------------------

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	@command -v npm >/dev/null 2>&1 && npm install || \
		echo "npm not found: skipping Node dependencies (needed only for the services and microbench)"
	@command -v npm >/dev/null 2>&1 && (cd bench && npm install) || true
	@echo ""
	@echo "setup complete. Activate with:  . $(VENV)/bin/activate"

example-data:
	$(PY) data/make_example_data.py --out data/example

analysis:
	$(PY) -m analysis.run_all --data $(DATA) --out $(ANALYSISDIR) --macros $(MACROS)

figures:
	$(PY) figures/make_all.py --data $(DATA) --out $(FIGDIR)

all: example-data analysis figures
	@echo ""
	@echo "Built from $(DATA)."
	@echo "If that directory is the synthetic example data, every figure in $(FIGDIR)"
	@echo "is watermarked and every macro in $(MACROS) is wrapped in \\SYNTHVAL."

# ---------------------------------------------------------------------------
# Measurement targets
# ---------------------------------------------------------------------------

# Tokens expire. An expired pool does not fail loudly -- the service answers 403
# to everything and the ramp yields a plausible curve for an error path.
TOKEN_COUNT ?= 64
TOKEN_TTL   ?= 24h

# Two pools. The plain one is what S1..S9 use: service-a verifies the signature
# and ignores iss/aud. The controller one additionally carries the issuer and
# audience the Istio RequestAuthentication demands -- without them, every request
# is rejected by the sidecar the moment the offload actuates.
PSAO_ISSUER   ?= https://psao.example/issuer
PSAO_AUDIENCE ?= psao-testbed

tokens:
	node experiments/mint_tokens.js --count $(TOKEN_COUNT) --ttl $(TOKEN_TTL)
	node experiments/mint_tokens.js --count $(TOKEN_COUNT) --ttl $(TOKEN_TTL) \
		--issuer "$(PSAO_ISSUER)" --audience "$(PSAO_AUDIENCE)" --kid psao-hs256 \
		--out-dir tokens/controller

# Mesh posture. posture-full does NOT accept a 200 from the ingress as proof of
# restoration: it checks PeerAuthentication STRICT, the ISTIO_MUTUAL
# DestinationRule, and a negative control (plaintext from an un-injected pod
# must be refused). It exits non-zero if any of the three fails.
posture-s1:
	experiments/set_mesh_posture.sh --posture s1

posture-full:
	experiments/set_mesh_posture.sh --posture full

posture-verify:
	experiments/set_mesh_posture.sh --verify

# The offload makes service-a trust x-psao-jwt-payload. This checks that a client
# cannot set it. It was a real bypass before
# controller/strip-untrusted-payload-header.yaml existed; run it after any change
# to the handler, the policy template, the EnvoyFilter or the mesh posture.
offload-safety:
	experiments/verify_offload_safety.sh

microbench:
	node bench/jwt-path-microbench.js --iterations $(ITERATIONS)

ramp:
	experiments/run_openloop_ramp.sh --scenario $(SCENARIO) \
		--environment $(ENVIRONMENT) --max-rps $(MAX_RPS) \
		--step-rps $(STEP_RPS) --step-duration $(STEP_DUR)

controller-experiment:
	experiments/run_controller_experiment.sh --scenario $(SCENARIO) \
		--environment $(ENVIRONMENT) --max-rps $(MAX_RPS) \
		--step-rps $(STEP_RPS) --step-duration $(STEP_DUR)

# Offline check that the policy, hysteresis and trace writing all work. Touches
# no cluster; see README for what its actuation latencies do and do not mean.
controller-dry-run:
	$(PY) controller/psao_controller.py --config controller/config.yaml \
		--dry-run --replay $(DATA)/controller_trace.csv \
		--out $(ANALYSISDIR)/controller_dry_run_trace.csv

scenario-s8:
	node scenarios/s8-token-cache.js

scenario-s9:
	node scenarios/s9-cluster-mode.js

# ---------------------------------------------------------------------------

clean-figures:
	rm -rf $(FIGDIR)

# Deliberately does NOT touch data/runs/: those are measurements, and a `clean`
# that deletes an experiment you cannot cheaply repeat is a trap.
clean: clean-figures
	rm -rf $(ANALYSISDIR) $(MACROS)
	rm -rf __pycache__ analysis/__pycache__ figures/__pycache__
	rm -rf .pytest_cache
	@echo "removed generated output. data/runs/ and data/example/ are untouched."
