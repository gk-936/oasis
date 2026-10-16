package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"net/http"
	"os"
	"time"
)

// Same TLS policy as tools/caddy/Caddyfile: TLS 1.3 only, ONLY the hybrid X25519MLKEM768 group.
func main() {
	k, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	t := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "localhost"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(24 * time.Hour),
		DNSNames: []string{"localhost"}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")},
		KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		BasicConstraintsValid: true, IsCA: true}
	der, _ := x509.CreateCertificate(rand.Reader, t, t, &k.PublicKey, k)
	os.WriteFile("cert.pem", pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0o644)
	cfg := &tls.Config{MinVersion: tls.VersionTLS13, CurvePreferences: []tls.CurveID{tls.X25519MLKEM768},
		Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: k}}}
	ln, err := tls.Listen("tcp", "127.0.0.1:8444", cfg)
	if err != nil { panic(err) }
	http.Serve(ln, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) }))
}
