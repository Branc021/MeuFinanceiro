import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import yfinance as yf
import feedparser
import psycopg2
from psycopg2.extras import execute_batch
import sqlite3
import tempfile
import os
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# =====================================================================
# 1. UI/UX 3D, GLASSMORPHISM E FORMATAÇÃO MONETÁRIA
# =====================================================================
st.set_page_config(page_title="Core Finance PRO | Enterprise", layout="wide", page_icon="⚡")

if 'perfil_ativo' not in st.session_state:
    st.session_state.perfil_ativo = 'Pessoal'

cor_primaria = "#0f3460" if st.session_state.perfil_ativo == 'Pessoal' else "#e94560"
cor_secundaria = "#16213e" if st.session_state.perfil_ativo == 'Pessoal' else "#1a1a2e"

st.markdown(f"""
    <style>
    .metric-card {{ background: linear-gradient(145deg, {cor_secundaria}, #111827); padding: 25px; border-radius: 16px; border-left: 6px solid {cor_primaria}; box-shadow: 5px 5px 15px rgba(0,0,0,0.5), -5px -5px 15px rgba(255,255,255,0.02); transition: transform 0.3s ease; margin-bottom: 15px; }}
    .metric-card:hover {{ transform: translateY(-5px); box-shadow: 8px 12px 20px rgba(0,0,0,0.6); }}
    .ai-box {{ background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); padding: 20px; border-radius: 12px; border-left: 5px solid #4facf7; margin-top:10px; }}
    .ai-box-green {{ border-left: 5px solid #4caf50; background-color: #0f3460; padding: 20px; border-radius: 10px; margin-top:10px; }}
    h1, h2, h3 {{ color: #F3F4F6; }}
    </style>
""", unsafe_allow_html=True)

def m_fmt(valor):
    """Formatador de Moeda para o padrão monetário real brasileiro (R$ 1.000,00)"""
    if pd.isna(valor): return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

cartoes_banco = ["NUBANK", "PICPAY", "INTER", "MERCADO PAGO", "WILL", "BRADESCO", "RENNER", "OUTRO"]
meses_pt = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

def detectar_cartao(descricao):
    """Identifica automaticamente o cartão vinculado com base na descrição"""
    if not descricao:
        return None
    desc_up = str(descricao).upper()
    if "NUBANK" in desc_up: return "NUBANK"
    if "PICPAY" in desc_up: return "PICPAY"
    if "INTER" in desc_up: return "INTER"
    if "MERCADO PAGO" in desc_up or "MARCADO PAGO" in desc_up: return "MERCADO PAGO"
    if "WILL" in desc_up: return "WILL"
    if "BRADESCO" in desc_up: return "BRADESCO"
    if "RENNER" in desc_up: return "RENNER"
    return None

# =====================================================================
# 2. CAMADA DE DADOS E CONEXÕES (SUPABASE POSTGRESQL)
# =====================================================================
def get_connection():
    return psycopg2.connect(st.secrets["connections"]["postgresql"]["url"])

def executar_query(query, params=()):
    conn = get_connection()
    cursor = conn.cursor()
    query = query.replace("?", "%s")
    cursor.execute(query, params)
    conn.commit()
    conn.close()

def get_df(query, params=()):
    conn = get_connection()
    query = query.replace("?", "%s")
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    tabelas = {
        "transacoes": "id SERIAL PRIMARY KEY, tipo TEXT, descricao TEXT, categoria TEXT, valor REAL, data_competencia DATE, detalhes TEXT, status TEXT DEFAULT 'Pendente', centro_custo TEXT DEFAULT 'Pessoal', cartao_vinculado TEXT",
        "compras_futuras": "id SERIAL PRIMARY KEY, item TEXT, valor REAL, prioridade TEXT, status TEXT DEFAULT 'Planejado', centro_custo TEXT, metodo TEXT DEFAULT 'PIX', parcelas INTEGER DEFAULT 1, cartao_vinculado TEXT",
        "investimentos": "id SERIAL PRIMARY KEY, ticker TEXT, tipo_ativo TEXT, quantidade REAL, preco_medio REAL, data_compra DATE"
    }
    
    for nome, colunas in tabelas.items():
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {nome} ({colunas})")
        
    conn.commit()
    conn.close()

