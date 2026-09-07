"""Contagem de tokens resiliente.

ADAPTAÇÃO deste fork. O upstream chama `tiktoken.encoding_for_model("gpt-4o")`
direto no caminho crítico de `gen_answer.py`. Na primeira execução o tiktoken
tenta BAIXAR o arquivo de encoding de `openaipublic.blob.core.windows.net` —
e o processo inteiro morre com um SSLError em máquinas sem saída para a
internet, atrás de proxy corporativo ou em CI isolado. Isso é especialmente
irônico quando o modelo avaliado é local.

Aqui a chamada é encapsulada: usa tiktoken quando ele está disponível e cai
para uma estimativa heurística (com aviso único) quando não está. O campo
`token_len` é usado pelo controle de estilo do `show_result.py`, então a
estimativa não é perfeita — mas é consistente entre modelos, que é o que
importa para a comparação relativa.

Para contagem exata offline, faça o cache do encoding uma vez com rede
disponível e aponte a variável TIKTOKEN_CACHE_DIR para esse diretório.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from typing import Optional

DEFAULT_MODEL = "gpt-4o"

# Aproxima a segmentação de um BPE: palavras, números, pontuação e quebras.
_FALLBACK_PATTERN = re.compile(r"\w+|[^\w\s]|\n")

_warned = False


@lru_cache(maxsize=8)
def _get_encoding(model: str):
    try:
        import tiktoken

        return tiktoken.encoding_for_model(model)
    except Exception as e:  # rede indisponível, modelo desconhecido, etc.
        global _warned
        if not _warned:
            print(
                f"AVISO: tiktoken indisponível ({type(e).__name__}). "
                f"Usando estimativa heurística para token_len. "
                f"Defina TIKTOKEN_CACHE_DIR para uma contagem exata offline.",
                file=sys.stderr,
            )
            _warned = True
        return None


def count_tokens(text: Optional[str], model: str = DEFAULT_MODEL) -> int:
    """Conta tokens de `text`, sem nunca levantar exceção por falta de rede."""
    if not text:
        return 0

    encoding = _get_encoding(model)
    if encoding is not None:
        try:
            return len(encoding.encode(text, disallowed_special=()))
        except Exception:
            pass

    # Heurística: tokens BPE ficam em torno de 1,3x o número de "palavras".
    return max(1, int(len(_FALLBACK_PATTERN.findall(text)) * 1.3))


def tiktoken_available(model: str = DEFAULT_MODEL) -> bool:
    return _get_encoding(model) is not None
