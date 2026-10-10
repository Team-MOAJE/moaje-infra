#!/bin/sh
set -eu
umask 077

# 개발용 mTLS 인증서는 실행 때 생성하고 Git에 넣지 않는다. Auth JWT 키와는 완전히 다른 인증서다.
# 서비스에는 자신의 개인키만 마운트한다. Work 추가 때문에 기존 CA를 교체하면
# Banking과 Asset의 신뢰 관계가 끊어지므로 CA는 보존하고 없는 서비스만 발급한다.
mkdir -p /certs/authority /certs/banking /certs/asset /certs/work
if [ -f /certs/authority/ca.key ] && [ -f /certs/authority/ca.crt ]; then
  openssl x509 -in /certs/authority/ca.crt -checkend 0 -noout
elif [ -e /certs/authority/ca.key ] || [ -e /certs/authority/ca.crt ]; then
  echo "Incomplete CA. Review existing files; keys will not be overwritten." >&2
  exit 1
else
  for service in banking asset work; do
    if [ -e "/certs/$service/$service.key" ] || [ -e "/certs/$service/$service.crt" ]; then
      echo "Service certificates exist without their CA. Restore the CA before continuing." >&2
      exit 1
    fi
  done

  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 365 \
  -keyout /certs/authority/ca.key -out /certs/authority/ca.crt \
  -subj /CN=moaje-development-grpc-ca \
  -addext basicConstraints=critical,CA:TRUE \
  -addext keyUsage=critical,keyCertSign,cRLSign
fi

for service in banking asset work; do
  if [ -f "/certs/$service/$service.crt" ] && [ -f "/certs/$service/$service.key" ] &&
     [ -f "/certs/$service/ca.crt" ]; then
    openssl verify -CAfile /certs/authority/ca.crt "/certs/$service/$service.crt"
    echo "Existing $service certificate retained."
    continue
  fi
  if [ -e "/certs/$service/$service.crt" ] || [ -e "/certs/$service/$service.key" ] ||
     [ -e "/certs/$service/ca.crt" ]; then
    echo "Incomplete $service certificate set. Review files; keys will not be overwritten." >&2
    exit 1
  fi
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
