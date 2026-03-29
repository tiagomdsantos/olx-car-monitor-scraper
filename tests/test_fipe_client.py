import pytest
from infrastructure.api.fipe_client import ParallelumFipeClient

def test_consultar_preco_medio_real():
    client = ParallelumFipeClient()
    # Teste com um carro comum (Toyota Corolla 2020)
    # Nota: Este teste requer internet ou um mock de requests
    preco = client.consultar_preco_medio("Toyota", "Corolla", 2020)
    
    assert isinstance(preco, float)
    if preco > 0:
        assert preco > 50000  # Corolla 2020 certamente vale mais que 50k
    else:
        # Se a API falhar, o retorno deve ser 0.0, não erro
        assert preco == 0.0

def test_modelo_inexistente_retorna_zero():
    client = ParallelumFipeClient()
    preco = client.consultar_preco_medio("MarcaInexistente", "ModeloX", 2024)
    assert preco == 0.0