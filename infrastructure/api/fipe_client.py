# infrastructure/api/fipe_client.py
import requests
import logging
import time
from typing import Optional, List, Dict
from core.interfaces import IFipeClient

logger = logging.getLogger(__name__)

class ParallelumFipeClient(IFipeClient):
    """
    Cliente FIPE com Rate Limiting para evitar erro 429.
    Fluxo: Marca -> Modelo -> Ano -> Valor.
    """
    BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros"

    def __init__(self):
        self._cache_marcas: List[Dict] = []
        self._cache_modelos: Dict[str, List[Dict]] = {}
        # User-Agent honesto ajuda a evitar bloqueios agressivos
        self._headers = {'User-Agent': 'MonitorOfertasSalvador/1.0 (Python/Requests)'}

    def _requisicao_segura(self, url: str, tentativas: int = 3) -> Optional[dict]:
        """
        Executa chamadas à API com delay de 1.5s e retry em caso de Erro 429.
        """
        for i in range(tentativas):
            # Delay preventivo (Crucial para não ser bloqueado pela Parallelum)
            time.sleep(1.5)
            
            try:
                response = requests.get(url, headers=self._headers, timeout=12)
                
                if response.status_code == 429:
                    espera = 35 * (i + 1) # Aumenta o tempo a cada erro
                    logger.warning(f"⏳ Limite excedido (429). Aguardando {espera}s antes de tentar: {url}")
                    time.sleep(espera)
                    continue
                
                response.raise_for_status()
                return response.json()
            
            except Exception as e:
                logger.error(f"❌ Erro na chamada FIPE ({url}): {e}")
                if i == tentativas - 1: return None
        return None

    def _obter_codigo_marca(self, nome_marca: str) -> Optional[str]:
        if not self._cache_marcas:
            dados = self._requisicao_segura(f"{self.BASE_URL}/marcas")
            if dados:
                self._cache_marcas = dados
            else:
                return None
        
        nome_clean = nome_marca.lower().strip()
        for m in self._cache_marcas:
            if nome_clean in m['nome'].lower():
                return str(m['codigo'])
        return None

    def _obter_codigo_modelo(self, codigo_marca: str, nome_modelo: str) -> Optional[str]:
        if codigo_marca not in self._cache_modelos:
            dados = self._requisicao_segura(f"{self.BASE_URL}/marcas/{codigo_marca}/modelos")
            if dados:
                # A API retorna um dicionário com a chave 'modelos'
                self._cache_modelos[codigo_marca] = dados.get('modelos', [])
            else:
                return None

        nome_busca = nome_modelo.lower().strip()
        modelos = self._cache_modelos[codigo_marca]
        
        # Match exato primeiro
        for m in modelos:
            if nome_busca == m['nome'].lower():
                return str(m['codigo'])
        
        # Match parcial depois
        for m in modelos:
            if nome_busca in m['nome'].lower():
                return str(m['codigo'])
        
        return None

    def consultar_preco_medio(self, marca: str, modelo: str, ano: int) -> float:
        """
        Consulta o preço médio real na FIPE com tratamento de erros e delay.
        """
        try:
            # 1. Código da Marca
            cod_marca = self._obter_codigo_marca(marca)
            if not cod_marca: return 0.0

            # 2. Código do Modelo
            cod_modelo = self._obter_codigo_modelo(cod_marca, modelo)
            if not cod_modelo: return 0.0

            # 3. Código do Ano (ex: 2023 -> 2023-1)
            url_anos = f"{self.BASE_URL}/marcas/{cod_marca}/modelos/{cod_modelo}/anos"
            lista_anos = self._requisicao_segura(url_anos)
            if not lista_anos: return 0.0

            cod_ano = None
            str_ano = str(ano)
            for a in lista_anos:
                if a['codigo'].startswith(str_ano):
                    cod_ano = a['codigo']
                    break
            
            # Fallback para Zero KM
            if not cod_ano and ano >= 2025:
                for a in lista_anos:
                    if "32000" in a['codigo']:
                        cod_ano = a['codigo']
                        break

            if not cod_ano:
                logger.warning(f"⚠️ Ano {ano} não disponível para {marca} {modelo}")
                return 0.0

            # 4. Preço Final
            url_valor = f"{self.BASE_URL}/marcas/{cod_marca}/modelos/{cod_modelo}/anos/{cod_ano}"
            dados_valor = self._requisicao_segura(url_valor)
            if not dados_valor: return 0.0

            # Limpeza do R$ e conversão
            valor_str = dados_valor.get('Valor', '0')
            valor_limpo = valor_str.replace('R$', '').replace('.', '').replace(',', '.').replace(' ', '').strip()
            
            preco = float(valor_limpo)
            logger.info(f"📊 FIPE Consultada: {marca} {modelo} ({ano}) -> R$ {preco:,.2f}")
            return preco

        except Exception as e:
            logger.error(f"❌ Erro fatal ao consultar FIPE: {e}")
            return 0.0