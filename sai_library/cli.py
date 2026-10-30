"""Linha de comando para testar a conexão e conversar sem escrever código.

    python -m sai_library health
    python -m sai_library models [--type chat|audio|image]
    python -m sai_library chat "mensagem" --model NOME [--system "prompt de sistema"]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from sai_library.config import ConfigError
from sai_library.extensions import extract_text
from sai_library.library import SAILibrary
from sai_library.models import ModelType
from sai_library.result import Result


def main(argv: Sequence[str] | None = None) -> int:
    """Código de saída: 0 em sucesso, 1 em erro de configuração ou da API."""
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sai_library", description="Cliente de linha de comando da API do SAI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="verifica a disponibilidade da API")
    models = commands.add_parser("models", help="lista os modelos disponíveis")
    models.add_argument("--type", choices=[kind.name.lower() for kind in ModelType])
    chat = commands.add_parser("chat", help="envia uma mensagem ao modelo")
    chat.add_argument("message")
    chat.add_argument("--model", required=True)
    chat.add_argument("--system")
    return parser


async def _run(args: argparse.Namespace) -> int:
    async with SAILibrary.connect() as sai:
        if args.command == "health":
            return _print(await sai.test_connection())
        if args.command == "models":
            return _print(await _models(sai, args.type))
        return _print(await _chat(sai, args.message, args.model, args.system))


async def _models(sai: SAILibrary, model_type: str | None) -> Result[Any]:
    if model_type is None:
        return await sai.models.get_models()
    return Result.ok(sai.models_of_type(ModelType[model_type.upper()]))


async def _chat(sai: SAILibrary, message: str, model: str, system_prompt: str | None) -> Result[Any]:
    try:
        sai.set_model(model)
    except ValueError as exc:
        return Result.error(str(exc))
    result = await sai.send_message(message, system_prompt)
    texts = extract_text(result)
    return Result.ok("\n".join(texts)) if texts else result


def _print(result: Result[Any]) -> int:
    if not result.success:
        print(result.error_message, file=sys.stderr)
        return 1
    data = result.data
    print(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2))
    return 0
