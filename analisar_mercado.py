import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import os
import logging
from datetime import datetime
from config.settings import load_settings

# Configuração de Logs
logger = logging.getLogger(__name__)

# --- 1. MOTORES DE INFERÊNCIA E CÁLCULO ---

def identificar_versao_precisa(titulo):
    """Extrai a versão (XLS, XS, XEi, etc) usando tokens para precisão."""
    t = str(titulo).lower().replace('-', ' ').replace('.', ' ')
    tokens = t.split()
    versoes_alvo = ["xls", "xs", "xl", "xei", "altis", "gli", "gr-sport", "exclusive", "advance", "sense", "exl", "touring", "ex", "lx", "sv", "sl"]
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
    # B) KM/Uso (30%) - Referência de 17k km/ano como limite tolerável
    idade = max(1, datetime.now().year - row['ano'])
    km_ano = row['km'] / idade
    score += max(0, (17000 - km_ano) * 0.003 * 10)
    # C) Idade (20%)
    score += max(0, (10 - idade) * 2)
    return round(min(100, score), 1)

def calcular_elite_score(row):
    """Ranking final: Bônus para conservação."""
    base = row['score'] if pd.notnull(row['score']) else 50.0
    elite = base
    idade = max(1, datetime.now().year - row['ano'])
    
    # Bônus: Carro Novo (<= 3 anos)
    if idade <= 3: elite += 6
    # Bônus: Baixa KM (< 10k km/ano)
    if (row['km'] / idade) < 10000: elite += 8
    # Penalidade: Termos de risco no título
    t = str(row['titulo']).lower()
    if any(x in t for x in ["urgente", "repasse", "detalhes", "detalhe"]): elite -= 12
    
    return round(elite, 1)

# --- 2. MOTOR DE PLOTAGEM VISUAL ---

