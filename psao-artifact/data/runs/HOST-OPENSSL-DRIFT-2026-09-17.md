# The host's OpenSSL changed mid-session, under an unchanged Node binary

**2026-09-17 16:02 local.** Installing the Oracle CLI (`brew install oci-cli`)
upgraded Homebrew's `openssl@3` formula from 3.6.3 to 3.6.4. Homebrew's Node
links OpenSSL *dynamically*:

    $ otool -L /opt/homebrew/Cellar/node/26.6.0/bin/node | grep ssl
        /opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib
        /opt/homebrew/opt/openssl@3/lib/libssl.3.dylib

    $ ls -la /opt/homebrew/opt/openssl@3
    ... Sep 17 16:02 /opt/homebrew/opt/openssl@3 -> ../Cellar/openssl@3/3.6.4

So `node --version` still reports v26.6.0 from the same binary installed on
5 August, while `process.versions.openssl` went 3.6.3 -> 3.6.4.

## What is and is not affected

| | |
|---|---|
| `2026-09-17T08-42-17Z-keypath-mechanism` (host) | **Unaffected.** Ran before 16:02 and recorded `openssl_version 3.6.3` on every row. |
| `2026-09-17T08-57-13Z-keypath-runtime-matrix` (containers) | **Unaffected.** Container images bundle their own OpenSSL; the host's is not on the path. |
| Any NEW host measurement | On 3.6.4. Not directly comparable to the Phase 1 host rows without saying so. |

Observed difference, same repro: `createPublicKey` probe 18.04 us on 3.6.3
(Phase 1, 15 invocations, CI [17.83, 18.25]) against 17.60 us on 3.6.4 (single
informal run). Small, and not established as a real difference -- one
unreplicated number against an interval is not a comparison.

## Why this is recorded rather than ignored

Two reasons.

1. **It was only detectable because the harness records
   `process.versions.openssl` per row.** Had it recorded only the Node version,
   this would have been an invisible change to the exact library the finding is
   about, on the exact machine producing the numbers. That column stays.

2. **It is a small instance of the paper's own claim.** The cost under
   investigation is governed by the bundled OpenSSL version, and here that
   version moved on an unchanged runtime, on one machine, as a side effect of
   installing an unrelated CLI tool. "The host" is not a stable baseline unless
   the crypto library is pinned and checked, which is exactly the trap that
   makes `node:18-alpine` and `node:26-alpine` differ by 25x.

## Consequence for future runs

Host rows must carry their OpenSSL version and must not be pooled across it.
`analysis/keypath_stats.py` groups on `environment`, which does NOT distinguish
3.6.3 from 3.6.4 -- both are labelled `host`. If a further host run is made,
label it distinctly (e.g. `host-openssl3.6.4`) rather than appending to `host`.

## Mitigation

`brew pin openssl@3` applied 2026-09-17, after the drift. This prevents
`brew upgrade` from moving the formula again. It does **not** revert the linked
version: the host stays on 3.6.4, and the Phase 1 rows on 3.6.3 remain the only
measurements taken against that version.

The pin is a backstop, not a guarantee. A formula requiring a newer OpenSSL will
still force an upgrade, and the pin can be lifted with one command. The rule
that matters is still the one above: do not install unrelated software on the
measurement host while a study is in progress.
