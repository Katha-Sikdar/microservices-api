if (secretOrPublicKey != null && !(secretOrPublicKey instanceof KeyObject)) {
  try {
    secretOrPublicKey = createPublicKey(secretOrPublicKey);
  } catch (_) {
    try {
      secretOrPublicKey = createSecretKey(typeof secretOrPublicKey === 'string' ? Buffer.from(secretOrPublicKey) : secretOrPublicKey);
    } catch (_) {
      return done(new JsonWebTokenError('secretOrPublicKey is not valid key material'))
    }
  }
}
