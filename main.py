# main.py
import time
import logging
import traceback
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
    
    # 1. Carregamento de Configurações Inicial
    try:
        settings = load_settings()
    except Exception as e:
        logger.error(f"❌ Erro crítico ao carregar config/config.yaml: {e}")
        return

    # 2. Injeção de Dependências
    fipe_client = ParallelumFipeClient()
    repository = SQLiteRepository(settings.app.database_path)
    notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
    scraper = OLXPlaywrightScraper(headless=False) 
    evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

    # 3. Loop Principal com Tratamento de Erros
    while True:
        try:
            logger.info("--- 🔄 Iniciando nova rodada de verificação ---")
            
            for local in settings.localizacoes:
                for veiculo in settings.veiculos:
                    # Montagem da URL Corrigida (Padrão www.olx.com.br)
                    url_busca = f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/{veiculo.marca}/{veiculo.modelo}"
                    
                    if veiculo.complemento_busca:
                        url_busca += f"/{veiculo.complemento_busca}"
                    
                    # Filtro de Estado e Região
                    url_busca += f"/estado-{local.estado}"
                    if local.regiao != "todas":
                        url_busca += f"/regiao-{local.regiao}"

                    logger.info(f"🔎 Buscando: {veiculo.marca} {veiculo.modelo} em {local.regiao}...")
                    
                    # Executa o Scraper (pode falhar por timeout ou bloqueio)
                    anuncios = scraper.buscar_anuncios(url_busca)
                    
                    if not anuncios:
                        logger.warning(f"⚠️ Nenhum anúncio extraído para {veiculo.modelo}. Verifique a URL ou conexão.")
                        continue

                    # Avalia os resultados
                    evaluator.avaliar_lista(anuncios)

            logger.info(f"✅ Rodada finalizada. Dormindo por {settings.app.intervalo_scraping_minutos} min.")
            time.sleep(settings.app.intervalo_scraping_minutos * 60)

        except KeyboardInterrupt:
            logger.info("🛑 Monitoramento interrompido pelo usuário. Saindo...")
            break
        except Exception as e:
            # Este catch captura qualquer erro inesperado (Rede, FIPE fora do ar, Erro de Parsing)
            # O robô NÃO para, ele apenas loga o erro e tenta novamente na próxima rodada.
            logger.error(f"🔥 ERRO INESPERADO NA RODADA: {str(e)}")
            logger.debug(traceback.format_exc()) # Loga o rastro do erro para debug
            
            logger.info("⏳ Aguardando 1 minuto antes de tentar recuperar...")
            time.sleep(60) 

if __name__ == "__main__":
    main()