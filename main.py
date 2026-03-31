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
from analisar_mercado import gerar_graficos_por_modelo, obter_texto_elite

# 1. Configuração de Logs e Ambiente
load_dotenv()
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Locks e Eventos Globais para Sincronização
db_lock = threading.Lock()
evento_scan_imediato = threading.Event()

def thread_scraper(settings, repository, scraper, evaluator):
    """Thread 1: Monitoramento Contínuo da OLX Salvador."""
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
            
            evento_scan_imediato.clear()

            logger.info("--- 🔄 INICIANDO VARREDURA OLX SALVADOR ---")
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{veiculo.marca}/{veiculo.modelo}"
                    if getattr(veiculo, 'complemento_busca', None):
                        url_busca += f"/{veiculo.complemento_busca}"
                    url_busca += f"/estado-{local.estado}/regiao-{local.regiao}"

                    logger.info(f"🔎 Analisando: {veiculo.modelo.upper()} em {local.regiao.upper()}...")
                    
                    with db_lock:
                        anuncios = scraper.buscar_anuncios(url_busca)
                        if anuncios:
                            evaluator.avaliar_lista(anuncios)

            repository.salvar_metadata("ultima_execucao", datetime.now().isoformat())
            logger.info(f"✅ Varredura concluída às {datetime.now().strftime('%H:%M')}")

        except Exception as e:
            logger.error(f"🔥 Erro na Thread Scraper: {e}")
            time.sleep(60)

