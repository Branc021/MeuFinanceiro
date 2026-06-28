import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import yfinance as yf
import feedparser
import io

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
    .bet-box {{ border-left: 5px solid #ff9800; background-color: #1a1a2e; padding: 20px; border-radius: 10px; margin-top:10px; }}
    h1, h2, h3 {{ color: #F3F4F6; }}
    </style>
""", unsafe_allow_html=True)

def m_fmt(valor):
    """Formatador de Moeda para o padrão monetário real brasileiro brasileiro (R$ 1.000,00)"""
    if pd.isna(valor): return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

DB_NAME = "financeiro_master.db"
cartoes_banco = ["NUBANK", "PICPAY", "INTER", "MERCADO PAGO", "WILL", "BRADESCO", "RENNER", "OUTRO"]

# =====================================================================
# 2. CAMADA DE DADOS E CONEXÕES
# =====================================================================
def get_connection(): return sqlite3.connect(DB_NAME)
def executar_query(query, params=()):
    conn = get_connection(); cursor = conn.cursor(); cursor.execute(query, params); conn.commit(); conn.close()
def get_df(query, params=()):
    conn = get_connection(); df = pd.read_sql(query, conn, params=params); conn.close(); return df

def init_db():
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT, descricao TEXT, categoria TEXT, valor REAL, data_competencia DATE, detalhes TEXT, status TEXT DEFAULT 'Pendente', centro_custo TEXT DEFAULT 'Pessoal', cartao_vinculado TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS compras_futuras (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT, valor REAL, prioridade TEXT, status TEXT DEFAULT 'Planejado', centro_custo TEXT, metodo TEXT, parcelas INTEGER, cartao_vinculado TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS diario_apostas (id INTEGER PRIMARY KEY AUTOINCREMENT, data DATE, esporte TEXT, mercado TEXT, odd REAL, stake REAL, resultado TEXT, lucro REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bancas_apostas (id INTEGER PRIMARY KEY AUTOINCREMENT, casa TEXT, saldo REAL)''')
    
    try: cursor.execute("ALTER TABLE transacoes ADD COLUMN cartao_vinculado TEXT")
    except: pass
    try: cursor.execute("ALTER TABLE compras_futuras ADD COLUMN metodo TEXT DEFAULT 'PIX'")
    except: pass
    try: cursor.execute("ALTER TABLE compras_futuras ADD COLUMN parcelas INTEGER DEFAULT 1")
    except: pass
    try: cursor.execute("ALTER TABLE compras_futuras ADD COLUMN cartao_vinculado TEXT")
    except: pass
    
    conn.commit(); conn.close()

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
# 5. FILTRAGEM GLOBAL DE DADOS
# =====================================================================
st.title(f"⚡ Core Finance PRO | {st.session_state.perfil_ativo}")
tabs = st.tabs(["📊 Dashboard", "💳 Operações & Cartões", "💼 Carteira", "⚽ Apostas Profissionais", "🤖 Consultor IA", "🔮 Simuladores", "💎 Radar 3D", "⚙️ Admin"])

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
# TAB 1: DASHBOARD
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
# TAB 2: OPERAÇÕES, VENCIMENTOS E CARTÕES
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
            categoria = c5.selectbox("Categoria", ["Moradia", "Alimentação", "Transporte", "Dieta/Treino", "Lazer", "Investimento", "Banca de Apostas", "Cartão", "Outros"])
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
# TAB 3: INVESTIMENTOS
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
# TAB 4: TRADER ESPORTIVO
# =====================================================================
with tabs[3]:
    st.header("⚽ Gestão de Banca e Apostas Profissionais")
    bet_menu = st.radio("Selecione a Ferramenta Esportiva:", ["Diário de Apostas", "Calculadora EV+", "Critério de Kelly", "Alavancagem"], horizontal=True)
    
    if bet_menu == "Diário de Apostas":
        st.subheader("🏦 Controle de Saldo por Casa de Apostas", help="Acompanhe o saldo real que você possui depositado em cada site.")
        with st.form("banca_form"):
            b1, b2 = st.columns(2)
            nome_casa = b1.text_input("Casa de Apostas (Ex: Betfair, Betano)")
            saldo_casa = b2.number_input("Saldo Disponível (R$)", min_value=0.0)
            if st.form_submit_button("Salvar Saldo"):
                executar_query("INSERT INTO bancas_apostas (casa, saldo) VALUES (?,?)", (nome_casa, saldo_casa))
                st.rerun()
        
        df_bancas = get_df("SELECT * FROM bancas_apostas")
        if not df_bancas.empty:
            df_bancas['Saldo Formatado'] = df_bancas['saldo'].apply(m_fmt)
            st.dataframe(df_bancas[['casa', 'Saldo Formatado']], use_container_width=True)
            if st.button("Zerar Contas"):
                executar_query("DELETE FROM bancas_apostas")
                st.rerun()

        st.markdown("---")
        st.subheader("📝 Registrar Nova Entrada")
        with st.form("form_bet"):
            bc1, bc2, bc3 = st.columns(3)
            esporte = bc1.selectbox("Esporte", ["Futebol (Série A/Ligas)", "NBA", "Tênis", "NFL"])
            mercado = bc2.text_input("Mercado Selecionado (Ex: Ambas Marcam)")
            odd = bc3.number_input("Odd Fechada", min_value=1.01, value=1.80, format="%.2f")
            
            bc4, bc5 = st.columns(2)
            stake = bc4.number_input("Stake Utilizada (R$)", min_value=0.0, value=10.0)
            resultado = bc5.selectbox("Resultado", ["Pendente", "Green ✅", "Red ❌", "Reembolso 🔄"])
            if st.form_submit_button("Registrar Bilhete"):
                lucro = (stake * odd) - stake if "Green" in resultado else -stake if "Red" in resultado else 0
                if resultado == "Pendente": lucro = 0
                executar_query("INSERT INTO diario_apostas (data, esporte, mercado, odd, stake, resultado, lucro) VALUES (?,?,?,?,?,?,?)", (hoje, esporte, mercado, odd, stake, resultado, lucro))
                st.rerun()
                
        df_bets = get_df("SELECT * FROM diario_apostas ORDER BY id DESC")
        if not df_bets.empty:
            df_resolvidos = df_bets[df_bets['resultado'] != "Pendente"]
            lucro_total = df_resolvidos['lucro'].sum()
            roi = (lucro_total / df_resolvidos['stake'].sum() * 100) if df_resolvidos['stake'].sum() > 0 else 0
            st.metric("P&L Acumulado (Lucro/Prejuízo)", m_fmt(lucro_total), f"ROI Geral: {roi:.2f}%")
            
            st.write("**Atualizar Status de Bilhete:**")
            edit_id = st.selectbox("ID do Bilhete Pendente:", df_bets[df_bets['resultado'] == 'Pendente']['id'].tolist() if not df_bets[df_bets['resultado'] == 'Pendente'].empty else ["Nenhum pendente"])
            if edit_id != "Nenhum pendente":
                edit_status = st.selectbox("Alterar Status:", ["Green ✅", "Red ❌", "Reembolso 🔄"])
                if st.button("Liquidar Bilhete"):
                    row_bet = df_bets[df_bets['id'] == edit_id].iloc[0]
                    n_lucro = (row_bet['stake'] * row_bet['odd']) - row_bet['stake'] if "Green" in edit_status else -row_bet['stake'] if "Red" in edit_status else 0
                    executar_query("UPDATE diario_apostas SET resultado = ?, lucro = ? WHERE id = ?", (edit_status, n_lucro, edit_id))
                    st.rerun()
                    
            df_display = df_bets.copy()
            df_display['stake'] = df_display['stake'].apply(m_fmt)
            df_display['lucro'] = df_display['lucro'].apply(m_fmt)
            st.dataframe(df_display, use_container_width=True)

    elif bet_menu == "Calculadora EV+":
        st.subheader("Expected Value (+EV) — Valor Esperado Positivo", help="O EV+ calcula se a precificação da casa de apostas te dá lucro estatístico a longo prazo.")
        odd_casa = st.number_input("Odd Oferecida pela Casa de Apostas", value=2.10, step=0.01)
        prob_real = st.slider("Qual a sua Probabilidade Estatística de Acerto? (%)", 1, 100, 55)
        
        ev = ((prob_real / 100) * odd_casa) - 1
        if ev > 0:
            st.success(f"✅ **APOSTA DE VALOR (+EV) DETECTADA!**\n\nVantagem matemática real de **{(ev*100):.2f}%** sobre a casa de apostas.")
        else:
            st.error(f"❌ **APOSTA SEM VALOR VALOR (-EV)**\n\nDesvantagem estatística de **{(ev*100):.2f}%**. Aborte a operação.")

    elif bet_menu == "Critério de Kelly":
        st.subheader("Equação de Kelly (Gerenciamento de Risco)", help="Mecanismo matemático que dita o tamanho exato da sua aposta com base na sua banca para evitar quebras por sequências de perdas.")
        ck1, ck2, ck3 = st.columns(3)
        banca_total = ck1.number_input("Banca Consolidada (R$)", value=1000.0)
        odd_kelly = ck2.number_input("Odd da Linha", value=1.90)
        prob_kelly = ck3.slider("Sua Probabilidade Real de Acerto (%)", 1, 100, 60)
        
        b = odd_kelly - 1; p = prob_kelly / 100; q = 1 - p
        f_star = ((b * p) - q) / b
        if f_star > 0: 
            st.markdown(f"<div class='bet-box'>🛡️ **Stake Exata Recomendada:** **{m_fmt(banca_total * f_star)}** ({f_star*100:.1f}% do caixa).</div>", unsafe_allow_html=True)
        else: 
            st.error("Risco acentuado. Stake recomendada: R$ 0,00.")
        
    elif bet_menu == "Alavancagem":
        st.subheader("Projeto de Alavancagem Exponencial")
        cs1, cs2, cs3 = st.columns(3)
        banca_inicial = cs1.number_input("Banca Inicial Operada (R$)", value=100.0)
        odd_media_diaria = cs2.number_input("Odd Alvo Diária", value=1.25, step=0.01)
        dias_acerto = cs3.slider("Ciclos Consecutivos em Green", 1, 60, 15)
        
        banca_final = banca_inicial * (odd_media_diaria ** dias_acerto)
        st.success(f"🚀 **Potencial da Alavancagem Coberta:** {m_fmt(banca_inicial)} transformam-se em **{m_fmt(banca_final)}** após {dias_acerto} dias.")

# =====================================================================
# TAB 5: INTELIGÊNCIA IA & SOMAS EXATAS
# =====================================================================
with tabs[4]:
    st.header("🤖 Consultor de IA e Mapa de Dívidas", help="Audita faturas futuras e parcelamentos agregados.")
    
    st.subheader("Radar de Passivos e Dívidas Futuras")
    meses_frente = st.slider("Mapear faturas acumuladas de quantos meses à frente?", 1, 12, 3)
    data_limite = hoje + relativedelta(months=meses_frente)
    
    if not df_trans.empty:
        df_dividas = df_trans[(df_trans['tipo'] == 'Despesa') & (df_trans['status'] == 'Pendente') & (df_trans['data_competencia'] >= hoje) & (df_trans['data_competencia'] <= data_limite)].copy()
        if not df_dividas.empty:
            st.error(f"🚨 **Passivo de Médio Prazo:** {m_fmt(df_dividas['valor'].sum())} acumulados nos próximos {meses_frente} meses.")
            df_dividas['Mês Referência'] = df_dividas['data_competencia'].dt.strftime('%m/%Y')
            resumo_dividas = df_dividas.groupby('Mês Referência')['valor'].sum().reset_index().sort_values('Mês Referência')
            resumo_dividas['Soma do Mês'] = resumo_dividas['valor'].apply(m_fmt)
            st.table(resumo_dividas[['Mês Referência', 'Soma do Mês']])
        else:
            st.success("✅ Nenhuma pendência futura mapeada para o período.")
            
    st.markdown("---")
    st.subheader("Consultar Registros")
    pergunta = st.text_input("Escreva (Ex: 'resumo' ou digite o nome de um mês por extenso em português):")
    if st.button("Mapear Tabela"):
        p = pergunta.lower()
        mes_detectado = next((mes for mes in meses_pt if mes in p), None)
        if mes_detectado:
            num_mes = meses_pt[mes_detectado]
            if not df_trans.empty:
                # CORREÇÃO CRÍTICA DO MOTOR DE SOMA DA IA
                df_m = df_trans[(df_trans['data_competencia'].dt.month == num_mes) & (df_trans['data_competencia'].dt.year == hoje.year) & (df_trans['tipo'] == 'Despesa')]
                st.info(f"📊 Relatório de {mes_detectado.capitalize()}/{hoje.year}:\n- O total de saídas no mês é **{m_fmt(df_m['valor'].sum())}**.\n- Deste montante, **{m_fmt(df_m[df_m['status'] == 'Pendente']['valor'].sum())}** constam como Pendentes.")
            else: st.warning("O banco de dados está vazio.")
        elif "resumo" in p: st.info(f"O seu Saldo Livre atual é de **{m_fmt(saldo_livre)}**.")

# =====================================================================
# TAB 6: ORÇAMENTO COMPLETO, F.I.R.E. E PRICE
# =====================================================================
with tabs[5]:
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
# TAB 7: VISÃO 3D E MERCADO
# =====================================================================
with tabs[6]:
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
# TAB 8: ADMIN (CORREÇÃO DE ÍNDICE CRÍTICO)
# =====================================================================
with tabs[7]:
    st.header("⚙️ Banco de Dados (Root Access)")
    df_tudo = get_df("SELECT * FROM transacoes ORDER BY data_competencia DESC")
    if not df_tudo.empty: 
        # CORREÇÃO INTEGRAL: Seleciona apenas as colunas que efetivamente existem dinamicamente
        df_tudo['valor_formatado'] = df_tudo['valor'].apply(m_fmt)
        colunas_exibicao = [col for col in ['id', 'tipo', 'descricao', 'categoria', 'valor_formatado', 'data_competencia', 'status', 'cartao_vinculado'] if col in df_tudo.columns]
        st.dataframe(df_tudo[colunas_exibicao], use_container_width=True)
        
        if st.button("Limpar Banco Consolidado 🗑️", help="Exclui todas as transações permanentemente de forma irreversível."):
            executar_query("DELETE FROM transacoes")
            st.rerun()
    else: 
        st.warning("O banco de dados está vazio. Registre transações para visualizar o Grid.")