# infrastructure/database/sqlite_repo.py
import sqlite3
import logging
from typing import Optional
from core.interfaces import IRepository

logger = logging.getLogger(__name__)

class SQLiteRepository(IRepository):
    def __init__(self, database_path: str):
        self.db_path = database_path.replace("sqlite:///", "")
        self._criar_tabelas()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _criar_tabelas(self):
        """Cria as tabelas de processamento e de cache da FIPE."""
        queries = [
            '''
            CREATE TABLE IF NOT EXISTS anuncios_processados (
                id_anuncio TEXT PRIMARY KEY,
                data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS cache_fipe (
                chave_busca TEXT PRIMARY KEY,
                preco FLOAT,
                data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        ]
        try:
            with self._get_connection() as conn:
                for q in queries:
                    conn.execute(q)
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar tabelas SQLite: {e}")

    # --- Lógica de Anúncios ---
    def anuncio_ja_processado(self, id_anuncio: str) -> bool:
        query = "SELECT 1 FROM anuncios_processados WHERE id_anuncio = ?"
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, (id_anuncio,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Erro ao verificar anúncio {id_anuncio}: {e}")
            return False

    def salvar_anuncio_processado(self, id_anuncio: str):
        query = "INSERT OR IGNORE INTO anuncios_processados (id_anuncio) VALUES (?)"
        try:
            with self._get_connection() as conn:
                conn.execute(query, (id_anuncio,))
        except Exception as e:
            logger.error(f"Erro ao guardar anúncio {id_anuncio}: {e}")

    # --- Lógica de Cache FIPE ---
    def obter_preco_cache(self, marca: str, modelo: str, ano: int) -> Optional[float]:
        chave = f"{marca.lower()}_{modelo.lower()}_{ano}"
        query = "SELECT preco FROM cache_fipe WHERE chave_busca = ?"
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, (chave,))
                res = cursor.fetchone()
                return res[0] if res else None
        except Exception as e:
            logger.error(f"Erro ao ler cache FIPE: {e}")
            return None

    def salvar_preco_cache(self, marca: str, modelo: str, ano: int, preco: float):
        chave = f"{marca.lower()}_{modelo.lower()}_{ano}"
        query = "INSERT OR REPLACE INTO cache_fipe (chave_busca, preco) VALUES (?, ?)"
        try:
            with self._get_connection() as conn:
                conn.execute(query, (chave, preco))
        except Exception as e:
            logger.error(f"Erro ao salvar cache FIPE: {e}")