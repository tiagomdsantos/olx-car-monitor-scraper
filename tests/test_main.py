# tests/test_main.py
import pytest
from unittest.mock import patch, MagicMock
import main

# A ordem dos argumentos na função deve ser a INVERSA da ordem dos patches
@patch('main.time.sleep', side_effect=InterruptedError)
@patch('main.CarEvaluator')
@patch('main.OLXPlaywrightScraper')
@patch('main.TelegramNotifier')
@patch('main.SQLiteRepository')
@patch('main.ParallelumFipeClient')
@patch('main.load_settings')
def test_main_orquestracao_sucesso(
    mock_load_settings,
    mock_fipe_cls,
    mock_repo_cls,
    mock_notifier_cls,
    mock_scraper_cls,
    mock_evaluator_cls,
    mock_sleep
):
    # 1. Configuração do Mock de Settings
    mock_settings = MagicMock()
    # Criamos uma localização e um veículo para o loop rodar
    loc = MagicMock()
    loc.estado = "ba"
    loc.regiao = "salvador"
    
    veic = MagicMock()
    veic.marca = "toyota"
    veic.modelo = "corolla"
    veic.complemento_busca = None
    
    mock_settings.localizacoes = [loc]
    mock_settings.veiculos = [veic]
    mock_settings.app.intervalo_scraping_minutos = 30
    mock_settings.app.database_path = "sqlite:///test.db"
    mock_settings.app.telegram_token = "token"
    mock_settings.app.telegram_chat_id = "123"
    
    mock_load_settings.return_value = mock_settings

    # 2. Configuração do Mock do Scraper
    mock_scraper_inst = mock_scraper_cls.return_value
    mock_scraper_inst.buscar_anuncios.return_value = [MagicMock(id_anuncio="123")]
    
    # 3. Execução do main (que deve quebrar no primeiro sleep)
    with pytest.raises(InterruptedError):
        main.main()

    # 4. Verificações
    assert mock_load_settings.called
    # Verifica se o Scraper foi instanciado e chamado
    assert mock_scraper_inst.buscar_anuncios.called
    # Verifica se o Evaluator foi instanciado
    assert mock_evaluator_cls.called