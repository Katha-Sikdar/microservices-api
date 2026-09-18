# The library's own test suite, against three builds

The proposed patch had been validated only against four assertions we wrote
ourselves. That is not sufficient for a change to a dependency of this size, so
the official repository was cloned at the `v9.0.3` tag (commit `ed59e76`),
`npm install` run, and `npx mocha` executed against three builds of `verify.js`.

| variant | passing | pending | failing |
|---|---|---|---|
| stock v9.0.3 | 511 | 1 | 0 |
| **patched (narrow)** | **511** | **1** | **0** |
| naive (material restriction removed) | 509 | 1 | **2** |

Two things follow, and the second was not expected.

**The patch applies cleanly to the release tag and passes the maintainers' own
suite**, with a result identical to unpatched. `git apply --check` succeeds; the
diff is +26/-4 in one file.

**The upstream suite already catches the unsafe variant.** The two failures are
in `test/wrong_alg.tests.js`:

- *should not allow HMAC verification with an RSA key in PEM format*
- *should not verify* (signing with pub key as symmetric)

These tests exist precisely for the property the naive variant breaks. That is
independent confirmation of the security analysis — the maintainers test for it —
and it means **the bespoke regression tests in `upstream/verify-keypath.tests.js`
are redundant**. The honest contribution is not a new test; it is the
observation that an existing test constrains a plausible optimisation, and that
anyone proposing that optimisation will be caught by the suite they are already
required to run.

`verify-keypath.tests.js` is retained as a minimal standalone reproduction that
does not require cloning the library, but the paper no longer claims it as a
contribution.
