#!/usr/bin/env bash
# Generates a local CA + a server certificate for the Mav dashboard.
# Adjust SAN if the IP or hostname change.
#
# Variables :
#   MAV_SAN_IP   one or more IPs, comma-separated  (e.g. 192.168.1.10,10.0.0.7)
#   MAV_SAN_DNS  one or more names, comma-separated  (e.g. mav.local,myserver.local)
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$DIR"
cd "$DIR"

SAN_IP="${MAV_SAN_IP:-127.0.0.1}"
SAN_DNS="${MAV_SAN_DNS:-mav.local}"

# Build the subjectAltName list: every entry must carry its type.
# "IP:a,DNS:b,DNS:c", not "IP:a,DNS:b,c" (openssl refuses).
build_san() {
  local out="" item
  IFS=',' read -ra ips <<<"$SAN_IP"
  for item in "${ips[@]}"; do
    item="$(echo "$item" | xargs)"          # trim
    [[ -n "$item" ]] && out="${out:+$out,}IP:$item"
  done
  IFS=',' read -ra dnss <<<"$SAN_DNS"
  for item in "${dnss[@]}"; do
    item="$(echo "$item" | xargs)"
    [[ -n "$item" ]] && out="${out:+$out,}DNS:$item"
  done
  # Toujours joindre localhost : utile pour tester depuis la machine.
  out="${out},IP:127.0.0.1,DNS:localhost"
  echo "$out"
}

SAN="$(build_san)"

# CA
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout ca.key -out ca.crt -subj "/CN=Mav Local CA/O=Mav" 2>/dev/null

# Server certificate (CN = first IP)
CN="$(echo "$SAN_IP" | cut -d',' -f1 | xargs)"
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout server.key -out server.csr -subj "/CN=${CN}/O=Mav" 2>/dev/null

cat > san.cnf <<EOF
subjectAltName=${SAN}
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF

# 397 days: beyond 398, Chrome/Android reject the certificate.
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 397 -sha256 -extfile san.cnf 2>/dev/null

# DER version for Android install (.cer file).
openssl x509 -in ca.crt -outform DER -out ca.cer

chmod 600 ./*.key
echo "Certificates generated in $DIR"
openssl verify -CAfile ca.crt server.crt
