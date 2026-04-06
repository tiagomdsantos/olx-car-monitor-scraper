import sqlite3
import logging
from datetime import datetime
from core.interfaces import IRepository
from core.models import Anuncio

logger = logging.getLogger(__name__)

class SQLiteRepository(IRepository):
    def __init__(self, db_path: str):
        # Remove o prefixo sqlite:/// se existir, para compatibilidade com a lib nativa
        self.db_path = db_path.replace("sqlite:///", "")
        self._criar_tabelas()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _criar_tabelas(self):
        """Garante que todas as tabelas e colunas existam antes de qualquer leitura/escrita."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Tabela de Controle de Loop (Evita reprocessar o que já foi descartado)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS anuncios_processados (
                        id_anuncio TEXT PRIMARY KEY,
                        data_processamento TEXT
                    )
                """)

                # 2. Tabela de Análises Detalhadas (O coração dos seus Gráficos)
                # OBS: Adicionada a coluna 'categoria' para o filtro Hatch/Sedan/SUV
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS anuncios_detalhados (
                        id_anuncio TEXT PRIMARY KEY,
                        titulo TEXT,
                        preco_anuncio REAL,
                        preco_fipe REAL,
                        percentual_fipe REAL,
                        km INTEGER,
                        ano INTEGER,
                        link TEXT,
                        bairro TEXT,
                        data_processamento TEXT,
                        categoria TEXT,
                        elite_score REAL
                    )
                """)

                # 3. Tabela de Configurações Dinâmicas e Estado do Bot
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bot_metadata (
                        chave TEXT PRIMARY KEY,
                        valor TEXT
                    )
                """)

                # 4. Tabela de Cache da Tabela FIPE (Economiza requisições)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cache_fipe (
                        marca TEXT,
                        modelo TEXT,
                        ano INTEGER,
                        preco REAL,
                        data_consulta TEXT,
                        PRIMARY KEY (marca, modelo, ano)
                    )
                """)
                try:
                    cursor.execute("ALTER TABLE anuncios_detalhados ADD COLUMN elite_score REAL DEFAULT 0.0")
                    logger.info("🛠️ Banco de dados atualizado: Coluna 'elite_score' adicionada com sucesso!")
                except sqlite3.OperationalError:
                    # O erro dispara se a coluna já existir, então podemos ignorar silenciosamente
                    pass
                    
                conn.commit()
                logger.debug("✅ Estrutura do banco de dados verificada/criada com sucesso.")
        except Exception as e:
            logger.error(f"❌ Erro fatal ao criar tabelas no SQLite: {e}")

    # --- METADATA (Estado do Bot) ---

    def ler_metadata(self, chave: str) -> str:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT valor FROM bot_metadata WHERE chave = ?", (chave,))
                row = cursor.fetchone()
                return row[0] if row else ""
        except Exception as e:
            logger.error(f"Erro ao ler metadata {chave}: {e}")
            return ""

    def salvar_metadata(self, chave: str, valor: str):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO bot_metadata (chave, valor)
                    VALUES (?, ?)
                    ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor
                """, (chave, str(valor)))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar metadata {chave}: {e}")

    # --- ANÚNCIOS ---

    def anuncio_ja_processado(self, id_anuncio: str, dias_expiracao: int = 7) -> bool:
        """
        Verifica se o anúncio está na lista de processados e se o silêncio ainda é válido.
        Se já tiverem passado 'dias_expiracao' (ex: 7 dias), permite que o bot volte a avaliar.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Tentar adicionar a coluna silenciosamente caso a base de dados seja a antiga
            try:
                cursor.execute("ALTER TABLE anuncios_processados ADD COLUMN data_processamento TEXT")
            except sqlite3.OperationalError:
                pass # A coluna já existe, podemos prosseguir

            cursor.execute("SELECT data_processamento FROM anuncios_processados WHERE id_anuncio = ?", (id_anuncio,))
            resultado = cursor.fetchone()
            
            if resultado:
                data_str = resultado[0]
                if data_str:
                    data_salva = datetime.fromisoformat(data_str)
                    agora = datetime.now()
                    
                    # Se já passaram os dias estipulados, retornamos False para ele ser reavaliado!
                    if (agora - data_salva).days >= dias_expiracao:
                        return False 
                
                # Caso não tenha data (registo antigo) ou ainda esteja no período de silêncio
                return True
                
        return False

    def salvar_anuncio_processado(self, id_anuncio: str):
        """
        Guarda o ID na base de dados com a data e hora actuais para iniciar a contagem.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            agora = datetime.now().isoformat()
            
            try:
                cursor.execute("ALTER TABLE anuncios_processados ADD COLUMN data_processamento TEXT")
            except sqlite3.OperationalError:
                pass
                
            # Verifica se já existe para actualizar a data, ou insere um novo
            cursor.execute("SELECT 1 FROM anuncios_processados WHERE id_anuncio = ?", (id_anuncio,))
            if cursor.fetchone():
                cursor.execute("UPDATE anuncios_processados SET data_processamento = ? WHERE id_anuncio = ?", (agora, id_anuncio))
            else:
                cursor.execute("INSERT INTO anuncios_processados (id_anuncio, data_processamento) VALUES (?, ?)", (id_anuncio, agora))
                
            conn.commit()

    def salvar_anuncio_completo(self, anuncio: Anuncio, preco_fipe: float, score: float = 0.0): # <-- Adiciona o parâmetro score
        try:
            percentual = (anuncio.preco / preco_fipe * 100) if preco_fipe > 0 else 0.0
            bairro = getattr(anuncio, 'bairro', '')
            categoria = getattr(anuncio, 'categoria', '')

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO anuncios_detalhados 
                    (id_anuncio, titulo, preco_anuncio, preco_fipe, percentual_fipe, km, ano, link, bairro, data_processamento, categoria, elite_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    anuncio.id_anuncio, anuncio.titulo, anuncio.preco, preco_fipe, 
                    percentual, anuncio.km, anuncio.ano, anuncio.link, bairro, 
                    datetime.now().isoformat(), categoria, score # <-- Grava o score
                ))
                
                # Marca também como processado para não avaliar de novo no próximo scan
                cursor.execute(
                    "INSERT OR IGNORE INTO anuncios_processados (id_anuncio, data_processamento) VALUES (?, ?)",
                    (anuncio.id_anuncio, datetime.now().isoformat())
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar dados detalhados do anúncio {anuncio.id_anuncio}: {e}")

    def obter_preco_anterior(self, id_anuncio: str) -> float:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT preco_anuncio FROM anuncios_detalhados WHERE id_anuncio = ?", (id_anuncio,))
                row = cursor.fetchone()
                return row[0] if row else 0.0
        except Exception as e:
            logger.error(f"Erro ao buscar preço anterior {id_anuncio}: {e}")
            return 0.0

    def atualizar_preco_anuncio(self, id_anuncio: str, novo_preco: float):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Atualiza o preço e recalcula o percentual da FIPE dinamicamente
                cursor.execute("""
                    UPDATE anuncios_detalhados 
                    SET preco_anuncio = ?, 
                        percentual_fipe = CASE WHEN preco_fipe > 0 THEN (? / preco_fipe) * 100 ELSE 0 END,
                        data_processamento = ?
                    WHERE id_anuncio = ?
                """, (novo_preco, novo_preco, datetime.now().isoformat(), id_anuncio))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar preço do anúncio {id_anuncio}: {e}")

    # --- CACHE FIPE ---

    def obter_preco_cache(self, marca: str, modelo: str, ano: int) -> float:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT preco FROM cache_fipe WHERE marca = ? AND modelo = ? AND ano = ?",
                    (marca, modelo, ano)
                )
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Erro ao ler cache FIPE: {e}")
            return None

    def salvar_preco_cache(self, marca: str, modelo: str, ano: int, preco: float):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO cache_fipe (marca, modelo, ano, preco, data_consulta)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(marca, modelo, ano) DO UPDATE SET preco=excluded.preco, data_consulta=excluded.data_consulta
                """, (marca, modelo, ano, preco, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro ao salvar cache FIPE: {e}")

    def resetar_anuncios(self) -> bool:
        """
        Limpa o histórico e os dados detalhados de todos os anúncios.
        Preserva a estrutura das tabelas, o cache da FIPE e os metadados do bot.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Deleta apenas as linhas de dados, mantendo as tabelas intactas
                cursor.execute("DELETE FROM anuncios_processados")
                cursor.execute("DELETE FROM anuncios_detalhados")
                
                conn.commit()
                logger.info("🗑️ Banco de anúncios resetado com sucesso (Cache FIPE e Metadata preservados).")
                return True
        except Exception as e:
            logger.error(f"❌ Erro ao tentar resetar as tabelas de anúncios: {e}")
            return False