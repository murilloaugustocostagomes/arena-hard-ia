PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
JUDGE  ?= gpt-4.1
BENCH  ?= arena-hard-v2.0

.DEFAULT_GOAL := help

.PHONY: help setup env data data-small smoke answer judge result result-creative \
        leaderboard browser clean-mock clean

help: ## Mostra esta ajuda
	@echo "Arena-Hard-IA — alvos disponíveis:"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Variáveis: JUDGE=$(JUDGE)  BENCH=$(BENCH)  PYTHON=$(PYTHON)"

setup: ## Cria o venv e instala as dependências
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo
	@echo "Pronto. Agora: make env"

env: ## Cria o .env a partir do .env.example
	@if [ -f .env ]; then \
		echo ".env já existe — não vou sobrescrever."; \
	else \
		cp .env.example .env; \
		echo ".env criado. Edite-o e preencha suas chaves de API."; \
	fi

data: ## Baixa TODAS as respostas e julgamentos oficiais (~147 MB)
	$(PYTHON) scripts/fetch_data.py

data-small: ## Baixa só o Arena-Hard-v0.1 (~18 MB)
	$(PYTHON) scripts/fetch_data.py -b arena-hard-v0.1

smoke: ## Roda o pipeline inteiro contra o servidor mock (sem chave, sem custo)
	bash scripts/smoke_test.sh

answer: ## Gera respostas do model_list em config/gen_answer_config.yaml
	$(PYTHON) gen_answer.py

judge: ## Gera julgamentos com o juiz configurado
	$(PYTHON) gen_judgment.py --setting-file config/$(BENCH).yaml

result: ## Leaderboard hard_prompt com controle de estilo (config oficial)
	$(PYTHON) show_result.py -b $(BENCH) -j $(JUDGE) -c hard_prompt -f markdown length

result-creative: ## Leaderboard creative_writing (ensemble dos dois juízes)
	$(PYTHON) show_result.py -b $(BENCH) -j gpt-4.1 gemini-2.5 -c creative_writing

leaderboard: result result-creative ## Roda os dois leaderboards

browser: ## Abre o visualizador Gradio de respostas e julgamentos
	$(PIP) install "gradio>=5.25.2"
	$(PYTHON) qa_browser.py

clean-mock: ## Remove os dados do benchmark sintético
	rm -rf data/arena-hard-mock

clean: clean-mock ## Remove caches do Python e dados sintéticos
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -not -path "./.venv/*" -delete
