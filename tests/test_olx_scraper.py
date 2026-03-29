from infrastructure.scrapers.olx_scraper import OLXPlaywrightScraper

def test_parse_html_json_extrai_anuncio():
    scraper = OLXPlaywrightScraper()
    # Simula o HTML com o script JSON da OLX
    html_fake = """
    <html>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "ads": [
                        {
                            "listId": "123456",
                            "subject": "Toyota Corolla 2020 XEi",
                            "url": "https://olx.com.br/anuncio-123456",
                            "price": "R$ 110.000",
                            "properties": [
                                {"name": "vehicle_year", "value": "2020"},
                                {"name": "mileage", "value": "45000"}
                            ]
                        }
                    ]
                }
            }
        }
        </script>
    </html>
    """
    anuncios = scraper._parse_html(html_fake, "url_teste")
    
    assert len(anuncios) == 1
    assert anuncios[0].id_anuncio == "123456"
    assert anuncios[0].preco == 110000.0
    assert anuncios[0].ano == 2020