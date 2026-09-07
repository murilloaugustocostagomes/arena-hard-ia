#!/usr/bin/env python3
"""Servidor mock compatível com a API OpenAI (`/v1/chat/completions`).

Serve para exercitar o pipeline completo do Arena-Hard
(gen_answer -> gen_judgment -> show_result) sem gastar um centavo e sem
precisar de nenhuma chave de API. Útil para:

  * validar a instalação e a configuração antes de rodar de verdade;
  * testar mudanças no código do benchmark em CI;
  * demonstrar o formato dos dados.

Ele NÃO é um modelo: as respostas são texto sintético determinístico e os
"veredictos" do juiz são sorteados com um viés fixo por modelo. Os números que
saem disso não têm significado nenhum — servem só para provar que o encanamento
funciona.

Uso:
    python scripts/mock_server.py --port 8000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Quanto maior, melhor o modelo "finge" ser. Usado só para gerar veredictos
# plausíveis e estáveis no juiz mock.
MODEL_SKILL = {
    "mock-strong": 0.75,
    "mock-baseline": 0.50,
    "mock-weak": 0.25,
}

VERDICTS = ["A>>B", "A>B", "A=B", "B>A", "B>>A"]

ANSWER_TEMPLATE = """## Resumo

{intro}

### Passos

1. Interpretar o enunciado: {topic}
2. Levantar as restrições relevantes.
3. Construir a solução de forma incremental.
4. Validar o resultado com um caso pequeno.

```python
def solve(entrada):
    # Implementação de exemplo gerada pelo servidor mock.
    return entrada
```

### Observações

{outro}
"""


def _seeded_random(*parts: str) -> random.Random:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _is_judge_request(messages: list) -> bool:
    system = next((m for m in messages if m.get("role") == "system"), None)
    return bool(system and "impartial judge" in str(system.get("content", "")))


def _extract_models(messages: list) -> tuple[str, str]:
    """Descobre quem é A e quem é B a partir do prompt de julgamento."""
    user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    content = str(user.get("content", ""))
    marks = re.findall(r"\[MOCK-MODEL:([^\]]+)\]", content)
    if len(marks) >= 2:
        return marks[0], marks[1]
    return "unknown-a", "unknown-b"


def build_answer(model: str, prompt: str) -> str:
    rng = _seeded_random(model, prompt)
    skill = MODEL_SKILL.get(model, 0.5)
    topic = " ".join(prompt.split()[:12]) or "a tarefa pedida"

    intro = rng.choice([
        "Vou resolver isso em etapas curtas e verificáveis.",
        "A abordagem mais direta aqui é decompor o problema.",
        "Segue uma solução completa com justificativa.",
    ])
    outro = rng.choice([
        "Casos de borda foram considerados.",
        "A complexidade é linear no tamanho da entrada.",
        "Vale revisar os limites do enunciado antes de submeter.",
    ])

    body = ANSWER_TEMPLATE.format(intro=intro, topic=topic, outro=outro)

    # Modelos "melhores" escrevem respostas mais longas — assim o controle de
    # estilo do show_result.py tem algum sinal com que trabalhar.
    extra_paragraphs = int(skill * 6)
    for i in range(extra_paragraphs):
        body += f"\n### Detalhe {i + 1}\n\n{rng.choice(['Justificativa adicional.', 'Exemplo trabalhado.', 'Prova de corretude resumida.'])}\n"

    # Marcador para o juiz mock saber quem escreveu o quê.
    return f"[MOCK-MODEL:{model}]\n\n{body}"


def build_judgment(messages: list) -> str:
    model_a, model_b = _extract_models(messages)
    rng = _seeded_random("judge", model_a, model_b, str(len(str(messages))))

    skill_a = MODEL_SKILL.get(model_a, 0.5)
    skill_b = MODEL_SKILL.get(model_b, 0.5)
    diff = skill_a - skill_b

    # Distribuição de veredictos deslocada pela diferença de "habilidade".
    weights = [
        max(0.02, 0.15 + diff),        # A>>B
        max(0.02, 0.25 + diff * 0.6),  # A>B
        0.20,                          # A=B
        max(0.02, 0.25 - diff * 0.6),  # B>A
        max(0.02, 0.15 - diff),        # B>>A
    ]
    verdict = rng.choices(VERDICTS, weights=weights)[0]

    return (
        "Comparando as duas respostas do ponto de vista de correção, utilidade e "
        "concisão, ambas cobrem o pedido do usuário, mas com profundidades "
        "diferentes.\n\n"
        "(Julgamento sintético produzido pelo servidor mock — sem valor "
        "avaliativo real.)\n\n"
        f"My final verdict is: [[{verdict}]]"
    )


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencia o log por requisição
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._send_json(200, {
                "object": "list",
                "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in MODEL_SKILL],
            })
        elif self.path.rstrip("/") in ("", "/health"):
            self._send_json(200, {"status": "ok", "models": list(MODEL_SKILL)})
        else:
            self._send_json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self):  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send_json(404, {"error": {"message": f"unknown path {self.path}"}})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": {"message": f"invalid JSON: {e}"}})
            return

        model = payload.get("model", "mock-baseline")
        messages = payload.get("messages", [])

        if _is_judge_request(messages):
            content = build_judgment(messages)
        else:
            user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
            content = build_answer(model, str(user.get("content", "")))

        self._send_json(200, {
            "id": f"chatcmpl-mock-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": sum(len(str(m.get("content", ""))) for m in messages) // 4,
                "completion_tokens": len(content) // 4,
                "total_tokens": 0,
            },
        })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"Servidor mock OpenAI-compatível em http://{args.host}:{args.port}/v1")
    print(f"Modelos: {', '.join(MODEL_SKILL)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
