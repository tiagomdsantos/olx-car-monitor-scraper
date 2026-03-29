import logging
import html
import datetime

logger = logging.getLogger(__name__)

class CarEvaluator:
    # Termos para ignorar anúncios problemáticos
    BLACKLIST = [
        "leilao", "leilão", "sinistro", "recuperado", "rs", "batido", 
        "consta", "finan", "agio", "ágio", "repasse", "pago pra ver", "venda de pecas"
    ]

    def __init__(self, settings, fipe_client, repository, notifier):
        self.settings = settings
        self.fipe_client = fipe_client
        self.repository = repository
        self.notifier = notifier

    def avaliar_lista(self, anuncios):
        total = len(anuncios)
        logger.info(f"🧐 Avaliando lote de {total} anúncios recebidos...")
        for index, anuncio in enumerate(anuncios, 1):
            try:
                self.processar_anuncio(anuncio)
            except Exception as e:
                logger.error(f"❌ Erro no anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio):
        # --- 1. DETECÇÃO DE REDUÇÃO DE PREÇO ---
        # Verificamos se o anúncio já existe no banco e se o preço baixou
        preco_anterior = self.repository.obter_preco_anterior(anuncio.id_anuncio)
        
        if preco_anterior > 0 and anuncio.preco < (preco_anterior - 100): # Margem de R$ 100 para evitar flutuação irrelevante
            reducao = preco_anterior - anuncio.preco
            percentual_queda = (reducao / preco_anterior) * 100
            
            logger.info(f"📉 QUEDA DE PREÇO: {anuncio.id_anuncio} baixou R$ {reducao:,.2f}")
            
            # Notifica a redução e atualiza o banco
            self._notificar_reducao_preco(anuncio, preco_anterior, percentual_queda)
            self.repository.atualizar_preco_anuncio(anuncio.id_anuncio, anuncio.preco)
            return

        # --- 2. FILTRO DE DUPLICADOS PADRÃO ---
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            return

        # --- 3. FILTROS DE SEGURANÇA E BLACKLIST ---
        titulo_low = anuncio.titulo.lower()
        for termo in self.BLACKLIST:
            if termo in titulo_low:
                logger.info(f"🚫 Blacklist: {anuncio.id_anuncio} ignorado por '{termo}'")
                self.repository.salvar_anuncio_completo(anuncio, 0)
                return

        # --- 4. FILTROS DE KM E IDADE ---
        km_limite = getattr(self.settings.filtros_globais, 'km_maximo_global', 100000)
        if anuncio.km > km_limite:
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        ano_atual = datetime.datetime.now().year
        idade_carro = max(1, ano_atual - anuncio.ano)
        km_por_ano = anuncio.km / idade_carro
        
        limite_km_ano = getattr(self.settings.filtros_globais, 'km_ano_maximo', 15000)
        if km_por_ano > limite_km_ano:
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        # --- 5. INFERIR MODELO E MARCA (Memória) ---
        marca = self._inferir_marca(anuncio.titulo)
        modelo = self._inferir_modelo(anuncio.titulo)
        
        # Filtro de Preço Máximo por Modelo (Configurado no YAML)
        limite_modelo = self._obter_limite_por_modelo(modelo)
        if anuncio.preco > limite_modelo:
            self.repository.salvar_anuncio_completo(anuncio, 0)
            return

        # --- 6. OBTENÇÃO DA FIPE (Prioridade OLX) ---
        preco_fipe = getattr(anuncio, 'preco_fipe_olx', 0.0)
        origem_fipe = "OLX"
        
        if preco_fipe > 0:
            self.repository.salvar_preco_cache(marca, modelo, anuncio.ano, preco_fipe)
        else:
            origem_fipe = "API"
            preco_fipe = self.repository.obter_preco_cache(marca, modelo, anuncio.ano)
            
            if preco_fipe is None:
                preco_fipe = self.fipe_client.consultar_preco_medio(marca, modelo, anuncio.ano)
                if preco_fipe > 0:
                    self.repository.salvar_preco_cache(marca, modelo, anuncio.ano, preco_fipe)

        # --- 7. AVALIAÇÃO FINAL E NOTIFICAÇÃO ---
        if preco_fipe and preco_fipe > 0:
            self.repository.salvar_anuncio_completo(anuncio, preco_fipe)
            
            percentual = (anuncio.preco / preco_fipe) * 100
            alerta_max = self.settings.filtros_globais.fipe_oportunidade_ate_percentual
            
            if percentual <= alerta_max:
                logger.info(f"🎯 OPORTUNIDADE: {modelo} a {percentual:.1f}% da FIPE!")
                self._notificar_oportunidade(anuncio, preco_fipe, percentual, km_por_ano, origem_fipe)
        else:
            self.repository.salvar_anuncio_completo(anuncio, 0)

    # --- MÉTODOS DE NOTIFICAÇÃO (TELEGRAM) ---

    def _notificar_oportunidade(self, anuncio, preco_fipe, percentual, km_por_ano, origem_fipe):
        titulo_seguro = html.escape(anuncio.titulo)
        tag = "💎 <i>(FIPE OLX)</i>" if origem_fipe == "OLX" else "🤖 <i>(FIPE API)</i>"
        
        msg = (
            f"<b>🚀 NOVA OPORTUNIDADE!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"💰 Preço: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"📊 FIPE: R$ {preco_fipe:,.2f} ({percentual:.1f}%) {tag}\n"
            f"📅 Ano: {anuncio.ano} | 🛣️ KM: {anuncio.km:,}\n"
            f"📈 Média: <b>{km_por_ano:.0f} km/ano</b>\n\n"
            f"🔗 <a href='{anuncio.link}'>Abrir no OLX</a>"
        )
        self.notifier.enviar_alerta(msg)

    def _notificar_reducao_preco(self, anuncio, preco_antigo, percentual_queda):
        titulo_seguro = html.escape(anuncio.titulo)
        msg = (
            f"<b>📉 BAIXOU O PREÇO!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"❌ De: <strike>R$ {preco_antigo:,.2f}</strike>\n"
            f"✅ Por: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"🔥 Queda de: <b>R$ {preco_antigo - anuncio.preco:,.2f}</b> ({percentual_queda:.1f}%)\n\n"
            f"🔗 <a href='{anuncio.link}'>Ver Oportunidade</a>"
        )
        self.notifier.enviar_alerta(msg)

    # --- AUXILIARES ---

    def _obter_limite_por_modelo(self, modelo_identificado: str) -> float:
        modelo_key = modelo_identificado.lower()
        for v in getattr(self.settings, 'veiculos', []):
            if v.modelo.lower() in modelo_key or modelo_key in v.modelo.lower():
                return float(v.preco_maximo)
        return float(getattr(self.settings.filtros_globais, 'preco_maximo', 95000))

    def _inferir_marca(self, texto: str) -> str:
        t = texto.lower()
        mapping = {"toyota": "Toyota", "honda": "Honda", "nissan": "Nissan", "hyundai": "Hyundai"}
        for k, v in mapping.items():
            if k in t: return v
        return "Desconhecida"

    def _inferir_modelo(self, texto: str) -> str:
        t = texto.lower()
        modelos_alvo = ["corolla cross", "corolla", "city", "wr-v", "hr-v", "kicks", "sentra", "versa", "yaris", "hb20", "creta"]
        for m in modelos_alvo:
            if m in t: return m.title()
        return texto.split()[0].capitalize() if texto.split() else "Outros"