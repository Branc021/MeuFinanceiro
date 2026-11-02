import sqlite3
import psycopg2
from psycopg2.extras import execute_batch

print("🔄 Iniciando a substituição completa de dados a partir do Despesas.db...")

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

# 1. Conecta no arquivo Despesas.db local
conn_local = sqlite3.connect('Despesas.db')
cursor_local = conn_local.cursor()

# 2. Conecta no Supabase
url_supabase = "postgresql://postgres.jyadrltgnuavejptvzam:Brancogoleiro123*@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"
conn_nuvem = psycopg2.connect(url_supabase)
cursor_nuvem = conn_nuvem.cursor()

try:
    # Lê as despesas e categorias do Despesas.db
    cursor_local.execute("""
        SELECT 
            e.description,
            COALESCE(c.name, 'Outros') as categoria,
            e.price,
            e.dateTransaction,
            e.status,
            e.countPart
        FROM expense e
        LEFT JOIN category c ON e.categoryId = c.id
    """)
    linhas = cursor_local.fetchall()
    
    registros = []
    for desc, cat, preco, data_tx, status_raw, count_part in linhas:
        descricao_limpa = str(desc).strip()
        categoria_limpa = str(cat).strip()
        valor_float = float(preco) if preco is not None else 0.0
        data_limpa = str(data_tx).strip()[:10]
        status_final = "Pago" if str(status_raw).strip().upper() == "PAID" else "Pendente"
        detalhes_txt = f"Importado | Parte {count_part}" if count_part else "Importado"
        cartao_vinc = detectar_cartao(descricao_limpa)
        
        registros.append((
            "Despesa", descricao_limpa, categoria_limpa, valor_float,
            data_limpa, detalhes_txt, status_final, "Pessoal", cartao_vinc
        ))

    # Limpa a tabela antiga no Supabase e insere todos os novos registros
    cursor_nuvem.execute("TRUNCATE TABLE transacoes RESTART IDENTITY")
    
    sql_insert = """
        INSERT INTO transacoes 
        (tipo, descricao, categoria, valor, data_competencia, detalhes, status, centro_custo, cartao_vinculado) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    execute_batch(cursor_nuvem, sql_insert, registros, page_size=100)
    conn_nuvem.commit()
    
    print(f"✅ Sucesso! O banco antigo foi limpo e {len(registros)} transações do Despesas.db foram gravadas na nuvem.")

except Exception as e:
    conn_nuvem.rollback()
    print(f"❌ Erro durante a migração: {e}")

finally:
    conn_local.close()
    conn_nuvem.close()