import re
import logging
from typing import List
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from core.interfaces import IScraper
from core.models import Anuncio
import json

logger = logging.getLogger(__name__)

class OLXPlaywrightScraper(IScraper):
    def __init__(self, headless: bool = True):
        self.headless = headless

    def buscar_anuncios(self, url_base: str, max_paginas: int = 5) -> List[Anuncio]:
        """
        Navega por múltiplas páginas da OLX para superar o limite de 50 anúncios.
        max_paginas = 5 significa que ele vai buscar até 250 anúncios por modelo.
        """
        anuncios_totais = []
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9"}
                )
                page = context.new_page()

                # TRUQUE: Anti-bot
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                # --- LOOP DE PAGINAÇÃO ---
                for pagina_atual in range(1, max_paginas + 1):
                    # A OLX usa ?o=1, ?o=2, etc para paginação
                    url_pagina = f"{url_base}?o={pagina_atual}"
                    
                    logger.info(f"🌐 Acessando OLX (Página {pagina_atual}/{max_paginas}): {url_pagina}")
                    
                    page.goto(url_pagina, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(4000) # Tempo para os scripts da OLX carregarem
                    
                    # Scroll até o fim para garantir que o JSON carregue tudo
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2000)
                    
                    html_content = page.content()
                    anuncios_da_pagina = self._parse_html(html_content, url_pagina)
                    
                    # Se a página não trouxe anúncios, significa que chegamos ao fim da lista real
                    if not anuncios_da_pagina:
                        logger.info(f"🏁 Fim da lista alcançado na página {pagina_atual}. Nenhuma oferta nova.")
                        break
                        
                    anuncios_totais.extend(anuncios_da_pagina)

                browser.close()
                
        except Exception as e:
            logger.error(f"❌ Erro no Playwright durante a paginação: {e}")

        # Remove duplicatas absolutas (A OLX costuma repetir anúncios patrocinados entre páginas)
        lista_final = list({a.id_anuncio: a for a in anuncios_totais}.values())
        logger.info(f"📦 Total extraído após paginação: {len(lista_final)} anúncios únicos.")
        return lista_final
        
    def _parse_html(self, html: str, url_origem: str) -> List[Anuncio]:
        soup = BeautifulSoup(html, 'html.parser')
        anuncios_encontrados = []

        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            logger.warning("⚠️ Não foi possível encontrar o JSON de dados da página.")
            return []

        try:
            dados = json.loads(script_tag.string)
            ads = dados.get('props', {}).get('pageProps', {}).get('ads', [])
            
            for ad in ads:
                id_anuncio = ad.get('listId')
                titulo = ad.get('subject', 'Sem título')
                descricao = ad.get('body', '')  
                link = ad.get('url')
                
                preco_raw = str(ad.get('price', '0')).replace('R$', '').replace('.', '').replace(' ', '').strip()
                preco = float(preco_raw) if preco_raw.isdigit() else 0.0
                
                properties = {p.get('name'): p.get('value') for p in ad.get('properties', [])}
                
                ano_val = properties.get('vehicle_year', properties.get('regdate', 0))
                ano = int(ano_val) if str(ano_val).isdigit() else 0
                
                km_val = str(properties.get('mileage', '0')).replace('.', '').replace(' ', '')
                km = int(km_val) if km_val.isdigit() else 0

                marca_olx = properties.get('vehicle_brand', '')
                modelo_olx = properties.get('vehicle_model', '')
                
                # --- SISTEMA DE TRIAGEM DE CATEGORIA ---
                categoria_olx = ""
                
                # TIER 1: Oficial
                cartype_raw = str(properties.get('cartype', '')).lower()
                if 'sed' in cartype_raw: categoria_olx = 'sedan'
                elif 'hatch' in cartype_raw: categoria_olx = 'hatch'
                elif 'suv' in cartype_raw or 'utilitário' in cartype_raw: categoria_olx = 'suv'

                # TIER 2: Título
                if not categoria_olx:
                    titulo_low = titulo.lower()
                    if re.search(r'\b(sedan|sedã|seda)\b', titulo_low): categoria_olx = 'sedan'
                    elif re.search(r'\b(hatch|hatchback)\b', titulo_low): categoria_olx = 'hatch'
                    elif re.search(r'\b(suv|utilitário|utilitario)\b', titulo_low): categoria_olx = 'suv'

                # TIER 3: Descrição
                if not categoria_olx:
                    descricao_low = descricao.lower()
                    if re.search(r'\b(sedan|sedã|seda)\b', descricao_low): categoria_olx = 'sedan'
                    elif re.search(r'\b(hatch|hatchback)\b', descricao_low): categoria_olx = 'hatch'
                    elif re.search(r'\b(suv|utilitário|utilitario)\b', descricao_low): categoria_olx = 'suv'
                    else: categoria_olx = 'outros'

                # Filtro de Sanidade
                if preco > 5000 and ano >= 2010:
                    anuncios_encontrados.append(Anuncio(
                        id_anuncio=str(id_anuncio),
                        titulo=titulo,
                        preco=preco,
                        ano=ano,
                        km=km,
                        link=link,
                        marca=marca_olx.capitalize(), 
                        modelo=modelo_olx.capitalize(),
                        categoria=categoria_olx
                    ))

        except Exception as e:
            logger.error(f"❌ Erro ao processar o JSON: {e}")

        # Retorna apenas os únicos daquela página
        return list({a.id_anuncio: a for a in anuncios_encontrados}.values())