#!/usr/bin/env python3
"""Baixa os dados pesados do Arena-Hard (respostas e julgamentos oficiais).

Por que este script existe
--------------------------
`data/*/model_answer/` e `data/*/model_judgment/` somam ~147 MB no repositório
oficial. Neste fork esses diretórios estão no `.gitignore` — só as
`question.jsonl` (pequenas) são versionadas. Assim o clone é rápido e o
histórico não carrega centenas de MB de JSONL.

Use este script para trazer os dados oficiais quando precisar deles, por
exemplo para reproduzir o leaderboard ou para ter o baseline
(`o3-mini-2025-01-31`, `gemini-2.0-flash-001`) exigido por `gen_judgment.py`.

O download usa `git` com clone parcial (`--filter=blob:none --sparse`), que
funciona em ambientes onde requests/HTTPS direto esbarra em proxy corporativo.

Exemplos
--------
    python scripts/fetch_data.py                       # tudo (~147 MB)
    python scripts/fetch_data.py -b arena-hard-v0.1    # só o v0.1 (~18 MB)
    python scripts/fetch_data.py --answers-only        # sem os julgamentos
    python scripts/fetch_data.py --list                # só lista o que existe
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

UPSTREAM = "https://github.com/lmarena/arena-hard-auto.git"
BENCHMARKS = ["arena-hard-v0.1", "arena-hard-v2.0"]


def run(cmd: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"Comando falhou: {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result.stdout


def human(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark", "-b", nargs="+", default=BENCHMARKS,
                        choices=BENCHMARKS, help="Quais benchmarks baixar.")
    parser.add_argument("--answers-only", action="store_true",
                        help="Baixa só model_answer (pula os julgamentos, que são os maiores).")
    parser.add_argument("--judgments-only", action="store_true",
                        help="Baixa só model_judgment.")
    parser.add_argument("--list", action="store_true",
                        help="Lista os arquivos disponíveis e sai, sem baixar.")
    parser.add_argument("--force", action="store_true",
                        help="Sobrescreve arquivos que já existem localmente.")
    parser.add_argument("--repo", default=UPSTREAM)
    args = parser.parse_args()

    if shutil.which("git") is None:
        raise SystemExit("git não encontrado no PATH — ele é necessário para baixar os dados.")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    subdirs = ["model_answer", "model_judgment"]
    if args.answers_only:
        subdirs = ["model_answer"]
    if args.judgments_only:
        subdirs = ["model_judgment"]

    patterns = [f"data/{b}/{s}" for b in args.benchmark for s in subdirs]

    with tempfile.TemporaryDirectory(prefix="arena-hard-data-") as tmp:
        clone_dir = os.path.join(tmp, "upstream")

        print(f"Clonando índice de {args.repo} (sem blobs)...")
        run(["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
             args.repo, clone_dir])
        run(["git", "sparse-checkout", "init", "--cone"], cwd=clone_dir)
        run(["git", "sparse-checkout", "set", *patterns], cwd=clone_dir)

        if args.list:
            print("\nArquivos disponíveis no upstream:")
            listing = run(["git", "ls-tree", "-r", "-l", "--name-only", "HEAD", "data/"],
                          cwd=clone_dir)
            for line in listing.splitlines():
                if line.endswith(".jsonl"):
                    print("  " + line)
            return

        print("Baixando blobs (isso pode levar alguns minutos)...")
        run(["git", "checkout"], cwd=clone_dir)

        copied = skipped = 0
        total_bytes = 0

        for pattern in patterns:
            src_dir = os.path.join(clone_dir, pattern)
            if not os.path.isdir(src_dir):
                print(f"  (nada em {pattern})")
                continue

            for root, _dirs, files in os.walk(src_dir):
                rel_root = os.path.relpath(root, clone_dir)
                dst_root = os.path.join(repo_root, rel_root)
                os.makedirs(dst_root, exist_ok=True)

                for name in sorted(files):
                    if not name.endswith(".jsonl"):
                        continue
                    src = os.path.join(root, name)
                    dst = os.path.join(dst_root, name)

                    if os.path.exists(dst) and not args.force:
                        skipped += 1
                        continue

                    shutil.copy2(src, dst)
                    size = os.path.getsize(dst)
                    total_bytes += size
                    copied += 1
                    print(f"  {os.path.join(rel_root, name)}  ({human(size)})")

        print(f"\n{copied} arquivo(s) copiado(s) ({human(total_bytes)}), "
              f"{skipped} já existia(m). Use --force para sobrescrever.")

        if copied:
            print("\nPróximo passo: python show_result.py --judge-names gpt-4.1 -f markdown length")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
