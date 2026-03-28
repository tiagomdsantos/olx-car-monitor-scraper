# config/settings.py
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

class VeiculoConfig(BaseModel):
    marca: str
    modelo: str
    complemento_busca: Optional[str] = None # Opcional, pois nem todos têm (ex: hatch)
    preco_maximo: float
    versoes_aceitas: List[str]

class Settings(BaseModel):
    app: AppConfig
    localizacoes: List[LocalizacaoConfig]
    filtros_globais: FiltrosGlobaisConfig
    veiculos: List[VeiculoConfig]

def load_settings(yaml_path: str = "config/config.yaml") -> Settings:
    """
    Lê o arquivo YAML e retorna um objeto Settings tipado e validado.
    """
    caminho = Path(yaml_path)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {caminho.absolute()}")

    with open(caminho, 'r', encoding='utf-8') as file:
        dados_yaml = yaml.safe_load(file)

    # O Pydantic faz a mágica de validar e instanciar tudo aqui
    return Settings(**dados_yaml)

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