"""
renomear_com_codigo.py
======================
Renomeia os arquivos já baixados na pasta 'convencoes' adicionando o código
do sindicato no início do nome.

Estratégia de correspondência:
  - Remove acentos e normaliza tanto o nome do arquivo quanto os nomes da planilha
  - Tenta correspondência exata de substring (nome do sindicato da planilha dentro do nome do arquivo)
  - Se não encontrar, usa correspondência por score de palavras em comum (fuzzy simples)
  - Gera um relatório ao final mostrando o que foi renomeado e o que não foi encontrado
"""

import os
import re
import unicodedata
import pandas as pd

# ── Configurações ──────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONV_DIR   = os.path.join(BASE_DIR, "convencoes")
SIS_FILE   = os.path.join(BASE_DIR, "sindicatosistema.xlsx")
# ──────────────────────────────────────────────────────────────────────────────


def normalizar(texto):
    """Remove acentos, coloca em maiúsculas e limpa espaços extras."""
    txt = str(texto)
    txt = unicodedata.normalize('NFD', txt).encode('ascii', 'ignore').decode('utf-8')
    txt = re.sub(r'\s+', ' ', txt).upper().strip()
    return txt


def score_palavras(texto_arquivo, texto_sindicato):
    """
    Calcula quantas palavras do nome do sindicato (planilha) estão presentes
    no nome do arquivo. Retorna proporção 0.0–1.0.
    Ignora palavras curtas (artigos, preposições etc.).
    """
    STOP = {'DE', 'DO', 'DA', 'DOS', 'DAS', 'EM', 'NO', 'NA', 'NOS', 'NAS',
            'E', 'A', 'O', 'AS', 'OS', 'EM', 'COM', 'POR', 'PARA', 'AO', 'AOS'}
    palavras = [p for p in texto_sindicato.split() if len(p) > 2 and p not in STOP]
    if not palavras:
        return 0.0
    encontradas = sum(1 for p in palavras if p in texto_arquivo)
    return encontradas / len(palavras)


def carregar_mapa_sindicatos():
    """Carrega sindicatosistema.xlsx e retorna lista de (codigo, sindicato_normalizado)."""
    df = pd.read_excel(SIS_FILE)
    col_sind   = next((c for c in df.columns if 'sindicato' in str(c).lower()), None)
    col_codigo = next((c for c in df.columns if 'codigo'    in str(c).lower()), None)
    if not col_sind or not col_codigo:
        raise ValueError("Colunas 'sindicato' e/ou 'codigo' não encontradas em sindicatosistema.xlsx")
    registros = []
    for _, row in df.iterrows():
        cod  = str(row[col_codigo]).strip()
        sind = normalizar(row[col_sind])
        registros.append((cod, sind))
    return registros


def ja_tem_prefixo(nome_arquivo, registros):
    """Retorna True se o arquivo já começa com algum código (ex: '356-CCT-...')."""
    codigos = {r[0] for r in registros}
    partes = nome_arquivo.split('-', 1)
    return partes[0].strip() in codigos


def encontrar_codigo(nome_norm, registros, limiar=0.60):
    """
    Tenta encontrar o código do sindicato mais compatível com o nome do arquivo.
    Retorna (codigo, score) ou (None, 0) se não encontrou.
    """
    melhor_cod   = None
    melhor_score = 0.0

    for cod, sind_norm in registros:
        # Tenta substring exata primeiro
        if sind_norm in nome_norm or nome_norm.startswith(sind_norm[:30]):
            return cod, 1.0

        s = score_palavras(nome_norm, sind_norm)
        if s > melhor_score:
            melhor_score = s
            melhor_cod   = cod

    if melhor_score >= limiar:
        return melhor_cod, melhor_score
    return None, melhor_score


def main():
    print("=" * 65)
    print("RENOMEAÇÃO DE ARQUIVOS — ADICIONANDO CÓDIGO DO SINDICATO")
    print("=" * 65)

    # Carrega mapa de códigos
    try:
        registros = carregar_mapa_sindicatos()
        print(f"Sindicatos carregados: {len(registros)} registro(s)\n")
    except Exception as e:
        print(f"[ERRO] {e}")
        return

    # Lista arquivos da pasta convencoes
    arquivos = sorted([
        f for f in os.listdir(CONV_DIR)
        if os.path.isfile(os.path.join(CONV_DIR, f))
    ])
    print(f"Arquivos encontrados em 'convencoes': {len(arquivos)}\n")

    renomeados   = []
    ja_prefixado = []
    nao_encontrados = []

    for nome_orig in arquivos:
        nome_sem_ext, ext = os.path.splitext(nome_orig)

        # Pula se já tem prefixo de código
        if ja_tem_prefixo(nome_sem_ext, registros):
            ja_prefixado.append(nome_orig)
            print(f"  [JÁ PREFIXADO] {nome_orig}")
            continue

        nome_norm = normalizar(nome_sem_ext)
        codigo, score = encontrar_codigo(nome_norm, registros)

        if codigo:
            novo_nome = f"{codigo}-{nome_orig}"
            caminho_orig = os.path.join(CONV_DIR, nome_orig)
            caminho_novo = os.path.join(CONV_DIR, novo_nome)

            # Evita sobrescrever se já existir
            if os.path.exists(caminho_novo):
                print(f"  [PULANDO] Destino já existe: {novo_nome}")
                ja_prefixado.append(nome_orig)
                continue

            os.rename(caminho_orig, caminho_novo)
            print(f"  [OK] {nome_orig}")
            print(f"    -> {novo_nome}  (score={score:.0%})")
            renomeados.append((nome_orig, novo_nome, score))
        else:
            print(f"  [NÃO ENCONTRADO] {nome_orig}  (melhor score={score:.0%})")
            nao_encontrados.append((nome_orig, score))

    # ── Relatório final ────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"RESUMO:")
    print(f"  Renomeados com sucesso : {len(renomeados)}")
    print(f"  Já tinham prefixo      : {len(ja_prefixado)}")
    print(f"  Não encontrados        : {len(nao_encontrados)}")
    print("=" * 65)

    if nao_encontrados:
        print("\nArquivos sem correspondência (verifique manualmente):")
        for nome, score in nao_encontrados:
            print(f"  {nome}  (melhor score={score:.0%})")

    print("\nConcluído!")


if __name__ == "__main__":
    main()
