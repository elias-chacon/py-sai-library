# py-sai-library

Cliente Python **assíncrono** para a API do SAI, portado do [ts-sai-library](https://github.com/elias-chacon/ts-sai-library) (commit `34c74f5`), com um recurso novo: **tools**, funções do seu script que o modelo pode acionar durante a conversa.

## Requisitos e instalação

- Python 3.12 ou superior.
- Dependências: `httpx` e `python-dotenv`.

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -e .
```

## Configuração

| Variável | Conteúdo |
|---|---|
| `SAI_API_BASE_URL` | URL do servidor **sem** o sufixo `/api`, porque as rotas já começam com `/api/...`. Ex.: `https://sai.exemplo.com` |
| `SAI_API_KEY` | Chave de API, enviada no cabeçalho `X-Api-Key` |

Os valores são procurados nesta ordem:
1. parâmetros explícitos (`with_api_key`, `with_base_url`, `connect(api_key=..., base_url=...)`);
2. variáveis de ambiente já definidas;
3. `helpers/py-sai-library/.env`;
4. o `.env` da raiz do repositório.

Fora deste repositório, defina as variáveis no ambiente ou use `with_env_files(...)`. A chave nunca aparece em `repr`, logs ou mensagens de erro.

## Uso

```python
import asyncio
from sai_library import SAILibrary

async def main():
    async with SAILibrary.connect() as sai:          # carrega os modelos e fecha o cliente HTTP ao sair
        print(sai.api_info())
        sai.set_model("nome-do-modelo")              # ValueError se não estiver entre os carregados
        result = await sai.send_message("Olá!", system_prompt="Responda em português.")
        if result.success:
            print(result.data["choices"][0]["message"]["content"])
        else:
            print(result.error_message)

asyncio.run(main())
```

Todos os métodos de serviço devolvem `Result`: `success`, `data`, `error_message` e `metadata` (com `status` HTTP quando há resposta). **Erros HTTP e de rede nunca lançam exceção.** Exceções só aparecem em erro de programação ou de configuração (`ConfigError`, `ValueError` em `set_model`).

### Builder

```python
async with (SAILibrary.builder()
            .with_timeout(60)           # segundos (padrão 30)
            .with_retry(3)              # repete só falhas transitórias: rede, timeout, 5xx e 429
            .with_request_logging()     # logging INFO: método, URL, duração e resultado
            .connect()) as sai:
    ...
```

### Serviços (paridade com o original)

`sai.health`, `profile`, `models`, `chat`, `templates`, `conversations`, `workspaces`, `tool_history`, `categories`, `files`, `user_secrets` e `notifications`, com os mesmos endpoints do ts-sai-library e os nomes em `snake_case`. Exemplos: `await sai.templates.execute_template(id, inputs)` e `await sai.files.upload_file("relatorio.pdf")`.

## Tools

Uma tool é uma função Python registrada com `@tools.tool("descrição")`. Nome, parâmetros e tipos vêm da assinatura.

```python
from sai_library import SAILibrary, ToolRegistry

tools = ToolRegistry()

@tools.tool("Consulta o status de uma issue no Jira", params={"chave": "chave Jira, ex.: SQD01-339"})
def status_issue(chave: str) -> str:
    return jira.get_issue_status(chave)

async with SAILibrary.connect() as sai:
    sai.set_model("nome-do-modelo")
    result = await sai.chat_with_tools("Qual o status da SQD01-339?", tools)
    if result.success:
        print(result.data.answer)          # resposta final
        print(result.data.calls)           # tools executadas: nome, argumentos, saída, ok
```

**Como o modelo aprende a acioná-las.** A cada `chat_with_tools`, a lib acrescenta ao prompt de sistema a lista de tools, o JSON Schema dos argumentos e o formato da chamada:

```text
<tool_call>
{"tool": "status_issue", "arguments": {"chave": "SQD01-339"}}
</tool_call>
```

A lib detecta o bloco, valida os argumentos, executa a função e devolve ao modelo:

```text
<tool_result name="status_issue" status="ok">
Em andamento
</tool_result>
```

O ciclo se repete até o modelo responder sem `<tool_call>`, ou até `max_rounds` (padrão 5), quando a lib devolve erro com a conversa parcial em `result.metadata["conversation"]`.

**Regras:**

- **Tipos aceitos:** `str`, `int`, `float`, `bool`, `list[...]`, `dict[...]` e as mesmas opções com `| None`. Parâmetro sem anotação, `*args`, `**kwargs` ou tipo diferente desses falha no **registro**, não durante a conversa.
- **Parâmetros opcionais:** os que têm valor padrão são opcionais.
- **Execução:** `def` roda em thread (`asyncio.to_thread`), para não travar o event loop; `async def` é aguardada diretamente.
- **Erros voltam ao modelo:** tool inexistente, JSON inválido, argumento errado ou exceção dentro da tool viram `status="erro"`, para o modelo corrigir.
- **Saída:** retorno que não é `str` vai como JSON. Saídas acima de 20 mil caracteres são truncadas.
- **Segurança:** o modelo só consegue chamar as funções registradas, com os argumentos validados. Ele não executa comandos livres.

### Modo nativo (function calling da API)

`chat_with_tools(..., mode=ToolMode.X)`:

| Modo | Como as tools chegam ao modelo | Quando usar |
|---|---|---|
| `ToolMode.PROMPT` (padrão) | instruções e formato `<tool_call>` no prompt de sistema | qualquer modelo |
| `ToolMode.NATIVE` | campo `tools` da API; o modelo responde com `tool_calls`, e os resultados voltam como `role: "tool"` | modelos dos provedores OPENAI e EMEA |
| `ToolMode.AUTO` | `NATIVE` se o `provider` do modelo estiver em `NATIVE_TOOL_FORMATS` (`OPENAI`, `EMEA`), `PROMPT` nos demais (`sai.tool_mode_for(nome)`) | quando o modelo muda |

O SAI repassa `tools` sem normalizar, e **cada provedor exige um formato** (`NativeToolFormat`, escolhido por `sai.native_tool_format_for(nome)`):

| Provedor | Formato | Definição |
|---|---|---|
| `OPENAI` | `RESPONSES` (API Responses) | `{"type": "function", "name", "description", "parameters"}` |
| `EMEA` | `CHAT_COMPLETIONS` | `{"type": "function", "function": {"name", "description", "parameters"}}` |
| outro, com `NATIVE` forçado | `CHAT_COMPLETIONS` | idem |

Verificado em 2026-10-30:

- **`gpt-4.1-mini` (OPENAI) com `auto`:** usa o nativo, e o ciclo completo funciona.
- **`emea-gpt-4o-mini-2024-07-18` e `gpt-5.4-mini-emea` (EMEA) com `auto`:** usam o nativo, e o ciclo completo funciona. Com o formato Responses, a API responde 400 (`Missing required parameter: 'tools[0].function'`).
- **`gemini-3.1-flash-lite` com `auto`:** usa o prompt e funciona.
- **Gemini com `native` forçado:** a API responde 400, porque o formato é o da OpenAI. Com o formato do Google (`functionDeclarations`) ela aceita, mas descarta a chamada da tool.

`result.data.mode` informa o modo efetivamente usado.

Exemplo completo: `examples/tools_demo.py` (`--mode prompt|native|auto`).

```powershell
.venv\Scripts\python examples\tools_demo.py --model NOME "Que horas são? E quanto é 12,5 + 30?"
```

## Linha de comando

```powershell
.venv\Scripts\python -m sai_library health
.venv\Scripts\python -m sai_library models --type chat
.venv\Scripts\python -m sai_library chat "Olá" --model NOME --system "Responda em português."
```

Código de saída 0 em sucesso e 1 em erro, com a mensagem em stderr.

## Diferenças em relação ao ts-sai-library

| Tema | Original | py-sai-library | Motivo |
|---|---|---|---|
| Tools | não existe | `ToolRegistry` + `chat_with_tools` | pedido do projeto |
| Retry | repete qualquer falha, inclusive 400/401/404 | só rede, timeout, 5xx e 429 | erros 4xx se repetem igual |
| Upload | `fetch` direto, fora do `IHttpClient` | pelo mesmo `HttpClient` | log e retry valem também no upload |
| Ids no caminho | interpolados sem codificar | codificados (`a/b` → `a%2Fb`) | um id não consegue alterar a rota |
| Booleanos na query | `true`/`false` (JS) | `true`/`false` (o `str(True)` do Python daria `True`) | mesmo formato do original |
| Sem modelo selecionado | `sendMessage` lança, `sendChatWithHistory` devolve erro | os dois devolvem `Result.error` | comportamento uniforme |
| `getChatModels`/`Audio`/`Image` | três métodos | `models_of_type(ModelType.X)` | um método só |
| `createMessage*` na fachada | delegações | `ChatMessage.text(...)` e `ChatMessage.with_image(...)` | sem classe intermediária |
| `sendMessageWithRetry` etc. | atalhos | `execute_with_retry(lambda: ...)` ou `with_retry()` no builder | uma forma só de repetir |
| Corpo não JSON | erro de parse | devolvido como texto | endpoints que respondem texto puro |
| Tipo do modelo | só número (0/1/2): o filtro devolve vazio | texto (`LLM`, `Image`) ou número | a API devolve texto (verificado em 2026-10-30) |

## Testes e qualidade

```powershell
.venv\Scripts\python -m unittest discover -s tests -t .
```

Os 80 testes rodam sem rede: o `httpx.MockTransport` simula o servidor, e o `FakeHttp` substitui o cliente nos serviços. Uma tabela em `tests/test_services.py` confere método, rota, query e corpo de **cada** método dos 12 serviços, e um teste falha se aparecer um método público sem caso na tabela.

pylint, coverage e SonarQube rodam a partir de um venv de ferramentas separado (`%USERPROFILE%\.venvs\qa`). Os comandos estão na nota "Comandos de Referência" do vault. Para o Sonar, use `--sonar-project-key py-sai-library --sonar-sources sai_library,examples --sonar-tests tests`.

## Verificado com a API real (2026-10-30)

- `health`, `models` (90 modelos, 86 de chat) e `chat` com `https://sai-library.saiapplications.com`.
- Tools: o `gpt-4.1-mini-2025-04-14` acionou duas tools numa resposta (nos modos prompt e nativo), e o `gemini-3.1-flash-lite` usou uma tool `async` (modo prompt). O protocolo depende de o modelo seguir o formato: teste o modelo que você vai usar.

## Observações

- Criar o `httpx.AsyncClient` carrega os certificados TLS de forma síncrona, por cerca de 1 s, uma vez por conexão.
- **Licença:** GPL-3.0, a mesma do `LICENSE` do ts-sai-library. Os dois projetos são open source e têm o mesmo autor.
