import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import os
import logging
from datetime import datetime

# Configuração de Logs
logger = logging.getLogger(__name__)

def gerar_graficos_por_modelo(db_path="data/anuncios.db"):
    """
    Analisa o banco de dados, gera gráficos individuais por modelo
    e um gráfico extra com as Top 10 Oportunidades Gerais (melhor Score).
    """
    if not os.path.exists(db_path):
        logger.error(f"❌ Banco de dados não encontrado em {db_path}")
        return []

    try:
        conn = sqlite3.connect(db_path)
        # Seleciona apenas anúncios com dados completos para o Score
        query = """
            SELECT titulo, preco_anuncio, preco_fipe, percentual_fipe, km, ano, link, bairro
            FROM anuncios_detalhados 
            WHERE preco_anuncio > 5000 AND km > 0 AND preco_fipe > 0
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        logger.error(f"❌ Erro ao acessar o banco para análise: {e}")
        return []

    if df.empty:
        logger.warning("⚠️ Banco de dados vazio ou sem anúncios precificados.")
        return []

    # --- 1. Motores de Inferência e Score (Réplica do Evaluator) ---
    def inferir_modelo(titulo):
        t = str(titulo).lower()
        modelos = ["corolla", "civic", "city", "kicks", "versa", "sentra", "hb20", "creta", "hr-v", "wr-v", "fit"]
        for m in modelos:
            if m in t: return m.capitalize()
        return "Outros"

    def calcular_score_grafico(row):
        """Calcula Score (0-100) baseada em Preço (50%), Uso (30%) e Idade (20%)."""
        score = 0
        # A) Preço vs FIPE (50%): 80% FIPE = 50pts | 100% FIPE = 0pts
        score += max(0, (100 - row['percentual_fipe']) * 2.5)
        # B) KM/Uso (30%): 7k km/ano = 30pts | 17k km/ano = 0pts
        idade = max(1, datetime.now().year - row['ano'])
        km_ano = row['km'] / idade
        score += max(0, (17000 - km_ano) * 0.003 * 10)
        # C) Idade (20%): Novo (0 anos) = 20pts | Velho (10 anos) = 0pts
        score += max(0, (10 - idade) * 2)
        return round(min(100, score), 1)

    # Aplica os motores ao DataFrame
    df['modelo_ref'] = df['titulo'].apply(inferir_modelo)
    df['score'] = df.apply(calcular_score_grafico, axis=1)
    
    arquivos_gerados = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    # --- 2. GERAÇÃO DO GRÁFICO: TOP 10 OPORTUNIDADES GERAIS ---
    logger.info("📈 Gerando gráfico do Top 10 Geral de Oportunidades...")
    
    # Seleciona os 10 melhores Scores absolutos do banco
    df_geral = df.sort_values(by='score', ascending=False).head(10).copy()
    
    if not df_geral.empty:
        nome_arquivo_geral = f"analise_top10geral_{timestamp}.png"
        
        plt.figure(figsize=(12, 7))
        
        # Gráfico de Dispersão Geral (Scatter)
        scatter = plt.scatter(
            df_geral['km'], 
            df_geral['preco_anuncio'], 
            c=df_geral['score'], 
            cmap='RdYlGn', 
            s=250, # Bolhas ligeiramente maiores no Geral
            edgecolors='black', 
            alpha=0.9,
            vmin=60, vmax=100
        )

        # Labels específicos para o Top 10 (Mostra Modelo e Score)
        for i, row in df_geral.iterrows():
            plt.annotate(
                f"{row['modelo_ref'].upper()}\n{row['ano']} | {row['score']}pts",
                (row['km'], row['preco_anuncio']),
                xytext=(0, 12), 
                textcoords='offset points', 
                ha='center', fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7, ec='none')
            )

        # Estilização do Gráfico Geral
        plt.title(f'Analise: Top 10 Melhores Oportunidades em Salvador\n(Ordenado por Score Técnico)', fontsize=14, fontweight='bold', pad=20)
        plt.xlabel('Quilometragem Total (KM)', fontsize=11)
        plt.ylabel('Preço de Venda (R$)', fontsize=11)
        plt.grid(True, linestyle=':', alpha=0.6)
        
        # Formatação de eixos
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R${x:,.0f}'))
        plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f} KM'))
        
        # Barra lateral de Score
        cbar = plt.colorbar(scatter)
        cbar.set_label('Score de Oportunidade (0-100)', rotation=270, labelpad=15)

        plt.tight_layout()
        plt.savefig(nome_arquivo_geral, dpi=130) # DPI maior para o Geral
        plt.close()
        arquivos_gerados.append(nome_arquivo_geral)

    # --- 3. LOOP DE GERAÇÃO: GRÁFICOS INDIVIDUAIS POR MODELO ---
    for modelo in df['modelo_ref'].unique():
        if modelo == "Outros": continue
        
        # Filtra e pega os 10 melhores daquele modelo
        df_top_modelo = df[df['modelo_ref'] == modelo].copy()
        df_top_modelo = df_top_modelo.sort_values(by='score', ascending=False).head(10)

        if df_top_modelo.empty: continue
        
        logger.info(f"📈 Gerando gráfico individual para: {modelo}")

        plt.figure(figsize=(12, 7))
        
        # Gráfico do Modelo (Scatter)
        scatter_mod = plt.scatter(
            df_top_modelo['km'], 
            df_top_modelo['preco_anuncio'], 
            c=df_top_modelo['score'], 
            cmap='RdYlGn', 
            s=200, edgecolors='black', alpha=0.85,
            vmin=50, vmax=100
        )

        # Labels do Modelo (Mostra Ano, Score e Bairro)
        for i, row in df_top_modelo.iterrows():
            bairro_curto = row['bairro'][:8] if row['bairro'] else 'Salvador'
            plt.annotate(
                f"{row['ano']} | {row['score']}pts\n{bairro_curto}",
                (row['km'], row['preco_anuncio']),
                xytext=(0, 10), textcoords='offset points', ha='center',
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.5, ec='none')
            )

        # Estilização do Gráfico do Modelo
        plt.title(f'Analise de Mercado: {modelo.upper()} em Salvador\n(Top 10 Vagas por Score)', fontsize=14, fontweight='bold', pad=20)
        plt.xlabel('Quilometragem Total (KM)', fontsize=11)
        plt.ylabel('Preço de Venda (R$)', fontsize=11)
        plt.grid(True, linestyle=':', alpha=0.6)
        
        # Formatação
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R${x:,.0f}'))
        plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f} KM'))
        
        # Barra lateral
        cbar_mod = plt.colorbar(scatter_mod)
        cbar_mod.set_label('Score de Oportunidade (0-100)', rotation=270, labelpad=15)

        # Nome do arquivo temporário
        nome_arquivo_modelo = f"analise_{modelo.lower()}_{timestamp}.png"
        
        plt.tight_layout()
        plt.savefig(nome_arquivo_modelo, dpi=120)
        plt.close()
        
        arquivos_gerados.append(nome_arquivo_modelo)

    return arquivos_gerados