# Arena-Hard-IA

Fork adaptado do [**Arena-Hard-Auto**](https://github.com/lmarena/arena-hard-auto) (LMArena) — o benchmark automático de LLMs com maior correlação e separabilidade em relação à LMArena/Chatbot Arena entre os benchmarks abertos ([paper](https://arxiv.org/abs/2406.11939)).

O código original está preservado. Este fork adiciona o que faltava para tirar o benchmark do papel: **segredos fora do repositório, um provedor genérico OpenAI-compatível, rodadas parciais baratas, um pipeline de teste sem custo e correções de bugs que travavam a execução.**

---

## Índice

- [O que é o benchmark](#o-que-é-o-benchmark)
- [Começando em 2 minutos](#começando-em-2-minutos)
- [Rodando de verdade](#rodando-de-verdade)
- [O que foi adaptado](#o-que-foi-adaptado)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Dados](#dados)
- [Custos](#custos)
- [Referência de comandos](#referência-de-comandos)
- [Créditos e licença](#créditos-e-licença)

---

## O que é o benchmark

O Arena-Hard avalia um modelo em **quatro etapas**:

```
question.jsonl  ──►  gen_answer.py   ──►  model_answer/*.jsonl
                                             │
                     gen_judgment.py  ◄──────┘   (compara com o baseline)
                          │
                          ▼
                     model_judgment/<juiz>/*.jsonl
                          │
                          ▼
                     show_result.py   ──►  leaderboard com IC 95%
```

1. **Perguntas** — 500 prompts difíceis (`hard_prompt`) + 250 de escrita criativa (`creative_writing`), extraídos de conversas reais da Chatbot Arena. Essa é a versão **v2.0-Preview**.
2. **Respostas** — seu modelo responde a cada prompt.
3. **Julgamento** — um modelo juiz (GPT-4.1 ou Gemini 2.5) compara sua resposta com a do **baseline** (`o3-mini-2025-01-31`), nas duas ordens, para cancelar viés de posição.
4. **Resultado** — as vitórias viram uma taxa de vitória via modelo Bradley-Terry, com intervalo de confiança por bootstrap e **controle de estilo** (desconta a vantagem de respostas simplesmente mais longas ou mais cheias de markdown).

O baseline sempre marca 50%. Acima disso, seu modelo é melhor que o `o3-mini` na visão do juiz.

---

## Começando em 2 minutos

```bash
make setup        # cria .venv e instala as dependências
make smoke        # roda o pipeline COMPLETO — sem chave de API, sem custo
```

`make smoke` sobe um servidor mock compatível com a API da OpenAI, gera respostas para três modelos fictícios, julga e imprime o leaderboard. Leva ~15 segundos:

```
##### Category: mock #####
           Model  Scores (%)         CI (%)
0    mock-strong        95.6  (-6.5 / +4.4)
1  mock-baseline        50.0  (-0.0 / +0.0)
2      mock-weak        15.7  (-7.4 / +7.0)
```

> Os números são sintéticos e não medem nada. O objetivo é provar que a instalação, as configs e as quatro etapas funcionam — antes de você gastar dinheiro de verdade.

Você também pode reproduzir o leaderboard oficial sem chamar nenhuma API, usando os julgamentos já publicados:

```bash
make data          # baixa respostas e julgamentos oficiais (~147 MB, fora do Git)
make result        # hard_prompt, com controle de estilo
make result-creative
```

---

## Rodando de verdade

### 1. Configurar as chaves

```bash
make env           # cria .env a partir do .env.example
$EDITOR .env       # preencha só o que for usar
```

Nada de chave dentro de YAML. Em `config/api_config.yaml` você escreve `${OPENAI_API_KEY}` e o valor é resolvido em tempo de execução a partir do `.env` ou do ambiente. Entradas cujas variáveis não estão definidas simplesmente ficam indisponíveis — não quebram o arquivo inteiro.

### 2. Declarar o seu modelo

Qualquer endpoint que fale a API da OpenAI (vLLM, SGLang, Ollama, LM Studio, OpenRouter, Together, Groq, DeepSeek...) funciona com o mesmo `api_type`:

```yaml
# config/api_config.yaml
meu-modelo:
    model: ${LOCAL_MODEL_NAME:-minha-llama}
    api_type: openai_compatible
    endpoints:
        - api_base: ${LOCAL_API_BASE:-http://localhost:8000/v1}
          api_key: ${LOCAL_API_KEY:-EMPTY}
    parallel: 8
    max_tokens: 4096
    temperature: 0.0
```

### 3. Rodada de teste (barata)

Antes de gastar com as 750 perguntas, valide com 20:

```bash
python gen_answer.py   -m meu-modelo -c hard_prompt -n 20
python gen_judgment.py -m meu-modelo -c hard_prompt -n 20
python show_result.py  -j gpt-4.1 -c hard_prompt
```

A amostragem é **determinística e estratificada**: com a mesma `--seed`, `gen_answer` e `gen_judgment` selecionam exatamente as mesmas perguntas.

> `gen_judgment.py` precisa das respostas do baseline (`o3-mini-2025-01-31`). Traga-as com `make data` ou `python scripts/fetch_data.py --answers-only`.

### 4. Rodada completa

```bash
# adicione seu modelo ao model_list de config/gen_answer_config.yaml
python gen_answer.py

# adicione seu modelo ao model_list de config/arena-hard-v2.0.yaml
python gen_judgment.py

make result
```

Tanto as respostas quanto os julgamentos têm **cache**: reexecutar pula o que já existe, então uma interrupção no meio do caminho não custa duas vezes.

---

## O que foi adaptado

| # | Mudança | Problema que resolve |
|---|---------|----------------------|
| 1 | **Segredos via `.env`** (`utils/config_env.py`) — `${VAR}` e `${VAR:-padrão}` nos YAMLs, resolvidos por entrada | O upstream pede chaves de API coladas em `config/api_config.yaml`, um arquivo versionado. Convite a vazamento. Agora, além disso, uma variável faltando não invalida o arquivo inteiro: só a entrada que depende dela fica indisponível, com mensagem explicando o que definir. |
| 2 | **`api_type: openai_compatible`** (`utils/completion.py`) | O handler `openai` original desiste no primeiro erro sem backoff e não lida com endpoints alternativos nem com modelos de raciocínio. O novo faz retry exponencial, aceita `api_base`/`base_url`, cai automaticamente de `max_tokens` para `max_completion_tokens`, remove `temperature` quando o servidor rejeita, e captura o texto de raciocínio quando exposto. Um handler para vLLM, SGLang, Ollama, OpenRouter, Groq, Together... |
| 3 | **Rodadas parciais** — `--category`, `--max-questions`, `--seed`, `--model` em `gen_answer.py` e `gen_judgment.py` | Só existia "tudo ou nada": 750 perguntas × (1 resposta + 2 julgamentos). Sem uma rodada de teste barata, um erro de config só aparece depois de dezenas de dólares gastos. A amostragem é determinística e estratificada por categoria, então as duas etapas veem o mesmo subconjunto. |
| 4 | **Servidor mock + `make smoke`** (`scripts/mock_server.py`) | Não havia nenhuma forma de exercitar o pipeline sem chave e sem custo. Agora `make smoke` roda as quatro etapas em ~15 s — bom para validar a instalação, testar mudanças no código e rodar em CI. |
| 5 | **`scripts/fetch_data.py`** + dados pesados no `.gitignore` | O upstream versiona ~147 MB de JSONL. Aqui só as `question.jsonl` entram no Git; o resto se baixa sob demanda com clone parcial via `git` (funciona atrás de proxy, onde HTTPS direto costuma falhar). |
| 6 | **Correção: `show_result.py` só processava a primeira categoria** | `battles` era reatribuído dentro do laço, então `-c hard_prompt creative_writing` retornava vazio a partir da segunda categoria. Agora cada iteração filtra a partir do conjunto completo. |
| 7 | **Correção: `tiktoken` derrubava `gen_answer.py` sem internet** (`utils/tokenizer.py`) | `tiktoken.encoding_for_model()` baixa o arquivo de encoding na primeira chamada. Em CI isolado, atrás de proxy ou avaliando um modelo local, o processo morria com `SSLError` depois de já ter gerado respostas. Agora há fallback heurístico com aviso único. |
| 8 | **Correção: atributo de estilo constante virava `AssertionError`** | Divisão por desvio-padrão zero gerava `NaN` e um assert sem mensagem. Comum em amostras pequenas. Agora a feature degenerada é neutralizada com um aviso claro. |
| 9 | **Correção: `boto3` era import obrigatório** | Quem não usa Amazon Bedrock não conseguia nem importar `utils/completion.py`. Virou import opcional com mensagem de instalação. |
| 10 | **Erros acionáveis em `gen_judgment.py`** | Faltar o baseline ou as respostas do modelo produzia um `KeyError` críptico no meio de um `ThreadPoolExecutor`. Agora a mensagem diz exatamente qual comando rodar. |
| 11 | **`Makefile` + README em português** | O fluxo de quatro etapas com flags espalhadas era difícil de descobrir. `make help` lista tudo. |

O README original está preservado em [`README.upstream.md`](README.upstream.md), incluindo os leaderboards oficiais publicados.

---

## Estrutura do repositório

```
├── gen_answer.py            # etapa 1: respostas do modelo
├── gen_judgment.py          # etapa 2: julgamento par a par
├── show_result.py           # etapa 3: leaderboard (Bradley-Terry + controle de estilo)
├── qa_browser.py            # visualizador Gradio de respostas e julgamentos
│
├── config/
│   ├── api_config.yaml      # endpoints e credenciais (via ${VAR})
│   ├── gen_answer_config.yaml
│   ├── arena-hard-v2.0.yaml # config do juiz (500 hard + 250 creative)
│   ├── arena-hard-v0.1.yaml # versão antiga (500 prompts)
│   ├── gen_answer_mock.yaml # ADAPTAÇÃO: benchmark sintético
│   └── arena-hard-mock.yaml # ADAPTAÇÃO: benchmark sintético
│
├── utils/
│   ├── completion.py        # handlers de API (+ openai_compatible, filter_questions)
│   ├── config_env.py        # ADAPTAÇÃO: .env e ${VAR} nos YAMLs
│   ├── tokenizer.py         # ADAPTAÇÃO: contagem de tokens resiliente
│   ├── judge_utils.py       # prompts do juiz e baseline por categoria
│   ├── math_utils.py        # Bradley-Terry, bootstrap
│   └── add_markdown_info.py # atributos de estilo
│
├── scripts/                 # ADAPTAÇÃO — tudo novo
│   ├── fetch_data.py        # baixa respostas/julgamentos oficiais
│   ├── mock_server.py       # API OpenAI falsa, custo zero
│   ├── make_mock_bench.py   # monta o benchmark sintético
│   └── smoke_test.sh        # pipeline completo de ponta a ponta
│
├── data/
│   ├── arena-hard-v2.0/question.jsonl   # versionado (928 KB)
│   └── arena-hard-v0.1/question.jsonl   # versionado (268 KB)
│
├── BenchBuilder/            # pipeline de curadoria dos prompts (upstream)
└── leaderboard/             # leaderboard histórico em CSV
```

---

## Dados

| Diretório | No Git? | Tamanho | Como obter |
|-----------|---------|---------|------------|
| `data/*/question.jsonl` | ✅ sim | 1,2 MB | já está aqui |
| `data/*/model_answer/` | ❌ não | ~40 MB | `make data` |
| `data/*/model_judgment/` | ❌ não | ~107 MB | `make data` |
| `data/arena-hard-mock/` | ❌ não | ~200 KB | `make smoke` |

```bash
python scripts/fetch_data.py --list              # ver o que existe no upstream
python scripts/fetch_data.py -b arena-hard-v0.1  # só o v0.1 (~18 MB)
python scripts/fetch_data.py --answers-only      # pular os julgamentos
```

---

## Custos

Avaliar **um** modelo no Arena-Hard-v2.0 completo:

| Etapa | Chamadas | Observação |
|-------|----------|------------|
| Respostas | 750 | preço do modelo avaliado |
| Julgamentos | 1.500 | 750 × 2 ordens; prompts longos (pergunta + duas respostas) |

O julgamento domina o custo. Estratégia recomendada:

```bash
# 1. valide a canalização de graça
make smoke

# 2. rodada piloto: 20 perguntas
python gen_answer.py -m meu-modelo -n 20 && python gen_judgment.py -m meu-modelo -n 20

# 3. só então a rodada completa
```

Use `gpt-4.1` como juiz para uma execução mais rápida e barata; `gemini-2.5` é a configuração oficial do leaderboard. Para escrita criativa, o ensemble dos dois é o recomendado.

---

## Referência de comandos

```bash
make help              # lista todos os alvos

make setup             # venv + dependências
make env               # cria o .env
make smoke             # pipeline completo sem custo
make data              # baixa dados oficiais (~147 MB)
make data-small        # só o v0.1 (~18 MB)
make answer            # etapa 1
make judge             # etapa 2
make result            # etapa 3 — hard_prompt com controle de estilo
make result-creative   # etapa 3 — creative_writing (ensemble)
make browser           # visualizador Gradio
make clean             # limpa caches e dados sintéticos
```

Flags úteis dos scripts:

```bash
python gen_answer.py   -m MODELO... -c CATEGORIA... -n N --seed S
python gen_judgment.py -m MODELO... -c CATEGORIA... -n N --seed S
python show_result.py  -b BENCH -j JUIZ... -c CATEGORIA... -f markdown length
```

`-f`/`--control-features` aceita `length`, `markdown`, ou ambos. Sem a flag, o leaderboard sai sem controle de estilo.

---

## Créditos e licença

Todo o mérito do benchmark é da equipe do **LMArena / LMSYS**. Este repositório é um fork de adaptação — a metodologia, os prompts e os prompts de julgamento são deles.

```bibtex
@article{li2024crowdsourced,
  title={From Crowdsourced Data to High-Quality Benchmarks: Arena-Hard and BenchBuilder Pipeline},
  author={Li, Tianle and Chiang, Wei-Lin and Frick, Evan and Dunlap, Lisa and Wu, Tianhao and Zhu, Banghua and Gonzalez, Joseph E and Stoica, Ion},
  journal={arXiv preprint arXiv:2406.11939},
  year={2024}
}
```

- Upstream: <https://github.com/lmarena/arena-hard-auto>
- Paper: <https://arxiv.org/abs/2406.11939>
- Demo: <https://huggingface.co/spaces/lmarena-ai/arena-hard-viewer>

Licença: [Apache 2.0](LICENSE), herdada do projeto original.
