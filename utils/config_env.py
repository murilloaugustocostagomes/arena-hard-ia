"""Carregamento de configuração com suporte a variáveis de ambiente e `.env`.

Adaptação do arena-hard-auto: em vez de colar chaves de API dentro de
`config/api_config.yaml`, escreva `${OPENAI_API_KEY}` e o valor é resolvido em
tempo de execução a partir do ambiente (ou do arquivo `.env` na raiz do repo).

Sintaxe suportada dentro dos YAMLs:
    ${VAR}              -> obrigatório; erro claro se não estiver definido
    ${VAR:-padrao}      -> usa "padrao" quando VAR não existe ou está vazia
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_dotenv_loaded = False


def load_dotenv(path: str | os.PathLike[str] | None = None, override: bool = False) -> dict:
    """Lê um arquivo `.env` simples (KEY=VALUE) para dentro de os.environ."""
    global _dotenv_loaded

    env_path = Path(path) if path else REPO_ROOT / ".env"
    loaded: dict[str, str] = {}

    if not env_path.is_file():
        _dotenv_loaded = True
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        if override or key not in os.environ:
            os.environ[key] = value
        loaded[key] = value

    _dotenv_loaded = True
    return loaded


def ensure_dotenv() -> None:
    """Carrega o `.env` uma única vez por processo."""
    if not _dotenv_loaded:
        load_dotenv()


class MissingEnvVar(RuntimeError):
    """Uma variável obrigatória referenciada no YAML não foi definida."""


def _substitute(value: str, source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        env_value = os.environ.get(name)
        if env_value:
            return env_value
        if default is not None:
            return default
        raise MissingEnvVar(
            f"A variável de ambiente '{name}' é usada em {source} mas não está definida. "
            f"Defina-a no arquivo .env (veja .env.example) ou exporte no shell."
        )

    return _ENV_PATTERN.sub(replace, value)


def expand_env(obj: Any, source: str = "config") -> Any:
    """Percorre dicts/listas resolvendo ${VAR} em todas as strings."""
    if isinstance(obj, dict):
        return {k: expand_env(v, source) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env(v, source) for v in obj]
    if isinstance(obj, str):
        return _substitute(obj, source)
    return obj


MISSING_KEY = "__missing_env__"


def load_config(config_file: str | os.PathLike[str]) -> dict:
    """Carrega um YAML de configuração já com as variáveis de ambiente resolvidas.

    A resolução é tolerante por entrada de primeiro nível: se `api_config.yaml`
    define dez modelos e você só configurou a chave de um deles, os outros nove
    NÃO derrubam o carregamento — eles ficam marcados como não resolvidos e só
    dão erro se você realmente tentar usá-los. Sem isso, uma única variável
    faltando tornaria o arquivo de config inteiro inutilizável.
    """
    ensure_dotenv()
    path = Path(config_file)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.load(f, Loader=yaml.SafeLoader) or {}

    if not isinstance(data, dict):
        return expand_env(data, source=str(path))

    resolved: dict = {}
    for key, value in data.items():
        try:
            resolved[key] = expand_env(value, source=f"{path} -> {key}")
        except MissingEnvVar as e:
            resolved[key] = {MISSING_KEY: str(e)} if isinstance(value, dict) else value
    return resolved


def assert_resolved(name: str, settings: Any) -> Any:
    """Falha com mensagem clara se a entrada depender de env vars ausentes."""
    if isinstance(settings, dict) and MISSING_KEY in settings:
        raise SystemExit(f"Configuração de '{name}' incompleta.\n{settings[MISSING_KEY]}")
    return settings

