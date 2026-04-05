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
        aprovados = 0
        reprovados = 0
        
        for index, anuncio in enumerate(anuncios, 1):
            try:
                # O processar_anuncio agora retorna True se passou no funil e False se foi filtrado
                if self.processar_anuncio(anuncio):
                    aprovados += 1
                else:
                    reprovados += 1
            except Exception as e:
                logger.error(f"❌ Erro crítico ao avaliar o anúncio {anuncio.id_anuncio}: {e}", exc_info=True)
                
        logger.info(f"📊 Resumo do Lote: {aprovados} Oportunidades Encontradas | {reprovados} Filtrados/Ignorados.")

    def processar_anuncio(self, anuncio) -> bool:
        """Avalia as regras do anúncio individual. Retorna True se for uma Oportunidade."""
        
        # --- 0. DUMP DE DEBUG DO ANÚNCIO ---
        logger.debug(
            f"\n{'-'*50}\n"
            f"🔍 DADOS BRUTOS DO ANÚNCIO [{anuncio.id_anuncio}]\n"
            f"🚘 Título:    {anuncio.titulo}\n"
            f"🏷️  Marca/Mod: {getattr(anuncio, 'marca', 'N/A')} {getattr(anuncio, 'modelo', 'N/A')}\n"
            f"📂 Categoria: {getattr(anuncio, 'categoria', 'N/A').upper()}\n"
            f"💰 Preço:     R$ {anuncio.preco:,.2f}\n"
            f"📅 Ano:       {anuncio.ano}\n"
            f"🛣️  KM:        {anuncio.km:,}\n"
            f"🔗 Link:      {anuncio.link}\n"
            f"{'-'*50}"
        )

        # --- 1. FILTROS DE SEGURANÇA (Blacklist com Regex) ---
        titulo_low = anuncio.titulo.lower()
        termo_encontrado = next(
            (termo for termo in self.BLACKLIST_DETALHADA if re.search(rf'\b{re.escape(termo)}\b', titulo_low)), 
            None
        )
        
        if termo_encontrado:
            motivo = self.BLACKLIST_DETALHADA[termo_encontrado]
            logger.warning(f"🚫 BLACKLIST: [{anuncio.id_anuncio}] Título contém '{termo_encontrado}' -> {motivo}")
            return False

        # --- 2. INFERÊNCIA E BUSCA DA CONFIGURAÇÃO DO YAML ---
        marca = self._inferir_marca(anuncio.titulo)
        modelo_base = self._inferir_modelo_base(anuncio.titulo)
        versao_anuncio = self._inferir_versao(anuncio.titulo)
        modelo_completo = f"{modelo_base} {versao_anuncio}".strip()

        config_veiculo = next((v for v in self.settings.veiculos if v.modelo.lower() == modelo_base.lower()), None)

        if not config_veiculo:
            logger.info(f"🛑 Modelo Intruso: [{anuncio.id_anuncio}] Identificado como '{modelo_base}'. Descartado.")
            return False

        cat_yaml = getattr(config_veiculo, 'categoria', '').lower()
        cat_anuncio = getattr(anuncio, 'categoria', '').lower()

        if cat_yaml in ["hatch", "sedan", "suv"]:
            if cat_anuncio in ["hatch", "sedan", "suv"] and cat_anuncio != cat_yaml:
                logger.info(f"⏭️ Categoria Incorreta: [{anuncio.id_anuncio}] A OLX classificou como {cat_anuncio.upper()}, busca exige {cat_yaml.upper()}.")
                return False
            
            if cat_yaml == "hatch" and re.search(r'\b(sedan|sedã|seda)\b', titulo_low):
                logger.info(f"⏭️ Categoria Incorreta (Título): [{anuncio.id_anuncio}] Título contém 'sedan' explicitamente.")
                return False
            if cat_yaml == "sedan" and re.search(r'\b(hatch|hatchback)\b', titulo_low):
                logger.info(f"⏭️ Categoria Incorreta (Título): [{anuncio.id_anuncio}] Título contém 'hatch' explicitamente.")
                return False

        versoes_aceitas = [str(v).lower() for v in getattr(config_veiculo, 'versoes_aceitas', [])]
        if versoes_aceitas and "todas" not in versoes_aceitas:
            if versao_anuncio.lower() not in versoes_aceitas:
                logger.info(f"⏭️ Versão Recusada: [{anuncio.id_anuncio}] Versão '{versao_anuncio}' não aceita.")
                return False
                
        preco_max = getattr(config_veiculo, 'preco_maximo', self.settings.filtros_globais.preco_maximo)
        if anuncio.preco > float(preco_max):
            logger.info(f"💲 Preço Acima do Teto: [{anuncio.id_anuncio}] R$ {anuncio.preco:,.2f} > Máximo R$ {preco_max:,.2f}.")
            return False

        # --- 3. FILTRO DE REGIÃO ESTRITA ---
        regioes_alvo = [loc.regiao.lower().strip() for loc in getattr(self.settings, 'localizacoes', []) if getattr(loc, 'regiao', None)]
        if regioes_alvo:
            link_low = anuncio.link.lower()
            passou_regiao = False
            for r in regioes_alvo:
                r_clean = r.replace('regiao-de-', '').replace('grande-', '').strip()
                if re.search(rf'\.olx\.com\.br/[^/]*{re.escape(r_clean)}[^/]*/', link_low):
                    passou_regiao = True
                    break
            
            if not passou_regiao:
                logger.info(f"📍 Região Recusada: [{anuncio.id_anuncio}] Fora da região configurada -> {anuncio.link}")
                return False

        # --- 4. OBTENÇÃO DA FIPE ---
        preco_fipe = getattr(anuncio, 'preco_fipe_olx', 0.0)
        origem_fipe = "OLX"
        
        if preco_fipe > 0:
            logger.debug(f"📊 [{anuncio.id_anuncio}] FIPE OLX: R$ {preco_fipe:,.2f}")
            self.repository.salvar_preco_cache(marca, modelo_completo, anuncio.ano, preco_fipe)
        else:
            origem_fipe = "API"
            preco_fipe = self.repository.obter_preco_cache(marca, modelo_completo, anuncio.ano)
            if preco_fipe:
                logger.debug(f"📊 [{anuncio.id_anuncio}] FIPE SQLite: R$ {preco_fipe:,.2f}")
            else:
                logger.info(f"🌐 [{anuncio.id_anuncio}] Buscando FIPE na API Externa para: {marca} {modelo_completo} {anuncio.ano}")
                preco_fipe = self.fipe_client.consultar_preco_medio(marca, modelo_completo, anuncio.ano)
                if preco_fipe > 0:
                    self.repository.salvar_preco_cache(marca, modelo_completo, anuncio.ano, preco_fipe)
                else:
                    logger.warning(f"⚠️ [{anuncio.id_anuncio}] Falha FIPE Externa.")
                    return False # Sem FIPE, não dá pra calcular Score, então aborta.

        # --- 5. FILTROS GLOBAIS RIGOROSOS (Anti-Lixo e Anti-Golpe) ---
        ano_atual = datetime.datetime.now().year
        idade_carro = max(1, ano_atual - anuncio.ano)
        km_por_ano = anuncio.km / idade_carro
        percentual_fipe = (anuncio.preco / preco_fipe) * 100

        ano_minimo = getattr(self.settings.filtros_globais, 'ano_minimo', 2010)
        if anuncio.ano < ano_minimo:
            logger.info(f"📅 Recusado: [{anuncio.id_anuncio}] Ano {anuncio.ano} < mínimo de {ano_minimo}.")
            return False

        km_limite = getattr(self.settings.filtros_globais, 'km_maximo_global', 100000)
        if anuncio.km > km_limite:
            logger.info(f"🛣️ Recusado: [{anuncio.id_anuncio}] KM excede o limite.")
            return False
            
        km_minimo = getattr(self.settings.filtros_globais, 'km_minimo_global', 0)
        if anuncio.km < km_minimo:
            logger.info(f"🛣️ Recusado: [{anuncio.id_anuncio}] KM suspeita/inferior ao mínimo.")
            return False

        km_ano_limite = getattr(self.settings.filtros_globais, 'km_ano_maximo', 16000)
        if km_por_ano > km_ano_limite:
            logger.info(f"🛣️ Recusado: [{anuncio.id_anuncio}] Uso severo ({km_por_ano:,.0f} km/ano).")
            return False

        alerta_min = getattr(self.settings.filtros_globais, 'fipe_alerta_abaixo_de_percentual', 65)
        if percentual_fipe < alerta_min:
            logger.warning(f"🚨 GOLPE SUSPEITO: [{anuncio.id_anuncio}] {anuncio.titulo} a {percentual_fipe:.1f}% da FIPE. Descartado da base.")
            return False

        # --- 6. CÁLCULO DE SCORE E SALVAMENTO NA BASE DE ELITE ---
        # Se chegou aqui, é um carro de verdade, com KM real e preço plausível!
        score_calculado = self._calcular_score(anuncio, percentual_fipe, km_por_ano)
        
        self.repository.salvar_anuncio_completo(anuncio, preco_fipe, score=score_calculado)
        logger.info(f"💾 Base de Mercado: [{anuncio.id_anuncio}] {modelo_completo} salvo no banco | Score: {score_calculado}/100 ({percentual_fipe:.1f}% FIPE).")
        
        if score_calculado >= 100:
            logger.info(f"🏆 Score perfeito detectado: {score_calculado}") 

        # --- 7. GATILHO DO TELEGRAM ---
        alerta_max = getattr(self.settings.filtros_globais, 'fipe_oportunidade_ate_percentual', 95)
        if percentual_fipe <= alerta_max:
            logger.info(f"💎 OPORTUNIDADE ENCONTRADA: [{anuncio.id_anuncio}] Score: {score_calculado}/100.")
            self._notificar_oportunidade(anuncio, preco_fipe, percentual_fipe, km_por_ano, origem_fipe, score_calculado)
            return True
        else:
            logger.info(f"💵 Preço normal de mercado: [{anuncio.id_anuncio}] {percentual_fipe:.1f}% da FIPE (Acima do alerta). Silenciado.")
            return False

    # --- MOTOR DE SCORE (ALGORITMO V1.0) ---
    def _calcular_score(self, anuncio, percentual_fipe, km_por_ano):
        pesos = getattr(self.settings, 'score', None)
        if pesos:
            pesos = getattr(pesos, 'pesos', None)
            
        p_preco = getattr(pesos, 'preco', 0.4) if pesos else 0.4
        p_km = getattr(pesos, 'km', 0.2) if pesos else 0.2
        p_ano = getattr(pesos, 'ano', 0.1) if pesos else 0.1
        p_fipe = getattr(pesos, 'fipe', 0.3) if pesos else 0.3

        score_total = 0.0

        nota_fipe = max(0, 100 - ((percentual_fipe - 80) * 5)) 
        score_total += nota_fipe * p_fipe

        nota_km = max(0, 100 - ((km_por_ano - 10000) / 100))
        score_total += nota_km * p_km

        idade = datetime.datetime.now().year - anuncio.ano
        nota_ano = max(0, 100 - (idade * 10))
        score_total += nota_ano * p_ano

        teto = getattr(self.settings.filtros_globais, 'preco_maximo_global', 120000)
        nota_preco = max(0, (1 - (anuncio.preco / float(teto))) * 100)
        score_total += nota_preco * p_preco

        return round(min(100.0, score_total), 1)

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
        """Infere o modelo dinamicamente com base apenas nos carros cadastrados no YAML."""
        t = texto.lower()
        
        # Puxa os modelos configurados na hora
        modelos_alvo = [str(v.modelo).lower() for v in getattr(self.settings, 'veiculos', [])]
        
        # Usa regex para garantir que encontrou a palavra inteira (evita achar "Ka" dentro de "Kardian")
        for m in modelos_alvo:
            if re.search(rf'\b{re.escape(m)}\b', t):
                return m.title()
                
        # Se não achou na lista, devolve a primeira palavra só para registrar no log do "Modelo Intruso"
        return texto.split()[0].capitalize() if texto.split() else "Desconhecido"

    def _inferir_versao(self, titulo):
        t = str(titulo).lower().replace('-', ' ').replace('.', ' ')
        tokens = t.split()
        versoes_alvo = ["xls", "xs", "xl", "xei", "altis", "gli", "gr-sport", "exclusive", "advance", "sense", "exl", "touring", "ex", "lx", "sv", "sl"]
        for v in versoes_alvo:
            if v in tokens: return v.upper()
        return ""