"""
=============================================================================
PROJETO: Core Finance PRO | Enterprise Commercial Edition
DESCRIÇÃO: Plataforma Cloud Multi-Usuário de Gestão Financeira, Poupança,
           Investimentos, Cotações Diárias (Selic/CDI/B3) e Google Gemini IA.
ARQUITETURA: Isolamento por Usuário + Hierarquia Admin (Dono) / PRO / FREE.
=============================================================================
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import yfinance as yf
import psycopg2
from psycopg2.extras import execute_batch
import sqlite3
import tempfile
import urllib.parse
import urllib.request
import json
import hashlib
import hmac
import os
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# =====================================================================
# 1. CONFIGURAÇÃO DA PÁGINA E DESIGN SYSTEM (GLASSMORPHISM)
# =====================================================================
st.set_page_config(
    page_title="Core Finance PRO | Multi-User Cloud",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="expanded"
)

if 'perfil_ativo' not in st.session_state:
    st.session_state.perfil_ativo = 'Pessoal'
if 'usuario_logado' not in st.session_state:
    st.session_state.usuario_logado = None

cor_primaria = "#0f3460" if st.session_state.perfil_ativo == 'Pessoal' else "#e94560"
cor_destaque = "#4facf7" if st.session_state.perfil_ativo == 'Pessoal' else "#ff9800"
cor_secundaria = "#16213e" if st.session_state.perfil_ativo == 'Pessoal' else "#1a1a2e"

st.markdown(f"""
    <style>
    .metric-card {{
        background: linear-gradient(145deg, {cor_secundaria}, #0f172a);
        padding: 20px;
        border-radius: 16px;
        border-left: 5px solid {cor_destaque};
        box-shadow: 0 8px 20px rgba(0,0,0,0.4);
        transition: transform 0.25s ease;
        margin-bottom: 14px;
    }}
    .metric-card:hover {{ transform: translateY(-3px); }}
    .cofrinho-card {{
        background: rgba(30, 41, 59, 0.75);
        border: 1px solid rgba(255,255,255,0.08);
        border-left: 5px solid #4caf50;
        padding: 18px;
        border-radius: 14px;
        margin-bottom: 12px;
    }}
    .admin-badge {{
        background: linear-gradient(90deg, #f59e0b, #d97706);
        color: #0f172a;
        padding: 6px 12px;
        border-radius: 8px;
        font-weight: 800;
        font-size: 0.85rem;
        display: inline-block;
        margin-bottom: 8px;
    }}
    .alert-card-red {{ background: rgba(233, 69, 96, 0.15); border-left: 5px solid #e94560; padding: 14px; border-radius: 10px; margin-bottom: 8px; }}
    .alert-card-yellow {{ background: rgba(255, 152, 0, 0.15); border-left: 5px solid #ff9800; padding: 14px; border-radius: 10px; margin-bottom: 8px; }}
    .alert-card-green {{ background: rgba(76, 175, 80, 0.15); border-left: 5px solid #4caf50; padding: 14px; border-radius: 10px; margin-bottom: 8px; }}
    .ai-response-box {{
        background: linear-gradient(135deg, rgba(15, 52, 96, 0.6), rgba(17, 24, 39, 0.9));
        border: 1px solid rgba(79, 172, 247, 0.35);
        border-left: 6px solid #4facf7;
        padding: 20px;
        border-radius: 14px;
        margin-top: 12px;
    }}
    h1, h2, h3 {{ color: #F8FAFC; }}
    </style>
""", unsafe_allow_html=True)

def m_fmt(valor):
    """Formata valores numéricos para o padrão monetário brasileiro (R$ 1.234,56)"""
    if pd.isna(valor) or valor is None:
        return "R$ 0,00"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

cartoes_banco = ["NUBANK", "PICPAY", "INTER", "MERCADO PAGO", "WILL", "BRADESCO", "RENNER", "OUTRO"]
EMAILS_ADMIN_PADRAO = ["evandrosps2013@gmail.com", "pereira.evandro@tjrj.jus.br"]

def detectar_cartao(descricao):
    """Identifica automaticamente o cartão vinculado com base no texto da descrição"""
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
# 2. SEGURANÇA, CRIPTOGRAFIA HÍBRIDA E CAMADA DE DADOS (SUPABASE)
# =====================================================================
def gerar_hash_senha(senha: str) -> str:
    """Gera hash PBKDF2-SHA256 com salt aleatório de 16 bytes e 100.000 iterações"""
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${dk.hex()}"

def verificar_senha(senha_digitada: str, hash_salvo: str, senha_legada: str = None) -> tuple:
    """
    Verifica a senha digitada.
    Retorna (autenticado: bool, precisa_atualizar_hash: bool).
    Aceita tanto o formato criptografado (salt$hash) quanto senhas antigas em texto puro
    no Supabase (ex.: 'Barcelona12*' ou '1234'), convertendo-as automaticamente no login.
    """
    if not senha_digitada:
        return False, False
    hash_str = str(hash_salvo or "").strip()
    if "$" in hash_str:
        try:
            salt, hex_hash = hash_str.split('$', 1)
            dk = hashlib.pbkdf2_hmac('sha256', senha_digitada.encode('utf-8'), salt.encode('utf-8'), 100000)
            if hmac.compare_digest(dk.hex(), hex_hash):
                return True, False
        except Exception:
            pass
    # Fallback para senha cadastrada manualmente no banco sem hash
    if hash_str and senha_digitada == hash_str:
        return True, True
    if senha_legada and senha_digitada == str(senha_legada).strip():
        return True, True
    return False, False

def obter_chave_gemini_secrets():
    """Busca a chave da API Gemini tanto na raiz do secrets.toml quanto dentro do bloco [connections.postgresql]"""
    try:
        k = st.secrets.get("GEMINI_API_KEY", None)
        if k and len(str(k).strip()) > 10:
            return str(k).strip()
        k_nested = st.secrets.get("connections", {}).get("postgresql", {}).get("GEMINI_API_KEY", None)
        if k_nested and len(str(k_nested).strip()) > 10:
            return str(k_nested).strip()
    except Exception:
        pass
    return None

def get_connection():
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
        st.cache_data.clear()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

@st.cache_data(ttl=300, show_spinner=False)
def get_df(query, params=()):
    """Leitura em cache por 5 minutos para máxima fluidez (limpo automaticamente ao gravar dados)"""
    conn = get_connection()
    try:
        query = query.replace("?", "%s")
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            df = pd.read_sql(query, conn, params=params)
        return df
    finally:
        conn.close()

@st.cache_resource(show_spinner=False)
def init_db():
    """Inicializa tabelas, índices e migrações apenas 1x por inicialização do servidor"""
    conn = get_connection()
    cursor = conn.cursor()
    
    tabelas = {
        "usuarios": "id SERIAL PRIMARY KEY, nome TEXT NOT NULL, email TEXT UNIQUE NOT NULL, senha_hash TEXT NOT NULL, renda_mensal REAL DEFAULT 2350.0, plano TEXT DEFAULT 'free', criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "transacoes": "id SERIAL PRIMARY KEY, usuario_id INTEGER, tipo TEXT, descricao TEXT, categoria TEXT, valor REAL, data_competencia DATE, detalhes TEXT, status TEXT DEFAULT 'Pendente', centro_custo TEXT DEFAULT 'Pessoal', cartao_vinculado TEXT",
        "compras_futuras": "id SERIAL PRIMARY KEY, usuario_id INTEGER, item TEXT, valor REAL, prioridade TEXT, status TEXT DEFAULT 'Planejado', centro_custo TEXT, metodo TEXT DEFAULT 'PIX', parcelas INTEGER DEFAULT 1, cartao_vinculado TEXT",
        "investimentos": "id SERIAL PRIMARY KEY, usuario_id INTEGER, ticker TEXT, tipo_ativo TEXT, quantidade REAL, preco_medio REAL, taxa_fixa_anual REAL DEFAULT 0.0, data_compra DATE, centro_custo TEXT DEFAULT 'Pessoal'",
        "poupanca_metas": "id SERIAL PRIMARY KEY, usuario_id INTEGER, nome_meta TEXT NOT NULL, categoria TEXT, valor_alvo REAL NOT NULL, valor_atual REAL DEFAULT 0.0, rentabilidade_mensal REAL DEFAULT 0.85, data_limite DATE, centro_custo TEXT DEFAULT 'Pessoal'",
        "cotas_ia": "id SERIAL PRIMARY KEY, usuario_id INTEGER NOT NULL, data_ref DATE NOT NULL DEFAULT CURRENT_DATE, requisicoes INTEGER DEFAULT 0, UNIQUE(usuario_id, data_ref)",
        "cotacoes_cache": "ticker TEXT PRIMARY KEY, preco REAL DEFAULT 0.0, atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    }
    for nome, colunas in tabelas.items():
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {nome} ({colunas})")
    
    migracoes = [
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS nome TEXT",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS email TEXT",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS senha_hash TEXT",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS renda_mensal REAL DEFAULT 2350.0",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS plano TEXT DEFAULT 'free'",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user'",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS senha TEXT DEFAULT '***'",
        "ALTER TABLE transacoes ADD COLUMN IF NOT EXISTS usuario_id INTEGER",
        "ALTER TABLE compras_futuras ADD COLUMN IF NOT EXISTS usuario_id INTEGER",
        "ALTER TABLE investimentos ADD COLUMN IF NOT EXISTS usuario_id INTEGER",
        "ALTER TABLE investimentos ADD COLUMN IF NOT EXISTS taxa_fixa_anual REAL DEFAULT 0.0",
        "ALTER TABLE investimentos ADD COLUMN IF NOT EXISTS centro_custo TEXT DEFAULT 'Pessoal'",
        "UPDATE usuarios SET plano = 'dono', role = 'admin' WHERE id = 1 OR LOWER(email) IN ('evandrosps2013@gmail.com', 'pereira.evandro@tjrj.jus.br')"
    ]
    conn.commit()
    conn.autocommit = True
    for m in migracoes:
        try:
            cursor.execute(m)
        except Exception:
            pass
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_trans_usuario ON transacoes(usuario_id, centro_custo)",
        "CREATE INDEX IF NOT EXISTS idx_trans_data ON transacoes(data_competencia)",
        "CREATE INDEX IF NOT EXISTS idx_trans_status ON transacoes(status)"
    ]
    for idx in indices:
        try:
            cursor.execute(idx)
        except Exception:
            pass
    conn.autocommit = False
    conn.commit()
    conn.close()
    return True

def consolidar_dados_admin(usuario_id: int, email_usuario: str):
    """
    Garante que o Admin (id=1 ou evandrosps2013@gmail.com) receba:
    1. Todos os registros órfãos (usuario_id IS NULL).
    2. Todos os registros que foram importados na conta provisória (terstegenelionelmessi@gmail.com),
       caso a conta Admin ainda esteja sem lançamentos.
    """
    eh_admin = (int(usuario_id) == 1) or (str(email_usuario).lower() in EMAILS_ADMIN_PADRAO)
    if not eh_admin:
        return
    executar_query("UPDATE transacoes SET usuario_id = ? WHERE usuario_id IS NULL", (usuario_id,))
    executar_query("UPDATE compras_futuras SET usuario_id = ? WHERE usuario_id IS NULL", (usuario_id,))
    executar_query("UPDATE investimentos SET usuario_id = ? WHERE usuario_id IS NULL", (usuario_id,))
    executar_query("UPDATE poupanca_metas SET usuario_id = ? WHERE usuario_id IS NULL", (usuario_id,))

    # Verifica se os dados ficaram na conta secundária terstegenelionelmessi@gmail.com
    df_count_admin = get_df("SELECT COUNT(*) AS total FROM transacoes WHERE usuario_id = ?", (usuario_id,))
    tot_admin = int(df_count_admin.iloc[0]['total']) if not df_count_admin.empty else 0
    if tot_admin == 0:
        df_sec = get_df("SELECT id FROM usuarios WHERE LOWER(email) = 'terstegenelionelmessi@gmail.com' AND id != ?", (usuario_id,))
        if not df_sec.empty:
            id_sec = int(df_sec.iloc[0]['id'])
            executar_query("UPDATE transacoes SET usuario_id = ? WHERE usuario_id = ?", (usuario_id, id_sec))
            executar_query("UPDATE compras_futuras SET usuario_id = ? WHERE usuario_id = ?", (usuario_id, id_sec))
            executar_query("UPDATE investimentos SET usuario_id = ? WHERE usuario_id = ?", (usuario_id, id_sec))
            executar_query("UPDATE poupanca_metas SET usuario_id = ? WHERE usuario_id = ?", (usuario_id, id_sec))

init_db()

# =====================================================================
# 3. TELA DE LOGIN E CADASTRO INDIVIDUAL (COM RECONHECIMENTO ADMIN)
# =====================================================================
if st.session_state.usuario_logado is None:
    col_esq, col_centro, col_dir = st.columns([1, 1.4, 1])
    with col_centro:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<h1 style='text-align: center;'>⚡ Core Finance PRO</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #94A3B8;'>Plataforma Cloud de Gestão Financeira, Poupança, Investimentos & IA</p>", unsafe_allow_html=True)
        
        aba_login, aba_cadastro = st.tabs(["🔐 Entrar na Minha Conta", "✨ Criar Nova Conta Individual"])
        
        with aba_login:
            with st.form("form_login"):
                email_in = st.text_input("E-mail Cadastrado", placeholder="Ex: evandrosps2013@gmail.com").strip().lower()
                senha_in = st.text_input("Sua Senha", type="password")
                if st.form_submit_button("🚀 Acessar Meu Painel", use_container_width=True, type="primary"):
                    if email_in and senha_in:
                        df_u = get_df("SELECT * FROM usuarios WHERE LOWER(email) = ?", (email_in,))
                        if not df_u.empty:
                            user_row = df_u.iloc[0]
                            senha_legada_db = user_row['senha'] if 'senha' in df_u.columns else None
                            autenticado, converter_hash = verificar_senha(senha_in, user_row.get('senha_hash'), senha_legada_db)
                            if autenticado:
                                uid = int(user_row['id'])
                                # Se a senha estava em texto puro no banco, criptografa automaticamente agora
                                if converter_hash:
                                    executar_query("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (gerar_hash_senha(senha_in), uid))
                                
                                # Verifica se é a conta Admin principal
                                role_db = str(user_row.get('role') or '').lower() if 'role' in df_u.columns else ''
                                plano_db = str(user_row.get('plano') or '').lower() if 'plano' in df_u.columns else ''
                                eh_dono = (uid == 1) or (role_db == 'admin') or (plano_db == 'dono') or (email_in in EMAILS_ADMIN_PADRAO)
                                plano_final = 'dono' if eh_dono else (plano_db if plano_db in ['pro', 'free'] else 'free')
                                
                                if eh_dono and plano_db != 'dono':
                                    executar_query("UPDATE usuarios SET plano = 'dono', role = 'admin' WHERE id = ?", (uid,))
                                
                                consolidar_dados_admin(uid, email_in)
                                st.session_state.usuario_logado = {
                                    "id": uid,
                                    "nome": user_row['nome'],
                                    "email": user_row['email'],
                                    "renda_mensal": float(user_row['renda_mensal'] or 2350.0),
                                    "plano": plano_final
                                }
                                st.success(f"Bem-vindo(a), {user_row['nome']}!")
                                st.rerun()
                            else:
                                st.error("❌ E-mail ou senha incorretos.")
                        else:
                            st.error("❌ E-mail não encontrado. Verifique a digitação ou crie uma conta.")
                    else:
                        st.warning("Preencha seu e-mail e senha.")

        with aba_cadastro:
            st.caption("Crie seu acesso exclusivo. Seus dados financeiros ficam 100% isolados e protegidos.")
            with st.form("form_cadastro"):
                nome_cad = st.text_input("Seu Nome Completo", placeholder="Ex: Evandro Santos").strip()
                email_cad = st.text_input("Seu Melhor E-mail", placeholder="seuemail@exemplo.com").strip().lower()
                renda_cad = st.number_input("Sua Renda Mensal Base (R$)", min_value=0.0, value=2350.0, step=100.0)
                c_s1, c_s2 = st.columns(2)
                senha_cad = c_s1.text_input("Crie uma Senha", type="password")
                senha_conf = c_s2.text_input("Confirme a Senha", type="password")
                
                if st.form_submit_button("✨ Criar Conta Agora", use_container_width=True, type="primary"):
                    if not nome_cad or not email_cad or not senha_cad:
                        st.warning("⚠️ Preencha todos os campos obrigatórios.")
                    elif len(senha_cad) < 4:
                        st.warning("⚠️ A senha deve ter pelo menos 4 caracteres.")
                    elif senha_cad != senha_conf:
                        st.error("❌ As senhas digitadas não conferem.")
                    else:
                        df_existe = get_df("SELECT id FROM usuarios WHERE LOWER(email) = ?", (email_cad,))
                        if not df_existe.empty:
                            st.error("❌ Este e-mail já possui uma conta cadastrada. Use a aba 'Entrar'.")
                        else:
                            hash_pw = gerar_hash_senha(senha_cad)
                            eh_email_admin = email_cad in EMAILS_ADMIN_PADRAO
                            plano_ini = 'dono' if eh_email_admin else 'free'
                            role_ini = 'admin' if eh_email_admin else 'user'
                            executar_query(
                                "INSERT INTO usuarios (nome, email, senha_hash, renda_mensal, plano, role, senha) VALUES (?,?,?,?,?,?,?)",
                                (nome_cad, email_cad, hash_pw, renda_cad, plano_ini, role_ini, '***')
                            )
                            df_novo = get_df("SELECT * FROM usuarios WHERE LOWER(email) = ?", (email_cad,))
                            novo_id = int(df_novo.iloc[0]['id'])
                            if novo_id == 1:
                                plano_ini = 'dono'
                                executar_query("UPDATE usuarios SET plano = 'dono', role = 'admin' WHERE id = 1")
                            consolidar_dados_admin(novo_id, email_cad)
                            st.session_state.usuario_logado = {
                                "id": novo_id,
                                "nome": nome_cad,
                                "email": email_cad,
                                "renda_mensal": float(renda_cad),
                                "plano": plano_ini
                            }
                            st.success("✅ Conta criada com sucesso! Entrando no sistema...")
                            st.rerun()
    st.stop()

# =====================================================================
# 4. MOTORES DE MERCADO, COTAÇÕES DIÁRIAS E INTELIGÊNCIA ARTIFICIAL
# =====================================================================
USER_ID = int(st.session_state.usuario_logado["id"])
USER_NOME = st.session_state.usuario_logado["nome"]
USER_EMAIL = str(st.session_state.usuario_logado["email"]).lower()
USER_PLANO = st.session_state.usuario_logado.get("plano", "free")
IS_ADMIN = (USER_ID == 1) or (USER_PLANO == "dono") or (USER_EMAIL in EMAILS_ADMIN_PADRAO)

hoje = datetime.now()
hoje_data = hoje.date()

def calcular_score_financeiro(renda, despesas, total_guardado):
    if renda <= 0:
        return 300
    taxa_poupanca = (renda - despesas) / renda
    bonus_reserva = min(150, (total_guardado / max(renda, 1)) * 50)
    if taxa_poupanca >= 0.20: base = 800 + (taxa_poupanca * 100)
    elif taxa_poupanca >= 0.10: base = 600 + (taxa_poupanca * 500)
    elif taxa_poupanca >= 0: base = 420 + (taxa_poupanca * 1000)
    else: base = max(100, 400 - (abs(taxa_poupanca) * 800))
    return min(1000, base + bonus_reserva)

def sincronizar_mercado_diario(forcar=False):
    """
    Atualiza Selic, CDI (via BrasilAPI) e principais cotações (via yfinance)
    apenas 1x por dia na tabela cotacoes_cache do Supabase, deixando o app instantâneo.
    """
    try:
        df_check = get_df("SELECT atualizado_em FROM cotacoes_cache WHERE ticker = 'SELIC_META'")
        if not forcar and not df_check.empty:
            ult_att = pd.to_datetime(df_check.iloc[0]['atualizado_em']).date()
            if ult_att == hoje_data:
                return False  # Já está atualizado hoje!
    except Exception:
        pass

    conn = get_connection()
    cur = conn.cursor()
    agora = datetime.now()
    # 1. Busca Selic Meta na BrasilAPI
    try:
        with urllib.request.urlopen("https://brasilapi.com.br/api/taxas/v1/selic", timeout=8) as r:
            dados_selic = json.loads(r.read().decode("utf-8"))
            val_raw = float(dados_selic.get("valor", 11.25))
            selic = val_raw * 100 if val_raw < 1.0 else val_raw
            for tk, v in [("SELIC_META", selic), ("CDI_ESTIMADO", max(0.0, selic - 0.10))]:
                cur.execute(
                    "INSERT INTO cotacoes_cache (ticker, preco, atualizado_em) VALUES (%s,%s,%s) "
                    "ON CONFLICT (ticker) DO UPDATE SET preco=EXCLUDED.preco, atualizado_em=EXCLUDED.atualizado_em",
                    (tk, v, agora)
                )
    except Exception:
        pass

    # 2. Busca Câmbio, Índices e Bitcoin
    for tk in ["USDBRL=X", "EURBRL=X", "BTC-USD", "^BVSP"]:
        try:
            hist = yf.Ticker(tk).history(period="1d")
            if not hist.empty:
                preco = float(hist["Close"].iloc[-1])
                cur.execute(
                    "INSERT INTO cotacoes_cache (ticker, preco, atualizado_em) VALUES (%s,%s,%s) "
                    "ON CONFLICT (ticker) DO UPDATE SET preco=EXCLUDED.preco, atualizado_em=EXCLUDED.atualizado_em",
                    (tk, preco, agora)
                )
        except Exception:
            pass
    conn.commit()
    conn.close()
    st.cache_data.clear()
    return True

@st.cache_data(ttl=43200, show_spinner=False)
def obter_cotacao_atual(ticker):
    """Lê instantaneamente do cache diário no Supabase ou busca no yfinance se for um ativo novo"""
    try:
        t = ticker.strip().upper()
        if not t.endswith('.SA') and not t.endswith('=X') and not t.endswith('-USD') and not t.startswith('^'):
            t += '.SA'
        df_cache = get_df("SELECT preco FROM cotacoes_cache WHERE ticker = ?", (t,))
        if not df_cache.empty and float(df_cache.iloc[0]['preco']) > 0:
            return float(df_cache.iloc[0]['preco'])
        hist = yf.Ticker(t).history(period="1d")
        if not hist.empty:
            preco = float(hist['Close'].iloc[-1])
            try:
                c = get_connection(); cur = c.cursor()
                cur.execute(
                    "INSERT INTO cotacoes_cache (ticker, preco, atualizado_em) VALUES (%s,%s,CURRENT_TIMESTAMP) "
                    "ON CONFLICT (ticker) DO UPDATE SET preco = EXCLUDED.preco, atualizado_em = CURRENT_TIMESTAMP",
                    (t, preco)
                )
                c.commit(); c.close()
            except Exception:
                pass
            return preco
        return 0.0
    except Exception:
        return 0.0

def calcular_price(valor_financiado, taxa_mensal, prazo_meses):
    i = taxa_mensal / 100
    if i == 0:
        return valor_financiado / prazo_meses
    return valor_financiado * (i * (1 + i)**prazo_meses) / ((1 + i)**prazo_meses - 1)

# Limites diários de IA por categoria de conta
LIMITES_IA = {"dono": 99999, "pro": 50, "free": 5}

def obter_consumo_ia_hoje():
    df_q = get_df("SELECT requisicoes FROM cotas_ia WHERE usuario_id = ? AND data_ref = ?", (USER_ID, hoje_data.isoformat()))
    return int(df_q.iloc[0]['requisicoes']) if not df_q.empty else 0

def registrar_consumo_ia():
    executar_query(
        "INSERT INTO cotas_ia (usuario_id, data_ref, requisicoes) VALUES (?,?,1) "
        "ON CONFLICT (usuario_id, data_ref) DO UPDATE SET requisicoes = cotas_ia.requisicoes + 1",
        (USER_ID, hoje_data.isoformat())
    )

def consultar_gemini_ia(prompt_usuario, contexto_financeiro, api_key_custom=None, modelo_admin_preferido="gemini-2.5-pro"):
    """
    Motor de Inteligência Artificial com separação de privilégios:
    - Conta ADMIN (Dono): Sem limite de consultas, até 2048 tokens de resposta, opção de usar Gemini 2.5 Pro (com fallback automático para 2.5 Flash).
    - Conta PRO: 50 consultas/dia com Gemini 2.5 Flash (1500 tokens).
    - Conta FREE: 5 consultas/dia com Gemini 2.5 Flash-Lite (750 tokens) para economizar cota da API.
    """
    chave_api = api_key_custom
    usa_chave_propria = bool(chave_api and len(str(chave_api).strip()) > 10)
    if not usa_chave_propria:
        chave_api = obter_chave_gemini_secrets()

    if chave_api and len(str(chave_api).strip()) > 10:
        limite = LIMITES_IA.get("dono" if IS_ADMIN else USER_PLANO, 5)

        if not usa_chave_propria and not IS_ADMIN and obter_consumo_ia_hoje() >= limite:
            return (
                f"⚠️ **Limite diário de IA atingido** (Plano {USER_PLANO.upper()}: {limite} análises/dia). "
                "Solicite o upgrade para o plano PRO ao administrador ou insira sua chave gratuita do Google AI Studio ao lado.\n\n"
                + gerar_diagnostico_nativo(contexto_financeiro)
            )

        if IS_ADMIN:
            modelos_tentativa = [modelo_admin_preferido, "gemini-2.5-flash"] if modelo_admin_preferido != "gemini-2.5-flash" else ["gemini-2.5-flash"]
            max_tokens = 2048
        elif USER_PLANO == "pro":
            modelos_tentativa = ["gemini-2.5-flash"]
            max_tokens = 1500
        else:
            modelos_tentativa = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
            max_tokens = 750

        instrucao_sistema = (
            f"Você é o Consultor Financeiro Pessoal e Estrategista Patrimonial de {USER_NOME} no sistema Core Finance PRO. "
            "Analise os números reais do usuário abaixo com precisão matemática, clareza executiva e foco prático. "
            "Use tópicos organizados, cite os nomes reais das despesas/cartões/metas quando relevante e proponha metas numéricas claras.\n\n"
            f"DADOS REAIS DO USUÁRIO NESTE MOMENTO:\n{contexto_financeiro}\n\n"
            f"SOLICITAÇÃO DO USUÁRIO: {prompt_usuario}"
        )
        payload = {
            "contents": [{"parts": [{"text": instrucao_sistema}]}],
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": max_tokens}
        }

        ultimo_erro = None
        for mod in modelos_tentativa:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={str(chave_api).strip()}"
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=25) as resp:
                    dados_resp = json.loads(resp.read().decode('utf-8'))
                    if not usa_chave_propria:
                        registrar_consumo_ia()
                    texto_ia = dados_resp['candidates'][0]['content']['parts'][0]['text']
                    tag_modelo = f"*(Motor utilizado: `{mod}`)*\n\n"
                    return tag_modelo + texto_ia
            except Exception as e:
                ultimo_erro = e
                continue

        return f"⚠️ **Aviso da API Gemini ({ultimo_erro}):** Exibindo diagnóstico imediato do Motor Analítico Interno:\n\n" + gerar_diagnostico_nativo(contexto_financeiro)
    else:
        return gerar_diagnostico_nativo(contexto_financeiro)

def gerar_diagnostico_nativo(contexto_txt):
    return (
        f"### 🧠 Diagnóstico Executivo Core Finance PRO ({USER_NOME})\n\n"
        f"{contexto_txt}\n\n"
        "**📌 Plano de Ação Recomendado:**\n"
        "1. **Blindagem de Fluxo de Caixa:** Priorize a baixa das despesas pendentes de maior valor e evite novos parcelamentos enquanto o comprometimento mensal estiver acima de 70%.\n"
        "2. **Aceleração de Reserva (Selic/CDI):** Direcione entre **10% e 20% das entradas** diretamente para a aba *🐷 Poupança & Cofrinhos*.\n"
        "3. **Recuperação de Recebíveis:** Utilize os links diretos de WhatsApp na aba *💰 Recebimentos & Cobranças* para antecipar valores pendentes."
    )

def importar_arquivo_sqlite_usuario(caminho_sqlite, usuario_id, centro_custo_padrao="Pessoal", preservar_manuais=True):
    conn_local = sqlite3.connect(caminho_sqlite)
    cur_local = conn_local.cursor()
    cur_local.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tabelas_existentes = [r[0] for r in cur_local.fetchall()]
    
    registros_para_inserir = []
    if "expense" in tabelas_existentes:
        query_local = """
            SELECT e.description, COALESCE(c.name, 'Outros') as categoria,
                   e.price, e.dateTransaction, e.status, e.countPart
            FROM expense e
            LEFT JOIN category c ON e.categoryId = c.id
        """
        cur_local.execute(query_local)
        for desc, cat, preco, data_tx, status_raw, count_part in cur_local.fetchall():
            descricao_limpa = str(desc).strip()
            categoria_limpa = str(cat).strip()
            valor_float = float(preco) if preco is not None else 0.0
            data_limpa = str(data_tx).strip()[:10]
            status_final = "Pago" if str(status_raw).strip().upper() == "PAID" else "Pendente"
            detalhes_txt = f"Importado | Parte {count_part}" if count_part else "Importado"
            registros_para_inserir.append((
                usuario_id, "Despesa", descricao_limpa, categoria_limpa, valor_float,
                data_limpa, detalhes_txt, status_final, centro_custo_padrao, detectar_cartao(descricao_limpa)
            ))
    elif "transacoes" in tabelas_existentes:
        cur_local.execute("SELECT tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado FROM transacoes")
        for t in cur_local.fetchall():
            cartao_vinc = t[8] if t[8] and str(t[8]) != "None" else detectar_cartao(t[1])
            registros_para_inserir.append((
                usuario_id, t[0], str(t[1]).strip(), str(t[2]).strip(), float(t[3]),
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
            cur_nuvem.execute("DELETE FROM transacoes WHERE usuario_id = %s AND tipo = 'Despesa' AND centro_custo = %s", (usuario_id, centro_custo_padrao))
        else:
            cur_nuvem.execute("DELETE FROM transacoes WHERE usuario_id = %s AND centro_custo = %s", (usuario_id, centro_custo_padrao))
            
        sql_insert = """
            INSERT INTO transacoes 
            (usuario_id, tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        execute_batch(cur_nuvem, sql_insert, registros_para_inserir, page_size=100)
        conn_nuvem.commit()
        st.cache_data.clear()
    except Exception as e:
        conn_nuvem.rollback()
        raise e
    finally:
        conn_nuvem.close()
    return len(registros_para_inserir)

# Sincroniza o cache diário de mercado silenciosamente 1x por dia
sincronizar_mercado_diario(forcar=False)

# =====================================================================
# 5. SIDEBAR CORPORATIVA PERSONALIZADA POR USUÁRIO
# =====================================================================
with st.sidebar:
    if IS_ADMIN:
        st.markdown("<div class='admin-badge'>👑 CONTA ADMIN / DONO (IA ∞)</div>", unsafe_allow_html=True)
    elif USER_PLANO == "pro":
        st.markdown("<div class='admin-badge' style='background:linear-gradient(90deg,#3b82f6,#1d4ed8);color:white;'>💎 ASSINANTE PRO</div>", unsafe_allow_html=True)
    else:
        st.caption("👤 Plano Gratuito (FREE)")

    st.markdown(f"### Olá, {USER_NOME.split()[0]}!")
    st.caption(f"📧 {st.session_state.usuario_logado['email']}")
    if st.button("🚪 Sair da Conta", use_container_width=True):
        st.session_state.usuario_logado = None
        st.rerun()
        
    st.markdown("---")
    with st.form("form_renda_sidebar"):
        nova_renda = st.number_input(
            "💵 Sua Renda Base Mensal (R$)",
            value=float(st.session_state.usuario_logado["renda_mensal"]),
            step=100.0,
            help="Salário ou renda fixa mensal. Fica salvo no seu perfil ao clicar em Salvar."
        )
        if st.form_submit_button("💾 Salvar Renda", use_container_width=True):
            executar_query("UPDATE usuarios SET renda_mensal = ? WHERE id = ?", (nova_renda, USER_ID))
            st.session_state.usuario_logado["renda_mensal"] = nova_renda
            st.success("✅ Renda atualizada!")
            st.rerun()
    renda_real_declarada = st.session_state.usuario_logado["renda_mensal"]
    
    st.session_state.perfil_ativo = st.selectbox("🏢 Contexto / Workspace:", ["Pessoal", "Elite Beach Performance / Negócios"])
    
    st.markdown("---")
    st.markdown("### ⚡ Anotação Rápida (5s)")
    with st.form("form_rapido_sidebar", clear_on_submit=True):
        r_tipo = st.radio("Fluxo", ["Despesa", "Receita"], horizontal=True)
        r_desc = st.text_input("Descrição (Ex: Mercado, Pix Aluno)")
        r_val = st.number_input("Valor (R$)", min_value=0.0, format="%.2f")
        r_status = st.selectbox("Status", ["Pago", "Pendente"])
        if st.form_submit_button("💾 Registrar Agora", use_container_width=True, type="primary"):
            if r_desc and r_val > 0:
                cat_padrao = "Recebimento de Terceiros" if r_tipo == "Receita" else "Outros"
                executar_query(
                    "INSERT INTO transacoes (usuario_id, tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (USER_ID, r_tipo, r_desc.strip(), cat_padrao, r_val, hoje_data, "Lançamento Rápido", r_status, st.session_state.perfil_ativo, detectar_cartao(r_desc))
                )
                st.success("✅ Registrado!")
                st.rerun()

# =====================================================================
# 6. CARREGAMENTO ISOLADO DE DADOS DO USUÁRIO LOGADO
# =====================================================================
st.title(f"⚡ Core Finance PRO | {st.session_state.perfil_ativo}")

df_trans = get_df("SELECT * FROM transacoes WHERE usuario_id = ? AND centro_custo = ?", (USER_ID, st.session_state.perfil_ativo))
if not df_trans.empty:
    df_trans['data_competencia_dt'] = pd.to_datetime(df_trans['data_competencia'], errors='coerce')
    df_trans['data_apenas'] = df_trans['data_competencia_dt'].dt.date
    df_mes = df_trans[(df_trans['data_competencia_dt'].dt.month == hoje.month) & (df_trans['data_competencia_dt'].dt.year == hoje.year)]
else:
    df_mes = pd.DataFrame()

df_poup = get_df("SELECT * FROM poupanca_metas WHERE usuario_id = ? AND centro_custo = ? ORDER BY id", (USER_ID, st.session_state.perfil_ativo))
total_poupanca_guardado = df_poup['valor_atual'].sum() if not df_poup.empty else 0.0

df_invest = get_df("SELECT * FROM investimentos WHERE usuario_id = ? ORDER BY id", (USER_ID,))
total_investido_custo = (df_invest['quantidade'] * df_invest['preco_medio']).sum() if not df_invest.empty else 0.0

receitas_pagas_mes = df_mes[(df_mes['tipo'] == 'Receita') & (df_mes['status'] == 'Pago')]['valor'].sum() if not df_mes.empty else 0.0
receitas_pendentes_mes = df_mes[(df_mes['tipo'] == 'Receita') & (df_mes['status'] == 'Pendente')]['valor'].sum() if not df_mes.empty else 0.0
despesas_totais_mes = df_mes[df_mes['tipo'] == 'Despesa']['valor'].sum() if not df_mes.empty else 0.0
despesas_pagas_mes = df_mes[(df_mes['tipo'] == 'Despesa') & (df_mes['status'] == 'Pago')]['valor'].sum() if not df_mes.empty else 0.0
despesas_pendentes_mes = df_mes[(df_mes['tipo'] == 'Despesa') & (df_mes['status'] == 'Pendente')]['valor'].sum() if not df_mes.empty else 0.0

entradas_confirmadas = renda_real_declarada + receitas_pagas_mes
saldo_livre_atual = entradas_confirmadas - despesas_totais_mes
saldo_projetado_mes = (entradas_confirmadas + receitas_pendentes_mes) - despesas_totais_mes
patrimonio_acumulado = total_poupanca_guardado + total_investido_custo

# --- CENTRAL DE ALERTAS DE COBRANÇA ---
if not df_trans.empty:
    df_cobrar = df_trans[(df_trans['tipo'] == 'Receita') & (df_trans['status'] == 'Pendente')].copy()
    if not df_cobrar.empty:
        atrasados = df_cobrar[df_cobrar['data_apenas'] < hoje_data]
        vencem_hoje = df_cobrar[df_cobrar['data_apenas'] == hoje_data]
        vencem_breve = df_cobrar[(df_cobrar['data_apenas'] > hoje_data) & (df_cobrar['data_apenas'] <= hoje_data + timedelta(days=3))]
        if not atrasados.empty or not vencem_hoje.empty or not vencem_breve.empty:
            with st.expander("🔔 CENTRAL DE LEMBRETES E COBRANÇAS ATIVAS", expanded=True):
                for _, r in atrasados.iterrows():
                    st.markdown(f"<div class='alert-card-red'>🚨 <b>ATRASADO:</b> <b>{r['descricao']}</b> ({m_fmt(r['valor'])}) venceu em <b>{r['data_apenas'].strftime('%d/%m/%Y')}</b>.</div>", unsafe_allow_html=True)
                for _, r in vencem_hoje.iterrows():
                    st.markdown(f"<div class='alert-card-yellow'>⚠️ <b>VENCE HOJE ({hoje_data.strftime('%d/%m')}):</b> Cobrar <b>{r['descricao']}</b> — <b>{m_fmt(r['valor'])}</b>.</div>", unsafe_allow_html=True)
                for _, r in vencem_breve.iterrows():
                    st.markdown(f"<div class='alert-card-green'>📅 <b>EM BREVE ({r['data_apenas'].strftime('%d/%m/%Y')}):</b> Receber <b>{m_fmt(r['valor'])}</b> de <b>{r['descricao']}</b>.</div>", unsafe_allow_html=True)

tabs = st.tabs([
    "📊 Dashboard 360°",
    "🐷 Poupança & Cofrinhos",
    "💰 Recebimentos & Cobranças",
    "💳 Despesas & Cartões",
    "📈 Investimentos",
    "🤖 Consultor Gemini IA",
    "🔮 Simuladores & Mercado",
    "⚙️ Conta, Backup & Admin" if IS_ADMIN else "⚙️ Conta & Backup"
])

# =====================================================================
# TAB 1 (tabs[0]): DASHBOARD 360°
# =====================================================================
with tabs[0]:
    col_f1, col_f2, col_f3 = st.columns([1.5, 1.5, 3])
    nomes_meses = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    mes_sel_nome = col_f1.selectbox("📅 Mês de Referência:", nomes_meses, index=hoje.month - 1)
    mes_sel_num = nomes_meses.index(mes_sel_nome) + 1
    
    anos_disp = sorted(list(set([hoje.year - 1, hoje.year, hoje.year + 1] + (df_trans['data_competencia_dt'].dt.year.dropna().astype(int).tolist() if not df_trans.empty else []))))
    ano_sel_num = col_f2.selectbox("📆 Ano:", anos_disp, index=anos_disp.index(hoje.year) if hoje.year in anos_disp else 0)

    if not df_trans.empty:
        df_dash = df_trans[(df_trans['data_competencia_dt'].dt.month == mes_sel_num) & (df_trans['data_competencia_dt'].dt.year == ano_sel_num)].copy()
        dt_ant = datetime(ano_sel_num, mes_sel_num, 1) - relativedelta(months=1)
        df_ant = df_trans[(df_trans['data_competencia_dt'].dt.month == dt_ant.month) & (df_trans['data_competencia_dt'].dt.year == dt_ant.year)]
        desp_mes_anterior = df_ant[df_ant['tipo'] == 'Despesa']['valor'].sum() if not df_ant.empty else 0.0
    else:
        df_dash = pd.DataFrame()
        desp_mes_anterior = 0.0

    rec_pagas_d = df_dash[(df_dash['tipo'] == 'Receita') & (df_dash['status'] == 'Pago')]['valor'].sum() if not df_dash.empty else 0.0
    rec_pend_d = df_dash[(df_dash['tipo'] == 'Receita') & (df_dash['status'] == 'Pendente')]['valor'].sum() if not df_dash.empty else 0.0
    desp_tot_d = df_dash[df_dash['tipo'] == 'Despesa']['valor'].sum() if not df_dash.empty else 0.0
    desp_pagas_d = df_dash[(df_dash['tipo'] == 'Despesa') & (df_dash['status'] == 'Pago')]['valor'].sum() if not df_dash.empty else 0.0
    desp_pend_d = df_dash[(df_dash['tipo'] == 'Despesa') & (df_dash['status'] == 'Pendente')]['valor'].sum() if not df_dash.empty else 0.0

    entradas_d = renda_real_declarada + rec_pagas_d
    saldo_d = entradas_d - desp_tot_d
    saldo_proj_d = (entradas_d + rec_pend_d) - desp_tot_d
    comprometimento_renda = (desp_tot_d / entradas_d * 100) if entradas_d > 0 else 0.0
    var_mom = ((desp_tot_d - desp_mes_anterior) / desp_mes_anterior * 100) if desp_mes_anterior > 0 else 0.0

    with col_f3:
        cor_comp = "#4caf50" if comprometimento_renda <= 70 else "#ff9800" if comprometimento_renda <= 90 else "#e94560"
        st.markdown(f"**🌡️ Termômetro de {mes_sel_nome}/{ano_sel_num}:** Renda comprometida em <span style='color:{cor_comp};font-weight:bold;'>{comprometimento_renda:.1f}%</span>", unsafe_allow_html=True)
        st.progress(min(comprometimento_renda / 100.0, 1.0))
        st.caption(f"✅ Quitadas: {m_fmt(desp_pagas_d)} | ⏳ Faltam pagar: {m_fmt(desp_pend_d)} | 📈 Variação vs mês anterior: {var_mom:+.1f}%")

    k1, k2, k3, k4, k5 = st.columns(5)
    score = calcular_score_financeiro(entradas_d + rec_pend_d, desp_tot_d, patrimonio_acumulado)
    
    k1.markdown(f"<div class='metric-card'>Entradas ({mes_sel_nome[:3]})<br><h3 style='color:#4caf50;margin:4px 0;'>{m_fmt(entradas_d)}</h3><small>A receber: <b>{m_fmt(rec_pend_d)}</b></small></div>", unsafe_allow_html=True)
    k2.markdown(f"<div class='metric-card'>Saídas ({mes_sel_nome[:3]})<br><h3 style='color:#e94560;margin:4px 0;'>{m_fmt(desp_tot_d)}</h3><small>Pendente: <b>{m_fmt(desp_pend_d)}</b></small></div>", unsafe_allow_html=True)
    cor_s = "#4facf7" if saldo_d >= 0 else "#e94560"
    k3.markdown(f"<div class='metric-card'>Saldo Livre<br><h3 style='color:{cor_s};margin:4px 0;'>{m_fmt(saldo_d)}</h3><small>Projetado: <b>{m_fmt(saldo_proj_d)}</b></small></div>", unsafe_allow_html=True)
    k4.markdown(f"<div class='metric-card'>Patrimônio & Reserva<br><h3 style='color:#a855f7;margin:4px 0;'>{m_fmt(patrimonio_acumulado)}</h3><small>Cofrinhos: <b>{m_fmt(total_poupanca_guardado)}</b></small></div>", unsafe_allow_html=True)
    k5.markdown(f"<div class='metric-card'>Score Financeiro<br><h3 style='color:#ff9800;margin:4px 0;'>{score:.0f} / 1000</h3><small>Nível: {'Excelente' if score >= 750 else 'Estável' if score >= 550 else 'Atenção'}</small></div>", unsafe_allow_html=True)

    st.markdown("---")
    r_col1, r_col2 = st.columns([1.2, 1])
    with r_col1:
        st.subheader("🚨 Radar de Vencimentos Próximos (Contas a Pagar)")
        if not df_trans.empty:
            df_venc_prox = df_trans[
                (df_trans['tipo'] == 'Despesa') &
                (df_trans['status'] == 'Pendente') &
                (df_trans['data_apenas'] >= hoje_data - timedelta(days=5)) &
                (df_trans['data_apenas'] <= hoje_data + timedelta(days=10))
            ].sort_values('data_apenas')
            if not df_venc_prox.empty:
                for _, rv in df_venc_prox.head(5).iterrows():
                    diff_d = (rv['data_apenas'] - hoje_data).days
                    icone_v = "🔴 Atrasada" if diff_d < 0 else "🟠 Vence Hoje" if diff_d == 0 else f"🟡 Em {diff_d}d"
                    cv1, cv2, cv3 = st.columns([3, 1.5, 1.2])
                    cv1.write(f"{icone_v} — **{rv['descricao']}**")
                    cv2.write(f"**{m_fmt(rv['valor'])}** ({rv['data_apenas'].strftime('%d/%m')})")
                    if cv3.button("Quitar ⚡", key=f"dash_pay_{rv['id']}"):
                        executar_query("UPDATE transacoes SET status = 'Pago' WHERE id = ? AND usuario_id = ?", (int(rv['id']), USER_ID))
                        st.rerun()
            else:
                st.success("🎉 Nenhuma conta pendente vencendo nos próximos 10 dias!")
        else:
            st.info("Sem lançamentos cadastrados.")

    with r_col2:
        st.subheader(f"🔥 Top 5 Maiores Gastos ({mes_sel_nome})")
        if not df_dash.empty and desp_tot_d > 0:
            df_top5 = df_dash[df_dash['tipo'] == 'Despesa'].sort_values('valor', ascending=False).head(5)
            for _, rt in df_top5.iterrows():
                perc_gasto = (rt['valor'] / desp_tot_d * 100) if desp_tot_d > 0 else 0
                st.write(f"• **{rt['descricao']}** ({rt['categoria']}): **{m_fmt(rt['valor'])}** — *{perc_gasto:.1f}% das saídas*")
        else:
            st.info("Nenhuma despesa neste mês.")

    st.markdown("---")
    cg1, cg2 = st.columns([1.7, 1.3])
    with cg1:
        st.subheader(f"Fluxo de Caixa em Cascata ({mes_sel_nome}/{ano_sel_num})")
        if not df_dash.empty and (entradas_d + rec_pend_d) > 0:
            df_wf = df_dash[df_dash['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            df_wf['valor'] = -df_wf['valor']
            x_labels = ['Entradas Confirmadas']
            y_vals = [entradas_d]
            measures = ['relative']
            if rec_pend_d > 0:
                x_labels.append('A Receber')
                y_vals.append(rec_pend_d)
                measures.append('relative')
            x_labels += df_wf['categoria'].tolist() + ['Saldo Projetado']
            y_vals += df_wf['valor'].tolist() + [saldo_proj_d]
            measures += ['relative']*len(df_wf) + ['total']
            fig_wf = go.Figure(go.Waterfall(
                orientation="v", measure=measures, x=x_labels, y=y_vals,
                decreasing={"marker":{"color":"#e94560"}}, increasing={"marker":{"color":"#4caf50"}}, totals={"marker":{"color":"#3b82f6"}},
                textposition="outside", texttemplate="%{y:,.2f}"
            ))
            fig_wf.update_layout(template="plotly_dark", height=360, margin=dict(l=0, r=0, t=30, b=0))
            st.plotly_chart(fig_wf, use_container_width=True)
        else:
            st.info("Registre transações no mês selecionado para visualizar a cascata de caixa.")
            
    with cg2:
        st.subheader("Divisão por Categoria & Cartão")
        if not df_dash.empty and desp_tot_d > 0:
            df_pie = df_dash[df_dash['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            fig_pie = px.pie(df_pie, values='valor', names='categoria', template="plotly_dark", hole=0.45)
            fig_pie.update_layout(height=360, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig_pie, use_container_width=True)

    if not df_trans.empty:
        st.markdown("---")
        st.subheader(f"📅 Evolução Mensal de Saídas em {ano_sel_num}")
        df_ano = df_trans[(df_trans['data_competencia_dt'].dt.year == ano_sel_num) & (df_trans['tipo'] == 'Despesa')].copy()
        if not df_ano.empty:
            df_ano['Mes_Num'] = df_ano['data_competencia_dt'].dt.month
            res_ano = df_ano.groupby(['Mes_Num', 'status'])['valor'].sum().reset_index()
            res_ano['Mês'] = res_ano['Mes_Num'].apply(lambda m: nomes_meses[int(m)-1][:3])
            fig_bar = px.bar(
                res_ano.sort_values('Mes_Num'), x='Mês', y='valor', color='status',
                barmode='stack', template="plotly_dark",
                color_discrete_map={'Pago': '#4caf50', 'Pendente': '#e94560'},
                labels={'valor': 'Total (R$)', 'status': 'Status'}
            )
            fig_bar.add_hline(y=renda_real_declarada, line_dash="dash", line_color="#4facf7", annotation_text="Renda Base")
            fig_bar.update_layout(height=300, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig_bar, use_container_width=True)

# =====================================================================
# TAB 2 (tabs[1]): POUPANÇA, COFRINHOS E RESERVA DE EMERGÊNCIA
# =====================================================================
with tabs[1]:
    st.header("🐷 Poupança, Cofrinhos & Metas de Reserva")
    st.write("Separe o dinheiro das suas metas (Reserva de Emergência, Poupança, CDB 100% CDI, Reforma, Viagem ou Fundo de Expansão) e acompanhe o rendimento mensal composto.")

    rendimento_mensal_estimado = (df_poup['valor_atual'] * (df_poup['rentabilidade_mensal'] / 100.0)).sum() if not df_poup.empty else 0.0
    total_alvo_metas = df_poup['valor_alvo'].sum() if not df_poup.empty else 0.0

    cp1, cp2, cp3 = st.columns(3)
    cp1.metric("🏦 Saldo Total Guardado nos Cofrinhos", m_fmt(total_poupanca_guardado))
    cp2.metric("📈 Rendimento Passivo Estimado / Mês", m_fmt(rendimento_mensal_estimado), "Juros sobre o saldo guardado")
    cp3.metric("🎯 Soma Total das Metas Planejadas", m_fmt(total_alvo_metas))

    with st.expander("➕ Criar Novo Cofrinho / Meta de Poupança", expanded=df_poup.empty):
        with st.form("form_novo_cofrinho", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns(3)
            nome_cofre = fc1.text_input("Nome do Cofrinho / Objetivo (Ex: Reserva de Emergência, Viagem)")
            cat_cofre = fc2.selectbox("Onde está guardado?", [
                "CDB Liquidez Diária (100% CDI ~0,90% a.m.)",
                "Caixinha Nubank / PicPay / Inter (~0,90% a.m.)",
                "Tesouro Selic (~0,92% a.m.)",
                "Caderneta de Poupança (~0,60% a.m.)",
                "Espécie / Conta Corrente (0% a.m.)"
            ])
            rent_padrao = 0.60 if "Poupança" in cat_cofre else 0.0 if "Espécie" in cat_cofre else 0.90
            
            fc4, fc5, fc6, fc7 = st.columns(4)
            alvo_cofre = fc4.number_input("Meta de Valor (R$)", min_value=10.0, value=5000.0, step=100.0)
            atual_cofre = fc5.number_input("Valor Já Guardado Hoje (R$)", min_value=0.0, value=0.0, step=50.0)
            taxa_cofre = fc6.number_input("Rentabilidade Mensal (%)", min_value=0.0, value=rent_padrao, step=0.05)
            data_lim_cofre = fc7.date_input("Data Alvo", value=hoje_data + relativedelta(months=12))
            
            if st.form_submit_button("🐷 Criar Cofrinho", type="primary"):
                if nome_cofre and alvo_cofre > 0:
                    executar_query(
                        "INSERT INTO poupanca_metas (usuario_id, nome_meta, categoria, valor_alvo, valor_atual, rentabilidade_mensal, data_limite, centro_custo) VALUES (?,?,?,?,?,?,?,?)",
                        (USER_ID, nome_cofre.strip(), cat_cofre, alvo_cofre, atual_cofre, taxa_cofre, data_lim_cofre, st.session_state.perfil_ativo)
                    )
                    st.success(f"✅ Cofrinho '{nome_cofre}' criado!")
                    st.rerun()

    st.markdown("---")
    if not df_poup.empty:
        for _, row_p in df_poup.iterrows():
            prog = min(float(row_p['valor_atual']) / max(float(row_p['valor_alvo']), 1.0), 1.0)
            rend_mes_item = float(row_p['valor_atual']) * (float(row_p['rentabilidade_mensal']) / 100.0)
            falta_guardar = max(0.0, float(row_p['valor_alvo']) - float(row_p['valor_atual']))
            
            st.markdown(f"""
                <div class='cofrinho-card'>
                    <h4>🐷 {row_p['nome_meta']} <small style='color:#94A3B8;'>({row_p['categoria']})</small></h4>
                    <p style='margin:4px 0;'>Guardado: <b style='color:#4caf50;font-size:1.15em;'>{m_fmt(row_p['valor_atual'])}</b> de <b>{m_fmt(row_p['valor_alvo'])}</b> ({prog*100:.1f}% concluído) | Falta: <b>{m_fmt(falta_guardar)}</b> | Rende aprox. <b>{m_fmt(rend_mes_item)}/mês</b></p>
                </div>
            """, unsafe_allow_html=True)
            st.progress(prog)
            
            ca_p1, ca_p2, ca_p3, ca_p4 = st.columns([2, 1.5, 1.5, 1])
            valor_mov = ca_p1.number_input(f"Valor para Guardar ou Resgatar em '{row_p['nome_meta']}' (R$)", min_value=0.0, step=50.0, key=f"val_cof_{row_p['id']}")
            if ca_p2.button("➕ Guardar Valor", key=f"dep_cof_{row_p['id']}", type="primary"):
                if valor_mov > 0:
                    novo_v = float(row_p['valor_atual']) + valor_mov
                    executar_query("UPDATE poupanca_metas SET valor_atual = ? WHERE id = ? AND usuario_id = ?", (novo_v, int(row_p['id']), USER_ID))
                    st.rerun()
            if ca_p3.button("➖ Resgatar Valor", key=f"res_cof_{row_p['id']}"):
                if valor_mov > 0:
                    novo_v = max(0.0, float(row_p['valor_atual']) - valor_mov)
                    executar_query("UPDATE poupanca_metas SET valor_atual = ? WHERE id = ? AND usuario_id = ?", (novo_v, int(row_p['id']), USER_ID))
                    st.rerun()
            if ca_p4.button("🗑️ Excluir", key=f"del_cof_{row_p['id']}"):
                executar_query("DELETE FROM poupanca_metas WHERE id = ? AND usuario_id = ?", (int(row_p['id']), USER_ID))
                st.rerun()
            st.markdown("<br>", unsafe_allow_html=True)
    else:
        st.info("Você ainda não criou nenhum cofrinho de poupança. Crie o primeiro acima para acompanhar sua Reserva de Emergência e objetivos!")

# =====================================================================
# TAB 3 (tabs[2]): PREVISÃO DE RECEBIMENTOS & COBRANÇAS
# =====================================================================
with tabs[2]:
    st.header("💰 Previsão de Recebimentos & Controle de Cobranças")
    df_rec_all = df_trans[df_trans['tipo'] == 'Receita'].copy() if not df_trans.empty else pd.DataFrame()
    tot_ja_recebido = df_rec_all[df_rec_all['status'] == 'Pago']['valor'].sum() if not df_rec_all.empty else 0.0
    tot_a_receber_geral = df_rec_all[df_rec_all['status'] == 'Pendente']['valor'].sum() if not df_rec_all.empty else 0.0
    tot_atrasado_cobrar = df_rec_all[(df_rec_all['status'] == 'Pendente') & (df_rec_all['data_apenas'] < hoje_data)]['valor'].sum() if not df_rec_all.empty else 0.0

    kr1, kr2, kr3 = st.columns(3)
    kr1.metric("✅ Total Já Recebido", m_fmt(tot_ja_recebido))
    kr2.metric("⏳ Total Pendente a Receber", m_fmt(tot_a_receber_geral))
    kr3.metric("🚨 Em Atraso (Cobrar!)", m_fmt(tot_atrasado_cobrar))

    with st.expander("➕ Cadastrar Novo Valor a Receber / Cobrança de Terceiro", expanded=True):
        with st.form("form_novo_recebimento", clear_on_submit=True):
            rc1, rc2, rc3 = st.columns(3)
            quem_paga = rc1.text_input("Quem vai pagar? / Origem (Ex: Aluno Consultoria, Empréstimo)")
            valor_rec = rc2.number_input("Valor Total a Receber (R$)", min_value=0.0, format="%.2f")
            cat_rec = rc3.selectbox("Categoria", [
                "Cobrança de Terceiros / Empréstimo", "Consultoria / Personal",
                "Venda / Serviço Extra", "Reembolso / Rateio", "Salário / Bônus Extra"
            ])
            rc4, rc5, rc6, rc7 = st.columns(4)
            data_prevista = rc4.date_input("Data Prevista", value=hoje_data)
            parcelas_rec = rc5.number_input("Parcelas", min_value=1, max_value=24, value=1)
            whatsapp_terceiro = rc6.text_input("WhatsApp (Opcional)", placeholder="21999999999")
            status_inicial_rec = rc7.selectbox("Status", ["Pendente", "Pago"])

            if st.form_submit_button("💾 Registrar Recebimento", type="primary"):
                if quem_paga and valor_rec > 0:
                    val_parcela_rec = valor_rec / parcelas_rec
                    for i in range(parcelas_rec):
                        dt_venc_rec = data_prevista + relativedelta(months=i)
                        sufixo_parc = f" ({i+1}/{parcelas_rec})" if parcelas_rec > 1 else ""
                        det_rec = f"Tel: {whatsapp_terceiro.strip()}" if whatsapp_terceiro.strip() else "Previsão de Recebimento"
                        executar_query(
                            "INSERT INTO transacoes (usuario_id, tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (USER_ID, "Receita", f"{quem_paga.strip()}{sufixo_parc}", cat_rec, val_parcela_rec, dt_venc_rec, det_rec, status_inicial_rec, st.session_state.perfil_ativo, None)
                        )
                    st.success("✅ Recebimento registrado!")
                    st.rerun()

    st.markdown("---")
    filtro_status_rec = st.radio("Filtrar:", ["⏳ Pendentes (A Cobrar)", "✅ Já Recebidos", "📊 Todos"], horizontal=True)
    if not df_rec_all.empty:
        df_rec_view = df_rec_all.sort_values('data_competencia_dt').copy()
        if "Pendentes" in filtro_status_rec: df_rec_view = df_rec_view[df_rec_view['status'] == 'Pendente']
        elif "Já Recebidos" in filtro_status_rec: df_rec_view = df_rec_view[df_rec_view['status'] == 'Pago']

        for _, row in df_rec_view.iterrows():
            dt_item = row['data_apenas']
            dias_diff = (dt_item - hoje_data).days if pd.notna(dt_item) else 0
            badge = "🟢 RECEBIDO" if row['status'] == 'Pago' else f"🚨 ATRASADO ({abs(dias_diff)}d)" if dias_diff < 0 else "⚠️ VENCE HOJE" if dias_diff == 0 else f"📅 EM {dias_diff} DIAS"
            with st.expander(f"{badge} | {row['descricao']} — {m_fmt(row['valor'])} ({dt_item.strftime('%d/%m/%Y') if pd.notna(dt_item) else 'N/A'})"):
                msg_wpp = urllib.parse.quote(f"Olá! Passando para lembrar do nosso combinado referente a '{row['descricao']}' no valor de {m_fmt(row['valor'])}. Me avise assim que conseguir confirmar!")
                num_limpo = "".join([c for c in str(row['detalhes'] or "") if c.isdigit()])
                link_wpp = f"https://wa.me/55{num_limpo}?text={msg_wpp}" if len(num_limpo) >= 10 else f"https://wa.me/?text={msg_wpp}"
                st.markdown(f"📲 **[Enviar lembrete via WhatsApp]({link_wpp})**")
                cb1, cb2 = st.columns(2)
                if row['status'] == 'Pendente':
                    if cb1.button("✅ Confirmar Recebimento", key=f"rec_pay_{row['id']}", type="primary"):
                        executar_query("UPDATE transacoes SET status = 'Pago' WHERE id = ? AND usuario_id = ?", (int(row['id']), USER_ID))
                        st.rerun()
                else:
                    if cb1.button("↩️ Voltar p/ Pendente", key=f"rec_pend_{row['id']}"):
                        executar_query("UPDATE transacoes SET status = 'Pendente' WHERE id = ? AND usuario_id = ?", (int(row['id']), USER_ID))
                        st.rerun()
                if cb2.button("🗑️ Excluir", key=f"rec_del_{row['id']}"):
                    executar_query("DELETE FROM transacoes WHERE id = ? AND usuario_id = ?", (int(row['id']), USER_ID))
                    st.rerun()

# =====================================================================
# TAB 4 (tabs[3]): DESPESAS, BAIXA MENSAL, CARTÕES E WISHLIST INTELIGENTE
# =====================================================================
with tabs[3]:
    op_menu = st.radio("Painel Operacional:", ["➕ Lançar Despesa", "✅ Dar Baixa nas Contas do Mês", "💳 Auditoria de Cartões", "🛒 Simulador 'Posso Comprar?' & Wishlist"], horizontal=True)
    
    if op_menu == "➕ Lançar Despesa":
        with st.form("form_lanc", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            tipo = c1.radio("Fluxo", ["Despesa", "Receita"], horizontal=True)
            valor = c2.number_input("Valor Total (R$)", min_value=0.0, format="%.2f")
            forma = c3.selectbox("Método", ["Cartão de Crédito", "PIX", "Boleto", "Débito", "Dinheiro"])
            c4, c5, c6 = st.columns(3)
            descricao = c4.text_input("Descrição do Lançamento")
            categoria = c5.selectbox("Categoria", ["Moradia", "Alimentação", "Transporte", "Dieta/Treino", "Educação", "Saúde", "Eletrônicos", "Entretenimento", "Lazer", "Investimento", "Cartão", "Outros"])
            parcelas = c6.number_input("Nº Parcelas", min_value=1, value=1)
            c7, c8, c9 = st.columns(3)
            cartao_selecionado = c7.selectbox("Cartão Vinculado (se crédito):", ["N/A"] + cartoes_banco)
            data = c8.date_input("Vencimento 1ª Parcela", value=hoje_data)
            status = c9.selectbox("Status", ["Pendente", "Pago"])
            
            if st.form_submit_button("💾 Gravar Transação", type="primary"):
                if valor > 0 and descricao:
                    val_parc = valor / parcelas
                    cartao_envio = None if cartao_selecionado == "N/A" else cartao_selecionado
                    for i in range(parcelas):
                        d_venc = data + relativedelta(months=i)
                        detalhe_txt = f"{forma} | Parcela {i+1}/{parcelas}" if parcelas > 1 else forma
                        cartao_final = cartao_envio or detectar_cartao(descricao)
                        executar_query(
                            "INSERT INTO transacoes (usuario_id, tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (USER_ID, tipo, descricao.strip(), categoria, val_parc, d_venc, detalhe_txt, status, st.session_state.perfil_ativo, cartao_final)
                        )
                    st.success("✅ Lançamento gravado!")
                    st.rerun()

    elif op_menu == "✅ Dar Baixa nas Contas do Mês":
        st.subheader(f"Checklist de Contas de {hoje.strftime('%m/%Y')}")
        if not df_mes.empty:
            for _, r in df_mes[df_mes['tipo'] == 'Despesa'].sort_values(['status', 'data_competencia_dt']).iterrows():
                cb1, cb2, cb3, cb4 = st.columns([3, 2, 2, 2])
                cb1.write(f"**{r['descricao']}** ({r['categoria']})")
                cb2.write(f"Venc: {r['data_apenas'].strftime('%d/%m/%Y') if pd.notna(r['data_apenas']) else 'N/A'}")
                cb3.write(f"**{m_fmt(r['valor'])}** — {'🟢 Pago' if r['status'] == 'Pago' else '🔴 Pendente'}")
                if r['status'] == 'Pendente':
                    if cb4.button("✅ Marcar Pago", key=f"pay_d_{r['id']}"):
                        executar_query("UPDATE transacoes SET status = 'Pago' WHERE id = ? AND usuario_id = ?", (int(r['id']), USER_ID))
                        st.rerun()
                else:
                    if cb4.button("↩️ Reabrir", key=f"reop_d_{r['id']}"):
                        executar_query("UPDATE transacoes SET status = 'Pendente' WHERE id = ? AND usuario_id = ?", (int(r['id']), USER_ID))
                        st.rerun()
        else:
            st.info("Nenhuma despesa para o mês atual.")

    elif op_menu == "💳 Auditoria de Cartões":
        df_cartoes = df_trans[(df_trans['cartao_vinculado'].notnull()) & (df_trans['cartao_vinculado'] != 'None')].copy() if not df_trans.empty else pd.DataFrame()
        if not df_cartoes.empty:
            df_cartoes['Mês de Vencimento'] = df_cartoes['data_competencia_dt'].dt.strftime('%m/%Y')
            resumo_c = df_cartoes[df_cartoes['status'] == 'Pendente'].groupby(['cartao_vinculado', 'Mês de Vencimento'])['valor'].sum().reset_index()
            resumo_c['Total da Fatura'] = resumo_c['valor'].apply(m_fmt)
            st.dataframe(resumo_c[['cartao_vinculado', 'Mês de Vencimento', 'Total da Fatura']], use_container_width=True)
            filtro_c = st.selectbox("Filtrar Extrato por Cartão:", cartoes_banco)
            df_f = df_cartoes[df_cartoes['cartao_vinculado'] == filtro_c].sort_values('data_competencia_dt')
            if not df_f.empty:
                df_f['Valor Formatado'] = df_f['valor'].apply(m_fmt)
                st.dataframe(df_f[['data_competencia', 'descricao', 'Valor Formatado', 'status']], use_container_width=True)
        else:
            st.info("Nenhuma fatura mapeada.")

    elif op_menu == "🛒 Simulador 'Posso Comprar?' & Wishlist":
        st.subheader("🔮 Simulador de Impacto antes da Compra")
        c_w1, c_w2, c_w3, c_w4 = st.columns(4)
        w_item = c_w1.text_input("Item Desejado (Ex: Monitor, Viagem)")
        w_valor = c_w2.number_input("Valor Total (R$)", min_value=0.0, step=50.0)
        w_parc = c_w3.number_input("Simular em quantas parcelas?", min_value=1, max_value=24, value=1)
        w_prio = c_w4.selectbox("Prioridade", ["Alta", "Média", "Baixa"])
        
        if w_valor > 0:
            val_p_sim = w_valor / w_parc
            sobra_base = max(saldo_projetado_mes, renda_real_declarada * 0.25)
            impacto_pct = (val_p_sim / max(renda_real_declarada, 1)) * 100
            if saldo_projetado_mes >= val_p_sim and impacto_pct <= 15:
                st.success(f"🟢 **Compra Segura!** A parcela de **{m_fmt(val_p_sim)}** representa apenas **{impacto_pct:.1f}%** da sua renda base e cabe na sua sobra projetada ({m_fmt(saldo_projetado_mes)}).")
            elif impacto_pct <= 30:
                st.warning(f"🟡 **Atenção Moderada:** A parcela de **{m_fmt(val_p_sim)}** compromete **{impacto_pct:.1f}%** da sua renda mensal. Avalie aumentar o número de parcelas ou aguardar o próximo mês.")
            else:
                st.error(f"🔴 **Alto Risco para o Caixa:** A parcela de **{m_fmt(val_p_sim)}** consome **{impacto_pct:.1f}%** da sua renda mensal. Recomendado guardar o valor primeiro em um Cofrinho!")

        if st.button("➕ Salvar na Wishlist Planejada", type="primary"):
            if w_item and w_valor > 0:
                executar_query(
                    "INSERT INTO compras_futuras (usuario_id, item, valor, prioridade, parcelas, centro_custo) VALUES (?,?,?,?,?,?)",
                    (USER_ID, w_item.strip(), w_valor, w_prio, int(w_parc), st.session_state.perfil_ativo)
                )
                st.rerun()

        df_wish = get_df("SELECT * FROM compras_futuras WHERE usuario_id = ? AND centro_custo = ?", (USER_ID, st.session_state.perfil_ativo))
        for _, row in df_wish.iterrows():
            n_p = int(row.get('parcelas') or 1)
            with st.expander(f"🛍️ {row['item']} — {m_fmt(row['valor'])} ({n_p}x de {m_fmt(float(row['valor'])/n_p)}) [{row['prioridade']}]"):
                cw_a, cw_b = st.columns(2)
                if cw_a.button("✅ Comprei! Lançar nas Despesas", key=f"buy_w_{row['id']}", type="primary"):
                    vp = float(row['valor']) / n_p
                    for i in range(n_p):
                        executar_query(
                            "INSERT INTO transacoes (usuario_id, tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo) VALUES (?,?,?,?,?,?,?,?,?)",
                            (USER_ID, "Despesa", row['item'], "Outros", vp, hoje_data + relativedelta(months=i), f"Wishlist {i+1}/{n_p}", "Pendente", st.session_state.perfil_ativo)
                        )
                    executar_query("DELETE FROM compras_futuras WHERE id = ? AND usuario_id = ?", (int(row['id']), USER_ID))
                    st.rerun()
                if cw_b.button("🗑️ Remover da Lista", key=f"del_w_{row['id']}"):
                    executar_query("DELETE FROM compras_futuras WHERE id = ? AND usuario_id = ?", (int(row['id']), USER_ID))
                    st.rerun()

# =====================================================================
# TAB 5 (tabs[4]): INVESTIMENTOS & CUSTÓDIA AVANÇADA
# =====================================================================
with tabs[4]:
    st.header("📈 Carteira de Investimentos (Renda Fixa, Ações, FIIs e Cripto)")
    with st.expander("➕ Registrar Ativo ou Aplicação Financeira"):
        with st.form("form_ativo", clear_on_submit=True):
            ca1, ca2, ca3, ca4, ca5 = st.columns(5)
            ticker = ca1.text_input("Código / Nome (Ex: PETR4, MXRF11, CDB INTER)").upper()
            tipo_ativo = ca2.selectbox("Classe", ["Renda Fixa (CDB/Tesouro/LCI)", "FII (Fundo Imobiliário)", "Ação B3", "Criptomoeda", "ETF / Exterior"])
            qtde = ca3.number_input("Quantidade / Cotas", min_value=0.0001, value=1.0, format="%.4f")
            preco_medio = ca4.number_input("Preço Médio / Valor Aplicado (R$)", min_value=0.0, value=100.0)
            taxa_anual = ca5.number_input("Taxa Anual % (Se Renda Fixa)", min_value=0.0, value=11.25)
            if st.form_submit_button("💾 Salvar Ativo na Carteira", type="primary"):
                if ticker and preco_medio > 0:
                    executar_query(
                        "INSERT INTO investimentos (usuario_id, ticker, tipo_ativo, quantidade, preco_medio, taxa_fixa_anual, data_compra, centro_custo) VALUES (?,?,?,?,?,?,?,?)",
                        (USER_ID, ticker.strip(), tipo_ativo, qtde, preco_medio, taxa_anual, hoje_data, st.session_state.perfil_ativo)
                    )
                    st.success("✅ Ativo adicionado à carteira!")
                    st.rerun()

    if not df_invest.empty:
        dados_carteira = []
        pat_inv, pat_atual = 0.0, 0.0
        for _, row in df_invest.iterrows():
            tot_pago = float(row['quantidade']) * float(row['preco_medio'])
            if "Renda Fixa" in str(row['tipo_ativo']):
                dias_decorridos = max(0, (hoje_data - pd.to_datetime(row['data_compra']).date()).days) if pd.notna(row['data_compra']) else 30
                taxa_aa = float(row.get('taxa_fixa_anual') or 11.25) / 100.0
                fator = (1.0 + taxa_aa) ** (dias_decorridos / 365.0)
                tot_hoje = tot_pago * fator
            else:
                preco_hoje = obter_cotacao_atual(row['ticker'])
                if preco_hoje <= 0:
                    preco_hoje = float(row['preco_medio'])
                tot_hoje = float(row['quantidade']) * preco_hoje
            pat_inv += tot_pago
            pat_atual += tot_hoje
            dados_carteira.append({
                "ID": row['id'], "Ativo": row['ticker'], "Classe": row['tipo_ativo'],
                "Qtde": row['quantidade'], "Custo Total": m_fmt(tot_pago),
                "Posição Atual": m_fmt(tot_hoje), "ValorizaçãoBruta": tot_hoje,
                "Rentabilidade": f"{((tot_hoje - tot_pago)/tot_pago*100) if tot_pago > 0 else 0:.2f}%"
            })
        ci1, ci2, ci3 = st.columns(3)
        ci1.metric("💵 Total Aportado", m_fmt(pat_inv))
        ci2.metric("💎 Patrimônio Atualizado", m_fmt(pat_atual), m_fmt(pat_atual - pat_inv))
        ci3.metric("📈 Rentabilidade Consolidada", f"{((pat_atual - pat_inv) / pat_inv * 100) if pat_inv > 0 else 0:.2f}%")
        
        df_cart_view = pd.DataFrame(dados_carteira)
        col_t1, col_t2 = st.columns([2, 1])
        with col_t1:
            st.dataframe(df_cart_view.drop(columns=['ValorizaçãoBruta']), use_container_width=True)
        with col_t2:
            fig_aloc = px.pie(df_cart_view, values='ValorizaçãoBruta', names='Classe', title="Alocação por Classe de Ativo", template="plotly_dark", hole=0.4)
            st.plotly_chart(fig_aloc, use_container_width=True)
    else:
        st.info("Sua carteira de investimentos está vazia. Cadastre seu primeiro ativo acima!")

# =====================================================================
# TAB 6 (tabs[5]): CONSULTOR GOOGLE GEMINI IA (MODO VIP ADMIN VS FREE)
# =====================================================================
with tabs[5]:
    st.header("🤖 Consultor Financeiro Google Gemini IA & Contas Futuras")
    
    top_categorias = df_mes[df_mes['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().to_dict() if not df_mes.empty else {}
    resumo_contexto_ia = (
        f"- Renda Base Mensal: {m_fmt(renda_real_declarada)} | Entradas Confirmadas no Mês: {m_fmt(entradas_confirmadas)}\n"
        f"- Despesas Totais deste Mês ({hoje.strftime('%m/%Y')}): {m_fmt(despesas_totais_mes)} (Pendentes: {m_fmt(despesas_pendentes_mes)})\n"
        f"- Saldo Disponível Hoje: {m_fmt(saldo_livre_atual)} | Saldo Projetado com Recebíveis: {m_fmt(saldo_projetado_mes)}\n"
        f"- Guardado em Poupança/Cofrinhos: {m_fmt(total_poupanca_guardado)} | Investido em Carteira: {m_fmt(total_investido_custo)}\n"
        f"- Gastos por Categoria no Mês: {top_categorias}"
    )

    col_ia1, col_ia2 = st.columns([2, 1])
    with col_ia2:
        st.markdown("#### 🔑 Motor Google Gemini")
        chave_detectada = obter_chave_gemini_secrets()
        if chave_detectada:
            st.success("✅ Chave Gemini Global Ativa nos Secrets")
        else:
            st.warning("⚠️ Chave não detectada nos Secrets.")
        
        if IS_ADMIN:
            modelo_escolhido_admin = st.selectbox(
                "👑 Motor Exclusivo Admin:",
                ["gemini-2.5-pro", "gemini-2.5-flash"],
                help="Como Admin/Dono, você pode alternar entre o Gemini 2.5 Pro (máxima inteligência) e o 2.5 Flash (alta velocidade)."
            )
        else:
            modelo_escolhido_admin = "gemini-2.5-flash"

        api_key_input = st.text_input("Chave API Própria (Opcional / BYOK):", type="password")
        consumo_hoje = obter_consumo_ia_hoje()
        rotulo_limite = "∞ Ilimitado (Admin)" if IS_ADMIN else f"{LIMITES_IA.get(USER_PLANO, 5)}/dia"
        st.info(f"👤 Conta: **{'ADMIN / DONO' if IS_ADMIN else USER_PLANO.upper()}**\n\n📊 Uso hoje: **{consumo_hoje} / {rotulo_limite}**")
        
    with col_ia1:
        st.markdown("#### 💬 Pergunte ao Gemini sobre suas Finanças")
        b_ia1, b_ia2, b_ia3 = st.columns(3)
        pergunta_rapida = None
        if b_ia1.button("🔍 Auditar Gastos do Mês", use_container_width=True):
            pergunta_rapida = "Faça uma auditoria detalhada dos meus gastos deste mês, aponte os maiores pesos no orçamento e diga quanto posso guardar na poupança."
        if b_ia2.button("✂️ Plano de Corte de Custos", use_container_width=True):
            pergunta_rapida = "Crie um plano prático em 3 passos para eu reduzir minhas despesas mensais e aumentar minha sobra de caixa."
        if b_ia3.button("📈 Estratégia de Investimentos", use_container_width=True):
            pergunta_rapida = "Com base na minha renda, despesas e saldo em poupança, como devo dividir meus aportes mensais entre Reserva de Emergência e Investimentos?"
            
        pergunta_custom = st.text_input("Ou digite sua pergunta personalizada para a IA:", placeholder="Ex: Analise minhas despesas de novembro e monte uma meta para dezembro.")
        if st.button("✨ Gerar Análise Profunda com IA", type="primary"):
            pergunta_rapida = pergunta_custom or "Faça um diagnóstico completo da minha saúde financeira atual."

        if pergunta_rapida:
            with st.spinner("🤖 O Google Gemini está analisando seus indicadores financeiros..."):
                resposta_ia = consultar_gemini_ia(pergunta_rapida, resumo_contexto_ia, api_key_input, modelo_escolhido_admin)
                st.markdown(f"<div class='ai-response-box'>{resposta_ia}</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🗓️ Projeção de Contas Futuras e Recebíveis")
    meses_frente = st.slider("Mapear quantos meses à frente?", 1, 12, 6)
    lista_meses = [(hoje + relativedelta(months=i)).strftime('%m/%Y') for i in range(meses_frente)]
    df_base = pd.DataFrame({'Mês Referência': lista_meses})
    inicio_mes_atual = datetime(hoje.year, hoje.month, 1)
    data_limite = hoje + relativedelta(months=meses_frente)
    
    if not df_trans.empty:
        df_fut_desp = df_trans[(df_trans['tipo'] == 'Despesa') & (df_trans['status'] == 'Pendente') & (df_trans['data_competencia_dt'] >= inicio_mes_atual) & (df_trans['data_competencia_dt'] <= data_limite)].copy()
        df_fut_rec_pend = df_trans[(df_trans['tipo'] == 'Receita') & (df_trans['status'] == 'Pendente') & (df_trans['data_competencia_dt'] >= inicio_mes_atual) & (df_trans['data_competencia_dt'] <= data_limite)].copy()
        
        res_desp = df_fut_desp.assign(**{'Mês Referência': df_fut_desp['data_competencia_dt'].dt.strftime('%m/%Y')}).groupby('Mês Referência')['valor'].sum().reset_index().rename(columns={'valor': 'desp'}) if not df_fut_desp.empty else pd.DataFrame(columns=['Mês Referência', 'desp'])
        res_rec = df_fut_rec_pend.assign(**{'Mês Referência': df_fut_rec_pend['data_competencia_dt'].dt.strftime('%m/%Y')}).groupby('Mês Referência')['valor'].sum().reset_index().rename(columns={'valor': 'rec'}) if not df_fut_rec_pend.empty else pd.DataFrame(columns=['Mês Referência', 'rec'])
        
        df_final = pd.merge(df_base, res_desp, on='Mês Referência', how='left')
        df_final = pd.merge(df_final, res_rec, on='Mês Referência', how='left').fillna(0)
        df_final['Sobra Projetada'] = (renda_real_declarada + df_final['rec']) - df_final['desp']
        df_final['Contas a Pagar'] = df_final['desp'].apply(m_fmt)
        df_final['A Receber'] = df_final['rec'].apply(m_fmt)
        df_final['Saldo Projetado (c/ Renda Base)'] = df_final['Sobra Projetada'].apply(m_fmt)
        st.table(df_final[['Mês Referência', 'Contas a Pagar', 'A Receber', 'Saldo Projetado (c/ Renda Base)']])

# =====================================================================
# TAB 7 (tabs[6]): SIMULADORES & MERCADO 3D (COM CACHE DIÁRIO)
# =====================================================================
with tabs[6]:
    sim = st.radio("Ferramenta Estratégica:", ["📐 Orçamento Base-Zero", "🔥 Independência Financeira (F.I.R.E)", "🏦 Simulador Tabela Price", "💎 Curva 3D & Cotações do Dia"], horizontal=True)
    if sim == "📐 Orçamento Base-Zero":
        c_s1, c_s2 = st.columns(2)
        p_essencial = c_s1.slider("🏠 Custos Essenciais e Moradia (%)", 0, 100, 50)
        p_estilo = c_s2.slider("🏋️ Estilo de Vida, Dieta e Lazer (%)", 0, 100, 20)
        p_poup = c_s1.slider("🐷 Poupança, Reserva & Metas (%)", 0, 100, 15)
        p_inv = c_s2.slider("📈 Investimentos de Longo Prazo (%)", 0, 100, 15)
        soma_p = p_essencial + p_estilo + p_poup + p_inv
        if soma_p == 100:
            k_s1, k_s2, k_s3, k_s4 = st.columns(4)
            k_s1.metric("Essenciais", m_fmt(renda_real_declarada * p_essencial / 100))
            k_s2.metric("Estilo de Vida", m_fmt(renda_real_declarada * p_estilo / 100))
            k_s3.metric("Poupança / Cofrinhos", m_fmt(renda_real_declarada * p_poup / 100))
            k_s4.metric("Investimentos", m_fmt(renda_real_declarada * p_inv / 100))
        else:
            st.warning(f"Ajuste os percentuais para somar 100% (Soma atual: {soma_p}%).")

    elif sim == "🔥 Independência Financeira (F.I.R.E)":
        renda_passiva = st.number_input("Renda Passiva Mensal Desejada (R$)", value=5000.0, step=500.0)
        pat_necessario = (renda_passiva * 12) / 0.04
        st.success(f"🎯 **Meta F.I.R.E.:** Acumule **{m_fmt(pat_necessario)}** para gerar {m_fmt(renda_passiva)}/mês perpetuamente (Regra dos 4%).")

    elif sim == "🏦 Simulador Tabela Price":
        v = st.number_input("Valor Financiado (R$)", value=20000.0)
        t = st.number_input("Taxa Mensal (%)", value=1.5, step=0.1)
        m = st.slider("Prazo (Meses)", 6, 72, 36)
        p = calcular_price(v, t, m)
        st.error(f"Parcela Fixa: **{m_fmt(p)}** | Total Pago: **{m_fmt(p*m)}** | Só de Juros: **{m_fmt((p*m)-v)}**.")

    elif sim == "💎 Curva 3D & Cotações do Dia":
        cr1, cr2 = st.columns([2, 1])
        with cr1:
            anos = np.linspace(1, 25, 25)
            taxas = np.linspace(0.06, 0.18, 13)
            X, Y = np.meshgrid(anos, taxas)
            Z = 1000 * ((1 + Y)**X)
            fig_3d = go.Figure(data=[go.Surface(z=Z, x=X, y=Y, colorscale='Viridis')])
            fig_3d.update_layout(height=420, scene=dict(xaxis_title='Anos', yaxis_title='Taxa a.a.', zaxis_title='Multiplicador'), template="plotly_dark", margin=dict(l=0, r=0, b=0, t=10))
            st.plotly_chart(fig_3d, use_container_width=True)
        with cr2:
            if st.button("🔄 Atualizar Indicadores Agora", use_container_width=True):
                sincronizar_mercado_diario(forcar=True)
                st.success("✅ Cotações e Selic atualizadas!")
                st.rerun()
            df_selic = get_df("SELECT preco, atualizado_em FROM cotacoes_cache WHERE ticker = 'SELIC_META'")
            if not df_selic.empty and float(df_selic.iloc[0]['preco']) > 0:
                selic_v = float(df_selic.iloc[0]['preco'])
                st.metric("🏦 Selic Meta (a.a.)", f"{selic_v:.2f}%")
                st.metric("💠 CDI Estimado (a.a.)", f"{max(0.0, selic_v - 0.10):.2f}%")
                st.caption(f"Cache de {pd.to_datetime(df_selic.iloc[0]['atualizado_em']).strftime('%d/%m/%Y %H:%M')}")
            for nome, tk in {"Dólar (R$)": "USDBRL=X", "Euro (R$)": "EURBRL=X", "Bitcoin (USD)": "BTC-USD", "Ibovespa": "^BVSP"}.items():
                st.metric(nome, f"{obter_cotacao_atual(tk):,.2f}")

# =====================================================================
# TAB 8 (tabs[7]): CONTA, BACKUP E PAINEL EXCLUSIVO DO ADMIN (SAAS)
# =====================================================================
with tabs[7]:
    st.header(f"⚙️ Gestão de Dados, Backup & Administração ({USER_NOME})")
    
    # --- PAINEL EXCLUSIVO DO ADMINISTRADOR (DONO DO SISTEMA) ---
    if IS_ADMIN:
        with st.expander("👑 PAINEL MASTER DO ADMINISTRADOR (Gestão de Clientes, Planos e Unificação)", expanded=True):
            st.caption("Controle exclusivo da sua conta Admin: gerencie planos de usuários (FREE / PRO / DONO), redefina senhas ou unifique dados.")
            df_raw_users = get_df("SELECT * FROM usuarios ORDER BY id")
            cols_u = [c for c in ['id', 'nome', 'email', 'plano', 'role', 'renda_mensal'] if c in df_raw_users.columns]
            df_todos_users = df_raw_users[cols_u]
            st.dataframe(df_todos_users, use_container_width=True)
            
            adm_c1, adm_c2, adm_c3, adm_c4 = st.columns(4)
            u_alvo = adm_c1.selectbox("Selecionar ID de Usuário:", df_todos_users['id'].tolist())
            novo_plano_u = adm_c2.selectbox("Alterar Plano para:", ["free", "pro", "dono"])
            if adm_c3.button("💾 Salvar Plano do Usuário", type="primary"):
                role_novo = "admin" if novo_plano_u == "dono" else "user"
                executar_query("UPDATE usuarios SET plano = ?, role = ? WHERE id = ?", (novo_plano_u, role_novo, int(u_alvo)))
                if int(u_alvo) == USER_ID:
                    st.session_state.usuario_logado["plano"] = novo_plano_u
                st.success(f"✅ Usuário ID {u_alvo} atualizado para o plano {novo_plano_u.upper()}!")
                st.rerun()
            if adm_c4.button("🔄 Puxar Dados da Conta Secundária p/ Admin"):
                df_sec_u = get_df("SELECT id FROM usuarios WHERE LOWER(email) = 'terstegenelionelmessi@gmail.com'")
                if not df_sec_u.empty:
                    id_s = int(df_sec_u.iloc[0]['id'])
                    executar_query("UPDATE transacoes SET usuario_id = ? WHERE usuario_id = ?", (USER_ID, id_s))
                    executar_query("UPDATE compras_futuras SET usuario_id = ? WHERE usuario_id = ?", (USER_ID, id_s))
                    executar_query("UPDATE investimentos SET usuario_id = ? WHERE usuario_id = ?", (USER_ID, id_s))
                    executar_query("UPDATE poupanca_metas SET usuario_id = ? WHERE usuario_id = ?", (USER_ID, id_s))
                    st.success("✅ Todos os registros foram unificados na sua conta Admin!")
                    st.rerun()

            st.markdown("##### 🔐 Redefinir Senha de Qualquer Usuário (Sem precisar de script externo)")
            rs1, rs2 = st.columns([2, 1])
            nova_senha_adm = rs1.text_input(f"Nova senha para o Usuário ID {u_alvo}:", type="password", key="adm_pw_reset")
            if rs2.button("🔑 Atualizar Senha Criptografada"):
                if len(nova_senha_adm) >= 4:
                    executar_query("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (gerar_hash_senha(nova_senha_adm), int(u_alvo)))
                    st.success(f"✅ Senha do usuário ID {u_alvo} atualizada com criptografia PBKDF2-SHA256!")
                else:
                    st.warning("Digite pelo menos 4 caracteres.")

    df_tudo_user = get_df("SELECT * FROM transacoes WHERE usuario_id = ? ORDER BY data_competencia DESC", (USER_ID,))
    
    c_adm1, c_adm2 = st.columns(2)
    with c_adm1:
        st.subheader("🛡️ 1. Exportar Backup Pessoal (.CSV)")
        if not df_tudo_user.empty:
            csv_bkp = df_tudo_user.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Baixar Planilha Completa dos Meus Dados", data=csv_bkp, file_name=f"backup_{USER_NOME.split()[0]}_{hoje.strftime('%Y%m%d')}.csv", mime="text/csv")
        else:
            st.caption("Sem transações para exportar.")

    with c_adm2:
        st.subheader("🔄 2. Importar Arquivo `Despesas.db` na Minha Conta")
        preservar_rec = st.checkbox("Preservar minhas Receitas e Cobranças ao atualizar Despesas", value=True)
        arq_db = st.file_uploader("Arquivo .db / .sqlite", type=["db", "sqlite", "sqlite3"])
        if arq_db is not None and st.button("🚀 Sincronizar Arquivo na Minha Conta", type="primary"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp.write(arq_db.read())
                caminho_tmp = tmp.name
            try:
                tot_imp = importar_arquivo_sqlite_usuario(caminho_tmp, USER_ID, st.session_state.perfil_ativo, preservar_manuais=preservar_rec)
                st.success(f"✅ {tot_imp} registros sincronizados exclusivamente na sua conta!")
                st.rerun()
            finally:
                if os.path.exists(caminho_tmp):
                    os.remove(caminho_tmp)

    st.markdown("---")
    st.subheader("📋 3. Base de Lançamentos da Sua Conta")
    if not df_tudo_user.empty:
        df_tudo_user['valor_formatado'] = df_tudo_user['valor'].apply(m_fmt)
        cols_ex = [c for c in ['id', 'tipo', 'descricao', 'categoria', 'valor_formatado', 'data_competencia', 'status', 'cartao_vinculado'] if c in df_tudo_user.columns]
        st.dataframe(df_tudo_user[cols_ex], use_container_width=True)
        
        ca1, ca2, ca3, ca4 = st.columns(4)
        id_sel = ca1.selectbox("ID do Registro:", df_tudo_user['id'].tolist())
        novo_st = ca2.selectbox("Novo Status:", ["Pago", "Pendente"])
        if ca3.button("💾 Alterar Status"):
            executar_query("UPDATE transacoes SET status = ? WHERE id = ? AND usuario_id = ?", (novo_st, int(id_sel), USER_ID))
            st.rerun()
        if ca4.button("🗑️ Excluir ID"):
            executar_query("DELETE FROM transacoes WHERE id = ? AND usuario_id = ?", (int(id_sel), USER_ID))
            st.rerun()