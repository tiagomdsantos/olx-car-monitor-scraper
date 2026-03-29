import sqlite3
import logging
from datetime import datetime
from typing import Optional, List
from core.interfaces import IRepository

logger = logging.getLogger(__name__)

class SQLiteRepository(IRepository):
    def __init__(self, database_path: str):
        # Limpa o prefixo do YAML se necessário
        self.db_path = database_path.replace("sqlite:///", "")
        self._criar_tabelas()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _criar_tabelas(self):
        """Cria a estrutura completa: IDs processados, Cache FIPE e Tabela Detalhada."""
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
            ''',
            '''
            CREATE TABLE IF NOT EXISTS anuncios_detalhados (
                id_anuncio TEXT PRIMARY KEY,
                titulo TEXT,
                preco_anuncio FLOAT,
                preco_fipe FLOAT,
                percentual_fipe FLOAT,
                ano INTEGER,
                km INTEGER,
                link TEXT,
                bairro TEXT,
                data_captura TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        ]
        try:
            with self._get_connection() as conn:
                for q in queries:
                    conn.execute(q)
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar tabelas SQLite: {e}")

    # --- Métodos de Verificação e Controle ---
    
    def anuncio_ja_processado(self, id_anuncio: str) -> bool:
        query = "SELECT 1 FROM anuncios_processados WHERE id_anuncio = ?"
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, (id_anuncio,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Erro ao verificar o anúncio {id_anuncio}: {e}")
            return False

    def salvar_anuncio_processado(self, id_anuncio: str):
        query = "INSERT OR IGNORE INTO anuncios_processados (id_anuncio) VALUES (?)"
        try:
            with self._get_connection() as conn:
                conn.execute(query, (id_anuncio,))
        except Exception as e:
            logger.error(f"Erro ao salvar ID do anúncio {id_anuncio}: {e}")

    # --- Lógica de Cache FIPE ---

    def obter_preco_cache(self, marca: str, modelo: str, ano: int) -> Optional[float]:
        chave = f"{marca.lower()}_{modelo.lower()}_{ano}"
        query = "SELECT preco FROM cache_fipe WHERE chave_busca = ?"
        try:
            with self._get_connection() as conn:
                res = conn.execute(query, (chave,)).fetchone()
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

    # --- Lógica de Gravação e Atualização (Alerta de Preço) ---

    def salvar_anuncio_completo(self, anuncio, preco_fipe: float):
        self.salvar_anuncio_processado(anuncio.id_anuncio)
        
        percentual = (anuncio.preco / preco_fipe) * 100 if preco_fipe > 0 else 0
        query_detalhe = '''
            INSERT OR REPLACE INTO anuncios_detalhados 
            (id_anuncio, titulo, preco_anuncio, preco_fipe, percentual_fipe, ano, km, link, bairro)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        try:
            with self._get_connection() as conn:
                conn.execute(query_detalhe, (
                    anuncio.id_anuncio, anuncio.titulo, anuncio.preco, 
                    preco_fipe, percentual, anuncio.ano, anuncio.km, 
                    anuncio.link, getattr(anuncio, 'bairro', 'Salvador')
                ))
        except Exception as e:
            logger.error(f"❌ Erro ao salvar dados detalhados de {anuncio.id_anuncio}: {e}")

    def obter_preco_anterior(self, id_anuncio: str) -> float:
        """Busca o último preço registrado para um anúncio de forma segura."""
        query = "SELECT preco_anuncio FROM anuncios_detalhados WHERE id_anuncio = ?"
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(query, (id_anuncio,))
                row = cursor.fetchone()
                return float(row[0]) if row else 0.0
        except Exception as e:
            logger.error(f"Erro ao obter preço anterior de {id_anuncio}: {e}")
            return 0.0

    def atualizar_preco_anuncio(self, id_anuncio: str, novo_preco: float):
        """Atualiza o preço e recalcula o percentual da FIPE após uma queda."""
        try:
            with self._get_connection() as conn:
                # Primeiro pegamos a FIPE para recalcular o percentual
                res = conn.execute("SELECT preco_fipe FROM anuncios_detalhados WHERE id_anuncio = ?", (id_anuncio,)).fetchone()
                preco_fipe = res[0] if res else 0
                novo_percentual = (novo_preco / preco_fipe) * 100 if preco_fipe > 0 else 0

                query = '''
                    UPDATE anuncios_detalhados 
                    SET preco_anuncio = ?, percentual_fipe = ?, data_captura = CURRENT_TIMESTAMP 
                    WHERE id_anuncio = ?
                '''
                conn.execute(query, (novo_preco, novo_percentual, id_anuncio))
                logger.info(f"💾 Banco atualizado: {id_anuncio} agora custa R$ {novo_preco:,.2f}")
        except Exception as e:
            logger.error(f"Erro ao atualizar preço no banco para {id_anuncio}: {e}")