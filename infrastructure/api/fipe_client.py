# infrastructure/api/fipe_client.py
import requests
import logging
import time
from typing import Optional, List, Dict
from core.interfaces import IFipeClient

logger = logging.getLogger(__name__)

class ParallelumFipeClient(IFipeClient):
    BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros"

    def __init__(self):
        self._cache_marcas: List[Dict] = []
        self._cache_modelos: Dict[str, List[Dict]] = {}
        self._headers = {'User-Agent': 'MonitorOfertasSalvador/2.0 (Python/Requests)'}

    def _requisicao_segura(self, url: str, tentativas: int = 3) -> Optional[dict]:
        for i in range(tentativas):
            time.sleep(1.5) # Respeito sagrado ao Rate Limit da Parallelum
            try:
                response = requests.get(url, headers=self._headers, timeout=12)
                if response.status_code == 429:
                    espera = 35 * (i + 1)
                    logger.warning(f"⏳ FIPE 429. Aguardando {espera}s...")
                    time.sleep(espera)
                    continue
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if i == tentativas - 1:
                    logger.error(f"❌ Erro FIPE ({url}): {e}")
                    return None
        return None

    def _obter_codigo_marca(self, nome_marca: str) -> Optional[str]:
        if not self._cache_marcas:
            dados = self._requisicao_segura(f"{self.BASE_URL}/marcas")
            if dados: self._cache_marcas = dados
            else: return None
        
        nome_clean = nome_marca.lower().strip()
        for m in self._cache_marcas:
            if nome_clean in m['nome'].lower():
                return str(m['codigo'])
        return None

    def _obter_codigos_candidatos(self, codigo_marca: str, nome_modelo: str) -> List[str]:
        """Retorna TODOS os códigos de modelo que dão match na busca."""
        if codigo_marca not in self._cache_modelos:
            dados = self._requisicao_segura(f"{self.BASE_URL}/marcas/{codigo_marca}/modelos")
            if dados: self._cache_modelos[codigo_marca] = dados.get('modelos', [])
            else: return []

        modelos = self._cache_modelos[codigo_marca]
        tokens_busca = nome_modelo.lower().strip().split()
        candidatos = []

        # 1. Tenta match exato com todos os tokens (Ex: "yaris" e "xs")
        for m in modelos:
            if all(t in m['nome'].lower() for t in tokens_busca):
                candidatos.append(str(m['codigo']))
                
        # 2. Se for muito restrito, tenta achar pelo menos pelo nome principal (Ex: "yaris")
        if not candidatos and tokens_busca:
            token_principal = tokens_busca[0]
            for m in modelos:
                if token_principal in m['nome'].lower():
                    candidatos.append(str(m['codigo']))

        return candidatos

    def consultar_preco_medio(self, marca: str, modelo: str, ano: int) -> float:
        try:
            cod_marca = self._obter_codigo_marca(marca)
            if not cod_marca: return 0.0

            codigos_candidatos = self._obter_codigos_candidatos(cod_marca, modelo)
            if not codigos_candidatos: return 0.0

            str_ano = str(ano)

            # SWEEPING: Testa os candidatos até achar um que foi fabricado no ano pedido
            for cod_modelo in codigos_candidatos:
                url_anos = f"{self.BASE_URL}/marcas/{cod_marca}/modelos/{cod_modelo}/anos"
                lista_anos = self._requisicao_segura(url_anos)
                
                if not lista_anos: continue

                cod_ano = None
                for a in lista_anos:
                    if a['codigo'].startswith(str_ano):
                        cod_ano = a['codigo']
                        break
                
                # Zero KM Fallback
                if not cod_ano and ano >= 2025:
                    for a in lista_anos:
                        if "32000" in a['codigo']:
                            cod_ano = a['codigo']
                            break

                if cod_ano:
                    # Achou o modelo correto para aquele ano! Pegamos o valor.
                    url_valor = f"{self.BASE_URL}/marcas/{cod_marca}/modelos/{cod_modelo}/anos/{cod_ano}"
                    dados_valor = self._requisicao_segura(url_valor)
                    
                    if dados_valor:
                        valor_limpo = dados_valor.get('Valor', '0').replace('R$', '').replace('.', '').replace(',', '.').replace(' ', '').strip()
                        preco = float(valor_limpo)
                        logger.info(f"📊 FIPE Consultada: {marca} {dados_valor.get('Modelo', modelo)} ({ano}) -> R$ {preco:,.2f}")
                        return preco

            # Se rodou todos os modelos e nenhum tinha o ano
            logger.warning(f"⚠️ Ano {ano} não disponível em NENHUMA variação de {marca} {modelo}")
            return 0.0

        except Exception as e:
            logger.error(f"❌ Erro fatal ao consultar FIPE: {e}")
            return 0.0