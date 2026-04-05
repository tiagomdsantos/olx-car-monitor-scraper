import logging
import requests

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        """
        Inicializa o notificador do Telegram.
        :param token: Token do Bot gerado pelo BotFather.
        :param chat_id: ID do Chat (seu ID pessoal ou do grupo).
        """
        self.token = token
        self.chat_id = chat_id
        self.url_base = f"https://api.telegram.org/bot{self.token}"

    def enviar_alerta(self, mensagem: str):
        """
        Envia mensagens de texto formatadas em HTML para o Telegram.
        """
        url = f"{self.url_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": mensagem,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        try:
            response = requests.post(url, data=payload, timeout=15)
            response.raise_for_status()
            logger.info("✅ Mensagem de texto enviada ao Telegram.")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao enviar mensagem para o Telegram: {e}")
            return False

    def enviar_grafico(self, caminho_arquivo: str, legenda: str):
        """
        Envia arquivos de imagem (.png, .jpg) para o Telegram.
        Utilizado pelo comando /grafico e pelo motor de análise.
        """
        url = f"{self.url_base}/sendPhoto"
        try:
            # Abrimos o arquivo em modo leitura binária ('rb')
            with open(caminho_arquivo, 'rb') as photo:
                payload = {
                    "chat_id": self.chat_id,
                    "caption": legenda,
                    "parse_mode": "HTML"
                }
                files = {"photo": photo}
                
                response = requests.post(url, data=payload, files=files, timeout=30)
                response.raise_for_status()
                
                logger.info(f"✅ Gráfico enviado com sucesso: {caminho_arquivo}")
                return True
        except FileNotFoundError:
            logger.error(f"❌ Arquivo não encontrado para envio: {caminho_arquivo}")
            return False
        except Exception as e:
            logger.error(f"❌ Erro ao enviar gráfico para o Telegram: {e}")
            return False
        
    def configurar_menu_comandos(self, lista_comandos: list):
        """
        Registra a lista de comandos no menu de autocompletar do Telegram.
        """
        url = f"{self.url_base}/setMyCommands"
        payload = {"commands": lista_comandos}
        
        try:
            # Importante usar json=payload para o requests formatar a lista corretamente
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            logger.info("✅ Menu de comandos nativo do Telegram configurado!")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao configurar o menu do Telegram: {e}")
            return False
        
    def enviar_documento(self, caminho_arquivo: str):
        """
        Faz o upload de um arquivo físico para o chat do Telegram.
        """
        url = f"{self.url_base}/sendDocument"
        try:
            with open(caminho_arquivo, 'rb') as f:
                # O requests precisa receber o arquivo no parâmetro 'files'
                files = {'document': f}
                data = {'chat_id': self.chat_id}
                
                # Aumentamos o timeout para 30s caso o arquivo de log esteja grande
                response = requests.post(url, data=data, files=files, timeout=30)
                response.raise_for_status()
                
            return True
        except Exception as e:
            # Não usamos logger.error aqui para não causar um loop infinito de erros de log
            print(f"❌ Erro ao enviar documento para o Telegram: {e}")
            return False