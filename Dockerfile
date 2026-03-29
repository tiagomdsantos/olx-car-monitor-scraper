# Usamos a imagem oficial do Playwright que já vem com Python e dependências de sistema
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Evita que o Python gere arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Instala dependências de sistema extras (se necessário)
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências primeiro (aproveita o cache do Docker)
COPY requirements.txt .

# Instala as bibliotecas do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código do projeto
COPY . .

# Cria a pasta para o banco de dados e garante permissões
RUN mkdir -p data

# Valores padrão (opcional, podem ser vazios)
ENV TELEGRAM_TOKEN=""
ENV TELEGRAM_CHAT_ID=""

# Comando para rodar o robô
CMD ["python", "main.py"]