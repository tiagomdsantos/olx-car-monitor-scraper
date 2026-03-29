# infrastructure/notifications/telegram_notifier.py
import requests
import logging
import html # Biblioteca nativa para limpar HTML

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def enviar_alerta(self, mensagem: str):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        # 1. Tenta enviar com HTML (Limpando caracteres especiais do título)
        payload = {
            "chat_id": self.chat_id,
            "text": mensagem,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            
            # Se der erro 400 (Bad Request), tenta enviar sem formatação nenhuma
            if response.status_code == 400:
                logger.warning("⚠️ Falha no HTML. Tentando enviar como texto puro...")
                # Remove todas as tags HTML usando uma regex rápida
                import re
                texto_puro = re.sub('<[^<]+?>', '', mensagem)
                payload["text"] = texto_puro
                payload.pop("parse_mode") # Remove o modo HTML
                response = requests.post(url, json=payload, timeout=10)

            response.raise_for_status()
            logger.info("✅ Notificação enviada com sucesso!")
            
        except Exception as e:
            logger.error(f"❌ Erro fatal ao enviar para Telegram: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Resposta do Telegram: {e.response.text}")


    def enviar_grafico(self, caminho_imagem, legenda="📊 Análise de Mercado atualizada"):
        """Envia um arquivo de imagem para o chat do Telegram."""
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        try:
            with open(caminho_imagem, 'rb') as photo:
                files = {'photo': photo}
                data = {'chat_id': self.chat_id, 'caption': legenda}
                response = requests.post(url, files=files, data=data)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Erro ao enviar gráfico para o Telegram: {e}")
            return False