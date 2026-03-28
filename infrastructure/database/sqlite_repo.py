# infrastructure/database/sqlite_repo.py
import sqlite3
import logging
from core.interfaces import IRepository

logger = logging.getLogger(__name__)

class SQLiteRepository(IRepository):
    """
    Implementação concreta do repositório utilizando SQLite.
    Guarda os IDs dos anúncios processados para evitar alertas duplicados.
    """
    def __init__(self, database_path: str):
        # Se a string vier com o formato do YAML "sqlite:///nome.db", limpamos o prefixo
        self.db_path = database_path.replace("sqlite:///", "")
        self._criar_tabela()

    def _get_connection(self):
        """Abre a ligação à base de dados SQLite."""
        return sqlite3.connect(self.db_path)

    def _criar_tabela(self):
        """Cria a tabela se ela ainda não existir no ficheiro."""
        query = '''
            CREATE TABLE IF NOT EXISTS anuncios_processados (
                id_anuncio TEXT PRIMARY KEY,
                data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
        try:
            with self._get_connection() as conn:
                conn.execute(query)
        except Exception as e:
            logger.error(f"Erro ao criar a tabela na base de dados: {e}")

    def anuncio_ja_processado(self, id_anuncio: str) -> bool:
        """Verifica se um ID de anúncio já existe na base de dados."""
        query = "SELECT 1 FROM anuncios_processados WHERE id_anuncio = ?"
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, (id_anuncio,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Erro ao verificar o anúncio {id_anuncio}: {e}")
            return False

    def salvar_anuncio_processado(self, id_anuncio: str):
        """Guarda o ID do anúncio. Usa INSERT OR IGNORE para evitar erros de duplicação."""
        query = "INSERT OR IGNORE INTO anuncios_processados (id_anuncio) VALUES (?)"
        try:
            with self._get_connection() as conn:
                conn.execute(query, (id_anuncio,))
        except Exception as e:
            logger.error(f"Erro ao guardar o anúncio {id_anuncio}: {e}")