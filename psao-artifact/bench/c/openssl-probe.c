/*
 * openssl-probe.c -- the discarded asymmetric parse, with Node taken out.
 *
 * Reproduces, call for call, what crypto.createPublicKey(<string>) asks of
 * OpenSSL when the string is an HMAC secret, as read from the Node source
 * (src/crypto/crypto_keys.cc at v18.20.8; deps/ncrypto/ncrypto.cc at v22.23.3,
 * which performs the same sequence):
 *
 *   ParsePublicKeyPEM:  BIO_new_mem_buf, then PEM_bytes_read_bio for
 *                       "PUBLIC KEY", "RSA PUBLIC KEY", "CERTIFICATE", each under
 *                       ERR_set_mark/ERR_pop_to_mark, with BIO_reset between.
 *   ParsePrivateKey:    all three "not recognised" -> BIO_new_mem_buf, then
 *                       PEM_read_bio_PrivateKey(bio, NULL, PasswordCallback, &p),
 *                       then ERR_peek_error.
 *   ThrowCryptoError:   ERR_get_error, ERR_error_string_n into a 128-byte
 *                       buffer, then CryptoErrorStore::Capture, which drains the
 *                       queue with ERR_get_error/ERR_error_string_n (256 bytes).
 *
 * The V8 half of ThrowCryptoError (building the Error object and its
 * properties) is deliberately absent: that is what bench/exception-cost.js
 * measures, and what the decomposition needs kept apart.
 *
 * ONE condition per process, like bench/keypath-mechanism.js; the runner
 * interleaves conditions within rounds and analysis aggregates across
 * processes.
 *
 * Conditions:
 *   full            the whole C-side sequence above       <- what Node asks for
 *   public_tries    ParsePublicKeyPEM only (three PEM header scans)
 *   private_parse   ParsePrivateKey only (PEM_read_bio_PrivateKey + peek)
 *   error_strings   the ThrowCryptoError C-side, on an error queue refilled by
 *                   one PEM_read_bio_PrivateKey outside the timed region
 *   spki_ok         a SUCCESSFUL parse of an RSA-2048 SPKI PEM through the same
 *                   ParsePublicKeyPEM path (probe_succeeds analogue)
 *   timer_overhead  empty body
 *
 * Usage: openssl-probe <condition> <iterations> <warmup> <invocation> <label>
 * Prints one CSV row (header with --header).
 */
#define _POSIX_C_SOURCE 199309L
#include <openssl/bio.h>
#include <openssl/crypto.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rsa.h>
#include <openssl/x509.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static const char HMAC_SECRET[] = "your-super-secret-key-that-is-long";
static char *SPKI_PEM = NULL;
static long SPKI_LEN = 0;
static volatile unsigned long sink = 0;

static int password_cb(char *buf, int size, int rwflag, void *u) {
  (void)buf; (void)size; (void)rwflag; (void)u;
  return -1; /* Node's PasswordCallback with no passphrase */
}

typedef EVP_PKEY *(*der_parser)(const unsigned char **p, long l);
static EVP_PKEY *p_pubkey(const unsigned char **p, long l) { return d2i_PUBKEY(NULL, p, l); }
static EVP_PKEY *p_rsapub(const unsigned char **p, long l) { return d2i_PublicKey(EVP_PKEY_RSA, NULL, p, l); }
static EVP_PKEY *p_x509(const unsigned char **p, long l) {
  X509 *x = d2i_X509(NULL, p, l);
  EVP_PKEY *k = x ? X509_get_pubkey(x) : NULL;
  X509_free(x);
  return k;
}

/* 0 = not recognised, 1 = ok, -1 = failed */
static int try_parse_public(EVP_PKEY **pkey, BIO *bp, const char *name, der_parser parse) {
  unsigned char *der = NULL;
  long der_len = 0;
  ERR_set_mark();
  int r = PEM_bytes_read_bio(&der, &der_len, NULL, name, bp, NULL, NULL);
  ERR_pop_to_mark();
  if (r != 1) return 0;
  const unsigned char *p = der;
  *pkey = parse(&p, der_len);
  OPENSSL_clear_free(der, der_len);
  return *pkey ? 1 : -1;
}

static int parse_public_pem(EVP_PKEY **pkey, const char *pem, int len) {
  BIO *bp = BIO_new_mem_buf(pem, len);
  int r = try_parse_public(pkey, bp, "PUBLIC KEY", p_pubkey);
  if (r == 0) { BIO_reset(bp); r = try_parse_public(pkey, bp, "RSA PUBLIC KEY", p_rsapub); }
  if (r == 0) { BIO_reset(bp); r = try_parse_public(pkey, bp, "CERTIFICATE", p_x509); }
  BIO_free(bp);
  return r;
}

static void parse_private_pem(EVP_PKEY **pkey, const char *pem, int len) {
  BIO *bio = BIO_new_mem_buf(pem, len);
  *pkey = PEM_read_bio_PrivateKey(bio, NULL, password_cb, NULL);
  unsigned long err = ERR_peek_error();
  if (err != 0 && *pkey) { EVP_PKEY_free(*pkey); *pkey = NULL; }
  BIO_free(bio);
}

