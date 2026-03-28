# core/models.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class Anuncio:
    id_anuncio: str
    titulo: str
    preco: float
    ano: int
    km: int
    link: str
    marca: str
    modelo: str
    versao_identificada: Optional[str] = None
    preco_fipe_estimado: Optional[float] = None