# Upstream status (revision item 12)

Checked 2026-09-24 from the public GitHub pages. Nothing below was posted from
the revision environment; everything outward-facing is left to the authors.

## Prior reports (search done first, as item 12 asks)

| | |
|---|---|
| **auth0/node-jsonwebtoken#966** | "What happened? The performance of jsonwebtoken 9.0.2 is 50 times slower than 8.5.1". Opened 2024-04-11 by `VxRain`. Node v20.12.2, Windows 11, AMD Ryzen 7 5800H. HS256 sign 53x slower, verify 34x slower (87,990 -> 2,568 ops/s). **Open, no root cause identified, no maintainer response visible.** |

#966 is the same defect observed from the outside. Node 20 bundles OpenSSL
3.0.x, which is exactly the regime in which the discarded parse dominates
(Table 2, and the C probe of the revision). Our issue explains #966; #966 is
independent, two-year-old evidence that users hit this in practice. The paper
should cite it, and #1046 should link it (draft comment below).

Other searches ("createPublicKey", "performance", "slow verify", "HS256") in
the issue tracker returned no other report of this mechanism.

## Our report

| | |
|---|---|
| **auth0/node-jsonwebtoken#1046** | Filed 2026-09-17 by `Katha-Sikdar` (text: `jsonwebtoken-issue.md`). **Open, 0 comments, no labels.** |
| **auth0/node-jsonwebtoken#1047** | "Skip failed public key parse for HMAC string secrets". Opened 2026-09-18 by **`Hashim1999164`**, references #1046. Open, no review. Its CI reports 513 passing, 1 pending. It guards on PEM, SSH and JWK formatting, i.e. the same narrow shape as `verify.js.patch`. |

**Authorship of #1047 is unresolved and must be settled by the authors before
the paper describes it.** If `Hashim1999164` is not a collaborator, the paper
must not call #1047 "our PR"; the text in the manuscript says only that a pull
request implementing the narrow form is open.

## Re-verification on a second architecture

`data/runs/2026-09-24-upstream-suite-x86_64/` re-runs the library's own suite
at v9.0.3 on x86_64 (Node 22.22.2, OpenSSL 3.5.5): 511 passing stock, 511 with
`verify.js.patch`, 515 with the patch plus `verify-keypath.tests.js`; the
unrestricted form fails 2 of the stock tests:

- `when verifying a malicious token` -> `should not allow HMAC verification with an RSA key in PEM format`
- `when setting a wrong header.alg` -> `should not verify` (the `signing with pub key as symmetric` case)

`verify-keypath.tests.js` was changed only to satisfy the repository's eslint
rule `no-div-regex` (`/=+$/` -> `/[=]+$/`); it now lints clean.

## To do (authors)

1. Post the comment below on #966 (it links the two reports).
2. Either review/adopt #1047, or open a PR from an author account using
   `PULL_REQUEST.md` as the body. Do not open a duplicate of #1047 without
   first commenting there.
3. Update the sentence in Section "A fix, and a constraint on it" with the
   status at submission (the manuscript carries it as a macro-free sentence
   marked `% STATUS-AT-SUBMISSION`).

### Draft comment for #966

> This looks like the mechanism reported in #1046. In 9.x, `verify()` resolves
> a string secret by calling `crypto.createPublicKey()` first and falling back
> to `createSecretKey()` only after it throws. On Node 20 (OpenSSL 3.0.x) that
> failed parse costs several hundred microseconds per call, which is consistent
> with the 34x verify slowdown here. Passing `crypto.createSecretKey(Buffer.from(secret))`
> instead of the string avoids it today.
