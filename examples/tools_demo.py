"""Exemplo: tools definidas neste script e acionadas pelo modelo.

    python examples/tools_demo.py --model NOME "Que horas são? E quanto é 12,5 + 30?"

Cada função decorada com `@tools.tool` vira uma tool. A lib informa ao modelo, no prompt de sistema, quais tools
existem e como acioná-las; quando o modelo pede, a lib executa a função e devolve o resultado a ele.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sai_library import SAILibrary, ToolMode, ToolRegistry

tools = ToolRegistry()


@tools.tool("Data e hora atuais do computador, no formato ISO 8601")
def hora_atual() -> str:
    return datetime.now().isoformat(timespec="seconds")


@tools.tool("Soma dois números", params={"a": "primeira parcela", "b": "segunda parcela"})
def somar(a: float, b: float) -> float:
    return a + b


@tools.tool("Conta as palavras de um texto")
async def contar_palavras(texto: str) -> int:
    return len(texto.split())


async def main() -> int:
    """Pergunta ao modelo e mostra as tools que ele acionou."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pergunta")
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", choices=[mode.value for mode in ToolMode], default=ToolMode.PROMPT.value,
                        help="prompt (padrão), native (function calling da API) ou auto (native para OPENAI)")
    args = parser.parse_args()

    async with SAILibrary.builder().with_retry(3).connect() as sai:
        sai.set_model(args.model)
        result = await sai.chat_with_tools(
            args.pergunta, tools, system_prompt="Responda em português.", mode=ToolMode(args.mode)
        )
    if not result.success:
        print("Erro:", result.error_message)
        return 1
    print(f"[modo] {result.data.mode}")
    for call in result.data.calls:
        print(f"[tool] {call.name}({call.arguments}) -> {call.output}")
    print(result.data.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
