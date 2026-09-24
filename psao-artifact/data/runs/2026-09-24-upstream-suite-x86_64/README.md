# Upstream suite re-run, x86_64 (revision item 12)

jsonwebtoken at tag v9.0.3 (commit ed59e76ea37a80f54b833668c02a5271984dcba3),
`npx mocha`, Node v22.22.2 / OpenSSL 3.5.5, x86_64,
run 2026-09-24T17:10Z. Reproduces 2026-09-18T-upstream-suite on a second
architecture.

| file | library | extra tests | result |
|---|---|---|---|
| stock.txt | unmodified | none | 511 passing (441ms) |
| stock_plus_keypath_tests.txt | unmodified | upstream/verify-keypath.tests.js | 515 passing (467ms) |
| narrow.txt | upstream/verify.js.patch | none | 511 passing (461ms) |
| narrow_plus_keypath_tests.txt | upstream/verify.js.patch | upstream/verify-keypath.tests.js | 515 passing (442ms) |
| unrestricted.txt | patch with the isPlainStringSecret guard removed | none | 509 passing (461ms) 2 failing |
| unrestricted_plus_keypath_tests.txt | same | upstream/verify-keypath.tests.js | 512 passing (462ms) 3 failing |

The two stock-suite failures under the unrestricted form are the suite's own
key-confusion tests ("when verifying a malicious token", "when setting a wrong
`header.alg`"). The narrow patch's verify.js sha256 is
27ae78cdda0f42b98632c762c7fc679a1868b2f294aef259cbee68426ae772b1.
