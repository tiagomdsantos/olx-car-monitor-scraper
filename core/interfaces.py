# core/interfaces.py
from abc import ABC, abstractmethod
from typing import List
from core.models import Anuncio

class IScraper(ABC):
    """Contrato para qualquer buscador de anúncios (OLX, Webmotors, etc)."""
    @abstractmethod
    def buscar_anuncios(self, url: str) -> List[Anuncio]:
        pass

class INotifier(ABC):
    """Contrato para qualquer sistema de notificação (Telegram, WhatsApp, Email)."""
    @abstractmethod
    def enviar_alerta(self, anuncio: Anuncio, percentual_fipe: float):
        pass

class IRepository(ABC):
    """Contrato para o banco de dados que salva os anúncios já vistos."""
    @abstractmethod
    def anuncio_ja_processado(self, id_anuncio: str) -> bool:
        pass

    @abstractmethod
    def salvar_anuncio_processado(self, id_anuncio: str):
        pass

class IFipeClient(ABC):
    """Contrato para o cliente da API da Tabela FIPE."""
    @abstractmethod
    def consultar_preco_medio(self, marca: str, modelo: str, ano: int) -> float:
        pass