#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "${0%/*}" && pwd)
INFRA_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
CONFIRMED=false
RESTART=false

for argument in "$@"; do
    case "$argument" in
        --yes) CONFIRMED=true ;;
        --restart) RESTART=true ;;
        *) echo "알 수 없는 옵션: $argument" >&2; exit 1 ;;
    esac
done

if [ "$CONFIRMED" != "true" ]; then
    echo "이 명령은 MOAJE 로컬 MySQL, Redis, Kafka 볼륨을 모두 삭제합니다." >&2
    echo "계속하려면 --yes를 함께 사용하세요." >&2
    exit 1
fi

cd "$INFRA_DIR"

echo "로컬 통합 환경과 테스트 데이터를 제거합니다."
docker compose --profile apps --profile test-tools down -v --remove-orphans

if [ "$RESTART" = "true" ]; then
    echo "빈 볼륨으로 통합 환경과 Fixture Console을 다시 시작합니다."
    docker compose --profile apps --profile test-tools up -d
fi

echo "초기화 완료"
