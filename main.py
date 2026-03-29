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

# 1. Configuração e Logs
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Locks e Eventos Globais
db_lock = threading.Lock()
evento_scan_imediato = threading.Event()

def gerir_timestamp_execucao(db_path, modo="ler"):
    """Lê ou grava o horário da última execução no banco de dados."""
    with db_lock:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Cria tabela de metadados se não existir
        cursor.execute("CREATE TABLE IF NOT EXISTS bot_metadata (chave TEXT PRIMARY KEY, valor TEXT)")
        
        if modo == "ler":
            cursor.execute("SELECT valor FROM bot_metadata WHERE chave = 'ultima_execucao'")
            row = cursor.fetchone()
            conn.close()
            return datetime.fromisoformat(row[0]) if row else None
        else:
            ts = datetime.now().isoformat()
            cursor.execute("INSERT OR REPLACE INTO bot_metadata (chave, valor) VALUES ('ultima_execucao', ?)", (ts,))
            conn.commit()
            conn.close()

def thread_scraper(settings, scraper, evaluator, db_path):
    """Thread 1: Controla o ciclo baseado no histórico real do banco."""
    logger.info("🧵 Thread SCRAPER iniciada.")
    
    intervalo_min = settings.app.intervalo_scraping_minutos

    while True:
        try:
            ultima = gerir_timestamp_execucao(db_path, "ler")
            agora = datetime.now()

            # Cálculo de quanto tempo falta baseado na última vez que o bot TRABALHOU
            if ultima:
                proxima_execucao = ultima + timedelta(minutes=intervalo_min)
                segundos_espera = (proxima_execucao - agora).total_seconds()
            else:
                segundos_espera = 0 # Nunca rodou, começa já

            if segundos_espera > 0:
                logger.info(f"⏳ Aguardando {int(segundos_espera/60)} min para completar o intervalo desde a última rodada.")
                # Espera o tempo restante OU o sinal do /scan
                ativado_por_comando = evento_scan_imediato.wait(timeout=segundos_espera)
            else:
                ativado_por_comando = False

            # Se foi acordado por comando ou o tempo acabou
            logger.info("--- 🔄 Iniciando varredura OLX ---")
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{veiculo.marca}/{veiculo.modelo}"
                    if getattr(veiculo, 'complemento_busca', None): 
                        url_busca += f"/{veiculo.complemento_busca}"
                    url_busca += f"/estado-{local.estado}"
                    if local.regiao != "todas": url_busca += f"/regiao-{local.regiao}"

                    logger.info(f"🔎 Buscando: {veiculo.modelo}...")
                    anuncios = scraper.buscar_anuncios(url_busca)
                    if anuncios:
                        evaluator.avaliar_lista(anuncios)

            # Grava no banco que terminou agora
            gerir_timestamp_execucao(db_path, "gravar")
            evento_scan_imediato.clear()
            logger.info(f"✅ Ciclo finalizado. Timestamp guardado no banco.")

        except Exception as e:
            logger.error(f"🔥 Erro na Thread Scraper: {e}")
            time.sleep(60)

def thread_telegram_listener(settings, notifier, db_path):
    """Thread 2: Interface de comandos via Telegram."""
    ultimo_update_id = 0
    token = settings.app.telegram_token
    chat_id_autorizado = str(settings.app.telegram_chat_id)

    while True:
        try:
            params = {"offset": ultimo_update_id + 1, "timeout": 20}
            res = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", params=params).json()

            if "result" in res:
                for update in res["result"]:
                    ultimo_update_id = update["update_id"]
                    if "message" not in update or "text" not in update["message"]: continue
                    
                    texto = update["message"].get("text", "").lower().strip()
                    if str(update["message"]["chat"]["id"]) != chat_id_autorizado: continue

                    # --- MENU DE AJUDA ---
                    if texto in ["/help", "/start", "ajuda", "comandos"]:
                        msg_help = (
                            "<b>🤖 Monitor OLX Salvador - Comandos</b>\n\n"
                            "🚀 /scan - Força uma busca imediata na OLX.\n"
                            "📊 /grafico - Gera análise visual (Top 10) por modelo.\n"
                            "📈 /status - Mostra o total de anúncios e tempo para o próximo ciclo.\n"
                            "❓ /help - Exibe este menu de ajuda."
                        )
                        notifier.enviar_alerta(msg_help)

                    # --- COMANDOS EXISTENTES ---
                    elif texto == "/scan":
                        notifier.enviar_alerta("⚡ <b>Forçando Scan...</b> O scraper será acordado imediatamente.")
                        evento_scan_imediato.set()

                    elif texto == "/status":
                        ultima = gerir_timestamp_execucao(db_path, "ler")
                        txt_ultima = ultima.strftime('%H:%M:%S') if ultima else "Nunca"
                        
                        # Cálculo de tempo restante
                        intervalo = settings.app.intervalo_scraping_minutos
                        proxima = (ultima + timedelta(minutes=intervalo)) if ultima else datetime.now()
                        faltam = max(0, int((proxima - datetime.now()).total_seconds() / 60))

                        with db_lock:
                            conn = sqlite3.connect(db_path)
                            total = conn.execute("SELECT COUNT(*) FROM anuncios_detalhados").fetchone()[0]
                            conn.close()
                        
                        status_txt = (
                            f"<b>📊 Status do Sistema</b>\n\n"
                            f"📦 Banco: <b>{total}</b> anúncios\n"
                            f"🕒 Última rodada: {txt_ultima}\n"
                            f"⏳ Próxima rodada em: <b>{faltam} min</b>"
                        )
                        notifier.enviar_alerta(status_txt)

                    elif texto == "/grafico":
                        notifier.enviar_alerta("📊 Gerando análise de mercado... Aguarde.")
                        with db_lock:
                            # Import local para evitar problemas de dependência circular
                            from analisar_mercado import gerar_graficos_por_modelo
                            arquivos = gerar_graficos_por_modelo()
                        
                        if not arquivos:
                            notifier.enviar_alerta("⚠️ Sem dados suficientes para gerar os gráficos.")
                        else:
                            for img in arquivos:
                                if os.path.exists(img):
                                    # Extrai o nome do modelo do arquivo para a legenda
                                    nome_modelo = img.split('_')[1].upper() if '_' in img else "GERAL"
                                    notifier.enviar_grafico(img, f"📈 Top 10 Oportunidades: {nome_modelo}")
                                    os.remove(img)
                            notifier.enviar_alerta("✅ Análise concluída!")

        except Exception as e:
            logging.error(f"Erro na Thread Telegram: {e}")
            time.sleep(5)

def main():
    settings = load_settings()
    db_full_path = settings.app.database_path.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_full_path), exist_ok=True)

    fipe_client = ParallelumFipeClient()
    repository = SQLiteRepository(settings.app.database_path)
    notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
    scraper = OLXPlaywrightScraper(headless=True) 
    evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

    t1 = threading.Thread(target=thread_scraper, args=(settings, scraper, evaluator, db_full_path), daemon=True)
    t2 = threading.Thread(target=thread_telegram_listener, args=(settings, notifier, db_full_path), daemon=True)

    t1.start()
    t2.start()

    while True: time.sleep(1)

if __name__ == "__main__":
    main()