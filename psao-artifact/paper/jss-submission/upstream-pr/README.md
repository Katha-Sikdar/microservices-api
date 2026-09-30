# Update for auth0/node-jsonwebtoken pull request 1047

`0001-fix-detect-a-PEM-header-anywhere-in-the-string-secre.patch` applies on
top of the pull request's head commit `0d88644` (branch on the fork of
GitHub user Hashim1999164). Whoever can push to that branch applies it with:

    git am 0001-fix-detect-a-PEM-header-anywhere-in-the-string-secre.patch
    npm test
    git push

What it changes:

* `verify.js`: `looksLikeAsymmetricKey()` looks for `-----BEGIN` anywhere in
  the string, not only at its start. OpenSSL skips text before a PEM header,
  so with the anchored check a PEM public key preceded by a comment line was
  taken as an HMAC secret, and an HS256 token HMACed with the key text was
  accepted (9.0.3 rejects it with "invalid algorithm").
* `test/issue_1046.tests.js`: regression test for that case.
* `test/verify-keypath.tests.js`: the four key-path tests of the paper.

Checked here with the library's mocha suite (Node 22.22.2, OpenSSL 3.5.5):
pull-request head alone 513 passing; with the new tests but the old
`verify.js`, 1 failing (the regression test); with the patch, 518 passing,
0 failing. `eslint` clean. The paper's 364 equivalence cases give no
difference from 9.0.3 with or without the patch (they do not include a PEM
key preceded by text).
