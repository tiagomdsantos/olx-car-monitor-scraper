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
    Analisa o banco, identifica versões (XEi, EXL, XS, XLS), calcula Scores 
    e gera o Top 10 Geral + Modelos Específicos com Fallback Híbrido.
    """
    if not os.path.exists(db_path):
        logger.error(f"❌ Banco de dados não encontrado em {db_path}")
        return []

    try:
        conn = sqlite3.connect(db_path)
        # Query aberta para permitir fallback de anúncios sem FIPE
        query = """
            SELECT titulo, preco_anuncio, preco_fipe, percentual_fipe, km, ano, link, bairro
            FROM anuncios_detalhados 
            WHERE preco_anuncio > 5000 AND km > 0
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        logger.error(f"❌ Erro ao acessar o banco para análise: {e}")
        return []

    if df.empty:
        logger.warning("⚠️ Banco de dados vazio ou sem anúncios válidos.")
        return []

    # --- 1. MOTORES DE INFERÊNCIA DE VERSÃO E SCORE ---
    
    def identificar_versao_precisa(titulo):
        """Identifica a versão exata usando split() para evitar confusão entre XL, XS e XLS."""
        t = str(titulo).lower().replace('-', ' ').replace('.', ' ')
        tokens = t.split()
        
        # Ordem de prioridade para siglas que podem estar contidas em outras
        # (Ex: XLS deve ser checado antes de XL)
        versoes_alvo = [
            "xls", "xs", "xl", "xei", "altis", "gli", "gr-sport", 
            "exclusive", "advance", "sense", "exl", "touring", "ex", "lx"
        ]
        
        for v in versoes_alvo:
            if v in tokens:
                return v.upper()
        return ""

    def inferir_modelo_base(titulo):
        t = str(titulo).lower()
        modelos = ["corolla", "civic", "city", "kicks", "versa", "sentra", "hb20", "creta", "hr-v", "fit", "yaris"]
        for m in modelos:
            if m in t: return m.capitalize()
        return "Outros"

    def calcular_score_hibrido(row):
        """Calcula Score se houver FIPE. Caso contrário, retorna None."""
        if pd.isna(row['preco_fipe']) or row['preco_fipe'] <= 0:
            return None
            
        score = 0
        # A) Preço vs FIPE (50%)
        score += max(0, (100 - row['percentual_fipe']) * 2.5)
        # B) KM/Uso (30%)
        idade = max(1, datetime.now().year - row['ano'])
        km_ano = row['km'] / idade
        score += max(0, (17000 - km_ano) * 0.003 * 10)
        # C) Idade (20%)
        score += max(0, (10 - idade) * 2)
        return round(min(100, score), 1)

    # Processamento Inicial
    df['modelo_ref'] = df['titulo'].apply(inferir_modelo_base)
    df['versao'] = df['titulo'].apply(identificar_versao_precisa)
    df['score'] = df.apply(calcular_score_hibrido, axis=1)
    
    # --- 2. FILTRO DE PREFERÊNCIAS (ESTRATÉGIA DE COMPRA) ---
    # Para o Yaris, você só quer XS ou XLS. O XL (básico) é removido da análise visual.
    filtro_yaris = (df['modelo_ref'] == 'Yaris') & (~df['versao'].isin(['XS', 'XLS']))
    df = df[~filtro_yaris].copy()

    arquivos_gerados = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    # --- 3. LÓGICA DE SELEÇÃO TOP 10 (COM FALLBACK) ---
    def selecionar_melhores(dataframe):
        """Prioriza Score Alto -> Menor Preço -> Ano Mais Novo."""
        com_score = dataframe[dataframe['score'].notnull()].sort_values(by='score', ascending=False)
        sem_score = dataframe[dataframe['score'].isnull()].sort_values(by=['preco_anuncio', 'ano'], ascending=[True, False])
        return pd.concat([com_score, sem_score]).head(10)

    # --- 4. GERAÇÃO: TOP 10 GERAL ---
    df_geral = selecionar_melhores(df)
    
    if not df_geral.empty:
        logger.info("📈 Gerando Top 10 Geral (Filtrado)...")
        nome_gr_geral = f"analise_top10geral_{timestamp}.png"
        
        plt.figure(figsize=(12, 7))
        scatter = plt.scatter(
            df_geral['km'], df_geral['preco_anuncio'], 
            c=df_geral['score'].fillna(0), cmap='RdYlGn', 
            s=280, edgecolors='black', alpha=0.9, vmin=50, vmax=100
        )

        for i, row in df_geral.iterrows():
            label_carro = f"{row['modelo_ref'].upper()} {row['versao']}".strip()
            label_score = f"{row['score']}pts" if pd.notnull(row['score']) else "S/ FIPE"
            
            plt.annotate(
                f"{label_carro}\n{row['ano']} | {label_score}",
                (row['km'], row['preco_anuncio']),
                xytext=(0, 12), textcoords='offset points', ha='center', 
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7, ec='none')
            )

        plt.title('Melhores Oportunidades em Salvador (Filtro Personalizado)', fontsize=14, fontweight='bold', pad=20)
        plt.xlabel('Quilometragem Total (KM)')
        plt.ylabel('Preço de Venda (R$)')
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R${x:,.0f}'))
        
        plt.tight_layout()
        plt.savefig(nome_gr_geral, dpi=130)
        plt.close()
        arquivos_gerados.append(nome_gr_geral)

    # --- 5. GERAÇÃO: GRÁFICOS POR MODELO ---
    for modelo in df['modelo_ref'].unique():
        if modelo == "Outros": continue
        
        df_mod = df[df['modelo_ref'] == modelo]
        df_top_modelo = selecionar_melhores(df_mod)

        if df_top_modelo.empty: continue
        
        logger.info(f"📈 Gerando gráfico para: {modelo}")
        plt.figure(figsize=(12, 7))
        
        plt.scatter(
            df_top_modelo['km'], df_top_modelo['preco_anuncio'], 
            c=df_top_modelo['score'].fillna(0), cmap='RdYlGn', 
            s=220, edgecolors='black', alpha=0.85, vmin=50, vmax=100
        )

        for i, row in df_top_modelo.iterrows():
            txt_versao = row['versao'] if row['versao'] else "Base"
            txt_score = f"{row['score']}pts" if pd.notnull(row['score']) else "S/ FIPE"
            
            plt.annotate(
                f"{txt_versao} | {row['ano']}\n{txt_score}",
                (row['km'], row['preco_anuncio']),
                xytext=(0, 10), textcoords='offset points', ha='center',
                fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.5, ec='none')
            )

        plt.title(f'Mercado: {modelo.upper()} em Salvador (Apenas Alvos)', fontsize=14, fontweight='bold', pad=20)
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R${x:,.0f}'))
        
        nome_arquivo = f"analise_{modelo.lower()}_{timestamp}.png"
        plt.tight_layout()
        plt.savefig(nome_arquivo, dpi=120)
        plt.close()
        arquivos_gerados.append(nome_arquivo)

    return arquivos_gerados