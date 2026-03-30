# core/models.py
from dataclasses import dataclass

@dataclass
class Anuncio:
    id_anuncio: str
    titulo: str
    preco: float
    ano: int
    km: int
    link: str
    marca: str = ""
    modelo: str = ""
    categoria: str = ""  # <--- NOVA LINHA AQUI
    preco_fipe_olx: float = 0.0