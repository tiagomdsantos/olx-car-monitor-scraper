# core/evaluator.py
import logging
import html
from core.models import Anuncio

logger = logging.getLogger(__name__)

class CarEvaluator:
    # Termos para ignorar anúncios problemáticos em Salvador
    BLACKLIST = [
        "leilao", "leilão", "sinistro", "recuperado", "rs", "batido", 
        "consta", "finan", "aguio", "repasse", "pago pra ver", "venda de pecas"
    ]

    def __init__(self, settings, fipe_client, repository, notifier):
        self.settings = settings
        self.fipe_client = fipe_client
        self.repository = repository
        self.notifier = notifier

    def avaliar_lista(self, anuncios):
        for anuncio in anuncios:
            try:
                self.processar_anuncio(anuncio)
            except Exception as e:
                logger.error(f"❌ Erro no Evaluator para o anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio):
        # 1. Evitar duplicados
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            return

        # 2. Filtro de Blacklist
        titulo_low = anuncio.titulo.lower()
        if any(termo in titulo_low for termo in self.BLACKLIST):
            logger.info(f"🚫 Blacklist: {anuncio.id_anuncio} ignorado.")
            self.repository.salvar_anuncio_completo(anuncio, 0)
            return

        # 3. Identificação de Marca/Modelo e Filtro de Preço Específico
        marca = self._inferir_marca(anuncio.titulo)
        modelo = self._inferir_modelo(anuncio.titulo)
        
        # Busca o limite de preço definido para este modelo específico no YAML
        # Se não encontrar o modelo no config, usa um teto global de 95k
        limite_modelo = self._obter_limite_por_modelo(modelo)

        if anuncio.preco > limite_modelo:
            logger.info(f"💰 Fora do Orçamento ({modelo}): R$ {anuncio.preco:,.2f} > Limite R$ {limite_modelo:,.2f}")
            self.repository.salvar_anuncio_completo(anuncio, 0)
            return

        if anuncio.ano < self.settings.filtros_globais.ano_minimo:
            return

        # 4. Consulta FIPE (Cache -> API)
        preco_fipe = self.repository.obter_preco_cache(marca, modelo, anuncio.ano)
        if preco_fipe is None:
            preco_fipe = self.fipe_client.consultar_preco_medio(marca, modelo, anuncio.ano)
            if preco_fipe > 0:
                self.repository.salvar_preco_cache(marca, modelo, anuncio.ano, preco_fipe)

        # 5. Avaliação Final e Gravação
        if preco_fipe and preco_fipe > 0:
            self.repository.salvar_anuncio_completo(anuncio, preco_fipe)
            
            percentual = (anuncio.preco / preco_fipe) * 100
            alerta_min = self.settings.filtros_globais.fipe_alerta_abaixo_de_percentual
            alerta_max = self.settings.filtros_globais.fipe_oportunidade_ate_percentual

            if alerta_min <= percentual <= alerta_max:
                self._notificar_telegram(anuncio, preco_fipe, percentual)
            else:
                logger.info(f"⏭️ {modelo} {anuncio.ano}: {percentual:.1f}% da FIPE (Fora da margem)")
        else:
            self.repository.salvar_anuncio_completo(anuncio, 0)

    def _obter_limite_por_modelo(self, modelo_identificado: str) -> float:
        """Busca o preço máximo no config.yaml baseado no modelo."""
        modelo_key = modelo_identificado.lower()
        # Tenta encontrar nas configurações de busca
        for busca in self.settings.buscas:
            if busca.modelo.lower() in modelo_key or modelo_key in busca.modelo.lower():
                return float(busca.preco_maximo)
        
        # Fallback para o preço global se não achar no loop
        return float(getattr(self.settings.filtros_globais, 'preco_maximo', 95000))

    def _notificar_telegram(self, anuncio, preco_fipe, percentual):
        titulo_seguro = html.escape(anuncio.titulo)
        msg = (
            f"<b>🚀 OPORTUNIDADE EM SALVADOR!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"💰 Preço: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"📊 FIPE: R$ {preco_fipe:,.2f} ({percentual:.1f}%)\n"
            f"📅 Ano: {anuncio.ano} | 🛣️ KM: {anuncio.km}\n\n"
            f"🔗 <a href='{anuncio.link}'>Ver no OLX</a>"
        )
        self.notifier.enviar_alerta(msg)

    def _inferir_marca(self, titulo: str) -> str:
        t = titulo.lower()
        mapping = {"toyota": "Toyota", "honda": "Honda", "nissan": "Nissan", "hyundai": "Hyundai"}
        for k, v in mapping.items():
            if k in t: return v
        return ""

    def _inferir_modelo(self, titulo: str) -> str:
        t = titulo.lower()
        # Modelos que você está monitorando
        modelos_alvo = ["corolla", "city", "wr-v", "kicks", "sentra", "versa", "yaris", "hb20"]
        for m in modelos_alvo:
            if m in t: return m.capitalize()
        return titulo.split()[0]