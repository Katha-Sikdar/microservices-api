'use strict';

const jwt = require('../index');
const crypto = require('crypto');
const expect = require('chai').expect;

describe('verify: resolving a string secret for HS* tokens', function () {
  const secret = 'a-shared-secret-of-reasonable-length';
  const secretKeyObject = crypto.createSecretKey(Buffer.from(secret));
  const rsa = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const publicPem = rsa.publicKey.export({ type: 'spki', format: 'pem' });

  function base64url(input) {
    return Buffer.from(input).toString('base64')
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  // Mints an HS256 token keyed on arbitrary material. Used only to assert that
  // such a token is REJECTED when the material is asymmetric.
  function hs256SignedWith(keyMaterial) {
    const header = base64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
    const payload = base64url(JSON.stringify({ sub: 'test' }));
    const signature = crypto.createHmac('sha256', keyMaterial)
      .update(`${header}.${payload}`).digest();
    return `${header}.${payload}.${base64url(signature)}`;
  }

  // INVARIANT — the property the fast path must not disturb.
  //
  // Asymmetric key material is resolved through createPublicKey(), and the
  // resulting KeyObject's `type` is what the algorithm/key-type check relies on
  // to refuse an HS* token. The fast path is restricted to plain string secrets
  // precisely so that PEM and JWK input still reaches that check unchanged.
  // Widening it would route asymmetric material around the check.
  it('refuses an HS* token when the configured key is asymmetric material', function () {
    const token = hs256SignedWith(publicPem);
    expect(function () { jwt.verify(token, publicPem); })
      .to.throw(jwt.JsonWebTokenError);
  });

  it('refuses it with `algorithms` pinned as well', function () {
    const token = hs256SignedWith(publicPem);
    expect(function () { jwt.verify(token, publicPem, { algorithms: ['RS256'] }); })
      .to.throw(jwt.JsonWebTokenError);
  });

  // NO REGRESSION — the fast path must be observationally identical to the
  // slow one for every input that legitimately used it.
  it('verifies a string secret and its KeyObject identically', function () {
    const token = jwt.sign({ sub: 'test' }, secret, { algorithm: 'HS256', expiresIn: '1h' });

    const viaString = jwt.verify(token, secret, { algorithms: ['HS256'] });
    const viaKeyObject = jwt.verify(token, secretKeyObject, { algorithms: ['HS256'] });

    expect(viaString).to.deep.equal(viaKeyObject);
    expect(viaString.sub).to.equal('test');
  });

  it('still rejects a string secret that does not match the signature', function () {
    const token = jwt.sign({ sub: 'test' }, secret, { algorithm: 'HS256' });
    expect(function () { jwt.verify(token, 'a-different-secret', { algorithms: ['HS256'] }); })
      .to.throw(jwt.JsonWebTokenError);
  });
});
