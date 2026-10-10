export LD_LIBRARY_PATH=/opt/openssl35/lib
O=/opt/openssl35/bin/openssl
H=$(ip route | awk '/default/{print $3}')
echo "host=$H"
for g in X25519MLKEM768 X25519; do
echo "=== groups=$g"
echo | $O s_client -connect $H:8443 -servername localhost -CAfile /mnt/d/china_hackathon/tools/tmp/root.crt -groups $g -tls1_3 2>&1 | grep -E "Protocol|Negotiated TLS1.3 group|Verification|alert|Cipher is|error" | head -8
done
