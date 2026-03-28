# main.py
import time
import logging
from config.settings import load_settings
from infrastructure.api.fipe_client import ParallelumFipeClient
from infrastructure.database.sqlite_repo import SQLiteRepository
from infrastructure.notifications.telegram_notifier import TelegramNotifier
from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper
from core.evaluator import CarEvaluator

# Configuração básica de Log para ver o que o robô está fazendo no console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("🚀 Iniciando o Monitor de Ofertas OLX...")
    
    # 1. Carrega as configurações do YAML
    try:
        settings = load_settings()
    except Exception as e:
        logger.error(f"Erro crítico ao carregar configurações: {e}")
        return

    # 2. Instancia a Infraestrutura (Injeção de Dependência)
    fipe_client = ParallelumFipeClient()
    repository = SQLiteRepository(settings.app.database_path)
    notifier = TelegramNotifier(settings.app.telegram_token, settings.app.telegram_chat_id)
    scraper = OLXPlaywrightScraper(headless=True) # Mude para False se quiser ver o navegador abrindo

    # 3. Instancia o Cérebro (Evaluator)
    evaluator = CarEvaluator(settings, fipe_client, repository, notifier)

    # 4. Loop Principal de Monitoramento
    while True:
        logger.info("--- Iniciando nova rodada de verificação ---")
        
        for local in settings.localizacoes:
            for veiculo in settings.veiculos:
                # Monta a URL da OLX dinamicamente conforme o YAML
                # Exemplo: https://ba.olx.com.br/salvador/autos-e-pecas/carros-vans-e-utilitarios/toyota/corolla
                base_url = f"https://{local.estado}.olx.com.br"
                if local.regiao != "todas":
                    base_url += f"/{local.regiao}"
                
                url_busca = f"{base_url}/autos-e-pecas/carros-vans-e-utilitarios/{veiculo.marca}/{veiculo.modelo}"
                
                # Adiciona o complemento (ex: 'hatch') se existir no YAML
                if veiculo.complemento_busca:
                    url_busca += f"/{veiculo.complemento_busca}"

                logger.info(f"Buscando {veiculo.marca} {veiculo.modelo} em {local.regiao}...")
                
                # Executa o Scraper
                anuncios = scraper.buscar_anuncios(url_busca)
                logger.info(f"Encontrados {len(anuncios)} anúncios potenciais.")

                # Envia para o Evaluator processar as regras de negócio
                evaluator.avaliar_lista(anuncios)

        logger.info(f"Rodada finalizada. Aguardando {settings.app.intervalo_scraping_minutos} minutos...")
        time.sleep(settings.app.intervalo_scraping_minutos * 60)

if __name__ == "__main__":
    main()