<!-- Draft PR body for auth0/node-jsonwebtoken. NOT submitted. See STATUS.md:
     PR #1047 by another account already implements the same narrow form. -->

**Title:** fix(verify): resolve plain HMAC string secrets without a failed `createPublicKey()`

### Description

Fixes #1046. Related: #966.

When `secretOrPublicKey` is not a `KeyObject`, `verify()` calls
`createPublicKey()` first and falls back to `createSecretKey()` in the `catch`.
For an HS* token with an ordinary string secret the first call can never
succeed, so every verification builds and discards an OpenSSL parse failure.
On runtimes bundling OpenSSL 3.0.x (Node 18, 20, 23) that failure costs
several hundred microseconds and is almost the whole `verify()` call; on
OpenSSL 3.5.x it is still the largest single component.

This change resolves the secret directly with `createSecretKey()` **only** when:

- the token declares an `HS*` algorithm, **and**
- the secret is a string that cannot be asymmetric key material: it contains no
  `-----BEGIN` marker and does not start with `{` (JWK).

Everything else — PEM, JWK, Buffers, any non-HS token — takes the existing
path unchanged.

### Why the guard is narrow (security)

The success of `createPublicKey()` on asymmetric material is what produces the
`KeyObject` whose `type` the later algorithm/key-type check relies on. A wider
fast path (e.g. "any string when alg is HS*") lets an RSA public key in PEM be
used as an HMAC secret. That is the classic key-confusion attack (RFC 8725
§2.1), and the existing suite catches it: with the guard removed, two tests in
`test/wrong_alg.tests.js` fail (`should not allow HMAC verification with an RSA
key in PEM format`, and `should not verify` under `signing with pub key as
symmetric`). With the guard, the suite is unchanged.

### Testing

- `npm test` at v9.0.3: 511 passing before, 511 passing after.
- Added `test/verify-keypath.tests.js` (4 tests): plain string secret verifies;
  a PEM public key offered as an HS256 secret is still rejected; a JWK string is
  still routed through `createPublicKey()`; a wrong secret still fails.
  515 passing with the patch.
- `eslint` clean on the changed files.
- Verified on macOS arm64 (Node 26.6.0 / OpenSSL 3.6.x) and Linux x86_64
  (Node 22.22.2 / OpenSSL 3.5.5).

### Performance

Median of per-process medians, HS256 `verify()` with a string secret, before →
after, and with a pre-parsed `KeyObject` for reference: see the tables in
#1046. The workaround for users on released versions remains passing
`crypto.createSecretKey(Buffer.from(secret))`.

### Checklist

- [x] tests added
- [x] no public API change
- [x] key-confusion protection unchanged (existing `wrong_alg` tests pass)
