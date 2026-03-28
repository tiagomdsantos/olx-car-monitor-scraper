# tests/test_settings.py
import pytest
import yaml
from pydantic import ValidationError
from config.settings import load_settings, Settings

# Fixture: Fornece um dicionário válido para usarmos nos testes
@pytest.fixture
def configuracao_valida():
    return {
        "app": {
            "intervalo_scraping_minutos": 30,
            "telegram_token": "token_falso_123",
            "telegram_chat_id": "chat_falso_123",
            "database_path": "sqlite:///banco_teste.db"
        },
        "localizacoes": [
            {"estado": "ba", "regiao": "salvador"}
        ],
        "filtros_globais": {
            "ano_minimo": 2019,
            "preco_maximo_global": 115000.0,
            "motor_minimo": "1.2"
        },
        "veiculos": [
            {
                "marca": "toyota",
                "modelo": "corolla",
                "preco_maximo": 115000.0,
                "versoes_aceitas": ["todas"]
            }
        ]
    }

def test_load_settings_com_arquivo_valido(tmp_path, configuracao_valida):
    # Cria um arquivo YAML temporário válido
    arquivo_yaml = tmp_path / "config_teste.yaml"
    with open(arquivo_yaml, 'w', encoding='utf-8') as f:
        yaml.dump(configuracao_valida, f)
    
    # Executa a função
    settings = load_settings(str(arquivo_yaml))
    
    # Verifica se carregou corretamente
    assert isinstance(settings, Settings)
    assert settings.app.intervalo_scraping_minutos == 30
    assert settings.filtros_globais.ano_minimo == 2019
    assert len(settings.veiculos) == 1

def test_load_settings_arquivo_nao_encontrado():
    # Deve lançar FileNotFoundError se o caminho for inválido
    with pytest.raises(FileNotFoundError):
        load_settings("caminho_que_nao_existe.yaml")

def test_load_settings_erro_validacao_tipo(tmp_path, configuracao_valida):
    # Sabota a configuração colocando uma string onde deveria ser int
    configuracao_valida["filtros_globais"]["ano_minimo"] = "dois mil e dezenove"
    
    arquivo_yaml = tmp_path / "config_erro_tipo.yaml"
    with open(arquivo_yaml, 'w', encoding='utf-8') as f:
        yaml.dump(configuracao_valida, f)
    
    # Pydantic deve barrar e lançar ValidationError
    with pytest.raises(ValidationError):
        load_settings(str(arquivo_yaml))

def test_load_settings_erro_validacao_regra_negocio(tmp_path, configuracao_valida):
    # Sabota a configuração colocando um intervalo menor que o permitido (ge=5)
    configuracao_valida["app"]["intervalo_scraping_minutos"] = 2
    
    arquivo_yaml = tmp_path / "config_erro_regra.yaml"
    with open(arquivo_yaml, 'w', encoding='utf-8') as f:
        yaml.dump(configuracao_valida, f)
    
    # Pydantic deve barrar por violar o limite mínimo
    with pytest.raises(ValidationError) as exc_info:
        load_settings(str(arquivo_yaml))
    
    # Opcional: Verifica se a mensagem de erro menciona o campo correto
    assert "intervalo_scraping_minutos" in str(exc_info.value)