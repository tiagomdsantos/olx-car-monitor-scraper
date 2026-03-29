# 🚗 Monitor de Ofertas OLX - Salvador/BA

Este é um robô de monitoramento inteligente para encontrar oportunidades de veículos seminovos em Salvador e Região Metropolitana. Ele varre a OLX, valida os preços contra a **Tabela FIPE** em tempo real e notifica as melhores ofertas diretamente no **Telegram**.

## 🚀 Funcionalidades Principais

* **Scraping Inteligente:** Extrai dados via JSON (`__NEXT_DATA__`) da OLX, evitando erros de parsing de HTML.
* **Validação FIPE:** Consulta automática da API FIPE para cada modelo e ano encontrado.
* **Cache Local:** Armazena preços da FIPE em SQLite para evitar bloqueios de API (Rate Limit 429) e acelerar buscas repetidas.
* **Filtros Avançados:** * Blacklist de termos (Leilão, Sinistro, Repasse, etc.).
    * Preço máximo personalizado por modelo de carro.
    * Filtro de oportunidade (notifica apenas se o preço for X% abaixo da FIPE).
* **Dockerizado:** Pronto para rodar 24/7 em qualquer servidor usando Docker e Docker Compose.
* **Filtros Avançados (v1.1.0)**: * Blacklist: Ignora termos como Leilão, Sinistro, Repasse, RS, etc.
* **Preço por Modelo**: Limites financeiros específicos para cada veículo configurado.
* **Trava de Odômetro**: Filtro global de KM máximo e média de KM/Ano (identifica carros de aplicativo ou frotas).
* **Análise de Oportunidade**: Notifica apenas se o preço estiver dentro da margem % da FIPE desejada.
* **Dockerizado**: Arquitetura pronta para rodar 24/7 com isolamento total.

## 🛠️ Tecnologias Utilizadas

* **Python 3.11+**
* **Playwright:** Para navegação e extração de dados.
* **SQLite:** Banco de dados para persistência e cache.
* **Docker & Docker Compose:** Containerização.
* **Telegram Bot API:** Para notificações em tempo real.

## ⚙️ Configuração

### 1. Requisitos
* Docker e Docker Compose instalados.
* Um bot no Telegram (criado via [@BotFather](https://t.me/botfather)).

### 2. Variáveis de Ambiente
Crie um arquivo `.env` na raiz do projeto:
```ini
TELEGRAM_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui
DOCKER_USER=seu_usuario_dockerhub
```
### 3. Ajustar Filtros
Edite o arquivo config/config.yaml para definir quais carros e regiões você deseja monitorar:
```ini
filtros_globais:
  km_maximo_global: 65000
  km_ano_maximo: 13000
veiculos:
  - marca: "toyota"
    modelo: "corolla"
    preco_maximo: 105000
localizacoes:
  - estado: "ba"
    regiao: "salvador"
```
## Como Rodar
Via Docker (Recomendado):
```ini
docker compose up -d --build
```

Via Python Local (Ubuntu):
```ini
pip install -r requirements.txt
playwright install chromium
python3 main.py
```
## 📊 Estrutura de Dados (Análise de Mercado)
O robô alimenta uma tabela detalhada no SQLite (data/anuncios.db) que permite análises posteriores como:

Média de preço por bairro em Salvador.

Depreciação real vs Tabela FIPE local.

Ranking de lojistas vs particulares.

## ⚠️ Notas de Versão

* **v1.1.0**
    * Implementação completa do fluxo Scraper (Playwright) -> Evaluator -> Notificação.
    * Sistema de Cache FIPE via SQLite para evitar erros `429 Too Many Requests`.
    * Suporte a Docker e Docker Compose com imagem Playwright v1.58.0.
    * Filtros personalizados por modelo e blacklist de termos (Leilão/Sinistro).
    * Persistência detalhada de dados para análise de mercado em Salvador.
* **v1.0.0 (Lançamento Inicial)**
    * Lançamento inicial com Scraper Playwright, Cache FIPE e Notificações Telegram.

# 📄 Licença
Uso livre para fins de estudo e monitoramento de mercado.

# 👨‍💻 Autor
Tiago Morais