#!/usr/bin/env python3
"""Monta o benchmark sintético `arena-hard-mock`.

Pega uma amostra pequena e determinística das perguntas reais do
Arena-Hard-v2.0 e reescreve a categoria para "mock", de modo que o pipeline
inteiro possa rodar contra `scripts/mock_server.py` — sem chave de API, sem
custo e em segundos.

Uso:
    python scripts/make_mock_bench.py --num-questions 12
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.completion import load_questions  # noqa: E402

SOURCE = "data/arena-hard-v2.0/question.jsonl"
TARGET_DIR = "data/arena-hard-mock"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-questions", "-n", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--source", default=SOURCE)
    parser.add_argument("--target-dir", default=TARGET_DIR)
    args = parser.parse_args()

    if not os.path.isfile(args.source):
        raise SystemExit(
            f"Não encontrei {args.source}. Esse arquivo é versionado no repo; "
            f"confira se você está na raiz do projeto."
        )

    questions = load_questions(args.source)
    rng = random.Random(args.seed)
    sample = rng.sample(questions, min(args.num_questions, len(questions)))

    os.makedirs(args.target_dir, exist_ok=True)
    out_path = os.path.join(args.target_dir, "question.jsonl")

    with open(out_path, "w", encoding="utf-8") as f:
        for q in sample:
            record = dict(q)
            record["subcategory"] = record.get("category", "")
            record["category"] = "mock"
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"{len(sample)} perguntas escritas em {out_path}")


if __name__ == "__main__":
    main()
