set -eu

if [ ! -f /certs/local.crt ] || [ ! -f /certs/local.key ]; then
  openssl req \
    -x509 \
    -nodes \
    -days 365 \
    -newkey rsa:2048 \
    -keyout /certs/local.key \
    -out /certs/local.crt \
    -subj "/C=KR/ST=Seoul/L=Seoul/O=Moaje/OU=Local/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi
