Thanks for the fix. One gap: `looksLikeAsymmetricKey()` only matches `-----BEGIN` at the start of the string, but OpenSSL skips any text before a PEM header. So a PEM public key preceded by, for example, a comment line now takes the secret-first path, and an HS256 token HMACed with the key text is accepted when `algorithms` is not set. 9.0.3 rejects the same token with "invalid algorithm".

Minimal repro:

```js
const crypto = require('crypto');
const jwt = require('jsonwebtoken');
const { publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const key = 'public key for service X\n' + publicKey.export({ type: 'spki', format: 'pem' });
const b64u = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
const data = `${b64u({ alg: 'HS256', typ: 'JWT' })}.${b64u({ sub: 'attacker' })}`;
const token = `${data}.${crypto.createHmac('sha256', key).update(data).digest('base64url')}`;
jwt.verify(token, key); // this PR: accepted; 9.0.3: throws "invalid algorithm"
```

Searching for the header anywhere in the string closes it:

```diff
 function looksLikeAsymmetricKey(key) {
   if (typeof key !== 'string') {
     return true;
   }
-  return /^\s*(-----BEGIN |ssh-|\{)/.test(key);
+  return key.indexOf('-----BEGIN') !== -1 || /^\s*(ssh-|\{)/.test(key);
 }
```

I have a patch on top of 0d88644 with that change, a regression test for the case above, and four key-path tests (an HS* token is refused when the configured key is asymmetric material, with and without `algorithms`; a string secret and its KeyObject verify identically; a wrong string secret is still rejected). With it the suite passes 518/0; without the `verify.js` change the new regression test fails. Happy to share it or push it wherever is convenient.
