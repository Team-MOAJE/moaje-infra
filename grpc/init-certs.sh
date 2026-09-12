#!/bin/sh
set -eu
umask 077

# 개발용 mTLS 인증서는 실행 때 생성하고 Git에 넣지 않는다. Auth JWT 키와는 완전히 다른 인증서다.
# 두 서비스가 서로 믿는 CA만 공유하며, 각 서비스에는 자신의 개인키만 마운트한다.
if [ -f /certs/asset/asset.crt ] && [ -f /certs/asset/asset.key ] &&
   [ -f /certs/asset/ca.crt ] && [ -f /certs/banking/banking.crt ] &&
   [ -f /certs/banking/banking.key ] && [ -f /certs/banking/ca.crt ]; then
  echo "Existing development gRPC certificates retained."
  exit 0
fi
if [ -f /certs/authority/ca.key ]; then
  echo "Incomplete certificate set. Review existing files; keys will not be overwritten." >&2
  exit 1
fi

mkdir -p /certs/authority /certs/banking /certs/asset
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
  -keyout /certs/authority/ca.key -out /certs/authority/ca.crt \
  -subj /CN=moaje-development-grpc-ca \
  -addext basicConstraints=critical,CA:TRUE \
  -addext keyUsage=critical,keyCertSign,cRLSign

for service in banking asset; do
  openssl req -new -newkey rsa:2048 -nodes \
    -keyout "/certs/$service/$service.key" -out "/certs/authority/$service.csr" \
    -subj "/CN=$service" \
    -addext "subjectAltName=DNS:$service,DNS:localhost" \
    -addext basicConstraints=critical,CA:FALSE \
    -addext keyUsage=critical,digitalSignature,keyEncipherment \
    -addext extendedKeyUsage=serverAuth,clientAuth
  openssl x509 -req -sha256 -days 365 -copy_extensions copy \
    -in "/certs/authority/$service.csr" -out "/certs/$service/$service.crt" \
    -CA /certs/authority/ca.crt -CAkey /certs/authority/ca.key -CAcreateserial
  cp /certs/authority/ca.crt "/certs/$service/ca.crt"
done
echo "Development gRPC certificates created. Rotate before expiry; do not use these in production."
