import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import os
import logging
from datetime import datetime
from config.settings import load_settings

# Configuração de Logs
logger = logging.getLogger(__name__)

# --- MOTORES DE INFERÊNCIA E CÁLCULO ---

def identificar_versao_precisa(titulo):
    """Extrai a versão (XLS, XS, XEi, etc) usando tokens para evitar falso-positivo."""
    t = str(titulo).lower().replace('-', ' ').replace('.', ' ')
    tokens = t.split()
    versoes_alvo = ["xls", "xs", "xl", "xei", "altis", "gli", "gr-sport", "exclusive", "advance", "sense", "exl", "touring", "ex", "lx"]
    for v in versoes_alvo:
        if v in tokens: return v.upper()
    return ""

def calcular_score_tecnico(row):
    """Cálculo base de oportunidade (0-100) baseado em FIPE, KM e Ano."""
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

def calcular_elite_score(row):
    """Critério de desempate para o ranking final (Bônus de conservação)."""
    base = row['score'] if pd.notnull(row['score']) else 50.0
    elite = base
    idade = max(1, datetime.now().year - row['ano'])
    # Bônus Carro Novo (<= 3 anos) em Salvador
    if idade <= 3: elite += 6
    # Bônus Baixa KM (< 10k km/ano)
    if (row['km'] / idade) < 10000: elite += 8
    # Penalidade por termos de risco
    t = str(row['titulo']).lower()
    if any(x in t for x in ["urgente", "repasse", "detalhes", "detalhe"]): elite -= 12
    return round(elite, 1)

# --- FUNÇÃO DE PLOTAGEM COLORIDA ---

def plotar_ranking_colorido(dataframe, title, filename):
    """Gera o gráfico com escala de cores vibrante RdYlGn."""
    # Seleciona Top 10 pelo Score Técnico e ordena pelo Elite para o ranking
    top_10 = dataframe.sort_values(by='score', ascending=False).head(10).copy()
    top_10 = top_10.sort_values(by='elite_score', ascending=False)
    
    if top_10.empty: return None

    plt.figure(figsize=(12, 8))
    
    # RESTAURAÇÃO DO MAPA DE CALOR: Vermelho (Ruim) -> Amarelo -> Verde (Bom)
    scatter = plt.scatter(
        top_10['km'], 
        top_10['preco_anuncio'], 
        c=top_10['elite_score'], 
        cmap='RdYlGn', 
        s=380, 
        edgecolors='black', 
        linewidths=1.2,
        alpha=0.9, 
        vmin=60,  # Score 60 para baixo = Vermelho
        vmax=95   # Score 95 para cima = Verde Escuro
    )

    for i, (idx, row) in enumerate(top_10.iterrows()):
        pos = i + 1
        medalia = "🥇" if pos == 1 else "🥈" if pos == 2 else "🥉" if pos == 3 else f"#{pos}"
        label_carro = f"{row['modelo_ref'].upper()} {row['versao']}".strip()
        
        plt.annotate(
            f"{medalia} {label_carro}\nElite: {row['elite_score']} | Tec: {row['score']}pts",
            (row['km'], row['preco_anuncio']),
            xytext=(0, 18), textcoords='offset points', ha='center', 
            fontsize=9, fontweight='bold', 
            bbox=dict(boxstyle='round,pad=0.4', fc='white', alpha=0.85, ec='gray')
        )

    plt.title(title, fontsize=15, fontweight='bold', color='darkgreen', pad=25)
    plt.xlabel('Quilometragem Total (KM)', fontsize=11)
    plt.ylabel('Preço de Venda (R$)', fontsize=11)
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'R${x:,.0f}'))
    
    # Adiciona a barra de cores lateral
    cbar = plt.colorbar(scatter)
    cbar.set_label('Qualidade da Oportunidade (Elite Score)', rotation=270, labelpad=20)

    plt.tight_layout()
    nome_final = f"{filename}_{datetime.now().strftime('%H%M')}.png"
    plt.savefig(nome_final, dpi=140)
    plt.close()
    return nome_final

# --- FUNÇÕES DE INTERFACE ---

