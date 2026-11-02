import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import yfinance as yf
import feedparser
import psycopg2
from psycopg2.extras import execute_batch
import sqlite3
import tempfile
import urllib.parse
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
    .metric-card {{ background: linear-gradient(145deg, {cor_secundaria}, #111827); padding: 22px; border-radius: 16px; border-left: 6px solid {cor_primaria}; box-shadow: 5px 5px 15px rgba(0,0,0,0.5), -5px -5px 15px rgba(255,255,255,0.02); transition: transform 0.3s ease; margin-bottom: 15px; }}
    .metric-card:hover {{ transform: translateY(-4px); box-shadow: 8px 12px 20px rgba(0,0,0,0.6); }}
    .alert-card-red {{ background: rgba(233, 69, 96, 0.15); border-left: 6px solid #e94560; padding: 15px; border-radius: 10px; margin-bottom: 10px; }}
    .alert-card-yellow {{ background: rgba(255, 152, 0, 0.15); border-left: 6px solid #ff9800; padding: 15px; border-radius: 10px; margin-bottom: 10px; }}
    .alert-card-green {{ background: rgba(76, 175, 80, 0.15); border-left: 6px solid #4caf50; padding: 15px; border-radius: 10px; margin-bottom: 10px; }}
    h1, h2, h3 {{ color: #F3F4F6; }}
    </style>
""", unsafe_allow_html=True)

def m_fmt(valor):
    """Formatador de Moeda para o padrão Real Brasileiro (R$ 1.000,00)"""
    if pd.isna(valor) or valor is None: return "R$ 0,00"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

cartoes_banco = ["NUBANK", "PICPAY", "INTER", "MERCADO PAGO", "WILL", "BRADESCO", "RENNER", "OUTRO"]
meses_pt = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

def detectar_cartao(descricao):
    if not descricao: return None
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
# 2. CAMADA DE DADOS BLINDADA (SUPABASE POSTGRESQL)
# =====================================================================
def get_connection():
    """Conexão com keepalives ativado para evitar quedas por inatividade"""
    return psycopg2.connect(
        st.secrets["connections"]["postgresql"]["url"],
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5
    )

def executar_query(query, params=()):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = query.replace("?", "%s")
        cursor.execute(query, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_df(query, params=()):
    conn = get_connection()
    try:
        query = query.replace("?", "%s")
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            df = pd.read_sql(query, conn, params=params)
        return df
    finally:
        conn.close()

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

def importar_arquivo_sqlite(caminho_sqlite, centro_custo_padrao="Pessoal", preservar_manuais=True):
    """Importa Despesas.db ou financeiro_master.db protegendo as Receitas/Cobranças cadastradas"""
    conn_local = sqlite3.connect(caminho_sqlite)
    cur_local = conn_local.cursor()
    
    cur_local.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelas_existentes = [r[0] for r in cur_local.fetchall()]
    
    registros_para_inserir = []
    
    if "expense" in tabelas_existentes:
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
    
    conn_nuvem = get_connection()
    cur_nuvem = conn_nuvem.cursor()
    try:
        if preservar_manuais:
            # Apaga apenas as despesas antigas do perfil ativo, mantendo as Receitas/Cobranças intactas!
            cur_nuvem.execute("DELETE FROM transacoes WHERE tipo = 'Despesa' AND centro_custo = %s", (centro_custo_padrao,))
        else:
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
# 4. SIDEBAR COM LANÇAMENTO RÁPIDO (PARA NÃO ESQUECER NADA)
# =====================================================================
hoje = datetime.now()
hoje_data = hoje.date()

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=70)
    st.markdown("### Workspace Corporativo")
    renda_real_declarada = st.number_input("💵 Renda Base Fixa Mensal", value=2350.0, help="Seu salário/renda fixa líquida garantida.")
    st.session_state.perfil_ativo = st.selectbox("Alternar Contexto:", ["Pessoal", "Elite Beach Performance"])
    
    st.markdown("---")
    st.markdown("### ⚡ Anotação Rápida (5s)")
    st.caption("Entrou ou saiu dinheiro agora? Anote aqui para nunca esquecer:")
    with st.form("form_rapido_sidebar", clear_on_submit=True):
        r_tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        r_desc = st.text_input("O que foi? (Ex: Almoço, Pix Cliente)")
        r_val = st.number_input("Valor (R$)", min_value=0.0, format="%.2f")
        r_status = st.selectbox("Status", ["Pago", "Pendente"])
        if st.form_submit_button("💾 Salvar Agora", use_container_width=True):
            if r_desc and r_val > 0:
                cat_padrao = "Recebimento de Terceiros" if r_tipo == "Receita" else "Outros"
                executar_query(
                    "INSERT INTO transacoes (tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?)",
                    (r_tipo, r_desc.strip(), cat_padrao, r_val, hoje_data, "Lançamento Rápido", r_status, st.session_state.perfil_ativo, detectar_cartao(r_desc))
                )
                st.success("✅ Anotado!")
                st.rerun()
            else:
                st.warning("Preencha descrição e valor.")

# =====================================================================
# 5. CARREGAMENTO GLOBAL E CENTRAL DE ALERTAS DE COBRANÇA
# =====================================================================
st.title(f"⚡ Core Finance PRO | {st.session_state.perfil_ativo}")

df_trans = get_df("SELECT * FROM transacoes WHERE centro_custo = ?", (st.session_state.perfil_ativo,))
if not df_trans.empty:
    df_trans['data_competencia_dt'] = pd.to_datetime(df_trans['data_competencia'], errors='coerce')
    df_trans['data_apenas'] = df_trans['data_competencia_dt'].dt.date
    df_mes = df_trans[(df_trans['data_competencia_dt'].dt.month == hoje.month) & (df_trans['data_competencia_dt'].dt.year == hoje.year)]
else:
    df_mes = pd.DataFrame()

# Cálculos Dinâmicos do Mês Atual (Integrando Recebimentos Pagos e Pendentes)
receitas_pagas_mes = df_mes[(df_mes['tipo'] == 'Receita') & (df_mes['status'] == 'Pago')]['valor'].sum() if not df_mes.empty else 0.0
receitas_pendentes_mes = df_mes[(df_mes['tipo'] == 'Receita') & (df_mes['status'] == 'Pendente')]['valor'].sum() if not df_mes.empty else 0.0

despesas_totais_mes = df_mes[df_mes['tipo'] == 'Despesa']['valor'].sum() if not df_mes.empty else 0.0
despesas_pagas_mes = df_mes[(df_mes['tipo'] == 'Despesa') & (df_mes['status'] == 'Pago')]['valor'].sum() if not df_mes.empty else 0.0
despesas_pendentes_mes = df_mes[(df_mes['tipo'] == 'Despesa') & (df_mes['status'] == 'Pendente')]['valor'].sum() if not df_mes.empty else 0.0

# O que você realmente tem de Entradas Confirmadas (Salário Base + Recebimentos já pagos por terceiros)
entradas_confirmadas = renda_real_declarada + receitas_pagas_mes
# Saldo Livre Real (Considerando entradas confirmadas menos todas as despesas do mês)
saldo_livre_atual = entradas_confirmadas - despesas_totais_mes
# Saldo Projetado (Quando todos os terceiros te pagarem no mês)
saldo_projetado_mes = (entradas_confirmadas + receitas_pendentes_mes) - despesas_totais_mes

# --- CENTRAL DE NOTIFICAÇÕES DE COBRANÇA NO TOPO ---
if not df_trans.empty:
    df_cobrar = df_trans[(df_trans['tipo'] == 'Receita') & (df_trans['status'] == 'Pendente')].copy()
    if not df_cobrar.empty:
        atrasados = df_cobrar[df_cobrar['data_apenas'] < hoje_data]
        vencem_hoje = df_cobrar[df_cobrar['data_apenas'] == hoje_data]
        vencem_breve = df_cobrar[(df_cobrar['data_apenas'] > hoje_data) & (df_cobrar['data_apenas'] <= hoje_data + timedelta(days=3))]
        
        if not atrasados.empty or not vencem_hoje.empty or not vencem_breve.empty:
            with st.expander("🔔 CENTRAL DE LEMBRETES E COBRANÇAS ATIVAS (CLIQUE PARA VER QUEM COBRAR)", expanded=True):
                for _, r in atrasados.iterrows():
                    st.markdown(f"<div class='alert-card-red'>🚨 <b>ATRASADO — COBRAR AGORA:</b> <b>{r['descricao']}</b> devia ter pago <b>{m_fmt(r['valor'])}</b> em <b>{r['data_apenas'].strftime('%d/%m/%Y')}</b> ({r['detalhes'] or 'Sem obs'}). Vá na aba <i>💰 Recebimentos & Cobranças</i> para dar baixa ou cobrar!</div>", unsafe_allow_html=True)
                for _, r in vencem_hoje.iterrows():
                    st.markdown(f"<div class='alert-card-yellow'>⚠️ <b>VENCE HOJE ({hoje_data.strftime('%d/%m')}):</b> Lembre-se de cobrar/conferir <b>{r['descricao']}</b> no valor de <b>{m_fmt(r['valor'])}</b>!</div>", unsafe_allow_html=True)
                for _, r in vencem_breve.iterrows():
                    st.markdown(f"<div class='alert-card-green'>📅 <b>PRÓXIMOS DIAS ({r['data_apenas'].strftime('%d/%m/%Y')}):</b> Previsão de receber <b>{m_fmt(r['valor'])}</b> de <b>{r['descricao']}</b>.</div>", unsafe_allow_html=True)

tabs = st.tabs([
    "📊 Dashboard",
    "💰 Recebimentos & Cobranças",
    "💳 Operações & Cartões",
    "💼 Carteira",
    "🤖 Consultor & Contas Futuras",
    "🔮 Simuladores",
    "💎 Radar 3D",
    "⚙️ Admin & Blindagem"
])

# =====================================================================
# TAB 1 (tabs[0]): DASHBOARD
# =====================================================================
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    score = calcular_score_financeiro(entradas_confirmadas + receitas_pendentes_mes, despesas_totais_mes)
    
    c1.markdown(f"<div class='metric-card'>Entradas Confirmadas <span title='Renda Base Fixa + Recebimentos de terceiros já marcados como Pagos neste mês.'>❓</span><br><h2 style='color:#4caf50;'>{m_fmt(entradas_confirmadas)}</h2><small>A receber no mês: <b>{m_fmt(receitas_pendentes_mes)}</b></small></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='metric-card'>Saídas do Mês <span title='Soma das despesas do mês corrente.'>❓</span><br><h2 style='color:#e94560;'>{m_fmt(despesas_totais_mes)}</h2><small>Falta pagar: <b>{m_fmt(despesas_pendentes_mes)}</b> | Pago: {m_fmt(despesas_pagas_mes)}</small></div>", unsafe_allow_html=True)
    
    cor_saldo = "#4facf7" if saldo_livre_atual >= 0 else "#e94560"
    c3.markdown(f"<div class='metric-card'>Saldo Disponível Hoje <span title='Entradas já confirmadas menos as saídas do mês.'>❓</span><br><h2 style='color:{cor_saldo};'>{m_fmt(saldo_livre_atual)}</h2><small>Projetado c/ recebíveis: <b>{m_fmt(saldo_projetado_mes)}</b></small></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='metric-card'>Score Financeiro <span title='Indicador de eficiência de poupança.'>❓</span><br><h2 style='color:#ff9800;'>{score:.0f} / 1000</h2><small>Status: {'Saudável' if score >= 600 else 'Atenção'}</small></div>", unsafe_allow_html=True)

    if st.session_state.perfil_ativo == 'Elite Beach Performance':
        st.markdown("---")
        st.subheader("🏖️ Roadmap de Lançamento (Meta: R$ 40.000,00)")
        capital_acumulado = max(saldo_projetado_mes, 0)
        progresso_eb = min(capital_acumulado / 40000.0, 1.0)
        st.progress(progresso_eb)
        st.write(f"**Progresso Atual:** {m_fmt(capital_acumulado)} de R$ 40.000,00 ({(progresso_eb*100):.1f}%)")

    st.markdown("---")
    cg1, cg2 = st.columns([2, 1])
    with cg1:
        st.subheader("Fluxo de Caixa Mensal (Waterfall)")
        if not df_mes.empty and (entradas_confirmadas + receitas_pendentes_mes) > 0:
            df_wf = df_mes[df_mes['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            df_wf['valor'] = -df_wf['valor']
            
            x_labels = ['Renda + Recebidos']
            y_vals = [entradas_confirmadas]
            measures = ['relative']
            
            if receitas_pendentes_mes > 0:
                x_labels.append('A Receber (Pendente)')
                y_vals.append(receitas_pendentes_mes)
                measures.append('relative')
                
            x_labels += df_wf['categoria'].tolist() + ['Saldo Projetado']
            y_vals += df_wf['valor'].tolist() + [saldo_projetado_mes]
            measures += ['relative']*len(df_wf) + ['total']
            
            fig_wf = go.Figure(go.Waterfall(
                orientation="v", measure=measures, x=x_labels, y=y_vals,
                decreasing={"marker":{"color":"#e94560"}}, increasing={"marker":{"color":"#4caf50"}}, totals={"marker":{"color":"#1f77b4"}},
                textposition="outside", texttemplate="%{y:,.2f}"
            ))
            fig_wf.update_layout(template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_wf, use_container_width=True)
    with cg2:
        st.subheader("Distribuição das Saídas")
        if not df_mes.empty and despesas_totais_mes > 0:
            df_pie = df_mes[df_mes['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            fig_pie = px.pie(df_pie, values='valor', names='categoria', template="plotly_dark", hole=0.3)
            st.plotly_chart(fig_pie, use_container_width=True)

# =====================================================================
# TAB 2 (tabs[1]): PREVISÃO DE RECEBIMENTOS & COBRANÇAS DE TERCEIROS
# =====================================================================
with tabs[1]:
    st.header("💰 Previsão de Recebimentos & Controle de Cobranças")
    st.write("Registre tudo o que você tem para receber de terceiros, alunos de consultoria, empréstimos ou serviços. Quando marcar como **Pago**, o valor entra imediatamente no seu caixa do mês e atualiza suas contas futuras!")

    # KPIs de Recebíveis
    df_rec_all = df_trans[df_trans['tipo'] == 'Receita'].copy() if not df_trans.empty else pd.DataFrame()
    tot_ja_recebido = df_rec_all[df_rec_all['status'] == 'Pago']['valor'].sum() if not df_rec_all.empty else 0.0
    tot_a_receber_geral = df_rec_all[df_rec_all['status'] == 'Pendente']['valor'].sum() if not df_rec_all.empty else 0.0
    tot_atrasado_cobrar = df_rec_all[(df_rec_all['status'] == 'Pendente') & (df_rec_all['data_apenas'] < hoje_data)]['valor'].sum() if not df_rec_all.empty else 0.0

    kr1, kr2, kr3 = st.columns(3)
    kr1.metric("✅ Total Já Recebido (Histórico)", m_fmt(tot_ja_recebido))
    kr2.metric("⏳ Total Pendente a Receber (Geral)", m_fmt(tot_a_receber_geral))
    kr3.metric("🚨 Em Atraso (Cobrar Imediatamente!)", m_fmt(tot_atrasado_cobrar))

    st.markdown("---")
    with st.expander("➕ Cadastrar Novo Valor a Receber / Cobrança de Terceiro", expanded=True):
        with st.form("form_novo_recebimento", clear_on_submit=True):
            rc1, rc2, rc3 = st.columns(3)
            quem_paga = rc1.text_input("Quem vai pagar? / Origem (Ex: João - Consultoria, Empréstimo Maria)")
            valor_rec = rc2.number_input("Valor Total a Receber (R$)", min_value=0.0, format="%.2f")
            cat_rec = rc3.selectbox("Categoria do Recebimento", [
                "Cobrança de Terceiros / Empréstimo",
                "Consultoria / Personal",
                "Venda / Serviço Extra",
                "Reembolso / Rateio de Contas",
                "Salário / Bônus Extra",
                "Outros Recebimentos"
            ])
            
            rc4, rc5, rc6, rc7 = st.columns(4)
            data_prevista = rc4.date_input("Data Prevista para Receber / Cobrar", value=hoje_data)
            parcelas_rec = rc5.number_input("Dividido em quantas vezes?", min_value=1, max_value=24, value=1)
            whatsapp_terceiro = rc6.text_input("WhatsApp p/ Cobrança (Opcional)", placeholder="Ex: 21999999999")
            status_inicial_rec = rc7.selectbox("Status Atual", ["Pendente", "Pago"])

            if st.form_submit_button("💾 Registrar Previsão de Recebimento", type="primary"):
                if quem_paga and valor_rec > 0:
                    val_parcela_rec = valor_rec / parcelas_rec
                    for i in range(parcelas_rec):
                        dt_venc_rec = data_prevista + relativedelta(months=i)
                        sufixo_parc = f" (Parcela {i+1}/{parcelas_rec})" if parcelas_rec > 1 else ""
                        det_rec = f"Tel: {whatsapp_terceiro.strip()}" if whatsapp_terceiro.strip() else "Previsão de Recebimento"
                        executar_query(
                            "INSERT INTO transacoes (tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?)",
                            ("Receita", f"{quem_paga.strip()}{sufixo_parc}", cat_rec, val_parcela_rec, dt_venc_rec, det_rec, status_inicial_rec, st.session_state.perfil_ativo, None)
                        )
                    st.success(f"✅ Recebimento de {quem_paga} registrado com sucesso! O painel e as contas futuras foram atualizados.")
                    st.rerun()
                else:
                    st.warning("⚠️ Informe quem vai pagar e o valor a receber.")

    st.markdown("---")
    st.subheader("📋 Painel de Cobranças e Recebimentos")
    filtro_status_rec = st.radio("Filtrar Visualização:", ["⏳ Pendentes (A Cobrar / Receber)", "✅ Já Recebidos (Pagos)", "📊 Todos"], horizontal=True)

    if not df_rec_all.empty:
        df_rec_view = df_rec_all.sort_values('data_competencia_dt').copy()
        if "Pendentes" in filtro_status_rec:
            df_rec_view = df_rec_view[df_rec_view['status'] == 'Pendente']
        elif "Já Recebidos" in filtro_status_rec:
            df_rec_view = df_rec_view[df_rec_view['status'] == 'Pago']

        if not df_rec_view.empty:
            for _, row in df_rec_view.iterrows():
                dt_item = row['data_apenas']
                dias_diff = (dt_item - hoje_data).days if pd.notna(dt_item) else 0
                
                if row['status'] == 'Pago':
                    badge = "🟢 RECEBIDO (EM CAIXA)"
                elif dias_diff < 0:
                    badge = f"🚨 ATRASADO HÁ {abs(dias_diff)} DIAS — COBRAR!"
                elif dias_diff == 0:
                    badge = "⚠️ VENCE HOJE — COBRAR!"
                else:
                    badge = f"📅 PREVISTO PARA DAQUI A {dias_diff} DIAS"

                with st.expander(f"{badge} | {row['descricao']} — {m_fmt(row['valor'])} (Data: {dt_item.strftime('%d/%m/%Y') if pd.notna(dt_item) else 'N/A'})"):
                    st.write(f"**Categoria:** {row['categoria']} | **Detalhes/Contato:** {row['detalhes'] or 'N/A'}")
                    
                    # Gerador automático de mensagem para cobrar no WhatsApp
                    msg_wpp = urllib.parse.quote(f"Olá! Tudo bem? Passando para lembrar do nosso combinado referente a '{row['descricao']}' no valor de {m_fmt(row['valor'])} com previsão para {dt_item.strftime('%d/%m/%Y') if pd.notna(dt_item) else 'hoje'}. Consegue me confirmar quando fizer o envio?")
                    num_limpo = "".join([c for c in str(row['detalhes'] or "") if c.isdigit()])
                    link_wpp = f"https://wa.me/55{num_limpo}?text={msg_wpp}" if len(num_limpo) >= 10 else f"https://wa.me/?text={msg_wpp}"
                    st.markdown(f"📲 **[Clique aqui para enviar lembrete de cobrança no WhatsApp]({link_wpp})**")
                    
                    cb1, cb2, cb3 = st.columns(3)
                    if row['status'] == 'Pendente':
                        if cb1.button("✅ Confirmar Recebimento (Pago)", key=f"rec_pay_{row['id']}", type="primary"):
                            executar_query("UPDATE transacoes SET status = 'Pago' WHERE id = ?", (int(row['id']),))
                            st.success("Recebimento confirmado e somado ao seu caixa!")
                            st.rerun()
                    else:
                        if cb1.button("↩️ Voltar para Pendente", key=f"rec_pend_{row['id']}"):
                            executar_query("UPDATE transacoes SET status = 'Pendente' WHERE id = ?", (int(row['id']),))
                            st.rerun()
                            
                    if cb3.button("🗑️ Excluir Registro", key=f"rec_del_{row['id']}"):
                        executar_query("DELETE FROM transacoes WHERE id = ?", (int(row['id']),))
                        st.rerun()
        else:
            st.info("Nenhum recebimento encontrado para este filtro.")
    else:
        st.info("Você ainda não cadastrou nenhuma previsão de recebimento. Use o formulário acima para começar!")

# =====================================================================
# TAB 3 (tabs[2]): OPERAÇÕES, BAIXA RÁPIDA DE DESPESAS E CARTÕES
# =====================================================================
with tabs[2]:
    op_menu = st.radio("Selecione o Painel Operacional:", ["Registrar Despesa / Transação", "✅ Dar Baixa nas Contas do Mês", "Auditoria de Cartões", "🛒 Wishlist (Planejador)"], horizontal=True)
    
    if op_menu == "Registrar Despesa / Transação":
        with st.form("form_lanc", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            tipo = c1.radio("Fluxo", ["Despesa", "Receita"], horizontal=True)
            valor = c2.number_input("Valor Total", min_value=0.0, format="%.2f")
            forma = c3.selectbox("Método de Pagamento", ["PIX", "Cartão de Crédito", "Débito", "Dinheiro", "Boleto"])
            
            c4, c5, c6 = st.columns(3)
            descricao = c4.text_input("Descrição do Lançamento")
            categoria = c5.selectbox("Categoria", ["Moradia", "Alimentação", "Transporte", "Dieta/Treino", "Educação", "Saúde", "Eletrônicos", "Entretenimento", "Lazer", "Investimento", "Cartão", "Outros"])
            parcelas = c6.number_input("Nº Parcelas", min_value=1, value=1)
            
            cartao_selecionado = st.selectbox("Se for crédito, selecione qual o cartão correspondente:", ["N/A"] + cartoes_banco)
            cartao_envio = None if cartao_selecionado == "N/A" else cartao_selecionado
                
            c7, c8 = st.columns(2)
            data = c7.date_input("Vencimento da 1ª Parcela", value=hoje_data)
            status = c8.selectbox("Status de Liquidação", ["Pendente", "Pago"])
            
            if st.form_submit_button("Gravar no Banco", type="primary"):
                if valor > 0 and descricao:
                    val_parc = valor / parcelas
                    for i in range(parcelas):
                        d_venc = data + relativedelta(months=i)
                        detalhe_txt = f"{forma} | Parcela {i+1}/{parcelas}" if parcelas > 1 else forma
                        cartao_final = cartao_envio or detectar_cartao(descricao)
                        executar_query("INSERT INTO transacoes (tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?)",
                                       (tipo, descricao.strip(), categoria, val_parc, d_venc, detalhe_txt, status, st.session_state.perfil_ativo, cartao_final))
                    st.success("Transação gravada com sucesso!")
                    st.rerun()

    elif op_menu == "✅ Dar Baixa nas Contas do Mês":
        st.subheader(f"Controle de Pagamentos de {hoje.strftime('%m/%Y')}")
        st.write("Marque rapidamente as despesas do mês que você já pagou para manter seu saldo 100% atualizado:")
        if not df_mes.empty:
            df_desp_mes = df_mes[df_mes['tipo'] == 'Despesa'].sort_values(['status', 'data_competencia_dt'])
            for _, r in df_desp_mes.iterrows():
                col_b1, col_b2, col_b3, col_b4 = st.columns([3, 2, 2, 2])
                cor_st = "🟢 Pago" if r['status'] == 'Pago' else "🔴 Pendente"
                col_b1.write(f"**{r['descricao']}** ({r['categoria']})")
                col_b2.write(f"Venc: {r['data_apenas'].strftime('%d/%m/%Y') if pd.notna(r['data_apenas']) else 'N/A'}")
                col_b3.write(f"**{m_fmt(r['valor'])}** — {cor_st}")
                if r['status'] == 'Pendente':
                    if col_b4.button("✅ Marcar Pago", key=f"pay_desp_{r['id']}"):
                        executar_query("UPDATE transacoes SET status = 'Pago' WHERE id = ?", (int(r['id']),))
                        st.rerun()
                else:
                    if col_b4.button("↩️ Reabrir", key=f"reopen_desp_{r['id']}"):
                        executar_query("UPDATE transacoes SET status = 'Pendente' WHERE id = ?", (int(r['id']),))
                        st.rerun()
        else:
            st.info("Nenhuma despesa registrada para o mês atual.")

    elif op_menu == "Auditoria de Cartões":
        st.subheader("Faturas Mapeadas por Cartão de Crédito")
        df_cartoes = df_trans[(df_trans['cartao_vinculado'].notnull()) & (df_trans['cartao_vinculado'] != 'None')].copy() if not df_trans.empty else pd.DataFrame()
        
        if not df_cartoes.empty:
            df_cartoes['Mês de Vencimento'] = df_cartoes['data_competencia_dt'].dt.strftime('%m/%Y')
            resumo_c = df_cartoes[df_cartoes['status'] == 'Pendente'].groupby(['cartao_vinculado', 'Mês de Vencimento'])['valor'].sum().reset_index()
            resumo_c['Total da Fatura'] = resumo_c['valor'].apply(m_fmt)
            
            st.write("**Resumo Geral de Faturas Abertas:**")
            st.dataframe(resumo_c[['cartao_vinculado', 'Mês de Vencimento', 'Total da Fatura']], use_container_width=True)
            
            st.write("**Extrato Detalhado do Cartão Selecionado:**")
            filtro_c = st.selectbox("Filtrar por Cartão:", cartoes_banco)
            df_f = df_cartoes[df_cartoes['cartao_vinculado'] == filtro_c].sort_values('data_competencia_dt')
            if not df_f.empty:
                df_f['Valor Formatado'] = df_f['valor'].apply(m_fmt)
                st.dataframe(df_f[['data_competencia', 'descricao', 'Valor Formatado', 'status']], use_container_width=True)
        else:
            st.info("Nenhuma despesa vinculada a cartões identificada no momento.")

    elif op_menu == "🛒 Wishlist (Planejador)":
        st.subheader("Wishlist Avançada")
        c_w1, c_w2 = st.columns(2)
        w_item = c_w1.text_input("Item Desejado (Ex: Equipamento, Viagem)")
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
# TAB 4 (tabs[3]): INVESTIMENTOS
# =====================================================================
with tabs[3]:
    st.header("💼 Carteira e Custódia de Ativos")
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
# TAB 5 (tabs[4]): CONSULTOR IA & PROJEÇÃO DE CONTAS FUTURAS (COM RECEBÍVEIS)
# =====================================================================
with tabs[4]:
    st.header("🤖 Consultor de IA & Mapa de Contas Futuras")
    st.write("Esta visão cruza automaticamente todas as suas **Despesas Pendentes** com as suas **Previsões de Recebimentos** nos próximos meses:")
    
    meses_frente = st.slider("Mapear faturas e recebimentos de quantos meses à frente?", 1, 12, 6)
    
    lista_meses = [(hoje + relativedelta(months=i)).strftime('%m/%Y') for i in range(meses_frente)]
    df_base = pd.DataFrame({'Mês Referência': lista_meses})
    
    inicio_mes_atual = datetime(hoje.year, hoje.month, 1)
    data_limite = hoje + relativedelta(months=meses_frente)
    
    if not df_trans.empty:
        # Filtra Despesas Pendentes e Receitas Pendentes/Pagas para o futuro
        df_fut_desp = df_trans[(df_trans['tipo'] == 'Despesa') & (df_trans['status'] == 'Pendente') & (df_trans['data_competencia_dt'] >= inicio_mes_atual) & (df_trans['data_competencia_dt'] <= data_limite)].copy()
        df_fut_rec_pend = df_trans[(df_trans['tipo'] == 'Receita') & (df_trans['status'] == 'Pendente') & (df_trans['data_competencia_dt'] >= inicio_mes_atual) & (df_trans['data_competencia_dt'] <= data_limite)].copy()
        df_fut_rec_pago = df_trans[(df_trans['tipo'] == 'Receita') & (df_trans['status'] == 'Pago') & (df_trans['data_competencia_dt'] >= inicio_mes_atual) & (df_trans['data_competencia_dt'] <= data_limite)].copy()

        total_passivo = df_fut_desp['valor'].sum() if not df_fut_desp.empty else 0.0
        total_receber_fut = df_fut_rec_pend['valor'].sum() if not df_fut_rec_pend.empty else 0.0
        
        cf1, cf2, cf3 = st.columns(3)
        cf1.metric(f"🚨 Contas a Pagar ({meses_frente} meses)", m_fmt(total_passivo))
        cf2.metric(f"💰 Previsão a Receber de Terceiros ({meses_frente} meses)", m_fmt(total_receber_fut))
        cf3.metric("⚖️ Passivo Líquido (Abatendo Recebíveis)", m_fmt(max(0.0, total_passivo - total_receber_fut)))

        if not df_fut_desp.empty:
            df_fut_desp['Mês Referência'] = df_fut_desp['data_competencia_dt'].dt.strftime('%m/%Y')
            res_desp = df_fut_desp.groupby('Mês Referência')['valor'].sum().reset_index().rename(columns={'valor': 'despesa_pendente'})
        else:
            res_desp = pd.DataFrame(columns=['Mês Referência', 'despesa_pendente'])

        if not df_fut_rec_pend.empty:
            df_fut_rec_pend['Mês Referência'] = df_fut_rec_pend['data_competencia_dt'].dt.strftime('%m/%Y')
            res_rec_p = df_fut_rec_pend.groupby('Mês Referência')['valor'].sum().reset_index().rename(columns={'valor': 'a_receber'})
        else:
            res_rec_p = pd.DataFrame(columns=['Mês Referência', 'a_receber'])

        if not df_fut_rec_pago.empty:
            df_fut_rec_pago['Mês Referência'] = df_fut_rec_pago['data_competencia_dt'].dt.strftime('%m/%Y')
            res_rec_ok = df_fut_rec_pago.groupby('Mês Referência')['valor'].sum().reset_index().rename(columns={'valor': 'ja_recebido'})
        else:
            res_rec_ok = pd.DataFrame(columns=['Mês Referência', 'ja_recebido'])

        df_final = pd.merge(df_base, res_desp, on='Mês Referência', how='left')
        df_final = pd.merge(df_final, res_rec_p, on='Mês Referência', how='left')
        df_final = pd.merge(df_final, res_rec_ok, on='Mês Referência', how='left').fillna(0)
        
        df_final['saldo_projetado'] = (renda_real_declarada + df_final['ja_recebido'] + df_final['a_receber']) - df_final['despesa_pendente']
        
        df_final['Contas a Pagar (Pendentes)'] = df_final['despesa_pendente'].apply(m_fmt)
        df_final['A Receber (Pendente)'] = df_final['a_receber'].apply(m_fmt)
        df_final['Extras Já Recebidos'] = df_final['ja_recebido'].apply(m_fmt)
        df_final['Sobra Projetada (c/ Renda Base)'] = df_final['saldo_projetado'].apply(m_fmt)
        
        st.table(df_final[['Mês Referência', 'Contas a Pagar (Pendentes)', 'A Receber (Pendente)', 'Extras Já Recebidos', 'Sobra Projetada (c/ Renda Base)']])
    else:
        st.success("✅ Nenhuma pendência mapeada no banco de dados.")
            
    st.markdown("---")
    st.subheader("Consultar Registros por Mês")
    pergunta = st.text_input("Escreva (Ex: 'resumo' ou digite o nome de um mês por extenso em português):")
    if st.button("Mapear Tabela"):
        p = pergunta.lower()
        mes_detectado = next((mes for mes in meses_pt if mes in p), None)
        if mes_detectado:
            num_mes = meses_pt[mes_detectado]
            if not df_trans.empty:
                df_m = df_trans[(df_trans['data_competencia_dt'].dt.month == num_mes) & (df_trans['data_competencia_dt'].dt.year == hoje.year)]
                desp_m = df_m[df_m['tipo'] == 'Despesa']['valor'].sum()
                pend_m = df_m[(df_m['tipo'] == 'Despesa') & (df_m['status'] == 'Pendente')]['valor'].sum()
                rec_m = df_m[(df_m['tipo'] == 'Receita') & (df_m['status'] == 'Pendente')]['valor'].sum()
                st.info(f"📊 Relatório de {mes_detectado.capitalize()}/{hoje.year}:\n- Total de saídas: **{m_fmt(desp_m)}** (Sendo **{m_fmt(pend_m)}** pendentes).\n- Previsão a receber de terceiros no mês: **{m_fmt(rec_m)}**.")
            else: st.warning("O banco de dados está vazio.")
        elif "resumo" in p: st.info(f"O seu Saldo Disponível hoje é de **{m_fmt(saldo_livre_atual)}** e o Saldo Projetado (com recebíveis) é de **{m_fmt(saldo_projetado_mes)}**.")

# =====================================================================
# TAB 6 (tabs[5]): SIMULADORES
# =====================================================================
with tabs[5]:
    st.header("🔮 Simuladores: Arquitetura de Vida e Orçamento")
    sim = st.selectbox("Escolha a Ferramenta de Planejamento:", ["Orçamento Inteligente Base-Zero", "Independência Financeira (F.I.R.E)", "Financiamentos (Tabela Price)"])

    if sim == "Orçamento Inteligente Base-Zero":
        st.write(f"Sua receita de exibição base é de **{m_fmt(renda_real_declarada)}**. Distribua esse valor fatiando os percentuais abaixo (A soma deve fechar em 100%).")
        col_s1, col_s2 = st.columns(2)
        p_moradia = col_s1.slider("🏠 Casa, Contas de Consumo e Família", 0, 100, 30)
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
            s_c1.metric("Aporte Elite Beach", m_fmt(renda_real_declarada * (p_projeto/100)))
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
# TAB 7 (tabs[6]): VISÃO 3D E MERCADO
# =====================================================================
with tabs[6]:
    st.header("💎 Visão Global de Mercado")
    st.subheader("Superfície 3D: A Montanha dos Juros Compostos")
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
# TAB 8 (tabs[7]): ADMIN, BACKUP E SINCRONIZAÇÃO BLINDADA
# =====================================================================
with tabs[7]:
    st.header("⚙️ Banco de Dados & Sincronização Blindada")
    
    df_tudo = get_df("SELECT * FROM transacoes ORDER BY data_competencia DESC")
    
    # 1. BACKUP EM 1 CLIQUE
    st.subheader("🛡️ 1. Backup de Segurança Instantâneo")
    if not df_tudo.empty:
        csv_backup = df_tudo.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 Baixar Backup Completo (.CSV) de Todos os Dados",
            data=csv_backup,
            file_name=f"backup_financeiro_{hoje.strftime('%Y_%m_%d')}.csv",
            mime="text/csv"
        )
    
    st.markdown("---")
    # 2. IMPORTADOR BLINDADO DO DESPESAS.DB
    st.subheader("🔄 2. Importar Arquivo `Despesas.db`")
    modo_import = st.radio(
        "Modo de Proteção ao Importar:",
        [
            "🛡️ Atualizar Despesas preservando minhas Receitas/Cobranças cadastradas (Recomendado)",
            "⚠️ Substituir ABSOLUTAMENTE TUDO (Apaga inclusive Receitas)"
        ]
    )
    preservar_rec = "preservando" in modo_import
    
    arquivo_db = st.file_uploader("Selecione o arquivo Despesas.db ou financeiro_master.db", type=["db", "sqlite", "sqlite3"])
    
    if arquivo_db is not None:
        if st.button("🚀 Executar Sincronização do Arquivo .DB", type="primary"):
            with st.spinner("Sincronizando registros no Supabase..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp.write(arquivo_db.read())
                    caminho_tmp = tmp.name
                try:
                    total_importado = importar_arquivo_sqlite(caminho_tmp, st.session_state.perfil_ativo, preservar_manuais=preservar_rec)
                    st.success(f"✅ Sucesso! {total_importado} registros sincronizados na nuvem.")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao importar o arquivo: {e}")
                finally:
                    if os.path.exists(caminho_tmp):
                        os.remove(caminho_tmp)
                        
    st.markdown("---")
    st.subheader("📋 3. Registros Atuais no Banco de Dados")
    if not df_tudo.empty: 
        df_tudo['valor_formatado'] = df_tudo['valor'].apply(m_fmt)
        colunas_exibicao = [col for col in ['id', 'tipo', 'descricao', 'categoria', 'valor_formatado', 'data_competencia', 'status', 'cartao_vinculado'] if col in df_tudo.columns]
        st.dataframe(df_tudo[colunas_exibicao], use_container_width=True)
        
        st.markdown("#### 🔧 Alterar ou Excluir Registro Específico pelo ID")
        ca_id, ca_st, ca_bt1, ca_bt2 = st.columns([2, 2, 2, 2])
        id_sel = ca_id.selectbox("Selecione o ID:", df_tudo['id'].tolist())
        novo_st = ca_st.selectbox("Novo Status:", ["Pago", "Pendente"])
        if ca_bt1.button("💾 Atualizar Status"):
            executar_query("UPDATE transacoes SET status = ? WHERE id = ?", (novo_st, int(id_sel)))
            st.success(f"ID {id_sel} atualizado para {novo_st}!")
            st.rerun()
        if ca_bt2.button("🗑️ Excluir Este ID"):
            executar_query("DELETE FROM transacoes WHERE id = ?", (int(id_sel),))
            st.warning(f"ID {id_sel} removido!")
            st.rerun()
    else: 
        st.warning("O banco de dados está vazio.")