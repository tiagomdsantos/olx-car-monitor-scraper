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

# --- As funções antigas de calcular score foram removidas daqui para não conflitarem com o Banco de Dados ---

# --- 2. MOTOR DE PLOTAGEM VISUAL ---

def plotar_ranking_colorido(dataframe, title, filename):
    """Gera o dashboard de dispersão com mapa de calor RdYlGn."""
    # Como o score agora é único (elite_score), usamos ele para ordenar
    top_10 = dataframe.sort_values(by='elite_score', ascending=False).head(10).copy()
    
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
            f"{medalia} {label_carro}\nScore: {row['elite_score']}pts",
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
    
    # >>> CORREÇÃO DO FANTASMA <<<
    # Ao invés de recalcular, nós pegamos o elite_score que O EVALUATOR já calculou e salvou no banco
    if 'elite_score' not in df.columns:
        df['elite_score'] = 0.0
    df['elite_score'] = df['elite_score'].fillna(0.0)
    
    # Ajusta o fallback visual para o plotar_ranking_colorido funcionar
    df['score'] = df['elite_score']

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

def obter_texto_elite(db_path="data/anuncios.db", categoria=None, tipo_vendedor=None):
    """
    Gera o ranking textual cruzando filtros de Categoria (Hatch/Sedan/SUV) e/ou Vendedor.
    """
    logger.debug(f"📊 Iniciando 'obter_texto_elite'. Parametros: categoria='{categoria}', vendedor='{tipo_vendedor}'")
    settings = load_settings()
    
    logger.debug("⏳ Chamando 'preparar_dataframe' para carregar os dados brutos...")
    df = preparar_dataframe(db_path, settings)
    
    if df.empty: 
        logger.debug("📭 Dataframe vazio logo após o carregamento inicial. Abortando.")
        return "📭 Nenhum anúncio passou pelos filtros globais iniciais."

    logger.debug(f"📈 Dataframe carregado com sucesso. Total inicial: {len(df)} registros.")

    # --- APLICAÇÃO DOS FILTROS (Múltiplos e Opcionais) ---
    titulo_ranking = "GERAL"
    
    if categoria:
        logger.debug(f"🔍 Aplicando filtro de categoria: '{categoria.upper()}'...")
        if 'categoria' in df.columns:
            df = df[df['categoria'].str.lower() == categoria.lower()]
            titulo_ranking = categoria.upper()
            logger.debug(f"📉 Após filtro de categoria, restaram {len(df)} registros.")
        else:
            logger.warning("⚠️ Atenção: A coluna 'categoria' não foi encontrada no DataFrame!")

    if tipo_vendedor:
        logger.debug(f"🔍 Aplicando filtro de vendedor: '{tipo_vendedor.upper()}'...")
        coluna_vendedor = 'tipo_vendedor' if 'tipo_vendedor' in df.columns else 'vendedor' if 'vendedor' in df.columns else None
        
        if coluna_vendedor:
            df = df[df[coluna_vendedor].str.lower() == tipo_vendedor.lower()]
            titulo_ranking += f" ({tipo_vendedor.upper()})"
            logger.debug(f"📉 Após filtro de vendedor ({coluna_vendedor}), restaram {len(df)} registros.")
        else:
            logger.warning("⚠️ A coluna de tipo de vendedor não existe no banco de dados atual.")
            return "⚠️ A coluna de tipo de vendedor não existe no banco de dados atual."

    if df.empty: 
        logger.debug("📭 Todos os registros foram filtrados. O DataFrame ficou vazio.")
        msg = f"❌ Nenhum registro encontrado "
        if categoria: msg += f"na categoria '{categoria.upper()}' "
        if tipo_vendedor: msg += f"do vendedor '{tipo_vendedor.upper()}'."
        return msg

    # --- MONTAGEM DO RANKING ---
    logger.debug("🏆 Ordenando os resultados pela coluna 'elite_score'...")
    top_5 = df.sort_values(by='elite_score', ascending=False).head(5)
    logger.debug(f"✅ Top 5 selecionado (Total de {len(top_5)} veículos). Montando texto do Telegram...")
    
    texto = f"🏆 <b>RANKING DE ELITE - {titulo_ranking}</b>\n\n"
    medalhas = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    for i, (idx, row) in enumerate(top_5.iterrows()):
        bairro = f"📍 {row['bairro'][:15]}" if row.get('bairro') else "📍 Salvador"
        modelo = row.get('modelo_ref', 'CARRO').upper()
        versao = row.get('versao', '')
        ano = row.get('ano', '')
        
        texto += f"{medalhas[i]} <b>{modelo} {versao} {ano}</b>\n"
        texto += f"⭐ Elite Score: <b>{row.get('elite_score', 0)}</b> | {bairro}\n"
        texto += f"💰 R$ {row.get('preco_anuncio', 0):,.0f} | 🛣️ {row.get('km', 0):,} km\n"
        texto += f"🔗 <a href='{row.get('link', '#')}'>Ver Anúncio</a>\n\n"
        
    logger.debug("🏁 Texto do ranking montado e pronto para envio.")
    return texto