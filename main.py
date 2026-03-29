import time
import logging
import os
import threading
import requests
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
from config.settings import load_settings
from infrastructure.api.fipe_client import ParallelumFipeClient
from infrastructure.database.sqlite_repo import SQLiteRepository
from infrastructure.notifications.telegram_notifier import TelegramNotifier
from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper
from core.evaluator import CarEvaluator
from analisar_mercado import gerar_graficos_por_modelo

# 1. Configuração de Ambiente e Logs
load_dotenv()
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Locks e Eventos de Sincronização
db_lock = threading.Lock()
evento_scan_imediato = threading.Event()

def thread_scraper(settings, repository, scraper, evaluator):
    """Thread 1: Ciclo de busca (Wait-First) com persistência no banco."""
    logger.info("🧵 Thread SCRAPER iniciada e monitorando...")
    
    intervalo_min = settings.app.intervalo_scraping_minutos

    while True:
        try:
            # Busca última execução no banco (Metadata)
            ultima_str = repository.ler_metadata("ultima_execucao")
            ultima = datetime.fromisoformat(ultima_str) if ultima_str else None
            
            agora = datetime.now()
            if ultima:
                proxima = ultima + timedelta(minutes=intervalo_min)
                segundos_espera = (proxima - agora).total_seconds()
            else:
                segundos_espera = 0

            # Lógica de Espera Inteligente
            if segundos_espera > 0:
                logger.info(f"⏳ Standby: Próximo ciclo em {int(segundos_espera/60)} min.")
                evento_scan_imediato.wait(timeout=segundos_espera)
            
            # Reseta sinal se foi acordado por /scan
            evento_scan_imediato.clear()

            logger.info("--- 🔄 EXECUTANDO VARREDURA OLX SALVADOR ---")
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    marca, modelo = veiculo.marca, veiculo.modelo
                    complemento = getattr(veiculo, 'complemento_busca', None)
                    
                    # Montagem de URL Robusta
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{marca}/{modelo}"
                    if complemento: url_busca += f"/{complemento}"
                    url_busca += f"/estado-{local.estado}"
                    if local.regiao != "todas": url_busca += f"/regiao-{local.regiao}"

                    logger.info(f"🔎 Analisando: {marca} {modelo}...")
                    
                    with db_lock:
                        anuncios = scraper.buscar_anuncios(url_busca)
                        if anuncios:
                            evaluator.avaliar_lista(anuncios)

            # Salva sucesso no banco
            repository.salvar_metadata("ultima_execucao", datetime.now().isoformat())
            logger.info(f"✅ Ciclo finalizado com sucesso.")

        except Exception as e:
            logger.error(f"🔥 Erro na Thread Scraper: {e}")
            time.sleep(60)

