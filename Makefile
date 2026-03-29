# Importa variáveis do arquivo .env
-include .env

# Variáveis de Configuração (DOCKER_USER agora vem do .env)
IMAGE_NAME = monitor-olx-salvador
DOCKER_USER ?= SEU-USUARIO# Valor padrão caso não esteja no .env
VERSION = 1.1.0
FULL_IMAGE_NAME = $(DOCKER_USER)/$(IMAGE_NAME)

.PHONY: help build up down logs restart status clean login push shell

help: ## Mostra as opções de comando
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Builda a imagem Docker localmente
	docker compose build

up: ## Sobe o container em segundo plano (detach)
	docker compose up -d

down: ## Para e remove os containers
	docker compose down

logs: ## Acompanha os logs em tempo real
	docker compose logs -f

restart: down up ## Reinicia o serviço completo

status: ## Verifica se o container está rodando
	docker ps -f name=$(IMAGE_NAME)

clean: ## Remove imagens antigas e arquivos temporários de Python
	docker system prune -f
	find . -type d -name "__pycache__" -exec rm -rf {} +

# --- Operações Docker Hub ---

login: ## Faz login no Docker Hub
	docker login

push: build ## Faz o build e o push da imagem para o Docker Hub
	@echo "🚀 Preparando push para $(FULL_IMAGE_NAME)..."
	docker tag $(IMAGE_NAME):latest $(FULL_IMAGE_NAME):latest
	docker tag $(IMAGE_NAME):latest $(FULL_IMAGE_NAME):$(VERSION)
	docker push $(FULL_IMAGE_NAME):latest
	docker push $(FULL_IMAGE_NAME):$(VERSION)
	@echo "✅ Push para o usuário [$(DOCKER_USER)] finalizado!"

shell: ## Abre um terminal dentro do container rodando
	docker exec -it monitor_olx_salvador /bin/bash