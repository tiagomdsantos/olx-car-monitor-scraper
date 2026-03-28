# infrastructure/notifications/telegram_notifier.py
import requests
import logging
from core.interfaces import INotifier
from core.models import Anuncio

logger = logging.getLogger(__name__)

class TelegramNotifier(INotifier):
    """
    Implementação concreta do Notificador utilizando a API do Telegram.
    Envia mensagens formatadas em HTML.
    """
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def enviar_alerta(self, anuncio: Anuncio, percentual_fipe: float):
        """Monta a mensagem HTML e envia para o chat configurado."""
        
        # Formatação do preço da FIPE lidando com casos onde a FIPE pode falhar (None)
        str_fipe = f"R$ {anuncio.preco_fipe_estimado:,.2f}" if anuncio.preco_fipe_estimado else "Não encontrada"
        
        mensagem = (
            f"🚗 <b>NOVA OPORTUNIDADE: {anuncio.marca.upper()} {anuncio.modelo.upper()}</b>\n\n"
            f"<b>Título:</b> {anuncio.titulo}\n"
            f"<b>Ano:</b> {anuncio.ano} | <b>KM:</b> {anuncio.km}\n"
            f"<b>Preço OLX:</b> R$ {anuncio.preco:,.2f}\n"
            f"<b>Preço FIPE:</b> {str_fipe}\n"
            f"<b>Diferença:</b> {percentual_fipe:.1f}% da tabela FIPE\n\n"
            f"🔗 <a href='{anuncio.link}'>Acessar Anúncio</a>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": mensagem,
            "parse_mode": "HTML",
            "disable_web_page_preview": False # Mantém a miniatura da foto do carro se a OLX permitir
        }

        url = f"{self.base_url}/sendMessage"

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status() # Lança um erro se o status HTTP não for 2xx
            logger.info(f"Alerta enviado com sucesso para: {anuncio.titulo}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar notificação para o Telegram: {e}")