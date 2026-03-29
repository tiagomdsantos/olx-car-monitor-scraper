# main.py
import time
import logging
import traceback
import os
import threading
import requests
from dotenv import load_dotenv
from config.settings import load_settings
from infrastructure.api.fipe_client import ParallelumFipeClient
from infrastructure.database.sqlite_repo import SQLiteRepository
from infrastructure.notifications.telegram_notifier import TelegramNotifier
from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper
from core.evaluator import CarEvaluator

# 1. Inicialização
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Controle Global
ULTIMO_UPDATE_ID = 0
SCRAPER_LOCK = threading.Lock() 

def executar_rodada_completa(settings, scraper, evaluator, repository):
    """Executa a busca e atualiza o timestamp de sucesso no banco."""
    with SCRAPER_LOCK:
        logger.info("📡 Iniciando execução do Scraper...")
        try:
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    marca, modelo = veiculo.marca, veiculo.modelo
                    complemento = getattr(veiculo, 'complemento_busca', None)
                    
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{marca}/{modelo}"
                    if complemento: url_busca += f"/{complemento}"
                    url_busca += f"/estado-{local.estado}"
                    if local.regiao != "todas": url_busca += f"/regiao-{local.regiao}"

                    logger.info(f"🔎 Buscando: {marca} {modelo}...")
                    anuncios = scraper.buscar_anuncios(url_busca)
                    if anuncios:
                        evaluator.avaliar_lista(anuncios)
            
            # Marca sucesso no banco para evitar re-runs imediatos em restarts
            repository.atualizar_ultimo_scan()
            logger.info("✅ Execução do Scraper finalizada com sucesso.")
        except Exception as e:
            logger.error(f"❌ Erro durante a rodada de busca: {e}")

def task_telegram_listener(settings, notifier, scraper, evaluator, repository):
    """Thread que escuta e executa comandos do usuário."""
    global ULTIMO_UPDATE_ID
    logger.info("📡 Listener do Telegram Ativo.")
    
    url = f"https://api.telegram.org/bot{settings.app.telegram_token}/getUpdates"
    
    while True:
        try:
            params = {"offset": ULTIMO_UPDATE_ID + 1, "timeout": 20}
            response = requests.get(url, params=params).json()
            
            if not response or "result" not in response:
                continue

            for update in response["result"]:
                ULTIMO_UPDATE_ID = update["update_id"]
                message = update.get("message", {})
                texto = message.get("text", "").lower() if message.get("text") else ""
                chat_id_origem = message.get("chat", {}).get("id")

                if str(chat_id_origem) != str(settings.app.telegram_chat_id):
                    continue

                if texto in ["/help", "/start"]:
                    msg_help = (
                        "<b>🤖 Monitor OLX Salvador - Comandos:</b>\n\n"
                        "🚀 /buscar - Executa o scraper <b>agora</b>\n"
                        "📊 /grafico - Gera gráfico Preço vs KM atualizado\n"
                        "✅ /status - Saúde do sistema e tempo desde último scan\n"
                        "❓ /help - Mostra esta lista"
                    )
                    notifier.enviar_alerta(msg_help)

                elif texto == "/buscar":
                    if SCRAPER_LOCK.locked():
                        notifier.enviar_alerta("⚠️ O scraper já está rodando. Aguarde.")
                    else:
                        notifier.enviar_alerta("🔎 Iniciando busca manual em Salvador...")
                        threading.Thread(target=executar_rodada_completa, args=(settings, scraper, evaluator, repository)).start()

                elif texto == "/grafico":
                    notifier.enviar_alerta("⏳ Gerando gráfico de mercado... Aguarde.")
                    from analisar_mercado import gerar_grafico_preco_km
                    gerar_grafico_preco_km()
                    if os.path.exists("analise_mercado_salvador.png"):
                        notifier.enviar_grafico("analise_mercado_salvador.png", "📊 Panorama Salvador: Preço vs KM")
                    else:
                        notifier.enviar_alerta("❌ Erro ao gerar gráfico.")

                elif texto == "/status":
                    minutos = repository.obter_minutos_desde_ultimo_scan()
                    status_msg = f"✅ Monitor Online!\n"
                    status_msg += f"🕒 Último scan: {minutos:.0f} min atrás\n"
                    status_msg += f"📅 Intervalo config: {settings.app.intervalo_scraping_minutos} min"
                    notifier.enviar_alerta(status_msg)

        except Exception as e:
            logger.debug(f"Erro Telegram Listener: {e}")
            time.sleep(5)

def task_scraper_periodico(settings, scraper, evaluator, repository):
    """Thread que executa a busca automática respeitando o histórico no banco."""
    intervalo_config = settings.app.intervalo_scraping_minutos
    
    while True:
        minutos_passados = repository.obter_minutos_desde_ultimo_scan()
        
        if minutos_passados < intervalo_config:
            tempo_restante = int(intervalo_config - minutos_passados)
            logger.info(f"⏳ Scan recente ({minutos_passados:.0f}min atrás). Aguardando {tempo_restante}min.")
            time.sleep(60) # Checa a cada minuto se já pode rodar
            continue

        if not SCRAPER_LOCK.locked():
            executar_rodada_completa(settings, scraper, evaluator, repository)
        
        time.sleep(60) # Ciclo de verificação de tempo

def main():
    logger.info("🚀 Monitor OLX Salvador v1.2.6 - Smart Persistence")
    
    try:
        settings = load_settings()
        os.makedirs(os.path.dirname(settings.app.database_path.replace("sqlite:///", "")), exist_ok=True)
        
        # Injeção
        fipe_client = ParallelumFipeClient()
        repository = SQLiteRepository(settings.app.database_path)
        notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
        scraper = OLXPlaywrightScraper(headless=True) 
        evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

        # Disparar Threads (Agora com os argumentos corretos)
        t_telegram = threading.Thread(
            target=task_telegram_listener, 
            args=(settings, notifier, scraper, evaluator, repository), 
            daemon=True
        )
        t_periodico = threading.Thread(
            target=task_scraper_periodico, 
            args=(settings, scraper, evaluator, repository), 
            daemon=True
        )

        t_telegram.start()
        t_periodico.start()

        while True: time.sleep(1)

    except KeyboardInterrupt:
        logger.info("🛑 Encerrando...")
    except Exception as e:
        logger.error(f"❌ Erro Fatal: {e}\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()