def importar_arquivo_sqlite(caminho_sqlite, centro_custo_padrao="Pessoal"):
    """Lê tanto o formato Despesas.db (expense/category) quanto financeiro_master.db (transacoes) e substitui no Supabase"""
    conn_local = sqlite3.connect(caminho_sqlite)
    cur_local = conn_local.cursor()
    
    cur_local.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelas_existentes = [r[0] for r in cur_local.fetchall()]
    
    registros_para_inserir = []
    
    if "expense" in tabelas_existentes:
        # Formato original do app de Despesas (Despesas.db)
        query_local = """
            SELECT 
                e.description,
                 COALESCE(c.name, 'Outros') as categoria,
                e.price,
                e.dateTransaction,
                e.status,
                e.countPart
            FROM expense e
            LEFT JOIN category c ON e.categoryId = c.id
        """
        cur_local.execute(query_local)
        linhas = cur_local.fetchall()
        
        for desc, cat, preco, data_tx, status_raw, count_part in linhas:
            descricao_limpa = str(desc).strip()
            categoria_limpa = str(cat).strip()
            valor_float = float(preco) if preco is not None else 0.0
            data_limpa = str(data_tx).strip()[:10]
            status_final = "Pago" if str(status_raw).strip().upper() == "PAID" else "Pendente"
            detalhes_txt = f"Importado | Parte {count_part}" if count_part else "Importado"
            cartao_vinc = detectar_cartao(descricao_limpa)
            
            registros_para_inserir.append((
                "Despesa", descricao_limpa, categoria_limpa, valor_float,
                data_limpa, detalhes_txt, status_final, centro_custo_padrao, cartao_vinc
            ))
            
    elif "transacoes" in tabelas_existentes:
        # Formato já convertido (financeiro_master.db)
        cur_local.execute("SELECT tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado FROM transacoes")
        linhas = cur_local.fetchall()
        for t in linhas:
            cartao_vinc = t[8] if t[8] and str(t[8]) != "None" else detectar_cartao(t[1])
            registros_para_inserir.append((
                t[0], str(t[1]).strip(), str(t[2]).strip(), float(t[3]),
                str(t[4]).strip()[:10], t[5], t[6], t[7] or centro_custo_padrao, cartao_vinc
            ))
    else:
        conn_local.close()
        raise ValueError("O arquivo enviado não possui a tabela 'expense' nem 'transacoes'.")
        
    conn_local.close()
    
    # Conecta ao Supabase, limpa os dados antigos e insere os novos em lote
    conn_nuvem = get_connection()
    cur_nuvem = conn_nuvem.cursor()
    try:
        cur_nuvem.execute("TRUNCATE TABLE transacoes RESTART IDENTITY")
        sql_insert = """
            INSERT INTO transacoes 
            (tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        execute_batch(cur_nuvem, sql_insert, registros_para_inserir, page_size=100)
        conn_nuvem.commit()
    except Exception as e:
        conn_nuvem.rollback()
        raise e
    finally:
        conn_nuvem.close()
        
    return len(registros_para_inserir)

init_db()

# =====================================================================
# 3. MOTORES DE CÁLCULO
# =====================================================================
def calcular_score_financeiro(renda, despesas):
    if renda <= 0: return 0
    taxa = (renda - despesas) / renda
    if taxa >= 0.20: return min(1000, 850 + (taxa * 100))
    elif taxa >= 0.10: return 600 + (taxa * 500)
    elif taxa >= 0: return 400 + (taxa * 1000)
    else: return max(100, 400 - (abs(taxa) * 1000))

@st.cache_data(ttl=86400)
def obter_cotacao_atual(ticker):
    try:
        if not ticker.endswith('.SA') and not ticker.endswith('=X') and not ticker.endswith('-USD') and not ticker.startswith('^'): ticker += '.SA'
        return float(yf.Ticker(ticker).history(period="1d")['Close'].iloc[-1])
    except: return 0.0

def calcular_price(valor_financiado, taxa_mensal, prazo_meses):
    i = taxa_mensal / 100
    if i == 0: return valor_financiado / prazo_meses
    return valor_financiado * (i * (1 + i)**prazo_meses) / ((1 + i)**prazo_meses - 1)

# =====================================================================
# 4. AMBIENTE MULTI-TENANT (SIDEBAR)
# =====================================================================
hoje = datetime.now()

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=80)
    st.markdown("### Workspace Corporativo")
    renda_real_declarada = st.number_input("💵 Renda Mensal Líquida", value=2350.0, help="Sua renda líquida individual real.")
    st.session_state.perfil_ativo = st.selectbox("Alternar Contexto:", ["Pessoal", "Elite Beach Performance"])

# =====================================================================
# 5. FILTRAGEM GLOBAL DE DADOS (SEM APOSTAS ESPORTIVAS)
# =====================================================================
st.title(f"⚡ Core Finance PRO | {st.session_state.perfil_ativo}")
tabs = st.tabs(["📊 Dashboard", "💳 Operações & Cartões", "💼 Carteira", "🤖 Consultor IA", "🔮 Simuladores", "💎 Radar 3D", "⚙️ Admin"])

df_trans = get_df("SELECT * FROM transacoes WHERE centro_custo = ?", (st.session_state.perfil_ativo,))
if not df_trans.empty:
    df_trans['data_competencia'] = pd.to_datetime(df_trans['data_competencia'], errors='coerce')
    df_mes = df_trans[(df_trans['data_competencia'].dt.month == hoje.month) & (df_trans['data_competencia'].dt.year == hoje.year)]
else:
    df_mes = pd.DataFrame()

renda_banco = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum() if not df_mes.empty else 0.0
renda_exibicao = renda_banco if renda_banco > 0 else renda_real_declarada
despesa_mes = df_mes[df_mes['tipo'] == 'Despesa']['valor'].sum() if not df_mes.empty else 0.0
pendente_mes = df_mes[(df_mes['tipo'] == 'Despesa') & (df_mes['status'] == 'Pendente')]['valor'].sum() if not df_mes.empty else 0.0
saldo_livre = renda_exibicao - despesa_mes

# =====================================================================
# TAB 1 (tabs[0]): DASHBOARD
# =====================================================================
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    score = calcular_score_financeiro(renda_exibicao, despesa_mes)
    c1.markdown(f"<div class='metric-card'>Entradas <span title='Montante de receitas consolidadas do mês.'>❓</span><br><h2 style='color:#4caf50;'>{m_fmt(renda_exibicao)}</h2></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='metric-card'>Saídas <span title='Soma das despesas e parcelas com vencimento no mês corrente.'>❓</span><br><h2 style='color:#e94560;'>{m_fmt(despesa_mes)}</h2><small>A pagar: {m_fmt(pendente_mes)}</small></div>", unsafe_allow_html=True)
    
    cor_saldo = "#4facf7" if saldo_livre >= 0 else "#e94560"
    c3.markdown(f"<div class='metric-card'>Saldo Livre <span title='Sobra de caixa limpa calculada.'>❓</span><br><h2 style='color:{cor_saldo};'>{m_fmt(saldo_livre)}</h2></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='metric-card'>Score Financeiro <span title='Indicador de eficiência comportamental de poupança.'>❓</span><br><h2 style='color:#ff9800;'>{score:.0f} / 1000</h2></div>", unsafe_allow_html=True)

    if st.session_state.perfil_ativo == 'Elite Beach Performance':
        st.markdown("---")
        st.subheader("🏖️ Roadmap de Lançamento (Meta: R$ 40.000,00)", help="Progresso acumulado rumo ao capital de giro necessário para o projeto da praia.")
        capital_acumulado = max(saldo_livre, 0)
        progresso_eb = min(capital_acumulado / 40000.0, 1.0)
        st.progress(progresso_eb)
        st.write(f"**Progresso Atual:** {m_fmt(capital_acumulado)} de R$ 40.000,00 ({(progresso_eb*100):.1f}%)")

    st.markdown("---")
    cg1, cg2 = st.columns([2, 1])
    with cg1:
        st.subheader("Fluxo de Caixa Mensal (Waterfall)", help="Demonstração em cascata de como as categorias de despesa drenam a receita.")
        if not df_mes.empty and renda_exibicao > 0:
            df_wf = df_mes[df_mes['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            df_wf['valor'] = -df_wf['valor']
            fig_wf = go.Figure(go.Waterfall(
                orientation="v", measure=['relative'] + ['relative']*len(df_wf) + ['total'],
                x=['Receitas'] + df_wf['categoria'].tolist() + ['Saldo Final'],
                y=[renda_exibicao] + df_wf['valor'].tolist() + [saldo_livre],
                decreasing={"marker":{"color":"#e94560"}}, increasing={"marker":{"color":"#4caf50"}}, totals={"marker":{"color":"#1f77b4"}},
                textposition="outside", texttemplate="%{y:,.2f}"
            ))
            fig_wf.update_layout(template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_wf, use_container_width=True)
    with cg2:
        st.subheader("Distribuição das Saídas")
        if not df_mes.empty and despesa_mes > 0:
            df_pie = df_mes[df_mes['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            fig_pie = px.pie(df_pie, values='valor', names='categoria', template="plotly_dark", hole=0.3)
            st.plotly_chart(fig_pie, use_container_width=True)

# =====================================================================
# TAB 2 (tabs[1]): OPERAÇÕES, VENCIMENTOS E CARTÕES
# =====================================================================
with tabs[1]:
    op_menu = st.radio("Selecione o Painel Operacional:", ["Registrar Transação", "Auditoria de Cartões", "🛒 Wishlist (Planejador)"], horizontal=True)
    
    if op_menu == "Registrar Transação":
        with st.form("form_lanc"):
            c1, c2, c3 = st.columns(3)
            tipo = c1.radio("Fluxo", ["Despesa", "Receita"], horizontal=True)
            valor = c2.number_input("Valor Total", min_value=0.0, format="%.2f")
            forma = c3.selectbox("Método de Pagamento", ["PIX", "Cartão de Crédito", "Débito", "Dinheiro"])
            
            c4, c5, c6 = st.columns(3)
            descricao = c4.text_input("Descrição do Lançamento")
            categoria = c5.selectbox("Categoria", ["Moradia", "Alimentação", "Transporte", "Dieta/Treino", "Educação", "Saúde", "Eletrônicos", "Entretenimento", "Lazer", "Investimento", "Cartão", "Outros"])
            parcelas = c6.number_input("Nº Parcelas", min_value=1, value=1)
            
            cartao_selecionado = st.selectbox("Se for crédito, selecione qual o cartão correspondente:", ["N/A"] + cartoes_banco)
            cartao_envio = None if cartao_selecionado == "N/A" else cartao_selecionado
                
            c7, c8 = st.columns(2)
            data = c7.date_input("Vencimento da 1ª Parcela")
            status = c8.selectbox("Status de Liquidação", ["Pendente", "Pago"])
            
            if st.form_submit_button("Gravar no Banco"):
                if valor > 0 and descricao:
                    val_parc = valor / parcelas
                    for i in range(parcelas):
                        d_venc = data + relativedelta(months=i)
                        detalhe_txt = f"{forma} | Parcela {i+1}/{parcelas}" if parcelas > 1 else forma
                        executar_query("INSERT INTO transacoes (tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?)",
                                       (tipo, descricao, categoria, val_parc, d_venc, detalhe_txt, status, st.session_state.perfil_ativo, cartao_envio))
                    st.success("Transação gravada!")
                    st.rerun()

    elif op_menu == "Auditoria de Cartões":
        st.subheader("Faturas Mapeadas por Cartão de Crédito", help="Audita faturas futuras calculando os parcelamentos de acordo com o vencimento do cartão.")
        df_cartoes = df_trans[(df_trans['cartao_vinculado'].notnull()) & (df_trans['cartao_vinculado'] != 'None')].copy()
        
        if not df_cartoes.empty:
            df_cartoes['Mês de Vencimento'] = df_cartoes['data_competencia'].dt.strftime('%m/%Y')
            resumo_c = df_cartoes[df_cartoes['status'] == 'Pendente'].groupby(['cartao_vinculado', 'Mês de Vencimento'])['valor'].sum().reset_index()
            resumo_c['Total da Fatura'] = resumo_c['valor'].apply(m_fmt)
            
            st.write("**Resumo Geral de Faturas Abertas:**")
            st.dataframe(resumo_c[['cartao_vinculado', 'Mês de Vencimento', 'Total da Fatura']], use_container_width=True)
            
            st.write("**Extrato Detalhado do Cartão Selecionado:**")
            filtro_c = st.selectbox("Filtrar por Cartão:", cartoes_banco)
            df_f = df_cartoes[df_cartoes['cartao_vinculado'] == filtro_c].sort_values('data_competencia')
            if not df_f.empty:
                df_f['Valor Formatado'] = df_f['valor'].apply(m_fmt)
                st.dataframe(df_f[['data_competencia', 'descricao', 'Valor Formatado', 'status']], use_container_width=True)
        else:
            st.info("Nenhuma despesa vinculada a cartões identificada no momento.")

    elif op_menu == "🛒 Wishlist (Planejador)":
        st.subheader("Wishlist Avançada")
        c_w1, c_w2 = st.columns(2)
        w_item = c_w1.text_input("Item Desejado (Ex: Notebook, Whey)")
        w_valor = c_w2.number_input("Valor Estimado", min_value=0.0)
        
        c_w3, c_w4, c_w5 = st.columns(3)
        w_metodo = c_w3.selectbox("Método de Aquisição Planejado", ["PIX", "Cartão de Crédito", "Dinheiro"])
        w_cartao = "N/A"
        w_parc = 1
        
        if w_metodo == "Cartão de Crédito":
            w_cartao = c_w4.selectbox("Selecione o Cartão:", cartoes_banco)
            w_parc = c_w5.number_input("Parcelas Previstas", min_value=1, value=1)
            
        w_prio = st.selectbox("Nível de Prioridade", ["Alta", "Média", "Baixa"])
        
        if st.button("Planejar Item"):
            if w_item and w_valor > 0:
                executar_query("INSERT INTO compras_futuras (item, valor, prioridade, centro_custo, metodo, parcelas, cartao_vinculado) VALUES (?,?,?,?,?,?,?)", 
                               (w_item, w_valor, w_prio, st.session_state.perfil_ativo, w_metodo, w_parc, w_cartao))
                st.success("Item adicionado ao mapa!")
                st.rerun()
                
        st.markdown("---")
        df_wish = get_df("SELECT * FROM compras_futuras WHERE centro_custo = ?", (st.session_state.perfil_ativo,))
        if not df_wish.empty:
            for _, row in df_wish.iterrows():
                meses_espera = int(row['valor'] / (renda_real_declarada * 0.2)) if (renda_real_declarada * 0.2) > 0 else 1
                mes_compra = hoje + relativedelta(months=max(1, meses_espera))
                txt_cartao = f" no cartão {row['cartao_vinculado']}" if row['cartao_vinculado'] and row['cartao_vinculado'] != 'N/A' else ""
                
                with st.expander(f"🛍️ {row['item']} — {m_fmt(row['valor'])} [Status: {row['status']}]"):
                    st.write(f"**Data Segura Mapeada pela IA:** {mes_compra.strftime('%m/%Y')}")
                    st.write(f"**Forma:** {row['metodo']} ({row['parcelas']}x){txt_cartao}")
                    c_edit1, c_edit2, c_edit3 = st.columns(3)
                    if c_edit1.button("✅ Marcar Comprado", key=f"comp_{row['id']}"):
                        executar_query("UPDATE compras_futuras SET status = 'Comprado' WHERE id = ?", (row['id'],))
                        st.rerun()
                    if c_edit2.button("⏱️ Prorrogar", key=f"pro_{row['id']}"):
                        executar_query("UPDATE compras_futuras SET status = 'Prorrogado' WHERE id = ?", (row['id'],))
                        st.rerun()
                    if c_edit3.button("🗑️ Excluir Item", key=f"del_{row['id']}"):
                        executar_query("DELETE FROM compras_futuras WHERE id = ?", (row['id'],))
                        st.rerun()

# =====================================================================
# TAB 3 (tabs[2]): INVESTIMENTOS
# =====================================================================
with tabs[2]:
    st.header("💼 Carteira e Custódia de Ativos", help="Espelho das suas ordens executadas na corretora de investimentos.")
    with st.expander("➕ Inserir Ordem Executada"):
        with st.form("form_ativo"):
            ca1, ca2, ca3, ca4 = st.columns(4)
            ticker = ca1.text_input("Código do Ativo (Ex: PETR4, BTC-USD)").upper()
            tipo_ativo = ca2.selectbox("Classe de Ativo", ["Ação", "FII", "Criptomoeda", "Renda Fixa"])
            qtde = ca3.number_input("Quantidade Operada", min_value=0.0, format="%.4f")
            preco_medio = ca4.number_input("Preço Médio Pago (R$)", min_value=0.0)
            if st.form_submit_button("Salvar na Custódia"):
                executar_query("INSERT INTO investimentos (ticker, tipo_ativo, quantidade, preco_medio, data_compra) VALUES (?,?,?,?,?)",
                               (ticker, tipo_ativo, qtde, preco_medio, datetime.now()))
                st.rerun()

    df_invest = get_df("SELECT * FROM investimentos")
    if not df_invest.empty:
        dados_carteira = []
        pat_inv, pat_atual = 0.0, 0.0
        for _, row in df_invest.iterrows():
            preco_hoje = obter_cotacao_atual(row['ticker']) if row['tipo_ativo'] != 'Renda Fixa' else row['preco_medio']
            tot_pago = row['quantidade'] * row['preco_medio']
            tot_hoje = row['quantidade'] * preco_hoje
            pat_inv += tot_pago; pat_atual += tot_hoje
            dados_carteira.append({
                "Ativo": row['ticker'], "Qtde": row['quantidade'], "P. Médio": m_fmt(row['preco_medio']),
                "Cotação Atual": m_fmt(preco_hoje), "Posição Final": m_fmt(tot_hoje),
                "Desempenho": f"{((tot_hoje - tot_pago)/tot_pago*100) if tot_pago>0 else 0:.2f}%"
            })
        ci1, ci2, ci3 = st.columns(3)
        ci1.metric("Capital Injetado", m_fmt(pat_inv))
        ci2.metric("Avaliação Atual", m_fmt(pat_atual), m_fmt(pat_atual - pat_inv))
        ci3.metric("Rentabilidade Líquida", f"{((pat_atual - pat_inv) / pat_inv * 100) if pat_inv > 0 else 0:.2f} %")
        st.dataframe(pd.DataFrame(dados_carteira), use_container_width=True)

# =====================================================================
# TAB 4 (tabs[3]): INTELIGÊNCIA IA & SOMAS EXATAS
# =====================================================================
with tabs[3]:
    st.header("🤖 Consultor de IA e Mapa de Dívidas", help="Audita faturas futuras e parcelamentos agregados.")
    
    st.subheader("Radar de Passivos e Dívidas Futuras")
    meses_frente = st.slider("Mapear faturas acumuladas de quantos meses à frente?", 1, 12, 3)
    
    lista_meses = [(hoje + relativedelta(months=i)).strftime('%m/%Y') for i in range(meses_frente)]
    df_base = pd.DataFrame({'Mês Referência': lista_meses})
    
    inicio_mes_atual = datetime(hoje.year, hoje.month, 1)
    data_limite = hoje + relativedelta(months=meses_frente)
    
    if not df_trans.empty:
        df_dividas = df_trans[(df_trans['tipo'] == 'Despesa') & (df_trans['status'] == 'Pendente') & (df_trans['data_competencia'] >= inicio_mes_atual) & (df_trans['data_competencia'] <= data_limite)].copy()
        
        total_passivo = df_dividas['valor'].sum() if not df_dividas.empty else 0.0
        
        if total_passivo > 0:
            st.error(f"🚨 **Passivo de Médio Prazo:** {m_fmt(total_passivo)} acumulados nos próximos {meses_frente} meses.")
        else:
            st.success(f"✅ Nenhuma pendência futura mapeada para os próximos {meses_frente} meses.")

        if not df_dividas.empty:
            df_dividas['Mês Referência'] = df_dividas['data_competencia'].dt.strftime('%m/%Y')
            resumo_dividas = df_dividas.groupby('Mês Referência')['valor'].sum().reset_index()
        else:
            resumo_dividas = pd.DataFrame(columns=['Mês Referência', 'valor'])

        df_final = pd.merge(df_base, resumo_dividas, on='Mês Referência', how='left').fillna(0)
        df_final['Soma do Mês'] = df_final['valor'].apply(m_fmt)
        
        st.table(df_final[['Mês Referência', 'Soma do Mês']])
    else:
        st.success("✅ Nenhuma pendência mapeada no banco de dados.")
            
    st.markdown("---")
    st.subheader("Consultar Registros")
    pergunta = st.text_input("Escreva (Ex: 'resumo' ou digite o nome de um mês por extenso em português):")
    if st.button("Mapear Tabela"):
        p = pergunta.lower()
        mes_detectado = next((mes for mes in meses_pt if mes in p), None)
        if mes_detectado:
            num_mes = meses_pt[mes_detectado]
            if not df_trans.empty:
                df_m = df_trans[(df_trans['data_competencia'].dt.month == num_mes) & (df_trans['data_competencia'].dt.year == hoje.year) & (df_trans['tipo'] == 'Despesa')]
                st.info(f"📊 Relatório de {mes_detectado.capitalize()}/{hoje.year}:\n- O total de saídas no mês é **{m_fmt(df_m['valor'].sum())}**.\n- Deste montante, **{m_fmt(df_m[df_m['status'] == 'Pendente']['valor'].sum())}** constam como Pendentes.")
            else: st.warning("O banco de dados está vazio.")
        elif "resumo" in p: st.info(f"O seu Saldo Livre atual é de **{m_fmt(saldo_livre)}**.")

# =====================================================================
# TAB 5 (tabs[4]): ORÇAMENTO COMPLETO, F.I.R.E. E PRICE
# =====================================================================
with tabs[4]:
    st.header("🔮 Simuladores: Arquitetura de Vida e Orçamento")
    sim = st.selectbox("Escolha a Ferramenta de Planejamento:", ["Orçamento Inteligente Base-Zero", "Independência Financeira (F.I.R.E)", "Financiamentos (Tabela Price)"])

    if sim == "Orçamento Inteligente Base-Zero":
        st.write(f"Sua receita de exibição base é de **{m_fmt(renda_real_declarada)}**. Distribua esse valor fatiando os percentuais abaixo (A soma deve fechar em 100%).")
        col_s1, col_s2 = st.columns(2)
        p_moradia = col_s1.slider("🏠 Casa, Contas de Consumo e Amanda", 0, 100, 30)
        p_transp = col_s2.slider("🚗 Locação de Veículos e Mobilidade", 0, 100, 15)
        p_dieta = col_s1.slider("🏋️ Dieta, Whey e Suplementação", 0, 100, 15)
        p_lazer = col_s2.slider("🍻 Saídas, Restaurantes e Lazer", 0, 100, 10)
        p_projeto = col_s1.slider("🏖️ Fundo de Expansão (CNPJ Elite Beach)", 0, 100, 20)
        p_reserva = col_s2.slider("🛡️ Investimentos B3 e Caixa de Emergência", 0, 100, 10)
        
        soma_p = p_moradia + p_transp + p_dieta + p_lazer + p_projeto + p_reserva
        if soma_p == 100:
            st.success("✅ Planejamento 100% otimizado. Divisão exata do capital:")
            s_c1, s_c2, s_c3 = st.columns(3)
            s_c1.metric("Moradia e Contas", m_fmt(renda_real_declarada * (p_moradia/100)))
            s_c2.metric("Locação Veículos", m_fmt(renda_real_declarada * (p_transp/100)))
            s_c3.metric("Fisiculturismo / Whey", m_fmt(renda_real_declarada * (p_dieta/100)))
            s_c1.metric("Aporte Elite Beach", m_fmt(renda_real_declarada * (p_projeto/100)), help="Dinheiro travado para a meta de abertura (40k).")
            s_c2.metric("Reserva / Ações / Cripto", m_fmt(renda_real_declarada * (p_reserva/100)))
            s_c3.metric("Lazer e Estilo de Vida", m_fmt(renda_real_declarada * (p_lazer/100)))
        else:
            st.error(f"⚠️ Distribuição incorreta ({soma_p}%). Ajuste os sliders até fechar em 100%.")

    elif sim == "Independência Financeira (F.I.R.E)":
        st.subheader("Calculadora F.I.R.E (Regra de Retirada dos 4%)")
        renda_passiva = st.number_input("Salário mensal desejado para viver de rendimentos (R$)", value=10000.0)
        montante_magico = (renda_passiva * 12) / 0.04
        st.success(f"🎯 **O Número Mágico:** Para sacar {m_fmt(renda_passiva)} todo mês sem reduzir seu patrimônio principal, acumule: **{m_fmt(montante_magico)}** investidos em ativos geradores de dividendos.")

    elif sim == "Financiamentos (Tabela Price)":
        st.subheader("Calculadora de Financiamento (Tabela Price)")
        v = st.number_input("Valor a Financiar", value=30000.0)
        t = st.number_input("Taxa de Juros Mensal (%)", value=1.5, step=0.1)
        m = st.slider("Prazo de Amortização (Meses)", 12, 72, 48)
        p = calcular_price(v, t, m)
        if v > 0:
            st.error(f"**Custo Real:** A sua parcela fixa será de **{m_fmt(p)}**. No final do período, terá desembolsado **{m_fmt(p*m)}**. Apenas de juros comerciais para o banco, você pagará **{m_fmt((p*m)-v)}**.")

# =====================================================================
# TAB 6 (tabs[5]): VISÃO 3D E MERCADO
# =====================================================================
with tabs[5]:
    st.header("💎 Visão Global de Mercado", help="Monitoração de indicadores econômicos e evolução patrimonial em 3D.")
    
    st.subheader("Superfície 3D: A Montanha dos Juros Compostos", help="Gire este gráfico livremente! Ele evidencia que o Tempo (X) aliado aos Juros (Y) cria uma curvatura explosiva de enriquecimento (Z).")
    anos = np.linspace(1, 30, 30) 
    taxas = np.linspace(0.05, 0.20, 16) 
    X, Y = np.meshgrid(anos, taxas)
    Z = 1000 * ((1 + Y)**X) 
    fig_3d = go.Figure(data=[go.Surface(z=Z, x=X, y=Y, colorscale='Viridis')])
    fig_3d.update_layout(title='', autosize=False, height=500, scene=dict(xaxis_title='Anos de Aporte', yaxis_title='Rentabilidade % a.a.', zaxis_title='Multiplicador'), template="plotly_dark", margin=dict(l=0, r=0, b=0, t=20))
    st.plotly_chart(fig_3d, use_container_width=True)

    st.markdown("---")
    cr1, cr2 = st.columns([2, 1])
    with cr1:
        st.subheader("📰 Notícias Estratégicas (Cripto & Investimentos)")
        try:
            feed = feedparser.parse("https://br.cointelegraph.com/rss")
            for i in range(min(5, len(feed.entries))): 
                st.markdown(f"**[{feed.entries[i].title}]({feed.entries[i].link})**")
                st.caption(f"Publicado: {feed.entries[i].published}")
        except: st.error("Erro na obtenção do feed do CoinTelegraph.")
    with cr2:
        st.subheader("🌐 Cotações Globais (Live)")
        ativos_globais = {
            "Dólar Comercial": "USDBRL=X", "Euro Comercial": "EURBRL=X", 
            "Libra Esterlina": "GBPBRL=X", "Bitcoin (BTC)": "BTC-USD", 
            "Ethereum (ETH)": "ETH-USD", "Ibovespa": "^BVSP",
            "S&P 500 (EUA)": "^GSPC"
        }
        for nome, ticker in ativos_globais.items(): 
            val = obter_cotacao_atual(ticker)
            st.metric(nome, f"{val:,.2f}")

# =====================================================================
# TAB 7 (tabs[6]): ADMIN & IMPORTADOR DE ARQUIVO .DB
# =====================================================================
with tabs[6]:
    st.header("⚙️ Banco de Dados & Sincronização (Root Access)")
    
    st.subheader("🔄 Importar Arquivo `Despesas.db` e Substituir Dados")
    st.write("Envie o seu arquivo `.db` atualizado abaixo. O sistema converterá automaticamente as tabelas `expense` e `category` (ou `transacoes`), limpará os registros antigos e atualizará toda a nuvem.")
    
    arquivo_db = st.file_uploader("Selecione o arquivo Despesas.db ou financeiro_master.db", type=["db", "sqlite", "sqlite3"])
    
    if arquivo_db is not None:
        if st.button("🚀 Substituir Todos os Valores do Banco de Dados", type="primary"):
            with st.spinner("Sincronizando e substituindo registros no Supabase..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp.write(arquivo_db.read())
                    caminho_tmp = tmp.name
                try:
                    total_importado = importar_arquivo_sqlite(caminho_tmp, st.session_state.perfil_ativo)
                    st.success(f"✅ Sucesso absoluto! {total_importado} registros foram importados e substituídos no banco de dados.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao importar o arquivo: {e}")
                finally:
                    if os.path.exists(caminho_tmp):
                        os.remove(caminho_tmp)
                        
    st.markdown("---")
    st.subheader("📋 Registros Atuais no Banco de Dados")
    df_tudo = get_df("SELECT * FROM transacoes ORDER BY data_competencia DESC")
    if not df_tudo.empty: 
        df_tudo['valor_formatado'] = df_tudo['valor'].apply(m_fmt)
        colunas_exibicao = [col for col in ['id', 'tipo', 'descricao', 'categoria', 'valor_formatado', 'data_competencia', 'status', 'cartao_vinculado'] if col in df_tudo.columns]
        st.dataframe(df_tudo[colunas_exibicao], use_container_width=True)
        
        if st.button("Limpar Banco Consolidado 🗑️", help="Exclui todas as transações permanentemente de forma irreversível."):
            executar_query("TRUNCATE TABLE transacoes RESTART IDENTITY")
            st.rerun()
    else: 
        st.warning("O banco de dados está vazio. Importe um arquivo .db acima ou registre transações.")