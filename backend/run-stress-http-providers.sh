#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./backend/run-stress-http-providers.sh [options]

Run loopback fake LLM and embedding services for local HTTP pool stress tests.
The embedding service reads its vector bank once from the isolated stress DB.

Options:
  --llm-port PORT         Fake LLM port (default: 8111)
  --embedding-port PORT   Fake embedding port (default: 8112)
  --postgres-port PORT    Isolated stress PostgreSQL host port (default: 5433)
  --postgres-db NAME      Isolated stress database (default: worker_ab_stress)
  --tls-dir DIR           Serve HTTPS using retained local CA/server material in DIR
  -h, --help              Show this help and exit
  --version               Show version and exit

Secrets are loaded from the repository .env file and are never accepted as flags.

Examples:
  ./backend/run-stress-http-providers.sh --postgres-port 5433 \
    --postgres-db worker_ab_stress
  ./backend/run-stress-http-providers.sh --tls-dir lode/tmp/worker-ab/tls \
    --postgres-port 5433 --postgres-db worker_ab_stress
EOF
}

is_port() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]] && ((10#$1 <= 65535))
}

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
llm_port="${STRESS_FAKE_LLM_PORT:-8111}"
embedding_port="${STRESS_FAKE_EMBEDDING_PORT:-8112}"
postgres_port="${STRESS_POSTGRES_PORT:-5433}"
postgres_db="${STRESS_POSTGRES_DB:-worker_ab_stress}"
tls_dir=""

while (($#)); do
  case "$1" in
    --llm-port|--embedding-port|--postgres-port|--postgres-db|--tls-dir)
      if (($# < 2)); then
        echo "error: $1 requires a value" >&2
        usage >&2
        exit 2
      fi
      case "$1" in
        --llm-port) llm_port="$2" ;;
        --embedding-port) embedding_port="$2" ;;
        --postgres-port) postgres_port="$2" ;;
        --postgres-db) postgres_db="$2" ;;
        --tls-dir) tls_dir="$2" ;;
      esac
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --version)
      echo "stress-http-providers 0.2"
      exit 0
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for value in "$llm_port" "$embedding_port" "$postgres_port"; do
  if ! is_port "$value"; then
    echo "error: ports must be integers between 1 and 65535" >&2
    exit 2
  fi
done
if [[ "$llm_port" == "$embedding_port" ]]; then
  echo "error: LLM and embedding ports must differ" >&2
  exit 2
fi
if [[ "$postgres_db" != *stress* ]]; then
  echo "error: --postgres-db must identify an isolated stress database" >&2
  exit 2
fi
for port in "$llm_port" "$embedding_port"; do
  if ss -ltn "( sport = :$port )" | tail -n +2 | grep -q .; then
    echo "error: loopback provider port $port is already in use" >&2
    exit 1
  fi
done

scheme=http
tls_args=()
if [[ -n "$tls_dir" ]]; then
  command -v openssl >/dev/null || { echo "error: openssl is required for --tls-dir" >&2; exit 1; }
  tls_dir="$(realpath -m "$tls_dir")"
  if [[ "$tls_dir/" != "$root/lode/tmp/"* ]]; then
    echo "error: --tls-dir must be inside the ignored lode/tmp directory" >&2
    exit 2
  fi
  mkdir -p "$tls_dir"
  chmod 700 "$tls_dir"
  ca_cert="$tls_dir/ca.pem"
  ca_key="$tls_dir/ca-key.pem"
  server_cert="$tls_dir/server.pem"
  server_key="$tls_dir/server-key.pem"
  server_csr="$tls_dir/server.csr"
  ca_serial="$tls_dir/ca.srl"
  tls_files=("$ca_cert" "$ca_key" "$server_cert" "$server_key" "$server_csr" "$ca_serial")
  existing_tls_files=0
  for tls_file in "${tls_files[@]}"; do
    [[ -e "$tls_file" ]] && existing_tls_files=$((existing_tls_files + 1))
  done
  if ((existing_tls_files == 0)); then
    openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 30 \
      -subj '/CN=Demo VA Stress Local CA' \
      -addext 'basicConstraints=critical,CA:TRUE' \
      -addext 'keyUsage=critical,keyCertSign,cRLSign' \
      -keyout "$ca_key" -out "$ca_cert"
    openssl req -new -newkey rsa:2048 -nodes -sha256 \
      -subj '/CN=localhost' -keyout "$server_key" -out "$server_csr"
    openssl x509 -req -sha256 -days 7 -in "$server_csr" \
      -CA "$ca_cert" -CAkey "$ca_key" -CAcreateserial -CAserial "$ca_serial" \
      -extfile <(printf '%s\n' \
        'basicConstraints=critical,CA:FALSE' \
        'keyUsage=critical,digitalSignature,keyEncipherment' \
        'extendedKeyUsage=serverAuth' \
        'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:0:0:0:0:0:0:0:1') \
      -out "$server_cert"
  elif ((existing_tls_files != ${#tls_files[@]})); then
    echo "error: --tls-dir contains incomplete retained TLS material" >&2
    exit 1
  fi
  chmod 600 "${tls_files[@]}"
  openssl verify -CAfile "$ca_cert" -verify_ip 127.0.0.1 "$server_cert" >/dev/null
  cert_public_key="$(openssl x509 -in "$server_cert" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum)"
  key_public_key="$(openssl pkey -in "$server_key" -pubout -outform DER 2>/dev/null | sha256sum)"
  if [[ "$cert_public_key" != "$key_public_key" ]]; then
    echo "error: retained TLS certificate and private key do not match" >&2
    exit 1
  fi
  scheme=https
  tls_args=(--tls-cert-file "$server_cert" --tls-key-file "$server_key")
fi

set -a
# shellcheck disable=SC1091
source "$root/.env"
set +a

llm_pid=""
embedding_pid=""
cleanup() {
  if [[ -n "$llm_pid" ]]; then kill -TERM "$llm_pid" 2>/dev/null || true; fi
  if [[ -n "$embedding_pid" ]]; then kill -TERM "$embedding_pid" 2>/dev/null || true; fi
  wait ${llm_pid:-} ${embedding_pid:-} 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$root/backend"
ENVIRONMENT=local STRESS_HTTP_PROVIDERS_ENABLED=true \
  uv run -m app.stress.http_provider llm --port "$llm_port" "${tls_args[@]}" &
llm_pid=$!
ENVIRONMENT=local STRESS_HTTP_PROVIDERS_ENABLED=true \
  POSTGRES_SERVER=localhost POSTGRES_PORT="$postgres_port" POSTGRES_DB="$postgres_db" \
  uv run -m app.stress.http_provider embedding --port "$embedding_port" "${tls_args[@]}" &
embedding_pid=$!

printf 'fake_llm=%s://127.0.0.1:%s fake_embedding=%s://127.0.0.1:%s stress_db=%s@localhost:%s' \
  "$scheme" "$llm_port" "$scheme" "$embedding_port" "$postgres_db" "$postgres_port"
if [[ "$scheme" == https ]]; then
  printf ' ca_file=%s' "$ca_cert"
fi
printf '\n'

set +e
wait -n "$llm_pid" "$embedding_pid"
status=$?
set -e
exit "$status"
