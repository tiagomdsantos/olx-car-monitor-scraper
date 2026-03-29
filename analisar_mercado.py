import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import os
import logging

logger = logging.getLogger(__name__)

def gerar_graficos_por_modelo(db_path="data/anuncios.db"):
    """
    Lê o banco de dados, identifica os modelos pelo título e gera 
    um gráfico para cada modelo com os 10 anúncios mais relevantes.
    """
    if not os.path.exists(db_path):
        logger.error(f"❌ Banco de dados não encontrado em {db_path}")
        return []

    try:
        conn = sqlite3.connect(db_path)
        # Seleciona apenas anúncios com FIPE válida e preço real
        query = """
            SELECT titulo, preco_anuncio, km, percentual_fipe, ano
            FROM anuncios_detalhados 
            WHERE preco_anuncio > 10000 AND km > 100 AND percentual_fipe > 0
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        logger.error(f"❌ Erro ao ler banco de dados para gráficos: {e}")
        return []

    if df.empty:
        return []

    # Lógica de inferência para o banco original (v1.2)
    def inferir_modelo(titulo):
        t = str(titulo).lower()
        modelos = ["corolla", "yaris", "city", "kicks", "versa", "sentra", "hb20", "creta", "hr-v", "wr-v"]
        for m in modelos:
            if m in t: return m.capitalize()
        return "Outros"

    df['modelo_ref'] = df['titulo'].apply(inferir_modelo)
    arquivos_gerados = []
    
    # Gera um gráfico para cada modelo encontrado
    for modelo in df['modelo_ref'].unique():
        if modelo == "Outros": continue
        
        # Filtra e pega os 10 MAIS RELEVANTES (Menor % FIPE primeiro)
        df_top = df[df['modelo_ref'] == modelo].copy()
        df_top = df_top.sort_values(by=['percentual_fipe', 'km']).head(10)

        if df_top.empty: continue

        plt.figure(figsize=(10, 6))
        
        # Cores: Verde (Barato) -> Amarelo -> Vermelho (Caro)
        scatter = plt.scatter(
            df_top['km'], 
            df_top['preco_anuncio'], 
            c=df_top['percentual_fipe'], 
            cmap='RdYlGn_r',
            s=120, 
            edgecolors='black', 
            alpha=0.8
        )

        # Anotações nos pontos
        for i, row in df_top.iterrows():
            plt.annotate(
                f"{row['ano']}\n{row['percentual_fipe']:.1f}%",
                (row['km'], row['preco_anuncio']),
                xytext=(5, 5), textcoords='offset points', fontsize=8, fontweight='bold'
            )

        plt.title(f'📊 Top 10 Oportunidades: {modelo.upper()} (Salvador)', fontsize=14)
        plt.xlabel('Quilometragem (KM)')
        plt.ylabel('Preço (R$)')
        plt.grid(True, linestyle='--', alpha=0.6)
        
        # Formatação de Moeda e KM
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R${x:,.0f}'))
        plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))
        
        plt.colorbar(scatter, label='% da Tabela FIPE')

        nome_arquivo = f"analise_{modelo.lower()}_salvador.png"
        plt.tight_layout()
        plt.savefig(nome_arquivo, dpi=120)
        plt.close()
        
        arquivos_gerados.append(nome_arquivo)

    return arquivos_gerados