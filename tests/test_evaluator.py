# tests/test_evaluator.py
import pytest
from unittest.mock import Mock
from core.evaluator import CarEvaluator
from core.models import Anuncio

@pytest.fixture
def mock_deps():
    # 1. Configura os filtros globais com valores REAIS (inteiros e floats)
    filtros_mock = Mock()
    filtros_mock.ano_minimo = 2019
    filtros_mock.fipe_alerta_abaixo_de_percentual = 75.0
    filtros_mock.fipe_oportunidade_ate_percentual = 95.0

    # 2. Configura o objeto Settings
    settings_mock = Mock()
    settings_mock.filtros_globais = filtros_mock
    
    # 3. Configura o veículo monitorado
    mock_veiculo = Mock()
    mock_veiculo.marca = "toyota"
    mock_veiculo.modelo = "corolla"
    mock_veiculo.preco_maximo = 150000.0
    mock_veiculo.versoes_aceitas = ["todas"]
    settings_mock.veiculos = [mock_veiculo]

    return {
        "settings": settings_mock,
        "fipe_client": Mock(),
        "repository": Mock(),
        "notifier": Mock()
    }

def test_deve_ignorar_anuncio_ja_processado(mock_deps):
    mock_deps["repository"].anuncio_ja_processado.return_value = True
    
    evaluator = CarEvaluator(**mock_deps)
    # CORREÇÃO: id_anuncio em vez de id_bom
    anuncio = Anuncio(
        id_anuncio="id1", 
        titulo="Toyota Corolla XEi", 
        preco=100000.0, 
        ano=2021, 
        km=10000, 
        link="link", 
        marca="Toyota", 
        modelo="Corolla"
    )
    
    evaluator.processar_anuncio(anuncio)
    assert mock_deps["fipe_client"].consultar_preco_medio.call_count == 0

def test_deve_detectar_golpe_e_nao_notificar(mock_deps):
    mock_deps["repository"].anuncio_ja_processado.return_value = False
    mock_deps["fipe_client"].consultar_preco_medio.return_value = 100000.0
    
    evaluator = CarEvaluator(**mock_deps)
    
    # Preço 50.000 para FIPE 100.000 (50% - Golpe)
    anuncio_golpe = Anuncio(
        id_anuncio="id_golpe", 
        titulo="Toyota Corolla XEi", 
        preco=50000.0, 
        ano=2021, 
        km=10000, 
        link="link", 
        marca="Toyota", 
        modelo="Corolla"
    )
    
    evaluator.processar_anuncio(anuncio_golpe)
    
    # Deve salvar no banco (para não reanalisar), mas não deve notificar
    assert mock_deps["repository"].salvar_anuncio_processado.call_count == 1
    assert mock_deps["notifier"].enviar_alerta.call_count == 0

def test_deve_notificar_oportunidade_real(mock_deps):
    mock_deps["repository"].anuncio_ja_processado.return_value = False
    mock_deps["fipe_client"].consultar_preco_medio.return_value = 100000.0
    
    evaluator = CarEvaluator(**mock_deps)
    
    # Preço 90.000 para FIPE 100.000 (90% - Oportunidade)
    anuncio_bom = Anuncio(
        id_anuncio="id_bom", 
        titulo="Toyota Corolla XEi", 
        preco=90000.0, 
        ano=2021, 
        km=10000, 
        link="link", 
        marca="Toyota", 
        modelo="Corolla"
    )
    
    evaluator.processar_anuncio(anuncio_bom)
    
    # Deve disparar o alerta para o Telegram
    assert mock_deps["notifier"].enviar_alerta.call_count == 1