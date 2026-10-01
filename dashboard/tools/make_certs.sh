#!/usr/bin/env bash
# Génère une CA locale + un certificat serveur pour le dashboard Mav.
# Ajuste SAN si l'IP ou le hostname changent.
#
# Variables :
#   MAV_SAN_IP   une ou plusieurs IP, séparées par des virgules  (ex. 192.168.1.32,10.0.0.7)
#   MAV_SAN_DNS  un ou plusieurs noms, séparés par des virgules  (ex. mav.local,opc.local)
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
mkdir -p "$DIR"
cd "$DIR"

SAN_IP="${MAV_SAN_IP:-192.168.1.32}"
SAN_DNS="${MAV_SAN_DNS:-mav.local,opc.local}"

# Construit la liste subjectAltName : chaque entrée doit porter son type.
# « IP:a,DNS:b,DNS:c » et non « IP:a,DNS:b,c » (openssl refuse).
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

# Certificat serveur (CN = première IP)
CN="$(echo "$SAN_IP" | cut -d',' -f1 | xargs)"
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout server.key -out server.csr -subj "/CN=${CN}/O=Mav" 2>/dev/null

cat > san.cnf <<EOF
subjectAltName=${SAN}
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
EOF

# 397 jours : au-delà de 398, Chrome/Android rejettent le certificat.
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 397 -sha256 -extfile san.cnf 2>/dev/null

# Version DER pour l'installation sur Android (fichier .cer).
openssl x509 -in ca.crt -outform DER -out ca.cer

chmod 600 ./*.key
echo "Certificats générés dans $DIR"
openssl verify -CAfile ca.crt server.crt