def thread_telegram_listener(settings, repository, notifier):
    """Thread 2: Console de Comandos e Interface do Usuário."""
    logger.info("🧵 Thread TELEGRAM iniciada e aguardando comandos...")
    
    ultimo_update_id = 0
    token = settings.app.telegram_token
    chat_id_autorizado = str(settings.app.telegram_chat_id)
    db_path_raw = repository.db_path

    while True:
        try:
            params = {"offset": ultimo_update_id + 1, "timeout": 20}
            res = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params=params).json()

            if "result" in res:
                for update in res["result"]:
                    ultimo_update_id = update["update_id"]
                    if "message" not in update or "text" not in update["message"]: continue
                    
                    msg_obj = update["message"]
                    texto = msg_obj.get("text", "").lower().strip()
                    if str(msg_obj["chat"]["id"]) != chat_id_autorizado: continue

                    # --- MENU CONSOLE STYLE ---
                    if texto in ["/help", "/start", "ajuda"]:
                        msg_help = (
                            "<b>🏎️ MONITOR OLX SALVADOR v1.3.1</b>\n"
                            "<i>Sua inteligência de mercado em tempo real</i>\n"
                            "────────────────────────\n"
                            "<b>💻 CONSOLE DE OPERAÇÃO:</b>\n\n"
                            "🚀 /scan\n"
                            "└─ <i>Força a varredura imediata na OLX.</i>\n\n"
                            "📊 /grafico\n"
                            "└─ <i>Mapa de calor (Top 10) por Score.</i>\n\n"
                            "📈 /status\n"
                            "└─ <i>Saúde do banco e tempo de espera.</i>\n\n"
                            "❓ /help\n"
                            "└─ <i>Exibe este console de ajuda.</i>\n"
                            "────────────────────────\n"
                            "🛰️ <b>Status:</b> <code>Online & Vigilante</code>\n"
                            "🎯 <b>Filtro:</b> <code>FIPE &lt; 95% | Score &gt; 70</code>"
                        )
                        notifier.enviar_alerta(msg_help)

                    elif texto == "/scan":
                        notifier.enviar_alerta("⚡ <b>Sinal enviado!</b> O scraper está sendo acordado...")
                        evento_scan_imediato.set()

                    elif texto == "/status":
                        ultima_str = repository.ler_metadata("ultima_execucao")
                        txt_ultima = datetime.fromisoformat(ultima_str).strftime('%H:%M:%S') if ultima_str else "Nunca"
                        
                        # Cálculo de tempo restante
                        intervalo = settings.app.intervalo_scraping_minutos
                        proxima = (datetime.fromisoformat(ultima_str) + timedelta(minutes=intervalo)) if ultima_str else datetime.now()
                        faltam = max(0, int((proxima - datetime.now()).total_seconds() / 60))

                        with db_lock:
                            conn = sqlite3.connect(db_path_raw)
                            total = conn.execute("SELECT COUNT(*) FROM anuncios_detalhados").fetchone()[0]
                            conn.close()
                        
                        status_txt = (
                            f"<b>📊 STATUS DO TERMINAL</b>\n\n"
                            f"📦 Banco: <code>{total} anúncios</code>\n"
                            f"🕒 Última Rodada: <code>{txt_ultima}</code>\n"
                            f"⏳ Próximo Ciclo: <code>{faltam} minutos</code>\n"
                            f"🛰️ Scanner: <code>Ativo</code>"
                        )
                        notifier.enviar_alerta(status_txt)

                    elif texto == "/grafico":
                        notifier.enviar_alerta("📊 <b>Analisando dados...</b> Gerando mapa de calor.")
                        with db_lock:
                            arquivos = gerar_graficos_por_modelo(db_path_raw)
                        
                        if not arquivos:
                            notifier.enviar_alerta("⚠️ <b>Erro:</b> Dados insuficientes para análise.")
                        else:
                            for img in arquivos:
                                if os.path.exists(img):
                                    modelo_nome = img.split('_')[1].upper() if '_' in img else "GERAL"
                                    notifier.enviar_grafico(img, f"📈 Oportunidades: {modelo_nome}")
                                    os.remove(img)
                            notifier.enviar_alerta("✅ <b>Dashboard enviado!</b>")

        except Exception as e:
            logger.error(f"❌ Erro na Interface Telegram: {e}")
            time.sleep(5)

def main():
    logger.info("🚀 SISTEMA INICIADO - MONITOR OLX v1.3.1")
    try:
        settings = load_settings()
        
        # Injeção de Dependências
        repository = SQLiteRepository(settings.app.database_path)
        fipe_client = ParallelumFipeClient()
        notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
        scraper = OLXPlaywrightScraper(headless=True) 
        evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

        # Configuração das Threads (Ordem Corrigida)
        t1 = threading.Thread(target=thread_scraper, args=(settings, repository, scraper, evaluator), daemon=True)
        t2 = threading.Thread(target=thread_telegram_listener, args=(settings, repository, notifier), daemon=True)

        t1.start()
        t2.start()

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("🛑 Encerrando Terminal...")
    except Exception as e:
        logger.error(f"💥 Falha Crítica: {e}")

if __name__ == "__main__":
    main()