def thread_telegram_listener(settings, repository, notifier):
    """Thread 2: Interface de Comandos do Telegram."""
    logger.info("🧵 Thread TELEGRAM ativa.")
    
    ultimo_update_id = 0
    token = settings.app.telegram_token
    chat_id_autorizado = str(settings.app.telegram_chat_id)
    db_path_raw = repository.db_path.replace("sqlite:///", "")

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

                    if texto in ["/help", "/start"]:
                        msg_help = (
                            "<b>🏎️ MONITOR OLX SALVADOR v2.0.0</b>\n"
                            "────────────────────────\n"
                            "🚀 /scan - Varredura Imediata\n"
                            "🔍 /analisar [ID] - Raio-X de um anúncio\n"
                            "🥇 /top - Melhores Ofertas (Geral)\n"
                            "🥇 /top [modelo/categoria] - Ex: /top sedan\n"
                            "📊 /grafico - Dashboards de Mercado\n"
                            "📈 /status - Saúde do Sistema\n"
                            "⚙️ /config - Ajustar Pesos do Score\n"
                            "────────────────────────"
                        )
                        notifier.enviar_alerta(msg_help)

                    elif texto == "/scan":
                        notifier.enviar_alerta("⚡ <b>Sinal enviado!</b> Iniciando varredura...")
                        evento_scan_imediato.set()

                    # --- COMANDO /ANALISAR (Cálculo 100% em Memória) ---
                    elif texto.startswith("/analisar"):
                        partes = texto.split()
                        
                        if len(partes) != 2 or not partes[1].isdigit():
                            notifier.enviar_alerta("⚠️ <b>Sintaxe incorreta.</b>\nUse: <code>/analisar 123456789</code>")
                            continue

                        id_anuncio = partes[1]
                        notifier.enviar_alerta(f"📡 <b>Buscando telemetria do anúncio {id_anuncio}...</b>")

                        with db_lock:
                            try:
                                conn = sqlite3.connect(db_path_raw)
                                conn.row_factory = sqlite3.Row
                                anuncio_db = conn.execute(
                                    "SELECT * FROM anuncios_detalhados WHERE id_anuncio = ?", 
                                    (id_anuncio,)
                                ).fetchone()
                                conn.close()

                                if anuncio_db:
                                    preco = float(anuncio_db['preco_anuncio'])
                                    fipe = float(anuncio_db['preco_fipe']) if anuncio_db['preco_fipe'] else 0.0
                                    
                                    # Cálculo Dinâmico do Score na hora
                                    score_calculado = 0.0
                                    
                                    if fipe > 0:
                                        # Puxa os pesos do banco (ou usa os padrões)
                                        p_pre = float(repository.ler_metadata("peso_preco") or 50)
                                        p_km = float(repository.ler_metadata("peso_km") or 30)
                                        p_id = float(repository.ler_metadata("peso_idade") or 20)
                                        
                                        ano_carro = int(anuncio_db['ano'])
                                        km_carro = int(anuncio_db['km'])
                                        
                                        # Matemática do Preço
                                        razao_preco = preco / fipe
                                        if razao_preco >= 1.0:
                                            pt_preco = max(0.0, 100.0 - ((razao_preco - 1.0) * 200.0))
                                        else:
                                            pt_preco = min(100.0, 50.0 + ((1.0 - razao_preco) * 200.0))
                                            
                                        # Matemática da KM e Idade
                                        ano_atual = datetime.now().year
                                        idade = max(1, ano_atual - ano_carro)
                                        km_ideal = idade * 12000
                                        pt_km = max(0.0, 100.0 - ((km_carro / km_ideal) * 50.0))
                                        pt_idade = max(0.0, 100.0 - (idade * 5.0))
                                        
                                        # Consolidação
                                        score_calculado = (pt_preco * (p_pre / 100.0)) + (pt_km * (p_km / 100.0)) + (pt_idade * (p_id / 100.0))
                                        score_calculado = round(max(0.0, min(100.0, score_calculado)), 2)
                                        
                                        diferenca = fipe - preco
                                        percentual = (preco / fipe) * 100
                                        fipe_texto = f"R$ {fipe:,.2f} ({percentual:.1f}%)"
                                        
                                        if diferenca > 0:
                                            status_preco = f"✅ Abaixo da FIPE (Economia de R$ {diferenca:,.2f})"
                                        else:
                                            status_preco = f"❌ Acima da FIPE (Prejuízo de R$ {abs(diferenca):,.2f})"
                                    else:
                                        fipe_texto = "Indisponível"
                                        status_preco = "⚠️ FIPE não encontrada na época da extração."

                                    msg_analise = (
                                        f"<b>🔬 RAIO-X DO ANÚNCIO</b>\n\n"
                                        f"🏎️ <b>{anuncio_db['titulo']}</b>\n"
                                        f"🏆 Score Dinâmico: <b>{score_calculado:.1f}/100</b>\n\n"
                                        f"💰 Preço Pedido: <b>R$ {preco:,.2f}</b>\n"
                                        f"📊 Tabela FIPE: {fipe_texto}\n"
                                        f"⚖️ Status: <i>{status_preco}</i>\n\n"
                                        f"📅 Ano: {anuncio_db['ano']} | 🛣️ KM: {anuncio_db['km']}\n"
                                        f"🔗 <a href='{anuncio_db['link']}'>Link Original da OLX</a>"
                                    )
                                    notifier.enviar_alerta(msg_analise)
                                else:
                                    notifier.enviar_alerta(
                                        f"❌ <b>Alvo não encontrado!</b>\n\n"
                                        f"O ID <code>{id_anuncio}</code> não está no banco de dados. "
                                    )
                            except Exception as e:
                                logger.error(f"Erro ao analisar ID {id_anuncio}: {e}")
                                notifier.enviar_alerta("⚠️ Erro interno ao acessar os dados do banco.")

                    # --- COMANDO /TOP ---
                    elif texto.startswith("/top"):
                        parts = texto.split()
                        alvo = parts[1] if len(parts) > 1 else None
                        
                        categorias_validas = ["hatch", "sedan", "suv"]
                        
                        if alvo in categorias_validas:
                            notifier.enviar_alerta(f"🥇 <b>Buscando os melhores {alvo.upper()}S de Salvador...</b>")
                        elif alvo:
                            notifier.enviar_alerta(f"🥇 <b>Garimpando Top 5 {alvo.capitalize()} em Salvador...</b>")
                        else:
                            notifier.enviar_alerta("🥇 <b>Garimpando Top 5 Geral em Salvador...</b>")
                        
                        with db_lock:
                            relatorio = obter_texto_elite(db_path_raw, alvo)
                        notifier.enviar_alerta(relatorio)

                    elif texto == "/grafico":
                        notifier.enviar_alerta("📊 <b>Gerando Dashboards de Elite...</b>")
                        with db_lock:
                            arquivos = gerar_graficos_por_modelo(db_path_raw)
                        
                        if not arquivos:
                            notifier.enviar_alerta("⚠️ Nenhum dado suficiente para gerar gráficos. Verifique seu settings.yaml.")
                        
                        for img in arquivos:
                            if os.path.exists(img):
                                notifier.enviar_grafico(img, "📈 <b>Ranking de Elite</b>")
                                os.remove(img)

                    elif texto == "/status":
                        ultima_str = repository.ler_metadata("ultima_execucao")
                        txt_ultima = datetime.fromisoformat(ultima_str).strftime('%H:%M:%S') if ultima_str else "Nunca"
                        
                        p_pre = repository.ler_metadata("peso_preco") or "50"
                        p_km = repository.ler_metadata("peso_km") or "30"
                        p_id = repository.ler_metadata("peso_idade") or "20"

                        with db_lock:
                            conn = sqlite3.connect(db_path_raw)
                            total = conn.execute("SELECT COUNT(*) FROM anuncios_detalhados").fetchone()[0]
                            conn.close()
                        
                        notifier.enviar_alerta(
                            f"<b>📊 STATUS DO TERMINAL</b>\n\n"
                            f"📦 Banco: <code>{total} anúncios</code>\n"
                            f"🕒 Última: <code>{txt_ultima}</code>\n"
                            f"⚙️ Pesos: <code>💰{p_pre}% | 🛣️{p_km}% | 📅{p_id}%</code>"
                        )

                    elif texto.startswith("/config"):
                        parts = texto.split()
                        if len(parts) == 4:
                            try:
                                p_pre, p_km, p_id = map(int, parts[1:])
                                if sum([p_pre, p_km, p_id]) == 100:
                                    repository.salvar_metadata("peso_preco", str(p_pre))
                                    repository.salvar_metadata("peso_km", str(p_km))
                                    repository.salvar_metadata("peso_idade", str(p_id))
                                    notifier.enviar_alerta("✅ <b>Pesos atualizados com sucesso!</b>")
                                else:
                                    notifier.enviar_alerta("⚠️ A soma deve ser 100!")
                            except:
                                notifier.enviar_alerta("⚠️ Use números inteiros: <code>/config 50 30 20</code>")
                        else:
                            notifier.enviar_alerta("⚙️ <b>Config:</b> Use <code>/config [preco] [km] [idade]</code>")

        except Exception as e:
            logger.error(f"❌ Erro Interface Telegram: {e}")
            time.sleep(5)

def main():
    logger.info("🚀 MONITOR OLX v2.0.0 - SALVADOR EDITION INICIADO")
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
            time.sleep(10)

    except KeyboardInterrupt:
        logger.info("🛑 Bot encerrado manualmente.")
    except Exception as e:
        logger.error(f"💥 Falha Crítica: {e}")

if __name__ == "__main__":
    main()