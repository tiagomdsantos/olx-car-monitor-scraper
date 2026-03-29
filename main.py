# main.py
import time
import logging
import traceback
import os # Adicionado para criar a pasta data
from config.settings import load_settings
from infrastructure.api.fipe_client import ParallelumFipeClient
from infrastructure.database.sqlite_repo import SQLiteRepository
from infrastructure.notifications.telegram_notifier import TelegramNotifier
from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper
from core.evaluator import CarEvaluator

# Configuração de Log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("🚀 Iniciando o Monitor de Ofertas OLX...")
    
    # 1. Carregamento de Configurações
    try:
        settings = load_settings()
    except Exception as e:
        logger.error(f"❌ Erro crítico ao carregar as configurações: {e}")
        return

    # --- CORREÇÃO DO BANCO DE DADOS ---
    # Garante que a pasta 'data' exista antes de iniciar o SQLite
    db_path = settings.app.database_path.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # 2. Injeção de Dependências
    fipe_client = ParallelumFipeClient()
    repository = SQLiteRepository(settings.app.database_path)
    notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
    scraper = OLXPlaywrightScraper(headless=True) 
    evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

    while True:
        try:
            logger.info("--- 🔄 Iniciando nova rodada de verificação ---")
            
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    # Montagem da URL Corrigida
                    # Usamos getattr para evitar o erro caso 'complemento_busca' não exista no YAML
                    marca = veiculo.marca
                    modelo = veiculo.modelo
                    complemento = getattr(veiculo, 'complemento_busca', None)
                    
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{marca}/{modelo}"
                    
                    if complemento:
                        url_busca += f"/{complemento}"
                    
                    url_busca += f"/estado-{local.estado}"
                    if local.regiao != "todas":
                        url_busca += f"/regiao-{local.regiao}"

                    logger.info(f"🔎 Buscando: {marca} {modelo} em {local.regiao}...")
                    
                    # Busca e Avaliação
                    anuncios = scraper.buscar_anuncios(url_busca)
                    
                    if anuncios:
                        evaluator.avaliar_lista(anuncios)
                    else:
                        logger.warning(f"⚠️ Sem anúncios para {modelo}.")

            intervalo = settings.app.intervalo_scraping_minutos
            logger.info(f"✅ Rodada finalizada em Salvador. Dormindo por {intervalo} min.")
            time.sleep(intervalo * 60)

        except KeyboardInterrupt:
            logger.info("🛑 Monitoramento interrompido. Saindo...")
            break
        except Exception as e:
            logger.error(f"🔥 ERRO INESPERADO: {str(e)}")
            logger.debug(traceback.format_exc())
            time.sleep(60) 

if __name__ == "__main__":
    main()