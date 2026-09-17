# Running the key-path matrix on Oracle Cloud

Everything measured so far is one machine: Apple silicon, arm64, Docker Desktop.
The central finding — that a per-request `createPublicKey()` probe costs ~400 us
under OpenSSL 3.0 and ~20 us under OpenSSL 3.5 — is either a property of the
library or a property of that laptop, and only a second machine can tell the
difference.

These scripts do not need Kubernetes, Istio or k6. They need a Linux box you can
ssh into.

## What to provision

Oracle's Always Free tier offers two shape families, and **both are worth having
for different reasons**. Check current quotas in your own tenancy rather than
trusting this table — they change, and Ampere capacity is frequently exhausted
in popular regions (you will see an out-of-capacity error; try another
availability domain or region).

| Shape | Arch | Why it matters here |
|---|---|---|
| `VM.Standard.A1.Flex` (Ampere) | **aarch64** | Same ISA as the laptop, *different* hypervisor and OS. Isolates "Apple Virtualization on macOS" from "arm64 Linux". Generous enough (up to 4 OCPU / 24 GB, splittable across up to 4 VMs) to also host Phase 3. |
| `VM.Standard.E2.1.Micro` (AMD) | **x86_64** | The only free x86_64. Small (1 GB) and shared, so treat its absolute numbers with care — but it answers whether the OpenSSL 3.0 penalty is architecture-specific, which is the question that matters most. |

For this phase, **one instance of each** is enough. Either Oracle Linux or
Ubuntu works; `bootstrap.sh` handles both.

Networking: the instance needs inbound TCP 22 from your address. That is a
security-list (or NSG) rule on the VCN subnet, not just the OS firewall — a
common first-time snag is a correct `sshd` behind a subnet that never allowed
the packet.

## These are VMs, not bare metal

Free-tier instances are guests on shared hardware. That is **not** a flaw for
this experiment — the point is a second, independent virtualisation stack (Oracle's
KVM rather than Apple's Virtualization framework), not an absence of one. Do not
claim bare metal in the paper.

What it does mean is that **CPU steal has to be reported**. Steal is time the
hypervisor gave to another tenant while our vCPU was runnable; it inflates every
duration and is invisible to the process's own clock. `capture_env.sh` reads it
from `/proc/stat`, the remote driver brackets every run with a 60 s window
before and after, and the orchestrator prints a warning above 1%. A run with
high steal is an upper bound, and must be described as one.

## Workflow

From the laptop, in `psao-artifact/`:

```sh
# 1. Install docker + node 18/20/26 on the instance (several minutes).
#    Reconnect afterwards: docker group membership needs a fresh login.
experiments/run_keypath_remote.sh --host opc@<ip> --label oracle-a1 \
    --key ~/.ssh/oracle --bootstrap --mode native

# 2. The full matrix, native and container.
experiments/run_keypath_remote.sh --host opc@<ip> --label oracle-a1 \
    --key ~/.ssh/oracle --rounds 10

# 3. Same again on the x86_64 instance.
experiments/run_keypath_remote.sh --host opc@<ip2> --label oracle-e2 \
    --key ~/.ssh/oracle --bootstrap --rounds 10

# 4. Analyse. Concatenate with the laptop runs to get one table.
python3 -m analysis.keypath_stats --run data/runs/<...>-keypath-remote-oracle-a1
```

Results land in a local `data/runs/<timestamp>-keypath-remote-<label>/`, which
is what you then commit with `git add -f`.

## Scripts

| Script | Runs on | Does |
|---|---|---|
| `bootstrap.sh` | instance | Installs Docker and nvm with Node 18.20.8 / 20.20.2 / 26.6.0. Idempotent. |
| `capture_env.sh` | instance | Emits JSON: Oracle shape/region/OCPUs from the instance metadata service, CPU model, hypervisor, kernel, and **steal**. Undetermined fields are `null`, never guessed. Safe to run anywhere. |
| `run_matrix_remote.sh` | instance | The matrix itself, native and container families, brackets the run with steal capture. Self-contained — does not need the repo or a cluster. |
| `../run_keypath_remote.sh` | **laptop** | Ships the harness, runs the above over ssh, retrieves results, writes provenance. |

## Two design choices worth knowing

**Environment labels are prefixed.** Every row is `<label>:<runtime>`, e.g.
`oracle-a1:node:18.20.8-alpine` or `oracle-e2:native-v20.20.2`. Rows from two
machines can therefore be concatenated into one CSV without colliding, and
`analysis/keypath_stats.py` will never pool them.

**Provenance comes from the instance, not from here.** `run_keypath_remote.sh`
deliberately does not call `psao::write_metadata`: that helper records the
*local* cluster, Istio version and `node --version`. Recording local state for a
measurement taken elsewhere is exactly the mistake that put "Node.js is v26.6.0"
into the manuscript for a service running v18.20.8. The authoritative record is
`instance_env_before.json` / `instance_env_after.json`.

## Node versions are not arbitrary

`NODE_VERSIONS="18.20.8 20.20.2 26.6.0"` in `bootstrap.sh` is load-bearing.
18.20.8 bundles OpenSSL 3.0.16 and V8 10.2; 20.20.2 bundles OpenSSL 3.0.19 and
V8 11.3; 26.6.0 bundles OpenSSL 3.5.7. The pair at 18 and 20 is what separates
OpenSSL from V8 — two different V8 majors sharing the OpenSSL 3.0 series. Drop
Node 20 and the attribution collapses back to "the runtime", which is what the
laptop matrix could say before that cell existed.

## Later: Phase 3

The A1 allocation splits into two VMs (2 OCPU each). Putting the service on one
and k6 on the other removes the load generator from the machine under test,
which deletes the contention paragraph from the manuscript's threats section and
turns "conservative under contention" into "measured". That needs the cluster
and is out of scope for these scripts.
