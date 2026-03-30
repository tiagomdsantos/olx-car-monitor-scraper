import logging
import html
import datetime
import re

logger = logging.getLogger(__name__)

class CarEvaluator:
    BLACKLIST = [
        "leilao", "leilão", "sinistro", "recuperado", "rs", "batido", 
        "consta", "finan", "agio", "ágio", "repasse", "pago pra ver", "venda de pecas"
    ]
    
    BLACKLIST_DETALHADA = {
        "leilao": "Veículo proveniente de leilão (baixa liquidez/recusa de seguro)",
        "leilão": "Veículo proveniente de leilão (baixa liquidez/recusa de seguro)",
        "sinistro": "Histórico de acidente grave registrado (Sinistro)",
        "recuperado": "Veículo recuperado de roubo ou financiamento (chassi remarcado)",
        "rs": "Recuperado de Sinistro (Consta no documento)",
        "batido": "Veículo com danos estruturais visíveis ou declarados",
        "consta": "Possui restrições ou observações no documento (CRLV)",
        "finan": "Veículo com dívida de financiamento pendente (NP/Finan)",
        "agio": "Venda de ágio (parcelas em aberto)",
        "ágio": "Venda de ágio (parcelas em aberto)",
        "repasse": "Venda abaixo do valor sem garantia mecânica (Risco alto)",
        "pago pra ver": "Anúncio suspeito ou golpe comum (NP)",
        "venda de pecas": "Veículo destinado a desmonte, não rodante"
    }

    def __init__(self, settings, fipe_client, repository, notifier):
        self.settings = settings
        self.fipe_client = fipe_client
        self.repository = repository
        self.notifier = notifier

    def avaliar_lista(self, anuncios):
        total = len(anuncios)
        logger.info(f"🧐 Avaliando lote de {total} anúncios...")
        for index, anuncio in enumerate(anuncios, 1):
            try:
                self.processar_anuncio(anuncio)
            except Exception as e:
                logger.error(f"❌ Erro no anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio):
        # --- 1. DETECÇÃO DE REDUÇÃO DE PREÇO ---
        preco_anterior = self.repository.obter_preco_anterior(anuncio.id_anuncio)
        
        if preco_anterior > 0 and anuncio.preco < (preco_anterior - 100):
            reducao = preco_anterior - anuncio.preco
            percentual_queda = (reducao / preco_anterior) * 100
            
            logger.info(f"📉 QUEDA DE PREÇO: {anuncio.id_anuncio} baixou R$ {reducao:,.2f}")
            self._notificar_reducao_preco(anuncio, preco_anterior, percentual_queda)
            self.repository.atualizar_preco_anuncio(anuncio.id_anuncio, anuncio.preco)
            return

        # --- 2. FILTRO DE DUPLICADOS ---
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            return

        # --- 3. FILTROS DE SEGURANÇA (Blacklist com Regex) ---
        titulo_low = anuncio.titulo.lower()
        termo_encontrado = next(
            (termo for termo in self.BLACKLIST_DETALHADA if re.search(rf'\b{re.escape(termo)}\b', titulo_low)), 
            None
        )
        
        if termo_encontrado:
            motivo = self.BLACKLIST_DETALHADA[termo_encontrado]
            logger.warning(f"🚫 BLACKLIST: {anuncio.id_anuncio} ({termo_encontrado})")
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        # --- 4. INFERÊNCIA E BUSCA DA CONFIGURAÇÃO DO YAML ---
        marca = self._inferir_marca(anuncio.titulo)
        modelo_base = self._inferir_modelo_base(anuncio.titulo)
        versao_anuncio = self._inferir_versao(anuncio.titulo)
        modelo_completo = f"{modelo_base} {versao_anuncio}".strip()

        # Localiza o carro específico no seu config.yaml
        config_veiculo = next((v for v in self.settings.veiculos if v.modelo.lower() == modelo_base.lower()), None)

        if config_veiculo:
            # SANITY CHECK: Hatch vs Sedan
            cat_yaml = getattr(config_veiculo, 'categoria', '').lower()
            if cat_yaml == "hatch" and "sedan" in titulo_low:
                logger.info(f"⏭️ [{anuncio.id_anuncio}] Ignorando Sedan (Alvo é Hatch): {anuncio.titulo}")
                self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                return
            if cat_yaml == "sedan" and "hatch" in titulo_low:
                logger.info(f"⏭️ [{anuncio.id_anuncio}] Ignorando Hatch (Alvo é Sedan): {anuncio.titulo}")
                self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                return

            # FILTRO DE VERSÕES ACEITAS
            versoes_aceitas = [str(v).lower() for v in getattr(config_veiculo, 'versoes_aceitas', [])]
            if versoes_aceitas and "todas" not in versoes_aceitas:
                if versao_anuncio.lower() not in versoes_aceitas:
                    logger.info(f"⏭️ [{anuncio.id_anuncio}] Versão Indesejada ({versao_anuncio}): {anuncio.titulo}")
                    self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                    return
                    
            # FILTRO DE PREÇO MÁXIMO DO MODELO
            preco_max = getattr(config_veiculo, 'preco_maximo', self.settings.filtros_globais.preco_maximo)
            if anuncio.preco > float(preco_max):
                self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                return

        # --- 5. FILTROS GLOBAIS (KM, Ano e Teto Orçamentário) ---
        ano_atual = datetime.datetime.now().year
        idade_carro = max(1, ano_atual - anuncio.ano)
        km_por_ano = anuncio.km / idade_carro
        
        km_limite = getattr(self.settings.filtros_globais, 'km_maximo_global', 100000)
        km_ano_limite = getattr(self.settings.filtros_globais, 'km_ano_maximo', 16000)
        ano_minimo = getattr(self.settings.filtros_globais, 'ano_minimo', 2010)

        if anuncio.km > km_limite or km_por_ano > km_ano_limite or anuncio.ano < ano_minimo:
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        # --- 6. OBTENÇÃO DA FIPE ---
        preco_fipe = getattr(anuncio, 'preco_fipe_olx', 0.0)
        origem_fipe = "OLX"
        
        if preco_fipe > 0:
            self.repository.salvar_preco_cache(marca, modelo_completo, anuncio.ano, preco_fipe)
        else:
            origem_fipe = "API"
            preco_fipe = self.repository.obter_preco_cache(marca, modelo_completo, anuncio.ano)
            if preco_fipe is None:
                preco_fipe = self.fipe_client.consultar_preco_medio(marca, modelo_completo, anuncio.ano)
                if preco_fipe > 0:
                    self.repository.salvar_preco_cache(marca, modelo_completo, anuncio.ano, preco_fipe)

        # --- 7. CÁLCULO DE SCORE E NOTIFICAÇÃO ---
        if preco_fipe > 0:
            self.repository.salvar_anuncio_completo(anuncio, preco_fipe)
            
            percentual_fipe = (anuncio.preco / preco_fipe) * 100
            alerta_max = getattr(self.settings.filtros_globais, 'fipe_oportunidade_ate_percentual', 95)
            alerta_min = getattr(self.settings.filtros_globais, 'fipe_alerta_abaixo_de_percentual', 65)
            
            # --- NOVO: FILTRO ANTI-GOLPE (Limiar Mínimo) ---
            if percentual_fipe < alerta_min:
                logger.warning(f"🚨 [{anuncio.id_anuncio}] POSSÍVEL GOLPE: {anuncio.titulo} a {percentual_fipe:.1f}% da FIPE (Abaixo de {alerta_min}%). Ignorado.")
                self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                return

            if percentual_fipe <= alerta_max:
                score = self._calcular_score(anuncio, percentual_fipe, km_por_ano)
                logger.info(f"🎯 OPORTUNIDADE: {modelo_completo} Score {score}/100!")
                self._notificar_oportunidade(anuncio, preco_fipe, percentual_fipe, km_por_ano, origem_fipe, score)
        else:
            self.repository.salvar_anuncio_completo(anuncio, 0)

    # --- MOTOR DE SCORE (ALGORITMO V1.0) ---

    def _calcular_score(self, anuncio, percentual_fipe, km_por_ano):
        p_preco = float(self.repository.ler_metadata("peso_preco") or 50)
        p_km = float(self.repository.ler_metadata("peso_km") or 30)
        p_idade = float(self.repository.ler_metadata("peso_idade") or 20)

        score = 0
        score += max(0, (100 - percentual_fipe) * (p_preco / 20))
        score += max(0, (17000 - km_por_ano) * (p_km / 10000))
        
        idade = datetime.datetime.now().year - anuncio.ano
        score += max(0, (10 - idade) * (p_idade / 10))

        return round(min(100, score), 1)

    def _obter_estrelas(self, score):
        if score >= 90: return "⭐⭐⭐⭐⭐ (IMPERDÍVEL)"
        if score >= 80: return "⭐⭐⭐⭐ (ÓTIMO)"
        if score >= 70: return "⭐⭐⭐ (BOM)"
        return "⭐⭐ (REGULAR)"

    # --- MÉTODOS DE NOTIFICAÇÃO ---

    def _notificar_oportunidade(self, anuncio, preco_fipe, percentual, km_por_ano, origem_fipe, score):
        titulo_seguro = html.escape(anuncio.titulo)
        estrelas = self._obter_estrelas(score)
        tag = "💎 <i>(OLX)</i>" if origem_fipe == "OLX" else "🤖 <i>(FIPE)</i>"
        
        msg = (
            f"<b>🚀 {estrelas}</b>\n\n"
            f"🏎️ <b>{titulo_seguro}</b>\n"
            f"🏆 Score: <b>{score}/100</b>\n\n"
            f"💰 Preço: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"📊 FIPE: R$ {preco_fipe:,.2f} ({percentual:.1f}%) {tag}\n"
            f"📅 Ano: {anuncio.ano} | 🛣️ KM: {anuncio.km:,}\n"
            f"📈 Média de Uso: <b>{km_por_ano:.0f} km/ano</b>\n\n"
            f"🔗 <a href='{anuncio.link}'>Abrir no OLX</a>"
        )
        self.notifier.enviar_alerta(msg)

    def _notificar_reducao_preco(self, anuncio, preco_antigo, percentual_queda):
        titulo_seguro = html.escape(anuncio.titulo)
        msg = (
            f"<b>📉 BAIXOU O PREÇO EM SALVADOR!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"❌ De: <strike>R$ {preco_antigo:,.2f}</strike>\n"
            f"✅ Por: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"🔥 Queda: <b>R$ {preco_antigo - anuncio.preco:,.2f}</b> ({percentual_queda:.1f}%)\n\n"
            f"🔗 <a href='{anuncio.link}'>Ver no OLX</a>"
        )
        self.notifier.enviar_alerta(msg)

    # --- AUXILIARES ---

    def _inferir_marca(self, texto: str) -> str:
        t = texto.lower()
        mapping = {"toyota": "Toyota", "honda": "Honda", "nissan": "Nissan", "hyundai": "Hyundai"}
        for k, v in mapping.items():
            if k in t: return v
        return "Desconhecida"

    def _inferir_modelo_base(self, texto: str) -> str:
        t = texto.lower()
        modelos_alvo = ["corolla cross", "corolla", "city", "wr-v", "hr-v", "kicks", "sentra", "versa", "yaris", "hb20", "creta"]
        for m in modelos_alvo:
            if m in t: return m.title()
        return texto.split()[0].capitalize() if texto.split() else "Outros"

    def _inferir_versao(self, titulo):
        """Usa tokens para extrair versões exatas do título do anúncio."""
        t = str(titulo).lower().replace('-', ' ').replace('.', ' ')
        tokens = t.split()
        versoes_alvo = ["xls", "xs", "xl", "xei", "altis", "gli", "gr-sport", "exclusive", "advance", "sense", "exl", "touring", "ex", "lx", "sv", "sl"]
        for v in versoes_alvo:
            if v in tokens: return v.upper()
        return ""