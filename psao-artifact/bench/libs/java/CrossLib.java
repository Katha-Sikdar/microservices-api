/*
 * CrossLib.java -- HS256 verification in two Java JWT libraries, string secret
 * vs pre-parsed key. Same protocol as bench/keypath-mechanism.js: ONE condition
 * per JVM; the runner interleaves; analysis aggregates across processes.
 *
 *   nimbus_string     SignedJWT.parse(t).verify(new MACVerifier(secretString))
 *                     per call -- MACVerifier(String) is Nimbus's string form
 *   nimbus_preparsed  the same with one MACVerifier(SecretKey) built once
 *   jjwt_string       a parser built ONCE from the only String-accepting form,
 *                     the deprecated setSigningKey(base64String)
 *   jjwt_preparsed    a parser built ONCE with verifyWith(SecretKey)
 *
 * jjwt resolves the key when the parser is built, not per call, and types it
 * (SecretKey vs PublicKey) at compile time, so no string ever reaches a parse.
 *
 * Usage: java -cp 'lib/*:.' CrossLib <condition> <iterations> <warmup> <invocation> <out.csv> <environment>
 */
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jose.crypto.MACVerifier;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;

import javax.crypto.SecretKey;
import java.io.FileWriter;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import java.util.Date;

public class CrossLib {
  interface Body { void run() throws Exception; }

  public static void main(String[] a) throws Exception {
    String cond = a[0];
    int iters = Integer.parseInt(a[1]), warm = Integer.parseInt(a[2]), inv = Integer.parseInt(a[3]);
    String out = a[4], envLabel = a[5];
    final String SECRET = "your-super-secret-key-that-is-long";
    final SecretKey KEY = Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8));
    Date exp = new Date(System.currentTimeMillis() + 86_400_000L);

    SignedJWT s = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256),
        new JWTClaimsSet.Builder().subject("user0").claim("name", "Load User 0").expirationTime(exp).build());
    s.sign(new MACSigner(KEY));
    final String TOKEN = s.serialize();

    Body fn; String lib, ver;
    switch (cond) {
      case "nimbus_string": {
        fn = () -> { if (!SignedJWT.parse(TOKEN).verify(new MACVerifier(SECRET))) throw new IllegalStateException(); };
        lib = "nimbus"; ver = MACVerifier.class.getPackage().getImplementationVersion(); break;
      }
      case "nimbus_preparsed": {
        final MACVerifier v = new MACVerifier(KEY);
        fn = () -> { if (!SignedJWT.parse(TOKEN).verify(v)) throw new IllegalStateException(); };
        lib = "nimbus"; ver = MACVerifier.class.getPackage().getImplementationVersion(); break;
      }
      case "jjwt_string": {
        @SuppressWarnings("deprecation")
        final JwtParser p = Jwts.parser().setSigningKey(
            Base64.getEncoder().encodeToString(SECRET.getBytes(StandardCharsets.UTF_8))).build();
        fn = () -> p.parseSignedClaims(TOKEN).getPayload().getSubject();
        lib = "jjwt"; ver = Jwts.class.getPackage().getImplementationVersion(); break;
      }
      case "jjwt_preparsed": {
        final JwtParser p = Jwts.parser().verifyWith(KEY).build();
        fn = () -> p.parseSignedClaims(TOKEN).getPayload().getSubject();
        lib = "jjwt"; ver = Jwts.class.getPackage().getImplementationVersion(); break;
      }
      default: throw new IllegalArgumentException("unknown condition " + cond);
    }
    if (ver == null) ver = lib.equals("nimbus") ? "10.10" : "0.13.0"; // jar manifest lacks it
    for (int i = 0; i < warm; i++) fn.run();
    double[] t = new double[iters];
    for (int i = 0; i < iters; i++) {
      long t0 = System.nanoTime(); fn.run(); t[i] = (System.nanoTime() - t0) / 1000.0;
    }
    Arrays.sort(t);
    int n = t.length; double sum = 0; for (double x : t) sum += x;
    java.util.function.DoubleUnaryOperator q = p -> t[Math.min(n - 1, (int) (n * p))];
    String header = "environment,language,library,library_version,condition,form,invocation,n,mean_us,median_us,p90_us,p99_us,runtime,crypto_backend,platform";
    String row = String.join(",", envLabel, "Java", lib, ver, cond, cond.substring(cond.indexOf('_') + 1),
        "" + inv, "" + n, String.format("%.4f", sum / n), String.format("%.4f", q.applyAsDouble(0.5)),
        String.format("%.4f", q.applyAsDouble(0.9)), String.format("%.4f", q.applyAsDouble(0.99)),
        "java " + System.getProperty("java.version"), "JCA " + javax.crypto.Mac.getInstance("HmacSHA256").getProvider().getName(),
        System.getProperty("os.name").toLowerCase() + "/" + System.getProperty("os.arch"));
    if (!out.equals("-")) {
      boolean exists = new File(out).exists();
      try (FileWriter w = new FileWriter(out, true)) { if (!exists) w.write(header + "\n"); w.write(row + "\n"); }
    }
    System.out.println(row);
  }
}