def gerar_graficos_por_modelo(db_path="data/anuncios.db"):
    """Lê o banco, aplica filtros do YAML e gera os PNGs coloridos."""
    settings = load_settings()
    if not os.path.exists(db_path): return []

    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM anuncios_detalhados WHERE preco_anuncio > 5000 AND km >= 0"
        df_bruto = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        logger.error(f"❌ Erro SQL: {e}")
        return []

    if df_bruto.empty: return []

    # Inferência baseada nos modelos do YAML
    modelos_config = {v.modelo.lower(): v.modelo.capitalize() for v in settings.veiculos}
    
    def inferir_mod(titulo):
        t = str(titulo).lower()
        for slug, nome in modelos_config.items():
            if slug in t: return nome
        return "Outros"

    df_bruto['modelo_ref'] = df_bruto['titulo'].apply(inferir_mod)
    df_bruto['versao'] = df_bruto['titulo'].apply(identificar_versao_precisa)
    df_bruto['score'] = df_bruto.apply(calcular_score_tecnico, axis=1)
    df_bruto['elite_score'] = df_bruto.apply(calcular_elite_score, axis=1)

    # Filtragem por Preferência do Tiago
    df_final = pd.DataFrame()
    for v_config in settings.veiculos:
        nome_mod = v_config.modelo.capitalize()
        temp = df_bruto[df_bruto['modelo_ref'] == nome_mod].copy()
        if hasattr(v_config, 'preco_maximo'):
            temp = temp[temp['preco_anuncio'] <= v_config.preco_maximo]
        if nome_mod == "Yaris":
            temp = temp[temp['versao'].isin(['XS', 'XLS'])]
        df_final = pd.concat([df_final, temp])

    if df_final.empty: return []

    arquivos = []
    # 1. Gráfico Geral
    arq_geral = plotar_ranking_colorido(df_final, "TOP 10 GERAL: Ranking de Decisão (Salvador)", "ranking_elite_geral")
    if arq_geral: arquivos.append(arq_geral)

    # 2. Gráficos por Modelo
    for mod in df_final['modelo_ref'].unique():
        if mod == "Outros": continue
        arq_mod = plotar_ranking_colorido(df_final[df_final['modelo_ref'] == mod], f"ELITE RANK: Melhores {mod.upper()} em Salvador", f"elite_{mod.lower()}")
        if arq_mod: arquivos.append(arq_mod)

    return arquivos

def obter_texto_elite(db_path="data/anuncios.db", modelo_alvo=None):
    """Gera o ranking textual com links para o comando /top."""
    settings = load_settings()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM anuncios_detalhados WHERE preco_anuncio > 5000", conn)
        conn.close()
        
        modelos_config = {v.modelo.lower(): v.modelo.capitalize() for v in settings.veiculos}
        df['modelo_ref'] = df['titulo'].apply(lambda t: next((m for s, m in modelos_config.items() if s in t.lower()), "Outros"))
        df['versao'] = df['titulo'].apply(identificar_versao_precisa)
        df['score'] = df.apply(calcular_score_tecnico, axis=1)
        df['elite_score'] = df.apply(calcular_elite_score, axis=1)

        # Filtros do YAML
        df_v = pd.DataFrame()
        for v_c in settings.veiculos:
            nome = v_c.modelo.capitalize()
            t = df[df['modelo_ref'] == nome].copy()
            if hasattr(v_c, 'preco_maximo'): t = t[t['preco_anuncio'] <= v_c.preco_maximo]
            if nome == "Yaris": t = t[t['versao'].isin(['XS', 'XLS'])]
            df_v = pd.concat([df_v, t])

        if modelo_alvo:
            df_v = df_v[df_v['modelo_ref'].str.lower() == modelo_alvo.lower()]
        
        top_5 = df_v.sort_values(by='elite_score', ascending=False).head(5)
        if top_5.empty: return "📭 Nenhum anúncio passou pelos filtros configurados."

        texto = f"🏆 <b>RANKING DE ELITE - {modelo_alvo.upper() if modelo_alvo else 'GERAL'}</b>\n\n"
        medalhas = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, (idx, row) in enumerate(top_5.iterrows()):
            bairro = f"📍 {row['bairro']}" if row['bairro'] else "📍 Salvador"
            texto += f"{medalhas[i]} <b>{row['modelo_ref'].upper()} {row['versao']} {row['ano']}</b>\n"
            texto += f"⭐ Elite: <b>{row['elite_score']}</b> | {bairro}\n"
            texto += f"💰 R$ {row['preco_anuncio']:,.0f} | 🛣️ {row['km']:,} km\n"
            texto += f"🔗 <a href='{row['link']}'>Ver Anúncio</a>\n\n"
        return texto
    except Exception as e:
        return f"❌ Erro ao processar ranking: {e}"