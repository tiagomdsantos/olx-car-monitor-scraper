# config/settings.py
import os
import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional

class AppConfig(BaseModel):
    intervalo_scraping_minutos: int = Field(default=30, ge=5) # Garante pelo menos 5 min para evitar block
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
    complemento_busca: "automatico"
    
class VeiculoConfig(BaseModel):
    marca: str
    modelo: str
    complemento_busca: Optional[str] = None # Opcional, pois nem todos têm (ex: hatch)
    preco_maximo: float
    versoes_aceitas: List[str]

class Settings:
    """Transforma um dicionário em um objeto para acesso via ponto (settings.app.path)."""
    def __init__(self, adict):
        for key, value in adict.items():
            if isinstance(value, dict):
                value = Settings(value)
            elif isinstance(value, list):
                value = [Settings(v) if isinstance(v, dict) else v for v in value]
            setattr(self, key, value)

def load_settings():
    """Carrega o YAML e sobrescreve com as Variáveis de Ambiente."""
    # Localiza o arquivo config.yaml na raiz do projeto
    base_path = Path(__file__).parent.parent
    camin_yaml = base_path / "config" / "config.yaml"
    
    if not camin_yaml.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado em: {camin_yaml}")

    with open(camin_yaml, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    # 1. Prioridade para Variáveis de Ambiente (Docker/Compose)
    token_env = os.getenv("TELEGRAM_TOKEN")
    chat_id_env = os.getenv("TELEGRAM_CHAT_ID")

    if token_env:
        config_dict['app']['telegram_token'] = token_env
        print("✅ Usando TELEGRAM_TOKEN das variáveis de ambiente.")
    
    if chat_id_env:
        config_dict['app']['telegram_chat_id'] = chat_id_env
        print("✅ Usando TELEGRAM_CHAT_ID das variáveis de ambiente.")

    # 2. Retorna como objeto Settings para permitir acesso settings.app.xxx
    return Settings(config_dict)

# Exemplo de uso rápido para teste local:
if __name__ == "__main__":
    try:
        configuracoes = load_settings()
        print(f"Configuração carregada com sucesso!")
        print(f"Monitorando {len(configuracoes.veiculos)} veículos "
              f"em {len(configuracoes.localizacoes)} localizações.")
        print(f"Token do Telegram configurado: {'Sim' if configuracoes.app.telegram_token else 'Não'}")
    except Exception as e:
        print(f"Erro ao carregar configurações: {e}")