static void throw_crypto_error_c_side(void) {
  char msg[128] = {0};
  unsigned long err = ERR_get_error();
  ERR_error_string_n(err, msg, sizeof msg);
  sink += (unsigned char)msg[0];
  unsigned long e;
  while ((e = ERR_get_error()) != 0) {
    char buf[256];
    ERR_error_string_n(e, buf, sizeof buf);
    sink += (unsigned char)buf[0];
  }
}

static void c_full(void) {
  EVP_PKEY *pkey = NULL;
  int n = (int)strlen(HMAC_SECRET);
  int r = parse_public_pem(&pkey, HMAC_SECRET, n);
  if (r == 0) parse_private_pem(&pkey, HMAC_SECRET, n);
  if (pkey) { fprintf(stderr, "unexpected: HMAC secret parsed\n"); exit(3); }
  throw_crypto_error_c_side();
}
static void c_public_tries(void) {
  EVP_PKEY *pkey = NULL;
  sink += parse_public_pem(&pkey, HMAC_SECRET, (int)strlen(HMAC_SECRET));
  ERR_clear_error();
}
static void c_private_parse(void) {
  EVP_PKEY *pkey = NULL;
  parse_private_pem(&pkey, HMAC_SECRET, (int)strlen(HMAC_SECRET));
  ERR_clear_error();
}
static void c_spki_ok(void) {
  EVP_PKEY *pkey = NULL;
  int r = parse_public_pem(&pkey, SPKI_PEM, (int)SPKI_LEN);
  if (r != 1) { fprintf(stderr, "unexpected: SPKI did not parse\n"); exit(3); }
  EVP_PKEY_free(pkey);
}
static void c_timer(void) {}

static double now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1e6 + ts.tv_nsec / 1e3;
}
static int cmp(const void *a, const void *b) {
  double x = *(const double *)a, y = *(const double *)b;
  return (x > y) - (x < y);
}

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--header") == 0) {
    puts("environment,condition,invocation,n,mean_us,median_us,p90_us,p99_us,min_us,max_us,"
         "timer_overhead_us,errors_queued,openssl_version,openssl_cflags");
    return 0;
  }
  if (argc != 6) { fprintf(stderr, "usage: %s <condition> <iterations> <warmup> <invocation> <label>\n", argv[0]); return 2; }
  const char *cond = argv[1];
  int iters = atoi(argv[2]), warm = atoi(argv[3]), inv = atoi(argv[4]);
  const char *label = argv[5];

  /* fixture: an RSA-2048 SPKI PEM, generated outside every timed region */
  {
    EVP_PKEY *rsa = EVP_PKEY_Q_keygen(NULL, NULL, "RSA", (size_t)2048);
    BIO *m = BIO_new(BIO_s_mem());
    PEM_write_bio_PUBKEY(m, rsa);
    char *d; SPKI_LEN = BIO_get_mem_data(m, &d);
    SPKI_PEM = malloc(SPKI_LEN); memcpy(SPKI_PEM, d, SPKI_LEN);
    BIO_free(m); EVP_PKEY_free(rsa);
  }

  void (*fn)(void) = NULL;
  int refill = 0;
  if (!strcmp(cond, "full")) fn = c_full;
  else if (!strcmp(cond, "public_tries")) fn = c_public_tries;
  else if (!strcmp(cond, "private_parse")) fn = c_private_parse;
  else if (!strcmp(cond, "error_strings")) { fn = throw_crypto_error_c_side; refill = 1; }
  else if (!strcmp(cond, "spki_ok")) fn = c_spki_ok;
  else if (!strcmp(cond, "timer_overhead")) fn = c_timer;
  else { fprintf(stderr, "unknown condition %s\n", cond); return 2; }

  /* how many errors the failure leaves queued: recorded, not assumed */
  int queued = 0;
  {
    EVP_PKEY *pkey = NULL;
    int n = (int)strlen(HMAC_SECRET);
    if (parse_public_pem(&pkey, HMAC_SECRET, n) == 0) parse_private_pem(&pkey, HMAC_SECRET, n);
    while (ERR_get_error() != 0) queued++;
  }

  EVP_PKEY *tmp = NULL;
  for (int i = 0; i < warm; i++) {
    if (refill) parse_private_pem(&tmp, HMAC_SECRET, (int)strlen(HMAC_SECRET));
    fn();
  }
  double *s = malloc(sizeof(double) * iters);
  for (int i = 0; i < iters; i++) {
    if (refill) parse_private_pem(&tmp, HMAC_SECRET, (int)strlen(HMAC_SECRET));
    double t0 = now_us();
    fn();
    s[i] = now_us() - t0;
  }
  double ov[20000];
  for (int i = 0; i < 20000; i++) { double t0 = now_us(); ov[i] = now_us() - t0; }
  qsort(ov, 20000, sizeof(double), cmp);
  qsort(s, iters, sizeof(double), cmp);
  double mean = 0; for (int i = 0; i < iters; i++) mean += s[i]; mean /= iters;
#define Q(p) s[(int)((iters) * (p)) < iters ? (int)((iters) * (p)) : iters - 1]
  printf("%s,%s,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%d,%s,\"%s\"\n", label, cond, inv, iters,
         mean, Q(0.5), Q(0.9), Q(0.99), s[0], s[iters - 1], ov[10000], queued,
         OpenSSL_version(OPENSSL_VERSION_STRING), OpenSSL_version(OPENSSL_CFLAGS));
  return 0;
}
