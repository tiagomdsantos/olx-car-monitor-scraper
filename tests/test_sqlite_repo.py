# tests/test_sqlite_repo.py
import pytest
from infrastructure.database.sqlite_repo import SQLiteRepository

@pytest.fixture
def repo_em_arquivo(tmp_path):
    # tmp_path é uma pasta temporária criada pelo pytest para este teste
    db_file = tmp_path / "banco_teste.db"
    
    # Passamos o caminho do arquivo temporário como se fosse o YAML
    return SQLiteRepository(f"sqlite:///{db_file}")

def test_criar_tabela_ao_iniciar(repo_em_arquivo):
    # Verifica se a tabela foi criada no arquivo temporário
    query = "SELECT name FROM sqlite_master WHERE type='table' AND name='anuncios_processados'"
    with repo_em_arquivo._get_connection() as conn:
        cursor = conn.execute(query)
        tabela_existe = cursor.fetchone() is not None
        
    assert tabela_existe is True

def test_anuncio_nao_processado_retorna_falso(repo_em_arquivo):
    resultado = repo_em_arquivo.anuncio_ja_processado("123456789")
    assert resultado is False

def test_salvar_e_verificar_anuncio(repo_em_arquivo):
    id_teste = "987654321"
    
    # Guarda o anúncio
    repo_em_arquivo.salvar_anuncio_processado(id_teste)
    
    # Agora deve retornar True
    resultado = repo_em_arquivo.anuncio_ja_processado(id_teste)
    assert resultado is True

def test_salvar_anuncio_duplicado_nao_causa_erro(repo_em_arquivo):
    id_teste = "duplicado_123"
    
    # Tentamos guardar o mesmo ID duas vezes
    repo_em_arquivo.salvar_anuncio_processado(id_teste)
    repo_em_arquivo.salvar_anuncio_processado(id_teste)
    
    # O código não deve quebrar (graças ao INSERT OR IGNORE)
    assert repo_em_arquivo.anuncio_ja_processado(id_teste) is True