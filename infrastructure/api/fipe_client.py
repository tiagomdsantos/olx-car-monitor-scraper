# infrastructure/api/fipe_client.py
import requests
import logging
from typing import Optional, List, Dict
from core.interfaces import IFipeClient

logger = logging.getLogger(__name__)

class ParallelumFipeClient(IFipeClient):
    """
    Cliente FIPE robusto usando a API Parallelum.
    Implementa busca em cascata: Marca -> Modelo -> Ano -> Valor.
    """
    BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros"

    def __init__(self):
        self._cache_marcas: List[Dict] = []
        self._cache_modelos: Dict[str, List[Dict]] = {}
        # Header para evitar bloqueios e identificar a requisição
        self._headers = {'User-Agent': 'MonitorOfertasOLX/1.0 (Python)'}

    def _obter_codigo_marca(self, nome_marca: str) -> Optional[str]:
        """Busca o código numérico da marca (ex: Toyota = 56)."""
        if not self._cache_marcas:
            try:
                response = requests.get(f"{self.BASE_URL}/marcas", headers=self._headers, timeout=10)
                response.raise_for_status()
                self._cache_marcas = response.json()
            except Exception as e:
                logger.error(f"❌ Erro ao buscar marcas FIPE: {e}")
                return None
        
        nome_marca_clean = nome_marca.lower().strip()
        for m in self._cache_marcas:
            if nome_marca_clean in m['nome'].lower():
                return str(m['codigo'])
        return None

    def _obter_codigo_modelo(self, codigo_marca: str, nome_modelo: str) -> Optional[str]:
        """Busca o código do modelo dentro de uma marca (ex: Corolla = 2500)."""
        if codigo_marca not in self._cache_modelos:
            try:
                url = f"{self.BASE_URL}/marcas/{codigo_marca}/modelos"
                response = requests.get(url, headers=self._headers, timeout=10)
                response.raise_for_status()
                self._cache_modelos[codigo_marca] = response.json().get('modelos', [])
            except Exception as e:
                logger.error(f"❌ Erro ao buscar modelos para marca {codigo_marca}: {e}")
                return None

        nome_busca = nome_modelo.lower().strip()
        modelos = self._cache_modelos[codigo_marca]

        # Tenta primeiro um match mais específico
        for m in modelos:
            if nome_busca == m['nome'].lower():
                return str(m['codigo'])
        
        # Fallback: primeira ocorrência que contenha o nome (ex: "Corolla")
        for m in modelos:
            if nome_busca in m['nome'].lower():
                return str(m['codigo'])
        
        return None

    def consultar_preco_medio(self, marca: str, modelo: str, ano: int) -> float:
        """
        Consulta o preço final baseado no ano específico do anúncio.
        Lida com formatos de ano como '2023-1' (Gasolina) e '32000' (Zero KM).
        """
        try:
            # 1. Obter Marca
            cod_marca = self._obter_codigo_marca(marca)
            if not cod_marca:
                return 0.0

            # 2. Obter Modelo
            cod_modelo = self._obter_codigo_modelo(cod_marca, modelo)
            if not cod_modelo:
                return 0.0

            # 3. Obter Anos disponíveis para este modelo
            url_anos = f"{self.BASE_URL}/marcas/{cod_marca}/modelos/{cod_modelo}/anos"
            res_anos = requests.get(url_anos, headers=self._headers, timeout=10)
            res_anos.raise_for_status()
            anos_disponiveis = res_anos.json()

            # 4. Localizar o código do ano (ex: 2023 -> 2023-1)
            cod_ano = None
            str_ano_buscado = str(ano)

            for a in anos_disponiveis:
                # Match exato do ano no início do código (2023-1, 2023-3, etc)
                if a['codigo'].startswith(str_ano_buscado):
                    cod_ano = a['codigo']
                    break
            
            # Fallback para carros novos/Zero KM (Código 32000 na FIPE)
            if not cod_ano and ano >= 2025:
                for a in anos_disponiveis:
                    if "32000" in a['codigo']:
                        cod_ano = a['codigo']
                        break

            if not cod_ano:
                logger.warning(f"⚠️ Ano {ano} não encontrado para {marca} {modelo}. Disponíveis: {[a['codigo'] for a in anos_disponiveis]}")
                return 0.0

            # 5. Obter Preço Final
            url_valor = f"{self.BASE_URL}/marcas/{cod_marca}/modelos/{cod_modelo}/anos/{cod_ano}"
            res_valor = requests.get(url_valor, headers=self._headers, timeout=10)
            res_valor.raise_for_status()
            dados_finais = res_valor.json()

            # Limpeza do valor: "R$ 115.450,00" -> 115450.0
            valor_str = dados_finais.get('Valor', '0')
            valor_limpo = valor_str.replace('R$', '').replace('.', '').replace(',', '.').replace(' ', '').strip()
            
            preco = float(valor_limpo)
            logger.info(f"📊 FIPE Localizada: {marca} {modelo} ({ano}) -> R$ {preco:,.2f}")
            return preco

        except Exception as e:
            logger.error(f"❌ Falha na consulta FIPE para {marca} {modelo} {ano}: {e}")
            return 0.0