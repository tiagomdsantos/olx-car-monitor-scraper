# infrastructure/scrapers/olx_scraper.py
import re
import logging
from typing import List, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

from core.interfaces import IScraper
from core.models import Anuncio

logger = logging.getLogger(__name__)

class OLXPlaywrightScraper(IScraper):
    """
    Scraper para a OLX utilizando Playwright para renderizar a página 
    e BeautifulSoup para extrair os dados do HTML.
    """
    def __init__(self, headless: bool = True):
        self.headless = headless

    def buscar_anuncios(self, url: str) -> List[Anuncio]:
        """Abre o navegador, acessa a URL e retorna o HTML para ser processado."""
        html_content = ""
        try:
            with sync_playwright() as p:
                # Lança o navegador Chromium
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                
                logger.info(f"Acessando OLX: {url}")
                # Espera até que a rede fique ociosa (garante que os anúncios carregaram)
                page.goto(url, wait_until="networkidle", timeout=30000)
                
                # Rola a página um pouco para baixo para forçar o lazy load das imagens/itens
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(2000) # Pausa de 2 segundos
                
                html_content = page.content()
                browser.close()
                
        except PlaywrightTimeoutError:
            logger.error("Timeout ao tentar carregar a página da OLX.")
            return []
        except Exception as e:
            logger.error(f"Erro inesperado no Playwright: {e}")
            return []

        return self._parse_html(html_content, url)

    def _parse_html(self, html: str, url_origem: str) -> List[Anuncio]:
            """Lê o código fonte da página e extrai a lista de anúncios de forma resiliente."""
            soup = BeautifulSoup(html, 'html.parser')
            anuncios_encontrados = []

            # CORREÇÃO 1: Adicionado .* para aceitar a região (ex: /salvador/) no meio da URL
            cards = soup.find_all('a', href=re.compile(r'olx\.com\.br.*/autos-e-pecas/carros-vans-e-utilitarios'))

            for card in cards:
                try:
                    link = card.get('href')
                    if not link or "galeria" in link:
                        continue

                    # Extrai o ID do anúncio a partir da URL
                    match_id = re.search(r'-(\d+)(?:$|\?)', link)
                    id_anuncio = match_id.group(1) if match_id else None
                    if not id_anuncio:
                        continue

                    # Extração do Título (Pode ser h2, h3 ou h4 dependendo da versão do site)
                    titulo_tag = card.find(['h2', 'h3', 'h4'])
                    titulo = titulo_tag.text.strip() if titulo_tag else "Desconhecido"

                    preco = 0.0
                    ano = 0
                    km = 0
                    
                    # CORREÇÃO 2: Pega todos os pedaços de texto dentro do link e varre de forma burra e segura
                    textos_card = list(card.stripped_strings)
                    for texto in textos_card:
                        texto_limpo = texto.lower()
                        
                        # Se achar "r$" e ainda não tivermos preço
                        if 'r$' in texto_limpo and preco == 0.0:
                            num = re.sub(r'[^\d]', '', texto_limpo)
                            if num: preco = float(num)
                            
                        # Se for exatamente 4 dígitos começando com 20xx e ainda não tivermos ano
                        elif re.match(r'^20[0-2][0-9]$', texto_limpo.replace('.', '')) and ano == 0:
                            ano = int(texto_limpo.replace('.', ''))
                            
                        # Se tiver "km" no texto
                        elif 'km' in texto_limpo:
                            num = re.sub(r'[^\d]', '', texto_limpo)
                            if num: km = int(num)

                    # Só adicionamos se tiver preço válido e ano
                    if preco > 0 and ano > 0:
                        partes_titulo = titulo.split()
                        marca = partes_titulo[0] if partes_titulo else "Desconhecida"
                        modelo = partes_titulo[1] if len(partes_titulo) > 1 else "Desconhecido"

                        anuncio = Anuncio(
                            id_anuncio=id_anuncio,
                            titulo=titulo,
                            preco=preco,
                            ano=ano,
                            km=km,
                            link=link,
                            marca=marca,
                            modelo=modelo
                        )
                        anuncios_encontrados.append(anuncio)

                except Exception as e:
                    logger.debug(f"Falha ao extrair dados de um card: {e}")
                    continue

            # Remove duplicados da própria página
            anuncios_unicos = {a.id_anuncio: a for a in anuncios_encontrados}.values()
            return list(anuncios_unicos)