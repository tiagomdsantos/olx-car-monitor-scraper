# core/evaluator.py
import logging
import html
from core.models import Anuncio

logger = logging.getLogger(__name__)

class CarEvaluator:
    # Termos que indicam roubada ou anúncios de baixa qualidade
    BLACKLIST = ["leilao", "leilão", "sinistro", "recuperado", "rs", "batido", "consta", "finan", "aguio", "repasse"]

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
                logger.error(f"❌ Erro ao avaliar anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio):
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            return

        # 1. Filtro de Blacklist
        titulo_comp = anuncio.titulo.lower()
        for termo in self.BLACKLIST:
            if termo in titulo_comp:
                logger.info(f"🚫 Blacklist: {anuncio.id_anuncio} ignorado por '{termo}'")
                self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                return

        # 2. Filtros Básicos
        if anuncio.preco <= 1000 or anuncio.ano < self.settings.filtros_globais.ano_minimo:
            return

        # 3. Identificação para FIPE
        marca_busca = anuncio.marca if anuncio.marca else self._inferir_marca(anuncio.titulo)
        modelo_busca = anuncio.modelo if anuncio.modelo else self._inferir_modelo(anuncio.titulo)

        # 4. Consulta de Preço com Cache
        preco_fipe = self.repository.obter_preco_cache(marca_busca, modelo_busca, anuncio.ano)
        
        if preco_fipe is None:
            # Não está no cache, busca na API
            preco_fipe = self.fipe_client.consultar_preco_medio(marca_busca, modelo_busca, anuncio.ano)
            if preco_fipe > 0:
                self.repository.salvar_preco_cache(marca_busca, modelo_busca, anuncio.ano, preco_fipe)
        else:
            logger.debug(f"⚡ Cache FIPE usado para {modelo_busca} {anuncio.ano}")

        # 5. Avaliação de Oportunidade
        if preco_fipe and preco_fipe > 0:
            percentual = (anuncio.preco / preco_fipe) * 100
            alerta_min = self.settings.filtros_globais.fipe_alerta_abaixo_de_percentual
            alerta_max = self.settings.filtros_globais.fipe_oportunidade_ate_percentual

            if alerta_min <= percentual <= alerta_max:
                self._notificar(anuncio, preco_fipe, percentual)
            else:
                logger.info(f"⏭️ {anuncio.id_anuncio}: {percentual:.1f}% da FIPE (Fora da margem)")

        self.repository.salvar_anuncio_processado(anuncio.id_anuncio)

    def _notificar(self, anuncio, preco_fipe, percentual):
        titulo_seguro = html.escape(anuncio.titulo)
        mensagem = (
            f"<b>🚀 OPORTUNIDADE EM SALVADOR!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"💰 Preço: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"📊 FIPE: R$ {preco_fipe:,.2f} ({percentual:.1f}%)\n"
            f"📅 Ano: {anuncio.ano} | 🛣️ KM: {anuncio.km}\n\n"
            f"🔗 <a href='{anuncio.link}'>Ver no OLX</a>"
        )
        self.notifier.enviar_alerta(mensagem)

    def _inferir_marca(self, titulo: str) -> str:
        t = titulo.lower()
        mapping = {"toyota": "Toyota", "honda": "Honda", "nissan": "Nissan", "hyundai": "Hyundai"}
        for k, v in mapping.items():
            if k in t: return v
        return ""

    def _inferir_modelo(self, titulo: str) -> str:
        t = titulo.lower()
        modelos = ["corolla", "city", "wr-v", "kicks", "sentra", "versa", "yaris", "hb20"]
        for m in modelos:
            if m in t: return m.capitalize()
        return titulo.split()[0]