# core/evaluator.py
import logging
import html
from core.models import Anuncio

logger = logging.getLogger(__name__)

class CarEvaluator:
    def __init__(self, settings, fipe_client, repository, notifier):
        """
        Orquestra a lógica de decisão: Filtragem -> Consulta FIPE -> Notificação.
        """
        self.settings = settings
        self.fipe_client = fipe_client
        self.repository = repository
        self.notifier = notifier

    def avaliar_lista(self, anuncios):
        """Processa uma lista de anúncios extraídos do scraper."""
        for anuncio in anuncios:
            try:
                self.processar_anuncio(anuncio)
            except Exception as e:
                logger.error(f"❌ Erro ao avaliar anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio):
        # 1. Verifica se o anúncio já foi processado anteriormente (Evita spam)
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            return

        # 2. Validação de Ano Mínimo (Configurado no seu YAML)
        if anuncio.ano < self.settings.filtros_globais.ano_minimo:
            return

        # 3. Busca o preço da FIPE para o modelo
        # Passamos a marca/modelo para a API encontrar o código correto
        preco_fipe = self.fipe_client.consultar_preco_medio(
            anuncio.marca, 
            anuncio.modelo, 
            anuncio.ano
        )

        if preco_fipe > 0:
            percentual_fipe = (anuncio.preco / preco_fipe) * 100
            
            # 4. Lógica de Filtro de Oportunidade
            # fipe_alerta_abaixo_de_percentual (ex: 70%): Abaixo disso pode ser golpe
            # fipe_oportunidade_ate_percentual (ex: 95%): Acima disso é preço de mercado
            alerta_min = self.settings.filtros_globais.fipe_alerta_abaixo_de_percentual
            alerta_max = self.settings.filtros_globais.fipe_oportunidade_ate_percentual

            if alerta_min <= percentual_fipe <= alerta_max:
                
                # Prepara o título para o Telegram (Evita erro 400 Bad Request)
                titulo_seguro = html.escape(anuncio.titulo)
                
                # Montagem da Mensagem em HTML
                mensagem = (
                    f"<b>🚀 OPORTUNIDADE EM SALVADOR!</b>\n\n"
                    f"🚗 <b>{titulo_seguro}</b>\n"
                    f"💰 Preço: <b>R$ {anuncio.preco:,.2f}</b>\n"
                    f"📊 FIPE: R$ {preco_fipe:,.2f} ({percentual_fipe:.1f}%)\n"
                    f"📅 Ano: {anuncio.ano} | 🛣️ KM: {anuncio.km}\n\n"
                    f"🔗 <a href='{anuncio.link}'>Clique aqui para ver o anúncio</a>"
                )

                # 5. Envia a notificação
                self.notifier.enviar_alerta(mensagem)
            
            else:
                logger.info(f"⏭️ Ignorado: {anuncio.id_anuncio} está a {percentual_fipe:.1f}% da FIPE.")

        # 6. Salva no banco de dados para marcar como "visto"
        self.repository.salvar_anuncio_processado(anuncio.id_anuncio)