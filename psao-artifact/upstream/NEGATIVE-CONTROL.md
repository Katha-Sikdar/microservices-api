# The three-way run, and why the third arm is the one that matters

`verify-keypath.tests.js` was executed against three builds of
`jsonwebtoken@9.0.3`. Two of those runs confirm the tests are sound. The third
is what makes them evidence.

| build | `verify.js` key resolution | result |
|---|---|---|
| **stock** | released 9.0.3, unmodified | 4 passing, 0 failing |
| **patched** | proposed patch (`upstream/verify.js.patch`) | 4 passing, 0 failing |
| **naive** | dispatch on `header.alg` with no restriction on key material | **3 passing, 1 failing** |

Failing assertion on `naive`:

```
FAIL  refuses an HS* token when the configured key is asymmetric material
      expected it to throw, it did not
```

## What each arm establishes

**stock — the test does not assert something new.** The invariant it checks is
already true of the released library. Had this arm failed, the test would be
describing a bug rather than protecting a property, and the correct response
would have been a security report rather than a performance one. It passed, which
is why this is filed as a performance issue and why the report says plainly that
current behaviour is not vulnerable.

**patched — the change is not a regression.** The proposed patch preserves every
assertion stock satisfies, including the invariant. Without this arm the patch
would be an untested claim about behaviour.

**naive — the test has teeth.** This is the arm that carries the argument. A
regression test that passes on both a broken and a fixed build constrains
nothing: it would pass equally if the property it names had never been
implemented, and it would keep passing if someone later removed it. Running
against a build where the property is genuinely absent is what demonstrates the
assertion is load-bearing rather than decorative.

A test suite that has never been observed to fail is an assumption, not a
control.

## On the deliberately broken build

`naive` is constructed at run time by relaxing one condition in the patched
source, used for a single assertion, and deleted. It is not committed as a
usable artifact and corresponds to no released version. The attack class it
exposes — algorithm confusion, an HS* token validated against asymmetric key
material — has been publicly documented since 2015.

## Why the upstream issue says less than this directory does

The public issue states the constraint at mechanism level: that the
key-type check depends on how asymmetric material is resolved, and that a fix
must not change which inputs reach it. It does not include the naive
construction, the failing arm, or a recipe.

This is deliberate, and the asymmetry is not inconsistency. The two have
different audiences and therefore different standards:

- **The repository** is a research artifact. Its purpose is that a reviewer can
  re-run every claim, including the negative control. Withholding the arm that
  makes the test meaningful would make the evidence unverifiable, which in a
  replication package is the worse failure.
- **The issue** is a public bug report read by people who have no interest in
  reproducing the methodology. There, a step-by-step for breaking a patch that
  does not exist yet is a liability with no compensating benefit. Publishing a
  roadmap to a vulnerability is one way such a vulnerability comes to exist.

The issue offers the maintainers the detail privately, which is the right
channel for the people who actually need it.