def plotar_ranking_colorido(dataframe, title, filename):
    """Gera o dashboard de dispersão com mapa de calor RdYlGn."""
    top_10 = dataframe.sort_values(by='score', ascending=False).head(10).copy()
    top_10 = top_10.sort_values(by='elite_score', ascending=False)
    
    if top_10.empty: return None

    plt.figure(figsize=(12, 8))
    
    # Mapa de Calor: Vermelho (<=60) para Verde Escuro (>=95)
    scatter = plt.scatter(
        top_10['km'], top_10['preco_anuncio'], 
        c=top_10['elite_score'], cmap='RdYlGn', 
        s=380, edgecolors='black', linewidths=1.2,
        alpha=0.9, vmin=60, vmax=95
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
    
    cbar = plt.colorbar(scatter)
    cbar.set_label('Decisão de Compra (Elite Score)', rotation=270, labelpad=20)

    plt.tight_layout()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    nome_final = f"{filename}_{timestamp}.png"
    plt.savefig(nome_final, dpi=140)
    plt.close()
    return nome_final

# --- 3. FUNÇÕES PRINCIPAIS DE INTEGRAÇÃO ---

def preparar_dataframe(db_path, settings):
    """Lê o banco, respeita a categoria extraída pela OLX e cruza com o YAML."""
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM anuncios_detalhados WHERE preco_anuncio > 5000 AND km >= 0"
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        logger.error(f"❌ Erro SQL: {e}")
        return pd.DataFrame()

    if df.empty: return df

    # Garante que a coluna existe para não quebrar com bancos antigos
    if 'categoria' not in df.columns:
        df['categoria'] = 'outros'

    # Mapeamento do YAML
    config_map = {
        v.modelo.lower(): {
            "nome": v.modelo.capitalize(), 
            "cat_yaml": getattr(v, 'categoria', '').lower()
        } for v in settings.veiculos
    }

    def processar_linha(row):
        t = str(row['titulo']).lower()
        cat_db = str(row.get('categoria', '')).lower() # Categoria oficial que o Scraper salvou

        for slug, info in config_map.items():
            if slug in t:
                cat_yaml = info["cat_yaml"]

                # --- 1. FONTE DE VERDADE: BANCO DE DADOS (OLX) ---
                if cat_db in ['hatch', 'sedan', 'suv', 'hatchback']:
                    cat_db_norm = 'hatch' if 'hatch' in cat_db else cat_db
                    
                    # Se o YAML exige um, mas o Banco diz outro: REJEITA
                    if cat_yaml and cat_yaml != 'geral' and cat_db_norm != cat_yaml:
                        return pd.Series([None, None]) 
                    
                    return pd.Series([info["nome"], cat_db_norm.capitalize()])

                # --- 2. FALLBACK PARA ANÚNCIOS ANTIGOS (Sem info no banco) ---
                if cat_yaml == "hatch" and "sedan" in t:
                    return pd.Series([None, None]) 
                if cat_yaml == "sedan" and "hatch" in t:
                    return pd.Series([None, None])
                
                return pd.Series([info["nome"], cat_yaml.capitalize() if cat_yaml else "Outros"])
                
        return pd.Series(["Outros", "Outros"])

    # Aplica a função linha a linha (axis=1) para ler título e categoria do banco simultaneamente
    df[['modelo_ref', 'categoria_final']] = df.apply(processar_linha, axis=1)
    
    # Remove sumariamente os anúncios que deram conflito (Os que retornaram None)
    df = df.dropna(subset=['modelo_ref'])
    
    # Atualiza a coluna de categoria para a versão validada
    df['categoria'] = df['categoria_final']

    df['versao'] = df['titulo'].apply(identificar_versao_precisa)
    df['score'] = df.apply(calcular_score_tecnico, axis=1)
    df['elite_score'] = df.apply(calcular_elite_score, axis=1)

    # Filtragem YAML (Preço e Regras de Negócio)
    df_filtrado = pd.DataFrame()
    for v_config in settings.veiculos:
        nome_mod = v_config.modelo.capitalize()
        temp = df[df['modelo_ref'] == nome_mod].copy()
        
        # Filtro de Preço Máximo
        if hasattr(v_config, 'preco_maximo'):
            temp = temp[temp['preco_anuncio'] <= v_config.preco_maximo]
        
        # Regra DURA do Yaris
        if nome_mod == "Yaris":
            temp = temp[temp['versao'].isin(['XS', 'XLS'])]
            
        df_filtrado = pd.concat([df_filtrado, temp])

    return df_filtrado

def gerar_graficos_por_modelo(db_path="data/anuncios.db"):
    """Gera todos os relatórios visuais baseados na configuração."""
    settings = load_settings()
    if not os.path.exists(db_path): return []

    df = preparar_dataframe(db_path, settings)
    if df.empty: return []

    arquivos = []
    
    # 1. Gráfico Top 10 Geral
    arq_geral = plotar_ranking_colorido(df, "TOP 10 GERAL: Oportunidades em Salvador", "ranking_geral")
    if arq_geral: arquivos.append(arq_geral)

    # 2. Gráficos por Categoria (Sedan, Hatch, SUV)
    for cat in df['categoria'].unique():
        if cat == "Outros": continue
        arq_cat = plotar_ranking_colorido(
            df[df['categoria'] == cat], 
            f"ELITE RANK: Melhores {cat.upper()}S em Salvador", 
            f"ranking_cat_{cat.lower()}"
        )
        if arq_cat: arquivos.append(arq_cat)

    # 3. Gráficos por Modelo Específico
    for mod in df['modelo_ref'].unique():
        if mod == "Outros": continue
        arq_mod = plotar_ranking_colorido(
            df[df['modelo_ref'] == mod], 
            f"ELITE RANK: Mercado {mod.upper()} (Salvador)", 
            f"ranking_mod_{mod.lower()}"
        )
        if arq_mod: arquivos.append(arq_mod)

    return arquivos

def obter_texto_elite(db_path="data/anuncios.db", alvo=None):
    """Gera o ranking textual, aceitando Busca Geral, por Categoria ou por Modelo."""
    settings = load_settings()
    df = preparar_dataframe(db_path, settings)
    
    if df.empty: return "📭 Nenhum anúncio passou pelos filtros (YAML/Versão)."

    # Se um alvo foi passado via Telegram (ex: /top sedan ou /top corolla)
    if alvo:
        alvo_str = alvo.lower()
        is_cat = df['categoria'].str.lower() == alvo_str
        is_mod = df['modelo_ref'].str.lower() == alvo_str
        
        df = df[is_cat | is_mod]
        if df.empty: return f"❌ Nenhum registro encontrado para a categoria ou modelo: '{alvo}'."

    top_5 = df.sort_values(by='elite_score', ascending=False).head(5)
    
    texto = f"🏆 <b>RANKING DE ELITE - {alvo.upper() if alvo else 'GERAL'}</b>\n\n"
    medalhas = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    for i, (idx, row) in enumerate(top_5.iterrows()):
        bairro = f"📍 {row['bairro'][:15]}" if row['bairro'] else "📍 Salvador"
        texto += f"{medalhas[i]} <b>{row['modelo_ref'].upper()} {row['versao']} {row['ano']}</b>\n"
        texto += f"⭐ Elite Score: <b>{row['elite_score']}</b> | {bairro}\n"
        texto += f"💰 R$ {row['preco_anuncio']:,.0f} | 🛣️ {row['km']:,} km\n"
        texto += f"🔗 <a href='{row['link']}'>Ver Anúncio</a>\n\n"
        
    return texto