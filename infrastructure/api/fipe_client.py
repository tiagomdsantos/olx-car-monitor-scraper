# infrastructure/api/fipe_client.py
import requests
import logging
from typing import Optional, List, Dict
from core.interfaces import IFipeClient

logger = logging.getLogger(__name__)

class ParallelumFipeClient(IFipeClient):
    """
    Implementação concreta do cliente FIPE usando a API Pública da Parallelum.
    """
    BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros"

    def __init__(self):
        self._cache_marcas: List[Dict] = []
        self._cache_modelos: Dict[str, List[Dict]] = {}
        # Header básico para evitar bloqueio por bot
        self._headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    def _obter_marcas(self) -> List[Dict]:
        if not self._cache_marcas:
            try:
                url = f"{self.BASE_URL}/marcas"
                response = requests.get(url, headers=self._headers)
                response.raise_for_status()
                self._cache_marcas = response.json()
            except Exception as e:
                logger.error(f"Erro ao buscar marcas: {e}")
        return self._cache_marcas

    def _obter_codigo_marca(self, nome_marca: str) -> Optional[str]:
        marcas = self._obter_marcas()
        for marca in marcas:
            # Na Parallelum, o ID vem na chave 'codigo'
            if nome_marca.lower() in marca['nome'].lower():
                return str(marca['codigo'])
        return None

    def _obter_modelos(self, codigo_marca: str) -> List[Dict]:
        if codigo_marca not in self._cache_modelos:
            try:
                url = f"{self.BASE_URL}/marcas/{codigo_marca}/modelos"
                response = requests.get(url, headers=self._headers)
                response.raise_for_status()
                dados = response.json()
                # A Parallelum devolve um objeto com 'modelos' e 'anos'
                self._cache_modelos[codigo_marca] = dados.get('modelos', [])
            except requests.exceptions.HTTPError as e:
                logger.error(f"Erro ao buscar modelos da marca {codigo_marca}: {e}")
                return []
        return self._cache_modelos[codigo_marca]

    def consultar_preco_medio(self, marca: str, modelo: str, ano: int) -> float:
        codigo_marca = self._obter_codigo_marca(marca)
        if not codigo_marca:
            logger.warning(f"Marca não encontrada na FIPE: {marca}")
            return 0.0

        modelos_marca = self._obter_modelos(codigo_marca)
        
        modelos_encontrados = [
            m for m in modelos_marca 
            if modelo.lower() in m['nome'].lower()
        ]

        if not modelos_encontrados:
            logger.warning(f"Modelo não encontrado na FIPE: {modelo}")
            return 0.0

        # MOCK DIDÁTICO: Mantido para a construção inicial do fluxo.
        if marca.lower() == 'honda' and 'city' in modelo.lower():
            return 125000.0
            
        return 100000.0