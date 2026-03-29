import pytest
from unittest.mock import patch
from infrastructure.notifications.telegram_notifier import TelegramNotifier

@patch('requests.post')
def test_enviar_alerta_sucesso(mock_post):
    # Simula resposta 200 OK do Telegram
    mock_post.return_value.status_code = 200
    
    notifier = TelegramNotifier("token_fake", "chat_id_fake")
    # Chamada correta: apenas a mensagem
    notifier.enviar_alerta("<b>Teste</b>")
    
    assert mock_post.called
    # Verifica se enviou como HTML
    args, kwargs = mock_post.call_args
    assert kwargs['json']['parse_mode'] == "HTML"