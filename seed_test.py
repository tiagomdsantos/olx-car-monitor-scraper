import sqlite3
import random
import logging
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def popular_banco_completo(db_path="data/anuncios.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Modelos e Preços FIPE de referência (Aproximados para 2019-2021)
    modelos_fipe = {
        "Corolla": {"fipe": 95000, "marca": "Toyota", "ano": 2020},
        "Civic":   {"fipe": 105000, "marca": "Honda", "ano": 2020},
        "City":    {"fipe": 82000, "marca": "Honda", "ano": 2021},
        "Fit":     {"fipe": 75000, "marca": "Honda", "ano": 2019},
        "Kicks":   {"fipe": 88000, "marca": "Nissan", "ano": 2020}
    }

    bairros_salvador = ["Caminho das Árvores", "Pituba", "Itaigara", "Imbuí", "Graça", "Stela Maris", "Alphaville", "Piatã"]

    logger.info("🧹 Limpando dados de teste anteriores...")
    cursor.execute("DELETE FROM anuncios_detalhados WHERE id_anuncio LIKE 'test_%'")

    logger.info(f"🚀 Inserindo 50 anúncios sintéticos em {db_path}...")

    query = '''
        INSERT OR REPLACE INTO anuncios_detalhados 
        (id_anuncio, titulo, preco_anuncio, preco_fipe, percentual_fipe, ano, km, link, bairro)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''

    contador = 0
    for nome_modelo, dados in modelos_fipe.items():
        # Gerar 10 variações para cada modelo
        for i in range(10):
            contador += 1
            id_fake = f"test_{nome_modelo.lower()}_{i}"
            
            # Lógica de variação aleatória para criar diversidade no Score
            # Variação de Preço: entre 80% e 115% da FIPE
            variacao_preco = random.uniform(0.80, 1.15)
            preco_venda = dados["fipe"] * variacao_preco
            
            # Variação de KM: entre 15.000 e 130.000 km
            km_fake = random.randint(15000, 130000)
            
            # Metadados
            bairro = random.choice(bairros_salvador)
            titulo = f"{dados['marca']} {nome_modelo} {dados['ano']} - {bairro}"
            percentual = (preco_venda / dados['fipe']) * 100
            link_fake = f"https://www.olx.com.br/item/teste-{id_fake}"

            cursor.execute(query, (
                id_fake, titulo, round(preco_venda, 2), float(dados['fipe']), 
                round(percentual, 2), dados['ano'], km_fake, link_fake, bairro
            ))

    conn.commit()
    conn.close()
    logger.info(f"✅ Sucesso! {contador} carros inseridos. Use /grafico para validar.")

if __name__ == "__main__":
    # Garante que a pasta data existe
    if not os.path.exists("data"):
        os.makedirs("data")
    popular_banco_completo()