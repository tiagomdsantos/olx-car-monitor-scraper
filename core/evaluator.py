# core/evaluator.py
import logging
from typing import List
from core.models import Anuncio
from core.interfaces import INotifier, IRepository, IFipeClient
from config.settings import Settings

logger = logging.getLogger(__name__)

class CarEvaluator:
    """
    O Cérebro do sistema. Valida anúncios baseados nas regras de 
    negócio e decide quais notificações enviar.
    """
    def __init__(self, settings: Settings, fipe_client: IFipeClient, 
                 repository: IRepository, notifier: INotifier):
        self.settings = settings
        self.fipe_client = fipe_client
        self.repository = repository
        self.notifier = notifier

    def avaliar_lista(self, anuncios: List[Anuncio]):
        """Processa uma lista de anúncios extraídos do Scraper."""
        for anuncio in anuncios:
            try:
                self.processar_anuncio(anuncio)
            except Exception as e:
                logger.error(f"Erro ao avaliar anúncio {anuncio.id_anuncio}: {e}")

    def processar_anuncio(self, anuncio: Anuncio):
        # 1. Verifica se já foi processado (Memória do Robô)
        if self.repository.anuncio_ja_processado(anuncio.id_anuncio):
            return

        # 2. Busca configuração específica do modelo no YAML
        config_modelo = self._obter_config_veiculo(anuncio.titulo)
        if not config_modelo:
            return # Não é um carro que estamos monitorando

        # 3. Validação de Ano e Preço Máximo
        if anuncio.ano < self.settings.filtros_globais.ano_minimo:
            return
        if anuncio.preco > config_modelo.preco_maximo:
            return

        # 4. Validação de Versão (Intermediária/Superior)
        if not self._validar_versao(anuncio.titulo, config_modelo.versoes_aceitas):
            return

        # 5. Consulta FIPE e Cálculo Anti-Golpe
        preco_fipe = self.fipe_client.consultar_preco_medio(
            config_modelo.marca, config_modelo.modelo, anuncio.ano
        )
        
        if preco_fipe > 0:
            anuncio.preco_fipe_estimado = preco_fipe
            anuncio.marca = config_modelo.marca
            anuncio.modelo = config_modelo.modelo
            
            percentual = (anuncio.preco / preco_fipe) * 100
            
            # Regra Anti-Golpe (Filtro do YAML)
            if percentual < self.settings.filtros_globais.fipe_alerta_abaixo_de_percentual:
                logger.warning(f"Possível GOLPE detectado ({percentual:.1f}% da FIPE): {anuncio.titulo}")
                # Salvamos para não analisar de novo, mas não notificamos
                self.repository.salvar_anuncio_processado(anuncio.id_anuncio)
                return

            # Se estiver dentro da margem de oportunidade
            if percentual <= self.settings.filtros_globais.fipe_oportunidade_ate_percentual:
                self.notifier.enviar_alerta(anuncio, percentual)
        
        # 6. Marca como processado para evitar duplicidade
        self.repository.salvar_anuncio_processado(anuncio.id_anuncio)

    def _obter_config_veiculo(self, titulo: str):
        """Encontra qual regra do YAML se aplica a este anúncio."""
        titulo_lower = titulo.lower()
        for v in self.settings.veiculos:
            # Verifica se Marca e Modelo estão no título
            if v.marca.lower() in titulo_lower and v.modelo.lower() in titulo_lower:
                return v
        return None

    def _validar_versao(self, titulo: str, versoes_aceitas: List[str]) -> bool:
        """Verifica se o título contém alguma das versões desejadas."""
        if "todas" in versoes_aceitas:
            return True
        
        titulo_lower = titulo.lower()
        return any(v.lower() in titulo_lower for v in versoes_aceitas)