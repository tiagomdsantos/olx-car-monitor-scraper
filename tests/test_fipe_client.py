# tests/test_fipe_client.py
import pytest
from unittest.mock import patch, Mock
from infrastructure.api.fipe_client import ParallelumFipeClient

@pytest.fixture
def fipe_client():
    return ParallelumFipeClient()

@patch('infrastructure.api.fipe_client.requests.get')
def test_obter_marcas_com_cache(mock_get, fipe_client):
    mock_response = Mock()
    mock_response.json.return_value = [
        {"nome": "Honda", "codigo": "26"},
        {"nome": "Toyota", "codigo": "56"}
    ]
    mock_get.return_value = mock_response

    marcas = fipe_client._obter_marcas()
    assert len(marcas) == 2
    assert mock_get.call_count == 1

    marcas_cache = fipe_client._obter_marcas()
    assert mock_get.call_count == 1

@patch('infrastructure.api.fipe_client.requests.get')
def test_obter_codigo_marca_existente(mock_get, fipe_client):
    mock_response = Mock()
    mock_response.json.return_value = [{"nome": "Nissan", "codigo": "43"}]
    mock_get.return_value = mock_response

    codigo = fipe_client._obter_codigo_marca("nIsSaN")
    assert codigo == "43"

@patch('infrastructure.api.fipe_client.requests.get')
def test_consultar_preco_medio_retorno_simulado(mock_get, fipe_client):
    # Agora sim! O teste está preso na jaula do mock.
    
    # Vamos criar uma função para simular diferentes respostas da API 
    # dependendo da URL que o código tentar acessar.
    def mock_get_side_effect(url, **kwargs):
        mock_resp = Mock()
        if url.endswith("/marcas"):
            mock_resp.json.return_value = [{"nome": "Honda", "codigo": "26"}]
        elif url.endswith("/modelos"):
            mock_resp.json.return_value = {"modelos": [{"nome": "City Hatch", "codigo": "123"}]}
        return mock_resp
        
    mock_get.side_effect = mock_get_side_effect
    
    preco_honda = fipe_client.consultar_preco_medio("Honda", "City", 2023)
    assert preco_honda == 125000.0