// crosslib (Go) -- HS256 verification in golang-jwt/jwt/v5, string secret vs
// pre-converted key. Same protocol as bench/keypath-mechanism.js: ONE condition
// per process; the runner interleaves; analysis aggregates across processes.
//
//   golangjwt_string     keyfunc returns []byte(secretString) -- a conversion
//                        per call, the closest a Go caller gets to "a string"
//   golangjwt_preparsed  keyfunc returns a []byte built once
//
// golang-jwt's SigningMethodHMAC.Verify accepts only []byte and returns
// ErrInvalidKeyType for anything else: it never attempts to parse the key.
package main

import (
	"encoding/csv"
	"flag"
	"fmt"
	"os"
	"runtime"
	"runtime/debug"
	"sort"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func main() {
	cond := flag.String("condition", "", "")
	iters := flag.Int("iterations", 20000, "")
	warm := flag.Int("warmup", 10000, "")
	inv := flag.Int("invocation", 0, "")
	out := flag.String("out", "", "")
	env := flag.String("environment", "host", "")
	flag.Parse()

	secret := "your-super-secret-key-that-is-long"
	pre := []byte(secret)
	tok, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "user0", "name": "Load User 0", "exp": time.Now().Add(24 * time.Hour).Unix(),
	}).SignedString(pre)
	if err != nil {
		panic(err)
	}
	var kf jwt.Keyfunc
	switch *cond {
	case "golangjwt_string":
		kf = func(*jwt.Token) (interface{}, error) { return []byte(secret), nil }
	case "golangjwt_preparsed":
		kf = func(*jwt.Token) (interface{}, error) { return pre, nil }
	default:
		fmt.Fprintln(os.Stderr, "unknown condition", *cond)
		os.Exit(2)
	}
	parser := jwt.NewParser(jwt.WithValidMethods([]string{"HS256"}))
	fn := func() {
		t, err := parser.Parse(tok, kf)
		if err != nil || !t.Valid {
			panic(err)
		}
	}
	for i := 0; i < *warm; i++ {
		fn()
	}
	s := make([]float64, *iters)
	for i := range s {
		t0 := time.Now()
		fn()
		s[i] = float64(time.Since(t0).Nanoseconds()) / 1000
	}
	sort.Float64s(s)
	n := len(s)
	q := func(p float64) float64 { i := int(float64(n) * p); if i >= n { i = n - 1 }; return s[i] }
	sum := 0.0
	for _, v := range s {
		sum += v
	}
	ver := "unknown"
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, d := range bi.Deps {
			if d.Path == "github.com/golang-jwt/jwt/v5" {
				ver = d.Version
			}
		}
	}
	hdr := []string{"environment", "language", "library", "library_version", "condition", "form", "invocation", "n",
		"mean_us", "median_us", "p90_us", "p99_us", "runtime", "crypto_backend", "platform"}
	row := []string{*env, "Go", "golangjwt", ver, *cond, (*cond)[len("golangjwt_"):], fmt.Sprint(*inv), fmt.Sprint(n),
		fmt.Sprintf("%.4f", sum/float64(n)), fmt.Sprintf("%.4f", q(0.5)), fmt.Sprintf("%.4f", q(0.9)), fmt.Sprintf("%.4f", q(0.99)),
		runtime.Version(), "Go crypto/hmac", runtime.GOOS + "/" + runtime.GOARCH}
	if *out != "" {
		_, statErr := os.Stat(*out)
		f, _ := os.OpenFile(*out, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		w := csv.NewWriter(f)
		if statErr != nil {
			w.Write(hdr)
		}
		w.Write(row)
		w.Flush()
		f.Close()
	}
	fmt.Println(row)
}
