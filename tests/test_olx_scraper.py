# tests/test_olx_scraper.py
import pytest
from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper

@pytest.fixture
def scraper():
    return OLXPlaywrightScraper(headless=True)

def test_parse_html_extrai_anuncio_corretamente(scraper):
    # Simulamos um pedaço de HTML com a estrutura típica de um card da OLX
    html_falso = """
    <div>
        <a href="https://ba.olx.com.br/salvador/autos-e-pecas/carros-vans-e-utilitarios/toyota-corolla-xei-2-0-123456789">
            <h2>Toyota Corolla XEi 2.0 Automático</h2>
            <div aria-label="Preço do item: R$ 110.000">R$ 110.000</div>
            <ul>
                <li aria-label="Ano: 2021">2021</li>
                <li aria-label="Quilometragem: 45.000 km">45.000 km</li>
            </ul>
        </a>
    </div>
    """
    
    anuncios = scraper._parse_html(html_falso, url_origem="https://olx.com.br")
    
    assert len(anuncios) == 1
    anuncio = anuncios[0]
    
    assert anuncio.id_anuncio == "123456789"
    assert anuncio.titulo == "Toyota Corolla XEi 2.0 Automático"
    assert anuncio.preco == 110000.0
    assert anuncio.ano == 2021
    assert anuncio.km == 45000
    assert anuncio.link == "https://ba.olx.com.br/salvador/autos-e-pecas/carros-vans-e-utilitarios/toyota-corolla-xei-2-0-123456789"

def test_parse_html_ignora_anuncios_incompletos(scraper):
    # Simulamos um HTML de anúncio patrocinado ou quebrado que não tem preço
    html_incompleto = """
    <div>
        <a href="https://ba.olx.com.br/salvador/autos-e-pecas/carros-vans-e-utilitarios/honda-city-999999999">
            <h2>Honda City 2023</h2>
            <ul>
                <li>2023</li>
                <li>10.000 km</li>
            </ul>
        </a>
    </div>
    """
    
    anuncios = scraper._parse_html(html_incompleto, url_origem="https://olx.com.br")
    
    # Como não tem preço, o scraper deve descartar para evitar erros no cálculo da FIPE
    assert len(anuncios) == 0