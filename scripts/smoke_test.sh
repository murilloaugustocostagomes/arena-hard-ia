#!/usr/bin/env bash
# Teste de fumaça: roda o pipeline COMPLETO do Arena-Hard de ponta a ponta
# contra um servidor mock local. Zero chaves de API, zero custo, ~15 segundos.
#
#   gen_answer.py -> gen_judgment.py -> show_result.py
#
# Serve para validar a instalação e para pegar regressões depois de mexer no
# código do benchmark.

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python}"
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

PORT="${MOCK_PORT:-8000}"
N="${SMOKE_QUESTIONS:-12}"
export MOCK_API_BASE="http://localhost:${PORT}/v1"

echo "==> Subindo servidor mock na porta ${PORT}"
"$PYTHON" scripts/mock_server.py --host 127.0.0.1 --port "$PORT" &
MOCK_PID=$!

cleanup() {
    echo "==> Encerrando servidor mock (pid ${MOCK_PID})"
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Espera o servidor aceitar conexões.
for _ in $(seq 1 40); do
    if "$PYTHON" -c "
import socket, sys
s = socket.socket()
s.settimeout(0.25)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${PORT})) == 0 else 1)
" 2>/dev/null; then
        break
    fi
    sleep 0.25
done

echo "==> Limpando execução anterior"
rm -rf data/arena-hard-mock

echo "==> Montando benchmark sintético (${N} perguntas)"
"$PYTHON" scripts/make_mock_bench.py -n "$N"

echo "==> Etapa 1/3: gerando respostas"
"$PYTHON" gen_answer.py --config-file config/gen_answer_mock.yaml

echo "==> Etapa 2/3: gerando julgamentos"
"$PYTHON" gen_judgment.py --setting-file config/arena-hard-mock.yaml

echo "==> Etapa 3/3: leaderboard (sem controle de estilo)"
"$PYTHON" show_result.py -b arena-hard-mock -j mock-baseline -c mock

echo "==> Etapa 3/3: leaderboard (com controle de estilo)"
"$PYTHON" show_result.py -b arena-hard-mock -j mock-baseline -c mock -f markdown length

echo
echo "==> Pipeline OK. Lembre: os números acima são sintéticos e não medem nada."
