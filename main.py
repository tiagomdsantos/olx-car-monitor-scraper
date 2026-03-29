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

# 1. Configuração de Logs
load_dotenv()
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Locks e Eventos Globais
db_lock = threading.Lock()
evento_scan_imediato = threading.Event()

def thread_scraper(settings, repository, scraper, evaluator):
    """Thread 1: Ciclo de busca persistente com inteligência de intervalo."""
    logger.info("🧵 Thread SCRAPER ativa.")
    
    intervalo_min = settings.app.intervalo_scraping_minutos

    while True:
        try:
            # Recupera última execução do banco
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
            
            evento_scan_imediato.clear()

            logger.info("--- 🔄 INICIANDO VARREDURA OLX SALVADOR ---")
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{veiculo.marca}/{veiculo.modelo}"
                    if getattr(veiculo, 'complemento_busca', None):
                        url_busca += f"/{veiculo.complemento_busca}"
                    url_busca += f"/estado-{local.estado}"
                    if local.regiao != "todas":
                        url_busca += f"/regiao-{local.regiao}"

                    logger.info(f"🔎 Analisando: {veiculo.modelo}...")
                    
                    with db_lock:
                        anuncios = scraper.buscar_anuncios(url_busca)
                        if anuncios:
                            evaluator.avaliar_lista(anuncios)

            # Salva sucesso no banco para o próximo restart
            repository.salvar_metadata("ultima_execucao", datetime.now().isoformat())
            logger.info(f"✅ Varredura concluída às {datetime.now().strftime('%H:%M')}")

        except Exception as e:
            logger.error(f"🔥 Erro na Thread Scraper: {e}")
            time.sleep(60)

def thread_telegram_listener(settings, repository, notifier):
    """Thread 2: Console de Comandos e Ajustes de Configuração."""
    logger.info("🧵 Thread TELEGRAM ativa.")
    
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

                    # --- COMANDOS OPERACIONAIS ---
                    if texto in ["/help", "/start", "ajuda"]:
                        msg_help = (
                            "<b>🏎️ MONITOR OLX SALVADOR v1.5.0</b>\n"
                            "────────────────────────\n"
                            "🚀 /scan - Busca Imediata\n"
                            "📊 /grafico - Mapa de Calor (Top 10)\n"
                            "📈 /status - Saúde do Sistema\n"
                            "⚙️ /config - Ajustar Pesos Score\n"
                            "────────────────────────\n"
                            "🛰️ <b>Status:</b> <code>Online & Vigilante</code>"
                        )
                        notifier.enviar_alerta(msg_help)

                    elif texto == "/scan":
                        notifier.enviar_alerta("⚡ <b>Sinal enviado!</b> Iniciando varredura...")
                        evento_scan_imediato.set()

                    elif texto == "/status":
                        ultima_str = repository.ler_metadata("ultima_execucao")
                        txt_ultima = datetime.fromisoformat(ultima_str).strftime('%H:%M:%S') if ultima_str else "Nunca"
                        
                        # Pesos Atuais
                        p_pre = repository.ler_metadata("peso_preco") or "50"
                        p_km = repository.ler_metadata("peso_km") or "30"
                        p_id = repository.ler_metadata("peso_idade") or "20"

                        with db_lock:
                            conn = sqlite3.connect(db_path_raw)
                            total = conn.execute("SELECT COUNT(*) FROM anuncios_detalhados").fetchone()[0]
                            conn.close()
                        
                        status_txt = (
                            f"<b>📊 STATUS DO TERMINAL</b>\n\n"
                            f"📦 Banco: <code>{total} anúncios</code>\n"
                            f"🕒 Última: <code>{txt_ultima}</code>\n"
                            f"⚙️ Pesos: <code>💰{p_pre}% | 🛣️{p_km}% | 📅{p_id}%</code>"
                        )
                        notifier.enviar_alerta(status_txt)

                    # --- COMANDO DE CONFIGURAÇÃO REMOTA ---
                    elif texto.startswith("/config"):
                        parts = texto.split()
                        if len(parts) == 4:
                            try:
                                p_pre, p_km, p_id = map(int, parts[1:])
                                if sum([p_pre, p_km, p_id]) == 100:
                                    repository.salvar_metadata("peso_preco", str(p_pre))
                                    repository.salvar_metadata("peso_km", str(p_km))
                                    repository.salvar_metadata("peso_idade", str(p_id))
                                    
                                    notifier.enviar_alerta(
                                        f"⚙️ <b>Configuração Atualizada!</b>\n"
                                        f"Pesos: Preço {p_pre}% | KM {p_km}% | Idade {p_id}%"
                                    )
                                else:
                                    notifier.enviar_alerta("⚠️ <b>Erro:</b> A soma deve ser 100!")
                            except:
                                notifier.enviar_alerta("⚠️ <b>Erro:</b> Use números inteiros.")
                        else:
                            p_pre = repository.ler_metadata("peso_preco") or "50"
                            p_km = repository.ler_metadata("peso_km") or "30"
                            p_id = repository.ler_metadata("peso_idade") or "20"
                            notifier.enviar_alerta(
                                f"⚙️ <b>Pesos Atuais:</b>\n💰:{p_pre}% 🛣️:{p_km}% 📅:{p_id}%\n\n"
                                f"Alterar: <code>/config [preço] [km] [idade]</code>"
                            )

                    elif texto == "/grafico":
                        notifier.enviar_alerta("📊 <b>Gerando análise...</b>")
                        with db_lock:
                            arquivos = gerar_graficos_por_modelo(db_path_raw)
                        for img in arquivos:
                            if os.path.exists(img):
                                notifier.enviar_grafico(img, "📈 <b>Mapa de Oportunidades</b>")
                                os.remove(img)

        except Exception as e:
            logger.error(f"❌ Erro Interface: {e}")
            time.sleep(5)

def main():
    logger.info("🚀 MONITOR OLX v1.5.0 INICIADO")
    try:
        settings = load_settings()
        repository = SQLiteRepository(settings.app.database_path)
        fipe_client = ParallelumFipeClient()
        notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
        scraper = OLXPlaywrightScraper(headless=True) 
        evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

        t1 = threading.Thread(target=thread_scraper, args=(settings, repository, scraper, evaluator), daemon=True)
        t2 = threading.Thread(target=thread_telegram_listener, args=(settings, repository, notifier), daemon=True)

        t1.start()
        t2.start()

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("🛑 Encerrando...")
    except Exception as e:
        logger.error(f"💥 Falha: {e}")

if __name__ == "__main__":
    main()