"""crosslib.py -- HS256 verification in PyJWT, string secret vs pre-parsed key.

Same protocol as bench/keypath-mechanism.js: ONE condition per process; the
runner interleaves; analysis aggregates across processes.

  pyjwt_string     jwt.decode(token, 'secret', algorithms=['HS256'])
  pyjwt_preparsed  jwt.decode(token, PyJWK(oct JWK, 'HS256'), algorithms=['HS256'])
                   -- PyJWK is PyJWT's key object, built once. PyJWT still
                   calls HMACAlgorithm.prepare_key on it per call; there is no
                   form that skips that step, so the two conditions differ only
                   by str->bytes coercion and the PEM/SSH text check.

Usage: python crosslib.py --condition pyjwt_string [--iterations N] [--warmup N]
       [--invocation i] [--out file.csv] [--environment label]
"""
import argparse, base64, csv, os, platform, ssl, statistics, sys, time

import jwt
from jwt import PyJWK

ap = argparse.ArgumentParser()
ap.add_argument("--condition", required=True)
ap.add_argument("--iterations", type=int, default=20000)
ap.add_argument("--warmup", type=int, default=10000)
ap.add_argument("--invocation", type=int, default=0)
ap.add_argument("--out")
ap.add_argument("--environment", default="host")
a = ap.parse_args()

SECRET = "your-super-secret-key-that-is-long"
TOKEN = jwt.encode({"sub": "user0", "name": "Load User 0", "exp": int(time.time()) + 86400},
                   SECRET, algorithm="HS256")
if a.condition == "pyjwt_string":
    key = SECRET
elif a.condition == "pyjwt_preparsed":
    k = base64.urlsafe_b64encode(SECRET.encode()).rstrip(b"=").decode()
    key = PyJWK({"kty": "oct", "k": k, "alg": "HS256"})
else:
    sys.exit(f"unknown condition {a.condition}")

fn = lambda: jwt.decode(TOKEN, key, algorithms=["HS256"])
assert fn()["sub"] == "user0"
for _ in range(a.warmup):
    fn()
pc = time.perf_counter_ns
s = [0.0] * a.iterations
for i in range(a.iterations):
    t0 = pc(); fn(); s[i] = (pc() - t0) / 1000.0
s.sort()
n = len(s)
q = lambda p: s[min(n - 1, int(n * p))]
row = {
    "environment": a.environment, "language": "Python", "library": "pyjwt",
    "library_version": jwt.__version__, "condition": a.condition, "form": a.condition.split("_")[1],
    "invocation": a.invocation, "n": n, "mean_us": f"{sum(s)/n:.4f}", "median_us": f"{q(0.5):.4f}",
    "p90_us": f"{q(0.9):.4f}", "p99_us": f"{q(0.99):.4f}",
    "runtime": f"cpython {platform.python_version()}", "crypto_backend": "hashlib/hmac " + ssl.OPENSSL_VERSION.replace(",", ""),
    "platform": f"{sys.platform}/{platform.machine()}",
}
if a.out:
    new = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row)); new and w.writeheader(); w.writerow(row)
print(",".join(str(v) for v in row.values()))
