# infrastructure/scrapers/olx_scraper.py
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

    def buscar_anuncios(self, url: str) -> List[Anuncio]:
        html_content = ""
        try:
            with sync_playwright() as p:
                # Lançamos o navegador normalmente
                browser = p.chromium.launch(headless=self.headless)
                
                # Criamos o contexto com User-Agent humano e desativamos o webdriver
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9"}
                )
                
                page = context.new_page()

                # TRUQUE: Remove a flag "navigator.webdriver" que sites usam para detectar bots
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                logger.info(f"🌐 Acessando OLX: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Espera o carregamento dinâmico
                page.wait_for_timeout(5000)
                
                # Scroll para garantir que a OLX renderize os cards
                page.evaluate("window.scrollTo(0, 1200)")
                page.wait_for_timeout(2000)
                
                html_content = page.content()
                
                # Salva debug para análise se necessário
                with open("debug_olx.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
                
                browser.close()
                
        except Exception as e:
            logger.error(f"❌ Erro no Playwright: {e}")
            return []

        return self._parse_html(html_content, url)
        

    def _parse_html(self, html: str, url_origem: str) -> List[Anuncio]:
        soup = BeautifulSoup(html, 'html.parser')
        anuncios_encontrados = []

        # 1. Busca o script JSON que contém todos os dados da página
        script_tag = soup.find('script', id='__NEXT_DATA__')
        
        if not script_tag:
            logger.warning("⚠️ Não foi possível encontrar o JSON de dados da OLX (__NEXT_DATA__).")
            return []

        try:
            dados = json.loads(script_tag.string)
            # A estrutura da OLX é profunda: props -> pageProps -> ads
            ads = dados.get('props', {}).get('pageProps', {}).get('ads', [])
            
            logger.info(f"📊 JSON extraído: {len(ads)} anúncios brutos encontrados.")

            for ad in ads:
                # Extraímos os dados diretamente do dicionário JSON
                id_anuncio = ad.get('listId')
                titulo = ad.get('subject', 'Sem título')
                link = ad.get('url')
                
                # Preço: remove caracteres não numéricos
                preco_raw = str(ad.get('price', '0')).replace('R$', '').replace('.', '').replace(' ', '').strip()
                preco = float(preco_raw) if preco_raw.isdigit() else 0.0
                
                # Mapeia as propriedades (Ano e KM)
                properties = {p.get('name'): p.get('value') for p in ad.get('properties', [])}
                
                # Ano: Tenta pegar de 'vehicle_year' ou 'regdate'
                ano_val = properties.get('vehicle_year', properties.get('regdate', 0))
                ano = int(ano_val) if str(ano_val).isdigit() else 0
                
                # KM: CORREÇÃO DA VARIÁVEL AQUI
                km_val = str(properties.get('mileage', '0')).replace('.', '').replace(' ', '')
                km = int(km_val) if km_val.isdigit() else 0

                # Filtro de segurança e integridade
                if preco > 5000 and ano >= 2010:
                    anuncios_encontrados.append(Anuncio(
                        id_anuncio=str(id_anuncio),
                        titulo=titulo,
                        preco=preco,
                        ano=ano,
                        km=km,
                        link=link,
                        marca="", modelo=""
                    ))

        except Exception as e:
            logger.error(f"❌ Erro ao processar o JSON da OLX: {e}")

        lista_final = list({a.id_anuncio: a for a in anuncios_encontrados}.values())
        logger.info(f"✅ Sucesso: {len(lista_final)} anúncios processados via JSON.")
        return lista_final