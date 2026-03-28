# tests/test_telegram_notifier.py
import pytest
from unittest.mock import patch, Mock
from infrastructure.notifications.telegram_notifier import TelegramNotifier
from core.models import Anuncio
import requests

@pytest.fixture
def notifier():
    # Instanciamos o notificador com credenciais falsas
    return TelegramNotifier(token="fake_token_123", chat_id="fake_chat_456")

@pytest.fixture
def anuncio_teste():
    # Criamos um anúncio mockado (falso) para os testes
    return Anuncio(
        id_anuncio="111222333",
        titulo="Toyota Corolla XEi 2.0",
        preco=100000.0,
        ano=2021,
        km=45000,
        link="https://ba.olx.com.br/salvador/...",
        marca="Toyota",
        modelo="Corolla",
        versao_identificada="xei",
        preco_fipe_estimado=115000.0
    )

@patch('infrastructure.notifications.telegram_notifier.requests.post')
def test_enviar_alerta_sucesso(mock_post, notifier, anuncio_teste):
    # Configuramos o mock para simular uma resposta HTTP 200 (OK)
    mock_response = Mock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    # Disparamos a função
    notifier.enviar_alerta(anuncio_teste, percentual_fipe=86.9)

    # Verificamos se o requests.post foi chamado exatamente 1 vez
    assert mock_post.call_count == 1
    
    # Pegamos os argumentos que foram passados para o requests.post
    args, kwargs = mock_post.call_args
    url_chamada = args[0]
    payload_enviado = kwargs['json']

    # Validamos se a URL foi montada corretamente com o token
    assert url_chamada == "https://api.telegram.org/botfake_token_123/sendMessage"
    
    # Validamos se o payload contém as chaves corretas do Telegram
    assert payload_enviado['chat_id'] == "fake_chat_456"
    assert payload_enviado['parse_mode'] == "HTML"
    
    # Verificamos se o texto da mensagem contém informações chave do anúncio
    assert "Toyota Corolla XEi 2.0" in payload_enviado['text']
    assert "86.9%" in payload_enviado['text']

@patch('infrastructure.notifications.telegram_notifier.requests.post')
def test_enviar_alerta_com_falha_de_conexao(mock_post, notifier, anuncio_teste, caplog):
    # Simulamos uma queda de internet ou erro do Telegram
    mock_post.side_effect = requests.exceptions.ConnectionError("Falha na rede")

    # A função não deve "quebrar" (crashar) o programa, apenas registrar o erro no log
    notifier.enviar_alerta(anuncio_teste, percentual_fipe=86.9)

    # Verificamos se a mensagem de erro foi parar no log do sistema
    assert "Erro ao enviar notificação para o Telegram" in caplog.text
    