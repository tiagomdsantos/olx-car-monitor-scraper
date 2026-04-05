import os
import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional

# --- MODELOS PYDANTIC (Para documentação/referência de tipagem) ---

class AppConfig(BaseModel):
    intervalo_scraping_minutos: int = Field(default=30, ge=5)
    telegram_token: str
    telegram_chat_id: str
    database_path: str

class LocalizacaoConfig(BaseModel):
    estado: str
    regiao: str

class FiltrosGlobaisConfig(BaseModel):
    ano_minimo: int = Field(ge=2000)
    preco_maximo_global: float
    motor_minimo: str
    fipe_alerta_abaixo_de_percentual: float = Field(default=75.0)
    fipe_oportunidade_ate_percentual: float = Field(default=95.0)
    complemento_busca: str

class VeiculoConfig(BaseModel):
    marca: str
    modelo: str
    complemento_busca: Optional[str] = None
    preco_maximo: float
    versoes_aceitas: List[str]

# Modelos do Score
class ScorePesosConfig(BaseModel):
    preco: float
    km: float
    ano: float
    fipe: float

class ScoreConfig(BaseModel):
    pesos: ScorePesosConfig

# NOVO: Modelo da FIPE
class FipeConfig(BaseModel):
    dias_cache: int = Field(default=15, description="Quantidade de dias para manter o valor do carro salvo no SQLite")

# --- CLASSE DINÂMICA DE CONFIGURAÇÃO ---

class Settings:
    def __init__(self, adict):
        for key, value in adict.items():
            if isinstance(value, dict):
                value = Settings(value)
            elif isinstance(value, list):
                value = [Settings(v) if isinstance(v, dict) else v for v in value]
            setattr(self, key, value)

def load_settings():
    # Caminho do YAML
    base_dir = Path(__file__).resolve().parent.parent
    caminho_yaml = base_dir / "config" / "config.yaml"
    
    # Se estiver no Docker, o volume monta aqui:
    if not caminho_yaml.exists():
        caminho_yaml = Path("/app/config/config.yaml")

    with open(caminho_yaml, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    # 🛡️ INJEÇÃO OBRIGATÓRIA DAS CREDENCIAIS (Exclusivo via ENV)
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise ValueError("❌ ERRO CRÍTICO: TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não definidos no ambiente/.env")

    # Garante que a estrutura 'app' existe no dict antes de injetar
    if 'app' not in config_dict:
        config_dict['app'] = {}
        
    config_dict['app']['telegram_token'] = token
    config_dict['app']['telegram_chat_id'] = chat_id

    # O construtor dinâmico vai mapear tudo automaticamente
    return Settings(config_dict)

if __name__ == "__main__":
    try:
        configuracoes = load_settings()
        print(f"✅ Configuração carregada com sucesso!")
        print(f"📊 Peso Preço: {configuracoes.score.pesos.preco}")
        print(f"💾 Fipe Dias Cache: {configuracoes.fipe.dias_cache}")
    except Exception as e:
        print(f"Erro ao carregar configurações: {e}")