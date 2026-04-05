import time
import logging
import os
import threading
import requests
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
import html  # <--- ADICIONE ESTE IMPORT

from dotenv import load_dotenv
from config.settings import load_settings
from infrastructure.api.fipe_client import ParallelumFipeClient
from infrastructure.database.sqlite_repo import SQLiteRepository
from infrastructure.notifications.telegram_notifier import TelegramNotifier
from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper
from core.evaluator import CarEvaluator
from analisar_mercado import gerar_graficos_por_modelo, obter_texto_elite

# 1. Configuração de Logs e Ambiente
load_dotenv()

# Cria a pasta 'logs' se não existir
os.makedirs("logs", exist_ok=True)

# Lógica para gerar o nome do arquivo com data e sufixo (1), (2)...
hoje_str = datetime.now().strftime('%Y-%m-%d')
caminho_base = f"logs/bot_olx_{hoje_str}"
arquivo_log = f"{caminho_base}.log"
contador = 1

while os.path.exists(arquivo_log):
    arquivo_log = f"{caminho_base} ({contador}).log"
    contador += 1

# Configura o formato padrão para os logs
log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'

# Configuração dupla: Salva no arquivo (nome dinâmico) e joga na tela
logging.basicConfig(
    level=logging.INFO, 
    format=log_format,
    handlers=[
        logging.FileHandler(arquivo_log, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"📝 Arquivo de log criado: {arquivo_log}")

# Opcional: Reduz o "barulho" das bibliotecas de terceiros no log
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING) # Adicionado para o Telegram

# Locks e Eventos Globais para Sincronização
db_lock = threading.Lock()
evento_scan_imediato = threading.Event()

# =========================================================================
# THREAD 1: SCRAPER
# =========================================================================
def thread_scraper(settings, repository, scraper, evaluator, notifier):
    """Thread 1: Monitoramento Contínuo da OLX (V1.5.2 - Unified Search Strategy)."""
    logger.info("🧵 Thread SCRAPER ativa.")
    intervalo_min = settings.app.intervalo_scraping_minutos

    while True:
        try:
            ultima_str = repository.ler_metadata("ultima_execucao")
            ultima = datetime.fromisoformat(ultima_str) if ultima_str else None
            
            agora = datetime.now()
            if ultima:
                proxima = ultima + timedelta(minutes=intervalo_min)
                segundos_espera = (proxima - agora).total_seconds()
            else:
                segundos_espera = 0

            if segundos_espera > 0:
                logger.info(f"⏳ Standby: Próximo ciclo automático em {int(segundos_espera/60)} min.")
                evento_scan_imediato.wait(timeout=segundos_espera)
            
            # PULO DO GATO: Verifica se a thread acordou por causa do /scan manual
            scan_manual = evento_scan_imediato.is_set()
            evento_scan_imediato.clear()

            logger.info("--- 🔄 INICIANDO VARREDURA OLX ---")
            total_anuncios_ciclo = 0

            for local in settings.localizacoes:
                logger.info(f"📍 Iniciando varredura no estado: {local.estado.upper()}")
                
                for veiculo in settings.veiculos:
                    logger.debug(f"🛠️ Construindo query de busca para: {veiculo.marca} {veiculo.modelo}")
                    
                    # 1. Montagem dinâmica dos QUERY PARAMETERS BASE
                    params_base = {}
                    params_base['ps'] = "5000"

                    preco_maximo = getattr(veiculo, 'preco_maximo', None)
                    if preco_maximo: params_base['pe'] = str(int(preco_maximo))

                    ano_minimo = getattr(veiculo, 'ano_minimo', None)
                    if ano_minimo:
                        params_base['rs'] = str(int(ano_minimo))
                        params_base['re'] = str(datetime.now().year + 1)

                    km_maximo = getattr(veiculo, 'km_maximo', None)
                    if km_maximo: params_base['me'] = str(int(km_maximo))

                    tipo_vendedor = getattr(veiculo, 'tipo_vendedor', None)
                    if tipo_vendedor:
                        tipo_clean = str(tipo_vendedor).lower().strip()
                        if tipo_clean == "particular": params_base['f'] = 'p'
                        elif tipo_clean in ["profissional", "loja", "comercial"]: params_base['f'] = 'c'

                    logger.debug(f"⚙️ Parâmetros HTTP mapeados: {params_base}")

                    # Identifica as versões desejadas no YAML
                    versoes_aceitas = [str(v).lower() for v in getattr(veiculo, 'versoes_aceitas', [])]
                    logger.debug(f"📋 Versões aceitas no YAML: {versoes_aceitas}")
                    urls_alvo = [] # Lista que guardará as URLs a serem raspadas

                    # --- NOVA ESTRATÉGIA ÚNICA: Busca pelo Modelo na Categoria (Inteligente e sem duplicidade) ---
                    # O bot puxa tudo do modelo de uma vez, e o evaluator.py filtra as versões localmente.
                    marca_url = veiculo.marca.lower().replace(' ', '-')
                    modelo_url = veiculo.modelo.lower().replace(' ', '-')
                    
                    path_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{marca_url}/{modelo_url}"
                    if getattr(veiculo, 'complemento_busca', None):
                        path_busca += f"/{veiculo.complemento_busca.lower().replace(' ', '-')}"
                    
                    path_busca += f"/estado-{local.estado.lower()}"
                    regiao = getattr(local, 'regiao', None)
                    if regiao:
                        path_busca += f"/{regiao.strip('/').lower()}"

                    query_string = urllib.parse.urlencode(params_base)
                    url_final = f"{path_busca}?{query_string}" if query_string else path_busca
                    
                    # Nome bonito para o log e notificação do Telegram
                    label_log = ", ".join(versoes_aceitas).upper() if versoes_aceitas and "todas" not in versoes_aceitas else "TODAS AS VERSÕES"
                    urls_alvo.append((url_final, label_log))

                    # Executa o Scraper para a URL única montada
                    for url_busca, label_versao in urls_alvo:
                        filtros_str = []
                        if preco_maximo: filtros_str.append(f"💰R$ {int(preco_maximo)/1000:.0f}k")
                        if ano_minimo: filtros_str.append(f"📅>={ano_minimo}")
                        if km_maximo: filtros_str.append(f"🛣️<{int(km_maximo)/1000:.0f}k")
                        if tipo_vendedor: filtros_str.append(f"👤{str(tipo_vendedor)[:4].capitalize()}.")
                        str_f = " | ".join(filtros_str) if filtros_str else "S/ filtros"

                        logger.info(f"🔎 Analisando modelo: {veiculo.marca.capitalize()} {veiculo.modelo.upper()} [{label_versao}]")
                        logger.info(f"🎯 Filtros aplicados: {str_f}")
                        logger.debug(f"🌐 Disparando navegador para: {url_busca}")
                        
                        if scan_manual:
                            # Converte < e > para formato seguro em HTML
                            str_f_seguro = html.escape(str_f)
                            label_versao_seguro = html.escape(label_versao)
                            
                            notifier.enviar_alerta(
                                f"🔄 <b>Analisando agora:</b> {veiculo.marca.capitalize()} {veiculo.modelo.upper()} [{label_versao_seguro}]\n"
                                f"↳ <i>{str_f_seguro}</i>"
                            )
                        
                        logger.debug("🔒 Aguardando liberação do db_lock para iniciar extração...")
                        with db_lock:
                            logger.debug("🔓 db_lock adquirido com sucesso.")
                            logger.info("🕷️ Solicitando extração de dados da página...")
                            anuncios = scraper.buscar_anuncios(url_busca)
                            
                            if anuncios:
                                qtd = len(anuncios)
                                total_anuncios_ciclo += qtd
                                logger.info(f"📥 Sucesso: {qtd} anúncios brutos extraídos da página.")
                                logger.info("⚙️ Repassando anúncios para o motor de avaliação (FIPE / Score)...")
                                
                                evaluator.avaliar_lista(anuncios)
                                
                                logger.info(f"✔️ Avaliação de {veiculo.modelo.upper()} [{label_versao}] finalizada.")
                            else:
                                logger.warning(f"⚠️ Nenhum anúncio retornado pela OLX para {veiculo.modelo.upper()} [{label_versao}].")
                        
                        logger.debug("🔓 db_lock liberado.")
                        logger.info("-" * 40)

            repository.salvar_metadata("ultima_execucao", datetime.now().isoformat())
            logger.info(f"✅ Varredura concluída às {datetime.now().strftime('%H:%M:%S')}. Total de anúncios capturados no ciclo: {total_anuncios_ciclo}")
            
            if scan_manual:
                notifier.enviar_alerta(f"✅ <b>Varredura manual concluída com sucesso!</b>\nForam processados {total_anuncios_ciclo} anúncios neste ciclo.")

        except Exception as e:
            logger.error("🔥 Erro Crítico na Thread Scraper", exc_info=True)
            time.sleep(60)

# =========================================================================
# HANDLER DO TELEGRAM (ROTEADOR DE COMANDOS)
# =========================================================================

class TelegramCommandHandler:
    """Roteador de comandos do Telegram (Command Pattern)."""
    
    def __init__(self, settings, repository, notifier):
        self.settings = settings
        self.repository = repository
        self.notifier = notifier
        self.db_path_raw = repository.db_path.replace("sqlite:///", "")
        
        # REGISTRO CENTRAL DE COMANDOS
        self.comandos = {
            "/scan": (self.cmd_scan, "🚀 Varredura Imediata"),
            "/analisar": (self.cmd_analisar, "🔍 Raio-X de um anúncio (Use: /analisar ID)"),
            "/top": (self.cmd_top, "🥇 Melhores Ofertas da Base"),
            "/grafico": (self.cmd_grafico, "📊 Dashboards de Mercado"),
            "/status": (self.cmd_status, "📈 Saúde do Sistema e Pesos"),
            "/config": (self.cmd_config, "⚙️ Ver limites orçamentários e filtros"),
            "/log": (self.cmd_log, "📄 Baixar arquivo de log atual"), # <--- NOVO COMANDO
            "/reset": (self.cmd_reset, "🧹 Limpar banco de anúncios processados"),
            "/help": (self.cmd_help, "❓ Mostra este menu de ajuda"),
            "/start": (self.cmd_help, None) # None oculta do menu
        }

        # MONTA E ENVIA O MENU PARA A API DO TELEGRAM
        comandos_formatados = []
        for cmd, dados in self.comandos.items():
            _, descricao = dados
            if descricao:  
                nome_comando = cmd.replace("/", "")
                comandos_formatados.append({
                    "command": nome_comando,
                    "description": descricao
                })
                
        self.notifier.configurar_menu_comandos(comandos_formatados)

    def processar_mensagem(self, texto: str):
        """Roteia a mensagem de texto para o método correto."""
        partes = texto.split()
        if not partes: return
        
        comando_base = partes[0].lower()
        logger.debug(f"📩 Processando comando do Telegram: '{texto}'")
        
        if comando_base in self.comandos:
            logger.debug(f"🔀 Roteando para o handler associado a: {comando_base}")
            metodo = self.comandos[comando_base][0]
            try:
                metodo(partes)
            except Exception as e:
                logger.error(f"❌ Erro ao executar comando {comando_base}: {e}", exc_info=True)
                self.notifier.enviar_alerta(f"⚠️ Erro ao processar comando: {e}")
        else:
            logger.debug(f"⚠️ Comando '{comando_base}' ignorado por não constar no registro de comandos.")

    # --- HANDLERS DOS COMANDOS ---

    def cmd_log(self, partes):
        """Manipulador para enviar o log atual."""
        self.notifier.enviar_alerta("📄 <b>Preparando envio do log...</b>\n<i>Isso pode levar alguns segundos dependendo do tamanho.</i>")
        
        global arquivo_log # Acessa a variável global definida no início do main.py
        
        if os.path.exists(arquivo_log):
            logger.debug(f"📤 Solicitando envio do arquivo {arquivo_log} ao Telegram.")
            sucesso = self.notifier.enviar_documento(arquivo_log)
            if not sucesso:
                self.notifier.enviar_alerta("❌ Falha ao enviar o arquivo de log. Verifique se o arquivo não está muito grande ou bloqueado.")
        else:
            self.notifier.enviar_alerta("⚠️ Arquivo de log não encontrado no servidor.")

    def cmd_help(self, partes):
        msg = "<b>🏎️ MONITOR OLX v1.5.1</b>\n────────────────────────\n"
        for cmd, dados in self.comandos.items():
            _, descricao = dados
            if descricao:
                msg += f"{descricao}\n"
        msg += "────────────────────────"
        self.notifier.enviar_alerta(msg)

    def cmd_scan(self, partes):
        msg_scan = "⚡ <b>Sinal de Varredura Recebido!</b>\n\n<b>Fila de Processamento:</b>\n"
        contador = 1
        for local in self.settings.localizacoes:
            for veiculo in self.settings.veiculos:
                filtros = []
                if getattr(veiculo, 'preco_maximo', None): filtros.append(f"💰Até R$ {int(veiculo.preco_maximo)/1000:.0f}k")
                if getattr(veiculo, 'ano_minimo', None): filtros.append(f"📅De {veiculo.ano_minimo}")
                if getattr(veiculo, 'km_maximo', None): filtros.append(f"🛣️Até {int(veiculo.km_maximo)/1000:.0f}k")
                if getattr(veiculo, 'tipo_vendedor', None): filtros.append(f"👤{str(veiculo.tipo_vendedor)[:4].capitalize()}.")
                
                string_filtros = " | ".join(filtros) if filtros else "Sem filtros extra"
                msg_scan += f"<b>{contador}. {veiculo.marca.capitalize()} {veiculo.modelo.upper()}</b>\n↳ <i>{string_filtros}</i>\n"
                contador += 1
                
        msg_scan += "\n<i>O Scraper foi acionado e enviará o passo-a-passo...</i>"
        self.notifier.enviar_alerta(msg_scan)
        evento_scan_imediato.set()

    def cmd_analisar(self, partes):
        if len(partes) != 2 or not partes[1].isdigit():
            self.notifier.enviar_alerta("⚠️ <b>Sintaxe incorreta.</b>\nUse: <code>/analisar 123456789</code>")
            return

        id_anuncio = partes[1]
        self.notifier.enviar_alerta(f"📡 <b>Buscando telemetria do anúncio {id_anuncio}...</b>")

        with db_lock:
            try:
                conn = sqlite3.connect(self.db_path_raw)
                conn.row_factory = sqlite3.Row
                anuncio_db = conn.execute("SELECT * FROM anuncios_detalhados WHERE id_anuncio = ?", (id_anuncio,)).fetchone()
                conn.close()

                if anuncio_db:
                    preco = float(anuncio_db['preco_anuncio'])
                    fipe = float(anuncio_db['preco_fipe']) if anuncio_db['preco_fipe'] else 0.0
                    
                    score_calculado = 0.0
                    if 'elite_score' in anuncio_db.keys() and anuncio_db['elite_score'] is not None:
                        score_calculado = float(anuncio_db['elite_score'])
                    
                    if fipe > 0:
                        diferenca = fipe - preco
                        fipe_texto = f"R$ {fipe:,.2f} ({(preco / fipe) * 100:.1f}%)"
                        status_preco = f"✅ Abaixo da FIPE (Economia R$ {diferenca:,.2f})" if diferenca > 0 else f"❌ Acima da FIPE (Prejuízo R$ {abs(diferenca):,.2f})"
                    else:
                        fipe_texto = "Indisponível"
                        status_preco = "⚠️ FIPE não encontrada na extração."

                    msg_analise = (
                        f"<b>🔬 RAIO-X DO ANÚNCIO</b>\n\n🏎️ <b>{anuncio_db['titulo']}</b>\n🏆 Score Dinâmico: <b>{score_calculado:.1f}/100</b>\n\n"
                        f"💰 Preço Pedido: <b>R$ {preco:,.2f}</b>\n📊 Tabela FIPE: {fipe_texto}\n⚖️ Status: <i>{status_preco}</i>\n\n"
                        f"📅 Ano: {anuncio_db['ano']} | 🛣️ KM: {anuncio_db['km']}\n🔗 <a href='{anuncio_db['link']}'>Link Original da OLX</a>"
                    )
                    self.notifier.enviar_alerta(msg_analise)
                else:
                    self.notifier.enviar_alerta(f"❌ <b>Alvo não encontrado!</b>\nO ID <code>{id_anuncio}</code> não está no banco.")
            except Exception as e:
                logger.error(f"Erro ao analisar ID {id_anuncio}: {e}", exc_info=True)
                self.notifier.enviar_alerta("⚠️ Erro interno ao acessar os dados do banco.")

    def cmd_top(self, partes):
        logger.debug(f"📊 Iniciando comando /top. Argumentos brutos recebidos: {partes[1:]}")
        cat_alvo, vend_alvo = None, None
        
        for p in partes[1:]:
            if p in ["hatch", "sedan", "suv"]: 
                cat_alvo = p
                logger.debug(f"🎯 Categoria alvo identificada: {cat_alvo}")
            elif p in ["particular", "profissional", "loja"]: 
                vend_alvo = p if p != "loja" else "profissional"
                logger.debug(f"👤 Vendedor alvo identificado: {vend_alvo}")

        msg_busca = "🥇 <b>Buscando Top 5 Elite</b>\n"
        if cat_alvo: msg_busca += f"Categoria: <i>{cat_alvo.upper()}</i>\n"
        if vend_alvo: msg_busca += f"Vendedor: <i>{vend_alvo.upper()}</i>\n"
        
        logger.debug("📨 Enviando aviso de início de busca ao Telegram...")
        self.notifier.enviar_alerta(msg_busca)
        
        logger.debug("🔒 Aguardando liberação do db_lock para gerar o relatório de elite...")
        with db_lock:
            logger.debug(f"🔓 db_lock adquirido. Executando obter_texto_elite(categoria={cat_alvo}, vendedor={vend_alvo})...")
            relatorio = obter_texto_elite(self.db_path_raw, categoria=cat_alvo, tipo_vendedor=vend_alvo)
            logger.debug("✅ Relatório de elite gerado com sucesso. Liberando db_lock.")
            
        logger.debug("📨 Enviando relatório final para o Telegram...")
        self.notifier.enviar_alerta(relatorio)
        logger.debug("🏁 Comando /top concluído.")

    def cmd_grafico(self, partes):
        self.notifier.enviar_alerta("📊 <b>Gerando Dashboards de Elite...</b>")
        with db_lock:
            arquivos = gerar_graficos_por_modelo(self.db_path_raw)
        
        if not arquivos:
            self.notifier.enviar_alerta("⚠️ Nenhum dado suficiente para gerar gráficos.")
        for img in arquivos:
            if os.path.exists(img):
                self.notifier.enviar_grafico(img, "📈 <b>Ranking de Elite</b>")
                os.remove(img)

    def cmd_status(self, partes):
        ultima_str = self.repository.ler_metadata("ultima_execucao")
        txt_ultima = datetime.fromisoformat(ultima_str).strftime('%H:%M:%S') if ultima_str else "Nunca"
        
        pesos = getattr(self.settings, 'score', None)
        p = getattr(pesos, 'pesos', None) if pesos else None
        
        p_pre = getattr(p, 'preco', 0.4) * 100 if p else 40
        p_km = getattr(p, 'km', 0.2) * 100 if p else 20
        p_id = getattr(p, 'ano', 0.1) * 100 if p else 10
        p_fipe = getattr(p, 'fipe', 0.3) * 100 if p else 30

        with db_lock:
            conn = sqlite3.connect(self.db_path_raw)
            total = conn.execute("SELECT COUNT(*) FROM anuncios_detalhados").fetchone()[0]
            conn.close()
        
        self.notifier.enviar_alerta(
            f"<b>📊 STATUS DO TERMINAL</b>\n\n"
            f"📦 Banco de Dados: <code>{total} anúncios</code>\n"
            f"🕒 Última Varredura: <code>{txt_ultima}</code>\n\n"
            f"⚖️ <b>Pesos do Score (YAML):</b>\n"
            f"💰 Preço: <code>{p_pre:.0f}%</code> | 📊 FIPE: <code>{p_fipe:.0f}%</code>\n"
            f"🛣️ KM: <code>{p_km:.0f}%</code>   | 📅 Idade: <code>{p_id:.0f}%</code>"
        )

    def cmd_config(self, partes):
        teto = getattr(self.settings.filtros_globais, 'preco_maximo_global', 0)
        km_max = getattr(self.settings.filtros_globais, 'km_maximo_global', 0)
        ano_min = getattr(self.settings.filtros_globais, 'ano_minimo', 0)
        
        self.notifier.enviar_alerta(
            "⚙️ <b>CONFIGURAÇÕES ATUAIS (YAML)</b>\n\n"
            f"💰 Teto Global: <b>R$ {teto:,.2f}</b>\n"
            f"🛣️ KM Limite: <b>{km_max:,} km</b>\n"
            f"📅 Ano Mínimo: <b>{ano_min}</b>\n\n"
            "<i>Nota: Para alterar a matemática do Score ou os Filtros Globais, edite o arquivo <code>config/config.yaml</code> no servidor e reinicie o bot. "
            "Isso garante que suas configurações fiquem salvas permanentemente sem que o bot apague os comentários do código!</i>"
        )

    def cmd_reset(self, partes):
        self.notifier.enviar_alerta("🧹 <b>Iniciando limpeza do banco de dados...</b>\n<i>Os anúncios serão apagados, mas a inteligência da FIPE mantida.</i>")
        with db_lock:
            sucesso = self.repository.resetar_anuncios()
        
        msg = "✅ <b>Banco resetado com sucesso!</b>\nUse /scan para nova varredura." if sucesso else "❌ <b>Erro ao limpar banco.</b> Verifique os logs."
        self.notifier.enviar_alerta(msg)

# =========================================================================
# THREAD 2: LISTENER DO TELEGRAM
# =========================================================================

def thread_telegram_listener(settings, repository, notifier):
    """Thread 2: Interface de Comandos do Telegram."""
    logger.info("🧵 Thread TELEGRAM ativa.")
    
    ultimo_update_id = 0
    token = settings.app.telegram_token
    chat_id_autorizado = str(settings.app.telegram_chat_id)
    
    # Instancia o roteador de comandos
    handler = TelegramCommandHandler(settings, repository, notifier)

    while True:
        try:
            params = {"offset": ultimo_update_id + 1, "timeout": 20}
            res = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params=params).json()

            if "result" in res:
                novas_mensagens = len(res["result"])
                if novas_mensagens > 0:
                    logger.debug(f"📬 {novas_mensagens} atualizações recebidas da API do Telegram.")
                    
                for update in res["result"]:
                    ultimo_update_id = update["update_id"]
                    if "message" not in update or "text" not in update["message"]: continue
                    
                    msg_obj = update["message"]
                    texto = msg_obj.get("text", "").strip()
                    
                    if str(msg_obj["chat"]["id"]) != chat_id_autorizado:
                        logger.debug(f"🚫 Ignorando mensagem de ID não autorizado: {msg_obj['chat']['id']}")
                        continue
                    
                    # Passa a string inteira para o roteador resolver
                    handler.processar_mensagem(texto)

        except Exception as e:
            logger.error(f"❌ Erro Interface Telegram: {e}")
            time.sleep(5)

# =========================================================================
# INICIALIZAÇÃO (MAIN)
# =========================================================================

def main():
    logger.info("🚀 MONITOR OLX v1.5.1 INICIADO")
    try:
        settings = load_settings()
        repository = SQLiteRepository(settings.app.database_path)
        fipe_client = ParallelumFipeClient()
        notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
        scraper = OLXPlaywrightScraper(headless=True) 
        evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

        t1 = threading.Thread(target=thread_scraper, args=(settings, repository, scraper, evaluator, notifier), daemon=True)
        t2 = threading.Thread(target=thread_telegram_listener, args=(settings, repository, notifier), daemon=True)

        t1.start()
        t2.start()

        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        logger.info("🛑 Bot encerrado manualmente.")
    except Exception as e:
        logger.error(f"💥 Falha Crítica: {e}", exc_info=True)

if __name__ == "__main__":
    main()