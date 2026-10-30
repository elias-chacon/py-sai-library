"""Configuração de acesso ao SAI a partir do ambiente e dos arquivos .env."""
from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_DIR = Path(__file__).resolve().parents[1]
# .env do projeto tem precedência sobre o da raiz do repositório, onde ficam as credenciais.
DEFAULT_ENV_FILES = (_PROJECT_DIR / ".env", _PROJECT_DIR.parents[1] / ".env")
API_KEY_VAR = "SAI_API_KEY"
BASE_URL_VAR = "SAI_API_BASE_URL"


class ConfigError(RuntimeError):
    """Configuração obrigatória ausente."""


def load_env(env_files: Iterable[Path] = DEFAULT_ENV_FILES) -> None:
    """Carrega os .env sem sobrescrever variáveis já definidas no ambiente."""
    for env_file in env_files:
        load_dotenv(env_file)


@dataclass(frozen=True)
class SaiSettings:
    """Endereço e chave da API; a chave nunca aparece no `repr`."""

    base_url: str
    api_key: str = field(repr=False)  # nunca aparece em logs ou mensagens de erro

    @classmethod
    def resolve(
        cls,
        api_key: str | None = None,
        base_url: str | None = None,
        env_files: Iterable[Path] = DEFAULT_ENV_FILES,
    ) -> SaiSettings:
        """Valores explícitos têm precedência; os ausentes vêm de SAI_API_KEY e SAI_API_BASE_URL."""
        load_env(env_files)
        values = {
            BASE_URL_VAR: (base_url or os.getenv(BASE_URL_VAR, "")).strip(),
            API_KEY_VAR: (api_key or os.getenv(API_KEY_VAR, "")).strip(),
        }
        absent = [name for name, value in values.items() if not value]
        if absent:
            raise ConfigError(f"Configuração ausente: {', '.join(absent)} (parâmetro ou variável de ambiente/.env)")
        return cls(base_url=values[BASE_URL_VAR].rstrip("/"), api_key=values[API_KEY_VAR])
