import sqlite3
import pandas as pd

print("Iniciando a limpeza e migração de dados...")

try:
    # 1. Extração
    conn_antigo = sqlite3.connect('Despesas.db')
    query = """
    SELECT 
        e.description AS descricao,
        c.name AS categoria,
        e.price AS valor,
        e.dateTransaction AS data_competencia,
        e.status
    FROM expense e
    LEFT JOIN category c ON e.categoryId = c.id
    """
    df_antigo = pd.read_sql_query(query, conn_antigo)
    conn_antigo.close()

    # 2. Transformação
    df_novo = pd.DataFrame()
    df_novo['tipo'] = 'Despesa'
    df_novo['descricao'] = df_antigo['descricao']
    df_novo['categoria'] = df_antigo['categoria']
    df_novo['valor'] = df_antigo['valor']

    # TRATAMENTO DE ERRO: Pegando apenas os 10 primeiros caracteres (YYYY-MM-DD) 
    # e forçando a conversão mesmo se o aplicativo antigo tiver gerado lixo
    datas_limpas = df_antigo['data_competencia'].astype(str).str[:10]
    df_novo['data_competencia'] = pd.to_datetime(datas_limpas, format='mixed', errors='coerce').dt.date

    df_novo['detalhes'] = "Importado do app antigo. Status: " + df_antigo['status'].astype(str)

    # 3. Carga
    conn_novo = sqlite3.connect('financeiro_master.db')
    df_novo.to_sql('transacoes', conn_novo, if_exists='append', index=False)
    conn_novo.close()

    print(f"✅ Sucesso! {len(df_novo)} registros foram higienizados e importados.")

except Exception as e:
    print(f"❌ Erro na importação: {e}")