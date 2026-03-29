# core/evaluator.py
import logging
import html
import datetime
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
        total = len(anuncios)
        logger.info(f"🧐 Avaliando lote de {total} anúncios recebidos do Scraper...")
        for index, anuncio in enumerate(anuncios, 1):
            try:
                self.processar_anuncio(anuncio)
            except Exception as e:
                logger.error(f"❌ [{index}/{total}] Erro crítico no anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio):
        # 1. Evitar duplicados
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            # Log de debug (menos barulhento que info)
            logger.debug(f"♻️  {anuncio.id_anuncio} já processado anteriormente.")
            return

        # 2. Filtro de Blacklist
        titulo_low = anuncio.titulo.lower()
        for termo in self.BLACKLIST:
            if termo in titulo_low:
                logger.info(f"🚫 Blacklist: ID {anuncio.id_anuncio} ignorado pelo termo '{termo}'")
                self.repository.salvar_anuncio_completo(anuncio, 0)
                return

        # 3. Filtros de Quilometragem (v1.1.0)
        km_limite = getattr(self.settings.filtros_globais, 'km_maximo_global', 100000)
        if anuncio.km > km_limite:
            logger.info(f"🛣️  KM Excessivo: ID {anuncio.id_anuncio} com {anuncio.km}km (Limite: {km_limite}km)")
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        ano_atual = datetime.datetime.now().year
        # Consideramos idade mínima de 1 para evitar divisão por zero e distorção em carros zero
        idade_carro = max(1, ano_atual - anuncio.ano)
        km_por_ano = anuncio.km / idade_carro
        
        limite_km_ano = getattr(self.settings.filtros_globais, 'km_ano_maximo', 15000)
        if km_por_ano > limite_km_ano:
            logger.info(f"🏃 Surrado: ID {anuncio.id_anuncio} rodou {km_por_ano:.0f}km/ano (Limite: {limite_km_ano})")
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        # 4. Identificação de Marca/Modelo e Filtro de Preço
        marca = self._inferir_marca(anuncio.titulo)
        modelo = self._inferir_modelo(anuncio.titulo)
        
        limite_modelo = self._obter_limite_por_modelo(modelo)
        if anuncio.preco > limite_modelo:
            logger.info(f"💰 Caro: {modelo} {anuncio.id_anuncio} por R$ {anuncio.preco:,.2f} (Teto: R$ {limite_modelo:,.2f})")
            self.repository.salvar_anuncio_completo(anuncio, 0)
            return

        if anuncio.ano < getattr(self.settings.filtros_globais, 'ano_minimo', 2010):
            logger.info(f"👴 Velho: ID {anuncio.id_anuncio} ano {anuncio.ano} abaixo do mínimo.")
            return

        # 5. Consulta FIPE (Cache -> API)
        logger.info(f"🔍 Consultando FIPE para {marca} {modelo} {anuncio.ano}...")
        preco_fipe = self.repository.obter_preco_cache(marca, modelo, anuncio.ano)
        
        if preco_fipe is None:
            preco_fipe = self.fipe_client.consultar_preco_medio(marca, modelo, anuncio.ano)
            if preco_fipe > 0:
                logger.info(f"💾 FIPE Atualizada via API: R$ {preco_fipe:,.2f} (Cache salvo)")
                self.repository.salvar_preco_cache(marca, modelo, anuncio.ano, preco_fipe)
            else:
                logger.warning(f"⚠️  FIPE não encontrada para {marca} {modelo} {anuncio.ano}")

        # 6. Avaliação Final
        if preco_fipe and preco_fipe > 0:
            self.repository.salvar_anuncio_completo(anuncio, preco_fipe)
            
            percentual = (anuncio.preco / preco_fipe) * 100
            alerta_min = self.settings.filtros_globais.fipe_alerta_abaixo_de_percentual
            alerta_max = self.settings.filtros_globais.fipe_oportunidade_ate_percentual
            
            if alerta_min <= percentual <= alerta_max:
                logger.info(f"🎯 OPORTUNIDADE: {modelo} a {percentual:.1f}% da FIPE! Enviando Telegram...")
                self._notificar_telegram(anuncio, preco_fipe, percentual, km_por_ano)
            else:
                logger.info(f"⏭️  Fora da margem: {modelo} {anuncio.ano} está a {percentual:.1f}% da FIPE (Alvo: {alerta_min}-{alerta_max}%)")
        else:
            self.repository.salvar_anuncio_completo(anuncio, 0)

    def _obter_limite_por_modelo(self, modelo_identificado: str) -> float:
        modelo_key = modelo_identificado.lower()
        lista_veiculos = getattr(self.settings, 'veiculos', [])
        for v in lista_veiculos:
            modelo_config = v.modelo.lower()
            if modelo_config in modelo_key or modelo_key in modelo_config:
                return float(v.preco_maximo)
        
        filtros = getattr(self.settings, 'filtros_globais', None)
        return float(getattr(filtros, 'preco_maximo', 95000))

    def _notificar_telegram(self, anuncio, preco_fipe, percentual, km_por_ano):
        titulo_seguro = html.escape(anuncio.titulo)
        msg = (
            f"<b>🚀 OPORTUNIDADE EM SALVADOR!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"💰 Preço: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"📊 FIPE: R$ {preco_fipe:,.2f} ({percentual:.1f}%)\n"
            f"📅 Ano: {anuncio.ano} | 🛣️ KM: {anuncio.km}\n"
            f"📈 Média: <b>{km_por_ano:.0f} km/ano</b>\n\n"
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
        modelos_alvo = ["corolla", "city", "wr-v", "kicks", "sentra", "versa", "yaris", "hb20"]
        for m in modelos_alvo:
            if m in t: return m.capitalize()
        return titulo.split()[0]