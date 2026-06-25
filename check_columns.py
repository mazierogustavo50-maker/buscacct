import pandas as pd

try:
    df = pd.read_excel('cnpjs.xlsx')
    print("Colunas encontradas:")
    print(df.columns.tolist())
    print("\nPrimeiras linhas:")
    print(df.head())
except Exception as e:
    print("Erro ao ler o arquivo:", e)
