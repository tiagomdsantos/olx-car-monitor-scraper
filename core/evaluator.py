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
    # Mapeamento de termos proibidos com suas respectivas justificativas
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

        # --- 3. FILTROS DE SEGURANÇA (Blacklist) ---
        titulo_low = anuncio.titulo.lower()
        termo_encontrado = next((termo for termo in self.BLACKLIST_DETALHADA if termo in titulo_low), None)
        
        if termo_encontrado:
            motivo = self.BLACKLIST_DETALHADA[termo_encontrado]
            logger.warning(f"🚫 BLACKLIST: {anuncio.id_anuncio} IGNORADO")
            logger.warning(f"└─ Termo: '{termo_encontrado}'")
            logger.warning(f"└─ Motivo: {motivo}")
            
            # Salvamos no banco com preco_fipe 0 para análise futura se necessário
            self.repository.salvar_anuncio_completo(anuncio, 0)
            return

        # --- 4. FILTROS DE KM E IDADE ---
        ano_atual = datetime.datetime.now().year
        idade_carro = max(1, ano_atual - anuncio.ano)
        km_por_ano = anuncio.km / idade_carro
        
        km_limite = getattr(self.settings.filtros_globais, 'km_maximo_global', 100000)
        km_ano_limite = getattr(self.settings.filtros_globais, 'km_ano_maximo', 15000)

        if anuncio.km > km_limite or km_por_ano > km_ano_limite:
            self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
            return

        # --- 5. INFERIR MODELO E MARCA ---
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

        # --- 7. CÁLCULO DE SCORE E NOTIFICAÇÃO ---
        if preco_fipe > 0:
            self.repository.salvar_anuncio_completo(anuncio, preco_fipe)
            
            percentual_fipe = (anuncio.preco / preco_fipe) * 100
            alerta_max = self.settings.filtros_globais.fipe_oportunidade_ate_percentual
            
            if percentual_fipe <= alerta_max:
                score = self._calcular_score(anuncio, percentual_fipe, km_por_ano)
                logger.info(f"🎯 OPORTUNIDADE: {modelo} Score {score}/100!")
                self._notificar_oportunidade(anuncio, preco_fipe, percentual_fipe, km_por_ano, origem_fipe, score)
        else:
            self.repository.salvar_anuncio_completo(anuncio, 0)

    # --- MOTOR DE SCORE (ALGORITMO V1.0) ---

    def _calcular_score(self, anuncio, percentual_fipe, km_por_ano):
        # Busca pesos no banco ou usa o padrão (50, 30, 20)
        p_preco = float(self.repository.ler_metadata("peso_preco") or 50)
        p_km = float(self.repository.ler_metadata("peso_km") or 30)
        p_idade = float(self.repository.ler_metadata("peso_idade") or 20)

        score = 0
        
        # 1. Componente Preço (Máximo = p_preco)
        score += max(0, (100 - percentual_fipe) * (p_preco / 20))

        # 2. Componente Uso/KM (Máximo = p_km)
        # 7k km/ano = full pts | 17k km/ano = 0 pts
        score += max(0, (17000 - km_por_ano) * (p_km / 10000))

        # 3. Componente Idade (Máximo = p_idade)
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
        tag = "💎 <i>(FIPE OLX)</i>" if origem_fipe == "OLX" else "🤖 <i>(FIPE API)</i>"
        
        msg = (
            f"<b>🚀 {estrelas}</b>\n\n"
            f"🏎️ <b>{titulo_seguro}</b>\n"
            f"🏆 Score de Oportunidade: <b>{score}/100</b>\n\n"
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
            f"<b>📉 BAIXOU O PREÇO EM SALVADOR!</b>\n\n"
            f"🚗 <b>{titulo_seguro}</b>\n"
            f"❌ De: <strike>R$ {preco_antigo:,.2f}</strike>\n"
            f"✅ Por: <b>R$ {anuncio.preco:,.2f}</b>\n"
            f"🔥 Queda de: <b>R$ {preco_antigo - anuncio.preco:,.2f}</b> ({percentual_queda:.1f}%)\n\n"
            f"🔗 <a href='{anuncio.link}'>Ver no OLX</a>"
        )
        self.notifier.enviar_alerta(msg)

    # --- AUXILIARES ---

    def _obter_limite_por_modelo(self, modelo_identificado: str) -> float:
        for v in getattr(self.settings, 'veiculos', []):
            if v.modelo.lower() in modelo_identificado.lower():
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

    def _inferir_versao(self, titulo):
        """Identifica a versão específica do carro para uma FIPE mais precisa."""
        t = titulo.lower()
        # Mapeamento de versões por relevância
        versoes = [
            "xei", "altis", "gli", "dynamic", "gr-sport", # Corolla
            "exl", "touring", "lx", "ex", "dx",            # Honda (Civic/City/Fit)
            "advance", "exclusive", "sense", "sv", "sl"     # Nissan Kicks
        ]
        for v in versoes:
            if v in t:
                return v.upper()
        return "" # Se não achar, mantém vazio para busca genérica

    def _inferir_modelo_completo(self, titulo):
        modelo = self._inferir_modelo(titulo)
        versao = self._inferir_versao(titulo)
        return f"{modelo} {versao}".strip()