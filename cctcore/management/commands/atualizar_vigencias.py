import os
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from pathlib import Path

from cctcore.models import DocumentoCCT
from cctcore.services import extrair_texto_pdf


def parse_data_br(data_str):
    """Converte string de data brasileira para objeto date."""
    if not data_str:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(data_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_data_escrita(texto):
    """
    Converte datas por extenso brasileiras para objeto date.
    Ex: '01 de janeiro de 2025', '1º de junho de 2025', '31 de dezembro de 2026'
    """
    meses = {
        'JANEIRO': 1, 'FEVEREIRO': 2, 'MARCO': 3, 'ABRIL': 4,
        'MAIO': 5, 'JUNHO': 6, 'JULHO': 7, 'AGOSTO': 8,
        'SETEMBRO': 9, 'OUTUBRO': 10, 'NOVEMBRO': 11, 'DEZEMBRO': 12,
        'JAN': 1, 'FEV': 2, 'FEB': 2, 'MAR': 3, 'ABR': 4, 'APR': 4,
        'MAI': 5, 'MAY': 5, 'JUN': 6, 'JUL': 7, 'AGO': 8, 'AUG': 8,
        'SET': 9, 'SEP': 9, 'OUT': 10, 'OCT': 10, 'NOV': 11, 'DEZ': 12, 'DEC': 12,
    }
    # Remove acentos e padroniza
    t = texto.upper()
    t = re.sub(r'[ÁÀÂÃÄáàâãä]', 'A', t)
    t = re.sub(r'[ÉÈÊËéèêë]', 'E', t)
    t = re.sub(r'[ÍÌÎÏíìîï]', 'I', t)
    t = re.sub(r'[ÓÒÔÕÖóòôõö]', 'O', t)
    t = re.sub(r'[ÚÙÛÜúùûü]', 'U', t)
    t = re.sub(r'[Çç]', 'C', t)
    t = re.sub(r'[º°]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()

    # Padrão: 01 de janeiro de 2025  ou  1 de janeiro de 2025
    m = re.search(r'(\d{1,2})\s+DE\s+(\w+)\s+DE\s+(\d{4})', t)
    if m:
        dia = int(m.group(1))
        mes_nome = m.group(2).strip()
        ano = int(m.group(3))
        mes_num = meses.get(mes_nome)
        if mes_num and 1 <= dia <= 31:
            try:
                from datetime import date as dt_date
                return dt_date(ano, mes_num, dia)
            except ValueError:
                return None
    return None


def extrair_datas_do_texto(texto):
    """
    Extrai datas de vigência (início, fim) e registro MTE do texto de uma CCT.
    Retorna dict com as chaves: data_inicio, data_fim, data_registro_mte.
    """
    resultado = {
        "data_inicio": None,
        "data_fim": None,
        "data_registro_mte": None,
    }

    if not texto or len(texto) < 50:
        return resultado

    texto_upper = texto.upper()

    # ============================================================
    # 1. VIGÊNCIA - múltiplas estratégias
    # ============================================================

    # Estratégia 1a: "VIGENCIA DE DD/MM/AAAA A DD/MM/AAAA"
    m = re.search(
        r'VIG[ÊE]NCI?A\s*(?:DE)?\s*(\d{2}[/-]\d{2}[/-]\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{2}[/-]\d{2}[/-]\d{4})',
        texto_upper
    )
    if m:
        resultado["data_inicio"] = parse_data_br(m.group(1))
        resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1b: "VIGÊNCIA: DD/MM/AAAA - DD/MM/AAAA"
    if not resultado["data_inicio"]:
        m = re.search(
            r'VIG[ÊE]NCI?A\s*[:\-]\s*(\d{2}[/-]\d{2}[/-]\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{2}[/-]\d{2}[/-]\d{4})', 
            texto_upper
        )
        if m:
            resultado["data_inicio"] = parse_data_br(m.group(1))
            resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1c: "PERÍODO DE VIGÊNCIA" ou "PRAZO DE VIGÊNCIA"
    if not resultado["data_inicio"]:
        m = re.search(
            r'(?:PER[IÍ]ODO|PRAZO)\s*DE\s*VIG[ÊE]NCI?A.*?([\d]{2}[/-][\d]{2}[/-][\d]{4}).*?(?:A|AT[EÉ]|–|-).*?([\d]{2}[/-][\d]{2}[/-][\d]{4})',
            texto_upper, re.DOTALL
        )
        if m:
            resultado["data_inicio"] = parse_data_br(m.group(1))
            resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1d: "VIGENCIA ATE DD/MM/AAAA" ou "VIGENCIA DE ... ATE ..."
    if not resultado["data_fim"]:
        m = re.search(
            r'VIGEN[CGÇ][IA]*.*?AT[EÉ]\s*(\d{2}[/-]\d{2}[/-]\d{4})',
            texto_upper, re.IGNORECASE
        )
        if m:
            candidata_fim = parse_data_br(m.group(1))
            if candidata_fim:
                resultado["data_fim"] = candidata_fim

    # Estratégia 1e: Duas datas próximas em contexto de vigência (fallback)
    if not resultado["data_inicio"]:
        # Procura bloco com a palavra vigência e pega as duas primeiras datas
        blocos = re.split(r'VIGEN[CGÇ][IA]*', texto_upper)
        if len(blocos) > 1:
            for bloco in blocos[1:3]:
                datas = re.findall(r'(\d{2}[/-]\d{2}[/-]\d{4})', bloco[:500])
                if len(datas) >= 2:
                    resultado["data_inicio"] = parse_data_br(datas[0])
                    resultado["data_fim"] = parse_data_br(datas[1])
                    break
                elif len(datas) == 1:
                    resultado["data_inicio"] = parse_data_br(datas[0])
                    break

    # Estratégia 1f: Datas por extenso — "01 de janeiro de 2025 a 31 de dezembro de 2026"
    if not resultado["data_inicio"]:
        m = re.search(
            r'(\d{1,2}\s*º?\s*DE\s+\w+\s+DE\s+\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{1,2}\s*º?\s*DE\s+\w+\s+DE\s+\d{4})',
            texto, re.IGNORECASE
        )
        if m:
            resultado["data_inicio"] = _parse_data_escrita(m.group(1))
            resultado["data_fim"] = _parse_data_escrita(m.group(2))

    # Estratégia 1g: Vigência por extenso com "até"
    if not resultado["data_fim"]:
        m = re.search(
            r'VIGEN[CGÇ][IA]*.*?AT[EÉ]\s*(\d{1,2}\s*º?\s*DE\s+\w+\s+DE\s+\d{4})',
            texto, re.IGNORECASE
        )
        if m:
            resultado["data_fim"] = _parse_data_escrita(m.group(1))

    # Estratégia 1h: Se só achou uma data numérica, tenta achar outra no documento inteiro como fim
    if resultado["data_inicio"] and not resultado["data_fim"]:
        # Procura por "até" ou "a" seguido de data após a data de início no texto
        pos = texto_upper.find(str(resultado["data_inicio"]).replace("-", "/"))
        if pos >= 0:
            trecho = texto_upper[pos:pos+800]
            m_fim = re.search(r'(?:AT[EÉ]|A)\s*(\d{2}[/-]\d{2}[/-]\d{4})', trecho)
            if m_fim:
                resultado["data_fim"] = parse_data_br(m_fim.group(1))

    # Estratégia 1i: Se ainda não achou fim, procura a próxima data no documento inteiro
    # que seja diferente da data de início e posterior a ela
    if resultado["data_inicio"] and not resultado["data_fim"]:
        todas_datas = re.findall(r'(\d{2}[/-]\d{2}[/-]\d{4})', texto_upper)
        inicio_str = str(resultado["data_inicio"]).replace("-", "/")
        for d_str in todas_datas:
            if d_str != inicio_str:
                candidata = parse_data_br(d_str)
                if candidata and candidata > resultado["data_inicio"]:
                    resultado["data_fim"] = candidata
                    break

    # ============================================================
    # 2. DATA DE REGISTRO NO MTE
    # ============================================================

    # Estratégia 2a: "DATA DE REGISTRO NO MTE" ou "REGISTRO NO MTE"
    m = re.search(
        r'DATA\s*DE\s*REGISTRO\s*(?:NO\s*MTE)?\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
        texto_upper
    )
    if m:
        resultado["data_registro_mte"] = parse_data_br(m.group(1))

    # Estratégia 2b: "REGISTRADO EM DD/MM/AAAA NO MTE"
    if not resultado["data_registro_mte"]:
        m = re.search(
            r'REGISTRAD[OA]\s+(?:EM\s+)?(\d{2}[/-]\d{2}[/-]\d{4}).*?MTE',
            texto_upper
        )
        if m:
            resultado["data_registro_mte"] = parse_data_br(m.group(1))

    # Estratégia 2c: "REGISTRO: DD/MM/AAAA" próximo de "MTE" ou "MINISTÉRIO"
    if not resultado["data_registro_mte"]:
        m = re.search(
            r'REGISTRO\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})',
            texto_upper
        )
        if m:
            # Verifica se há menção a MTE/ministério em um raio de 300 chars
            pos_reg = texto_upper.find("REGISTRO")
            if pos_reg >= 0:
                trecho = texto_upper[max(0, pos_reg-200):pos_reg+300]
                if "MTE" in trecho or "MINISTERIO" in trecho or "MINISTÉRIO" in trecho:
                    resultado["data_registro_mte"] = parse_data_br(m.group(1))

    # Estratégia 2d: "Protocolo" ou "Processo" com data (algumas CCTs usam esse formato)
    if not resultado["data_registro_mte"]:
        m = re.search(
            r'(?:PROTOCOLO|PROCESSO)\s*(?:N[º°]?\s*)?\d+.*?([\d]{2}[/-][\d]{2}[/-][\d]{4})',
            texto_upper, re.DOTALL
        )
        if m:
            # Só usa se não houver outra data de registro
            candidata = parse_data_br(m.group(1))
            # Evita confundir com data de início de vigência
            if candidata != resultado["data_inicio"]:
                resultado["data_registro_mte"] = candidata

    return resultado


def extrair_dados_complementares_do_texto(texto):
    """
    Extrai dados complementares de uma CCT do texto do PDF:
      - data_base
      - reajuste_percentual
      - contribuicao_sindical_empregado
      - contribuicao_sindical_patronal
      - contribuicao_sindical_empregado_meses
    Retorna dict com as chaves acima.
    """
    resultado = {
        "data_base": None,
        "reajuste_percentual": None,
        "contribuicao_sindical_empregado": None,
        "contribuicao_sindical_patronal": None,
        "contribuicao_sindical_empregado_meses": None,
        "trecho_contribuicao_empregado": None,
        "trecho_contribuicao_patronal": None,
    }
    if not texto or len(texto) < 50:
        return resultado

    texto_upper = texto.upper()

    def _extrair_trecho_contribuicao(texto_original, padroes_marcador, max_chars=1500):
        """
        Busca no texto original pelos marcadores de contribuição e retorna
        um trecho de até max_chars caracteres a partir do marcador.
        Para no primeiro delimitador forte (CLÁUSULA, ARTIGO, TÍTULO, CAPÍTULO)
        que apareça após o marcador, desde que esteja a mais de 300 chars de distância
        (evita parar muito cedo).
        """
        for padrao in padroes_marcador:
            m = re.search(padrao, texto_original, re.IGNORECASE)
            if m:
                inicio = m.start()
                # Procura delimitadores de cláusula após o início
                fim_candidatos = []
                for delim_padrao in [
                    r'\n\s*CL[ÁA]USULA',
                    r'\n\s*ARTIGO',
                    r'\n\s*T[ÍI]TULO',
                    r'\n\s*CAP[ÍI]TULO',
                    r'\n\s*SE[ÇC][ÃA]O',
                    r'\n\s*SUBSE[ÇC][ÃA]O',
                    r'\n\s*ANEXO',
                ]:
                    for dm in re.finditer(delim_padrao, texto_original[inicio + 300:]):
                        fim_candidatos.append(inicio + 300 + dm.start())
                        break  # só o primeiro de cada tipo
                if fim_candidatos:
                    fim = min(fim_candidatos)
                else:
                    fim = inicio + max_chars
                trecho = texto_original[inicio:fim].strip()
                # Normaliza quebras de linha e espaços excessivos
                trecho = re.sub(r'\n+', '\n', trecho)
                trecho = re.sub(r'[ \t]+', ' ', trecho)
                return trecho
        return None

    # ============================================================
    # 1. DATA BASE
    # ============================================================
    padroes_data_base = [
        r'DATA[-\s]*BASE\s*[:\-\s]*(\d{2}[/-]\d{2}[/-]\d{4})',
        r'EFEITOS\s+FINANCEIROS\s*(?:A\s*PARTIR\s*DE)?\s*[:\-\s]*(\d{2}[/-]\d{2}[/-]\d{4})',
        r'REAJUSTE\s*(?:SALARIAL)?\s*A\s*PARTIR\s*DE\s*[:\-\s]*(\d{2}[/-]\d{2}[/-]\d{4})',
        r'PAGAMENTO\s*A\s*PARTIR\s*DE\s*[:\-\s]*(\d{2}[/-]\d{2}[/-]\d{4})',
        r'RETROATIVO\s*(?:A)?\s*[:\-\s]*(\d{2}[/-]\d{2}[/-]\d{4})',
    ]
    for padrao in padroes_data_base:
        m = re.search(padrao, texto_upper)
        if m:
            resultado["data_base"] = parse_data_br(m.group(1))
            if resultado["data_base"]:
                break

    if not resultado["data_base"]:
        m = re.search(
            r'DATA[-\s]*BASE.*?((?:\d{1,2}\s*º?\s*DE\s+\w+\s+DE\s+\d{4}))',
            texto, re.IGNORECASE
        )
        if m:
            resultado["data_base"] = _parse_data_escrita(m.group(1))

    # ============================================================
    # 2. REAJUSTE PERCENTUAL
    # ============================================================
    padroes_reajuste = [
        r'REAJUSTE\s*(?:SALARIAL)?\s*DE\s*([\d.,]+)\s*%',
        r'AUMENTO\s*(?:SALARIAL)?\s*DE\s*([\d.,]+)\s*%',
        r'[IÍ]NDICE\s*DE\s*([\d.,]+)\s*%',
        r'PERCENTUAL\s*DE\s*([\d.,]+)\s*%',
        r'REAJUSTE\s*DE\s*([\d.,]+)\s*PER\s*CENTO',
        r'REAJUSTE\s*[:\-]?\s*([\d.,]+)\s*%',
        r'REAJUSTE\s*SALARIAL\s*[:\-]?\s*([\d.,]+)\s*%',
        r'REAJUSTE\s*NO\s*SAL[ÁA]RIO\s*DE\s*([\d.,]+)\s*%',
    ]
    for padrao in padroes_reajuste:
        m = re.search(padrao, texto_upper)
        if m:
            try:
                val_str = m.group(1).strip().replace(".", "").replace(",", ".")
                val = float(val_str)
                if 0 < val < 1000:
                    resultado["reajuste_percentual"] = val
                    break
            except (ValueError, AttributeError):
                continue

    # ============================================================
    # 3. SEPARAÇÃO DE SEÇÕES: EMPREGADO vs PATRONAL
    # ============================================================
    marcadores_empregado = [
        # Flexíveis: permitem texto intermediário (até 50 chars)
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}SINDICAL.{0,50}(?:DOS?\s*)?EMPREGAD',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}NEGOCIAL(?!\s*PATRONAL)',  # negocial que não seja patronal
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}ASSISTENCIAL(?!\s*PATRONAL)',  # assistencial que não seja patronal
        r'TAXA\s*NEGOCIAL(?!\s*PATRONAL)',
        r'TAXA\s*ASSISTENCIAL(?!\s*PATRONAL)',
        r'TAXA\s*SINDICAL(?!\s*PATRONAL)',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}PROFISSIONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}(?:NEGOCIAL|ASSISTENCIAL).{0,50}(?:DOS?\s*)?EMPREGAD',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}NEGOCIAL.{0,20}EMPREGAD',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}DOS\s*TRABALHAD',
        # Padrões mais flexíveis: permitem texto intermediário (até 50 chars)
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}(?:NEGOCIAL|ASSISTENCIAL|SINDICAL).{0,50}PROFISSIONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,30}PROFISSIONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}(?:NEGOCIAL|ASSISTENCIAL).{0,30}(?:DOS?\s*)?EMPREGADOS',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,30}NEGOCIAL.{0,20}EMPREGADO',
        # Padrões estritos originais (mantidos como fallback)
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:NEGOCIAL|ASSISTENCIAL|SINDICAL)\s*PROFISSIONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*PROFISSIONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:NEGOCIAL|ASSISTENCIAL)\s*(?:DOS?\s*)?EMPREGADOS',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*NEGOCIAL\s*EMPREGADO',
    ]
    marcadores_patronal = [
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}NEGOCIAL.{0,50}PATRONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}ASSISTENCIAL.{0,50}PATRONAL',
        r'TAXA\s*NEGOCIAL.{0,30}PATRONAL',
        r'TAXA\s*ASSISTENCIAL.{0,30}PATRONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}EMPREGADOR',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}PATRONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}(?:NEGOCIAL|SINDICAL|ASSISTENCIAL).{0,50}PATRONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,30}(?:DO|DOS)\s*EMPREGADOR',
        r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}(?:NEGOCIAL|SINDICAL).{0,20}PATR[A\u00c3]O',
        # Padrões estritos originais
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:NEGOCIAL|SINDICAL|ASSISTENCIAL)\s*PATRONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*PATRONAL',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:DO|DOS)\s*EMPREGADOR',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:NEGOCIAL|SINDICAL)\s*PATR[A\u00c3]O',
    ]

    # Colhe TODAS as posições de TODOS os marcadores (não apenas o primeiro match).
    # Depois usa a posição mais cedo no texto, garantindo que a primeira cláusula
    # de contribuição empregado seja capturada mesmo se houver vários tipos.
    pos_empregado = None
    for padrao in marcadores_empregado:
        m = re.search(padrao, texto_upper)
        if m:
            if pos_empregado is None or m.start() < pos_empregado:
                pos_empregado = m.start()

    pos_patronal = None
    for padrao in marcadores_patronal:
        m = re.search(padrao, texto_upper)
        if m:
            if pos_patronal is None or m.start() < pos_patronal:
                pos_patronal = m.start()

    if pos_patronal is not None and pos_empregado is not None:
        if pos_patronal < pos_empregado:
            secao_patronal = texto_upper[pos_patronal:pos_empregado]
            secao_empregado = texto_upper[pos_empregado:]
        else:
            secao_empregado = texto_upper[pos_empregado:pos_patronal]
            secao_patronal = texto_upper[pos_patronal:]
    elif pos_patronal is not None:
        secao_patronal = texto_upper[pos_patronal:]
        secao_empregado = texto_upper[:pos_patronal]
    elif pos_empregado is not None:
        secao_empregado = texto_upper[pos_empregado:]
        secao_patronal = texto_upper[:pos_empregado]
    else:
        secao_empregado = None
        secao_patronal = None

    # ============================================================
    # 3b. EXTRAÇÃO DOS TRECHOS DE TEXTO (empregado e patronal)
    # ============================================================
    # Usa as posições já encontradas na separação de seções para
    # extrair o trecho do texto ORIGINAL (case preservado).
    # Isso garante que, se a seção foi encontrada, o trecho também será.

    def _extrair_trecho_da_posicao(texto_original, pos_inicio, pos_fim, max_chars=1800):
        """Extrai trecho do texto original entre pos_inicio e pos_fim (ou max_chars)."""
        if pos_inicio is None:
            return None
        inicio = pos_inicio
        # Tenta achar o fim da cláusula por delimitadores
        trecho_busca = texto_original[inicio:inicio + max_chars]
        fim_delimitadores = []
        for delim in [
            r'\n\s*CL[\u00c1A]USULA',
            r'\n\s*ARTIGO',
            r'\n\s*T[\u00cdI]TULO',
            r'\n\s*CAP[\u00cdI]TULO',
            r'\n\s*SE[\u00c7C][\u00c3A]O',
            r'\n\s*SUBSE[\u00c7C][\u00c3A]O',
            r'\n\s*ANEXO',
        ]:
            m = re.search(delim, trecho_busca)
            if m and m.start() > 200:  # evita parar muito cedo
                fim_delimitadores.append(inicio + m.start())
        if fim_delimitadores and pos_fim is not None:
            fim = min(min(fim_delimitadores), pos_fim)
        elif fim_delimitadores:
            fim = min(fim_delimitadores)
        elif pos_fim is not None:
            fim = pos_fim
        else:
            # Fallback: se nenhum delimitador encontrado, amplia a busca
            fim = inicio + 2500
        trecho = texto_original[inicio:fim].strip()
        trecho = re.sub(r'\n+', '\n', trecho)
        trecho = re.sub(r'[ \t]+', ' ', trecho)
        if len(trecho) < 30:
            return None
        return trecho

    resultado["trecho_contribuicao_empregado"] = _extrair_trecho_da_posicao(
        texto, pos_empregado,
        pos_patronal if pos_patronal is not None and pos_empregado is not None and pos_patronal > pos_empregado else None,
        max_chars=2500
    )
    resultado["trecho_contribuicao_patronal"] = _extrair_trecho_da_posicao(
        texto, pos_patronal,
        pos_empregado if pos_empregado is not None and pos_patronal is not None and pos_empregado > pos_patronal else None,
        max_chars=2500
    )

    # Fallback: se ainda não achou trecho empregado, tenta busca por mais marcadores
    if not resultado["trecho_contribuicao_empregado"]:
        marcadores_empregado_extra = [
            # Flexíveis: permitem intermediário
            r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}SINDICAL.{0,20}EMPREGADO',
            r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}ASSISTENCIAL.{0,20}EMPREGADO',
            r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}DOS\s*EMPREGADOS',
            r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}DOS\s*TRABALHADORES',
            r'CONTRIBUI[\u00c7C][\u00c3A]O.{0,50}NEGOCIAL.{0,30}TRABALHADORES',
            r'TAXA\s*NEGOCIAL.{0,30}PROFISSIONAL',
            r'TAXA\s*ASSISTENCIAL.{0,30}PROFISSIONAL',
            # Fallback amplo: captura casos sem "EMPREGADO" explícito
            r'TAXA\s*NEGOCIAL',
            r'TAXA\s*ASSISTENCIAL',
            r'TAXA\s*SINDICAL',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*NEGOCIAL(?!.*PATRONAL)',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*SINDICAL(?!.*PATRONAL)',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*DOS\s*EMPREGAD',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*DOS\s*TRABALHAD',
            r'DESCONTO\s+(?:DA|DO)\s+CONTRIBUI',
            r'DESCONTO\s+PREVIDENCI[ÁA]RIA',
            r'EMPREGADO.*?CONTRIBUI[\u00c7C][\u00c3A]O',
            # Estritos originais
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*SINDICAL\s*EMPREGADO',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*EMPREGADO',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*DOS\s*EMPREGADOS',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*DOS\s*TRABALHADORES',
            r'CONTRIBUI[\u00c7C][\u00c3A]O\s*NEGOCIAL\s*DOS\s*TRABALHADORES',
            r'TAXA\s*NEGOCIAL\s*PROFISSIONAL',
            r'TAXA\s*ASSISTENCIAL\s*PROFISSIONAL',
        ]
        for padrao in marcadores_empregado_extra:
            m = re.search(padrao, texto, re.IGNORECASE)
            if m:
                resultado["trecho_contribuicao_empregado"] = _extrair_trecho_da_posicao(
                    texto, m.start(), None, max_chars=2500
                )
                break

    # Deduplicação: se os trechos forem idênticos ou um contém inteiramente o outro, anula o empregado
    trecho_emp = resultado.get("trecho_contribuicao_empregado")
    trecho_pat = resultado.get("trecho_contribuicao_patronal")
    if trecho_emp and trecho_pat:
        if trecho_emp == trecho_pat or trecho_emp in trecho_pat or trecho_pat in trecho_emp:
            resultado["trecho_contribuicao_empregado"] = None

    # ============================================================
    # 4. CONTRIBUIÇÃO SINDICAL / NEGOCIAL EMPREGADO
    # ============================================================
    # Estratégia em 3 camadas:
    #   A) Padrões específicos que combinam contexto + valor
    #   B) Busca contextual por âncoras (trecho restrito ±250 chars)
    #   C) Valores por extenso no trecho contextual
    #   D) NENHUM fallback genérico na seção inteira

    def _extrair_valor_percentual(secao, palavras_chave_ancora, max_val=10000):
        """
        Procura na seção por valores percentuais ou em R$.
        Dá prioridade a valores próximos das palavras-chave de âncora.
        NUNCA faz fallback genérico na seção inteira.
        """
        # ---- CAMADA A: Padrões específicos combinados ----
        padroes_combinados = [
            r'CONTRIBUI[ÇC][ÃA]O(?:\s*(?:NEGOCIAL|ASSISTENCIAL|SINDICAL))?\s*PROFISSIONAL[^\d]{0,300}([\d.,]+)\s*%',
            r'CONTRIBUI[ÇC][ÃA]O(?:\s*(?:NEGOCIAL|ASSISTENCIAL|SINDICAL))?\s*PROFISSIONAL[^\d]{0,300}R\$\s*([\d.,]+)',
            r'CONTRIBUI[ÇC][ÃA]O\s*(?:NEGOCIAL|ASSISTENCIAL)[^\d]{0,300}([\d.,]+)\s*%',
            r'CONTRIBUI[ÇC][ÃA]O\s*(?:NEGOCIAL|ASSISTENCIAL)[^\d]{0,300}R\$\s*([\d.,]+)',
            r'VALOR\s*CORRESPONDENTE[^\d]{0,100}A\s*([\d.,]+)\s*%',
            r'VALOR\s*CORRESPONDENTE[^\d]{0,100}([\d.,]+)\s*%',
            r'NO\s*VALOR\s*DE\s*R\$\s*([\d.,]+)',
            r'TAXA\s*(?:NEGOCIAL|ASSISTENCIAL)[^\d]{0,200}([\d.,]+)\s*%',
            r'TAXA\s*(?:NEGOCIAL|ASSISTENCIAL)[^\d]{0,200}R\$\s*([\d.,]+)',
        ]
        for padrao in padroes_combinados:
            m = re.search(padrao, secao, re.DOTALL)
            if m:
                try:
                    val_str = m.group(1).strip().replace(".", "").replace(",", ".")
                    val = float(val_str)
                    if 0 < val < max_val:
                        # Determina se é % ou R$ pelo padrão usado
                        eh_pct = '%' in m.group(0) or 'POR CENTO' in m.group(0)
                        return val, eh_pct
                except (ValueError, AttributeError):
                    continue

        # ---- CAMADA B: Busca contextual por âncoras ----
        melhor_valor = None
        melhor_eh_percentual = False

        for ancora in palavras_chave_ancora:
            for match in re.finditer(ancora, secao):
                inicio = max(0, match.start() - 250)
                fim = min(len(secao), match.end() + 350)
                trecho = secao[inicio:fim]

                # Procura % no trecho (todos os matches, escolhe o mais próximo da âncora)
                for m_pct in re.finditer(r'([\d.,]+)\s*%', trecho):
                    try:
                        val_str = m_pct.group(1).strip().replace(".", "").replace(",", ".")
                        val = float(val_str)
                        if 0 < val < max_val:
                            dist = abs(m_pct.start() - (match.end() - inicio))
                            if melhor_valor is None or dist < melhor_dist:
                                melhor_valor = val
                                melhor_eh_percentual = True
                                melhor_dist = dist
                    except (ValueError, AttributeError):
                        pass

                # Procura R$ no trecho
                for m_rs in re.finditer(r'R\$\s*([\d.,]+)', trecho):
                    try:
                        val_str = m_rs.group(1).strip().replace(".", "").replace(",", ".")
                        val = float(val_str)
                        if 0 < val < max_val:
                            dist = abs(m_rs.start() - (match.end() - inicio))
                            if melhor_valor is None or dist < melhor_dist:
                                melhor_valor = val
                                melhor_eh_percentual = False
                                melhor_dist = dist
                    except (ValueError, AttributeError):
                        pass

                # ---- CAMADA C: Valores por extenso no trecho ----
                extenso_map = {
                    'UM': 1, 'DOIS': 2, 'TRÊS': 3, 'TRES': 3, 'QUATRO': 4, 'CINCO': 5,
                    'SEIS': 6, 'SETE': 7, 'OITO': 8, 'NOVE': 9, 'DEZ': 10, 'ONZE': 11,
                    'DOZE': 12, 'TREZE': 13, 'CATORZE': 14, 'QUATORZE': 14, 'QUINZE': 15,
                    'DEZESSEIS': 16, 'DEZESSETE': 17, 'DEZOITO': 18, 'DEZENOVE': 19,
                    'VINTE': 20, 'TRINTA': 30, 'QUARENTA': 40, 'CINQUENTA': 50,
                    'SESSENTA': 60, 'SETENTA': 70, 'OITENTA': 80, 'NOVENTA': 90,
                    'CEM': 100, 'DUZENTOS': 200, 'TREZENTOS': 300, 'QUATROCENTOS': 400,
                    'QUINHENTOS': 500, 'SEISCENTOS': 600, 'SETECENTOS': 700,
                    'OITOCENTOS': 800, 'NOVECENTOS': 900, 'MIL': 1000,
                }
                padroes_extenso = [
                    r'(UM|DOIS|TR[ÊE]S|QUATRO|CINCO|SEIS|SETE|OITO|NOVE|DEZ|ONZE|DOZE|TREZE|CATORZE|QUATORZE|QUINZE|DEZESSEIS|DEZESSETE|DEZOITO|DEZENOVE|VINTE|TRINTA|QUARENTA|CINQUENTA|SESSENTA|SETENTA|OITENTA|NOVENTA|CEM|DUZENTOS|TREZENTOS|QUATROCENTOS|QUINHENTOS|SEISCENTOS|SETECENTOS|OITOCENTOS|NOVECENTOS|MIL)\s+POR\s*CENTO',
                ]
                for padrao_extenso in padroes_extenso:
                    for m_ext in re.finditer(padrao_extenso, trecho):
                        palavra = m_ext.group(1).strip().upper()
                        palavra = re.sub(r'[ÁÀÂÃÄáàâãä]', 'A', palavra)
                        palavra = re.sub(r'[ÉÈÊËéèêë]', 'E', palavra)
                        palavra = re.sub(r'[ÍÌÎÏíìîï]', 'I', palavra)
                        palavra = re.sub(r'[ÓÒÔÕÖóòôõö]', 'O', palavra)
                        palavra = re.sub(r'[ÚÙÛÜúùûü]', 'U', palavra)
                        palavra = re.sub(r'[Çç]', 'C', palavra)
                        if palavra in extenso_map:
                            val = extenso_map[palavra]
                            if 0 < val < max_val:
                                dist = abs(m_ext.start() - (match.end() - inicio))
                                if melhor_valor is None or dist < melhor_dist:
                                    melhor_valor = val
                                    melhor_eh_percentual = True
                                    melhor_dist = dist

            # Se já achou um valor próximo desta âncora, para
            if melhor_valor is not None:
                break

        if melhor_valor is not None:
            return melhor_valor, melhor_eh_percentual

        # Sem fallback genérico — evita capturar reajustes, juros, multas etc.
        return None, False

    # Âncoras para empregado (do mais específico ao mais genérico)
    palavras_chave_empregado = [
        r'CONTRIBUI[ÇC][ÃA]O\s*(?:NEGOCIAL|ASSISTENCIAL)\s*PROFISSIONAL',
        r'CONTRIBUI[ÇC][ÃA]O\s*PROFISSIONAL',
        r'DEVIDA\s+POR\s+TODOS\s+OS\s+EMPREGADOS',
        r'INTEGRANTES\s*DA\s*CATEGORIA\s*PROFISSIONAL',
        r'DO\s*SAL[ÁA]RIO\s*DO\s*M[ÊE]S',
        r'DESCONTADOS?\s*DO\s*EMPREGADO',
        r'TAXA\s*(?:NEGOCIAL|ASSISTENCIAL)',
        r'TAXA\s*NEGOCIAL',
        r'TAXA\s*ASSISTENCIAL',
        r'CONTRIBUI[ÇC][ÃA]O\s*ASSISTENCIAL(?!.*PATRONAL)',
        r'CONTRIBUI[ÇC][ÃA]O\s*NEGOCIAL(?!.*PATRONAL)',
        r'CONTRIBUI[ÇC][ÃA]O\s*SINDICAL(?!.*PATRONAL)',
    ]

    if secao_empregado:
        val_emp, eh_pct_emp = _extrair_valor_percentual(
            secao_empregado, palavras_chave_empregado, max_val=10000
        )
        if val_emp is not None:
            resultado["contribuicao_sindical_empregado"] = val_emp

    # ============================================================
    # 5. MESES DE DESCONTO DA CONTRIBUIÇÃO (empregado)
    # ============================================================
    meses_map = {
        'JANEIRO': 'JAN', 'FEVEREIRO': 'FEV', 'MARCO': 'MAR', 'ABRIL': 'ABR',
        'MAIO': 'MAI', 'JUNHO': 'JUN', 'JULHO': 'JUL', 'AGOSTO': 'AGO',
        'SETEMBRO': 'SET', 'OUTUBRO': 'OUT', 'NOVEMBRO': 'NOV', 'DEZEMBRO': 'DEZ',
        'JAN': 'JAN', 'FEV': 'FEV', 'MAR': 'MAR', 'ABR': 'ABR', 'MAI': 'MAI',
        'JUN': 'JUN', 'JUL': 'JUL', 'AGO': 'AGO', 'SET': 'SET', 'OUT': 'OUT',
        'NOV': 'NOV', 'DEZ': 'DEZ',
    }
    meses_encontrados = []

    # Procura meses SOMENTE em trechos próximos de menções a contribuição/desconto
    # na seção do empregado. Evita pegar meses aleatórios de outras cláusulas.
    trechos_contribuicao = []
    if secao_empregado:
        for m in re.finditer(r'CONTRIBUI[ÇC][ÃA]O', secao_empregado):
            inicio = max(0, m.start() - 100)
            fim = min(len(secao_empregado), m.end() + 400)
            trechos_contribuicao.append(secao_empregado[inicio:fim])

        # Também procura em trechos com "desconto", "cobrança", "devida"
        for termo in [r'DESCONTO', r'COBRAN[ÇC]A', r'DEVIDA', r'VALOR\s*CORRESPONDENTE', r'RECOLHIDO']:
            for m in re.finditer(termo, secao_empregado):
                inicio = max(0, m.start() - 100)
                fim = min(len(secao_empregado), m.end() + 300)
                trecho = secao_empregado[inicio:fim]
                if trecho not in trechos_contribuicao:
                    trechos_contribuicao.append(trecho)

    padroes_meses = [
        r'M[ÊE]S\s*DE\s*(\w+)(?:\s+DE\s+\d{4})?',
        r'DO\s*SAL[ÁA]RIO\s*DO\s*M[ÊE]S\s*DE\s*(\w+)(?:\s+DE\s+\d{4})?',
        r'DESCONTADO.*?M[ÊE]S\s*DE\s*(\w+)(?:\s+DE\s+\d{4})?',
        r'COBRAN[ÇC]A.*?M[ÊE]S\s*DE\s*(\w+)(?:\s+DE\s+\d{4})?',
        r'NO\s*M[ÊE]S\s*DE\s*(\w+)(?:\s+DE\s+\d{4})?',
        r'EM\s*(\w+)(?:\s+DE\s+\d{4})?.*?DESCONTO',
        r'NOS?\s*M[ÊE]S(?:ES)?\s*DE\s*(.+?)(?:\.|;|,)',
        r'(?:DESCONTO|DESCONTADA|COBRAN[ÇC]A|ARRECADA[ÇC][ÃA]O)\s*(?:NO|NA|EM)\s*M[ÊE]S\s*DE\s*(\w+)',
        r'(?:DESCONTO|DESCONTADA|COBRAN[ÇC]A)\s*(?:NO|NA|EM)\s*(\w+)',
        r'VERBA\s*DESCONTADA\s*(?:NO|NA|EM)\s*(\w+)',
        r'IMPORT[ÂA]NCIA\s*DESCONTADA\s*(?:NO|NA|EM)\s*(\w+)',
        r'RETEN[ÇC][ÃA]O\s*(?:NO|NA|EM)\s*(\w+)',
        r'ARRECADA[ÇC][ÃA]O\s*(?:NO|NA|EM)\s*(\w+)',
        r'DESCONTAR\s*(?:NO|NA|EM)\s*(\w+)',
        r'COBRAR\s*(?:NO|NA|EM)\s*(\w+)',
        r'12\s*(?:PARCELAS?|VEZES?|X|PRESTA[ÇC][ÕO]ES?)',
        r'DOZE\s*(?:PARCELAS?|VEZES?|PRESTA[ÇC][ÕO]ES?)',
        r'MENSALMENTE|MENSAL',
        r'TODOS\s*OS\s*M[ÊE]S(?:ES)?',
    ]

    for trecho in trechos_contribuicao:
        for padrao in padroes_meses:
            m = re.search(padrao, trecho, re.DOTALL)
            if m:
                grupo = m.group(1).strip() if m.lastindex else None
                if grupo:
                    partes = re.split(r',|\s+E\s+|\s+OU\s+', grupo)
                    for parte in partes:
                        parte_limpa = parte.strip().upper()
                        parte_limpa = re.sub(r'[ÁÀÂÃÄáàâãä]', 'A', parte_limpa)
                        parte_limpa = re.sub(r'[ÉÈÊËéèêë]', 'E', parte_limpa)
                        parte_limpa = re.sub(r'[ÍÌÎÏíìîï]', 'I', parte_limpa)
                        parte_limpa = re.sub(r'[ÓÒÔÕÖóòôõö]', 'O', parte_limpa)
                        parte_limpa = re.sub(r'[ÚÙÛÜúùûü]', 'U', parte_limpa)
                        parte_limpa = re.sub(r'[Çç]', 'C', parte_limpa)
                        parte_limpa = re.sub(r'[^A-Z]', '', parte_limpa)
                        if parte_limpa in meses_map and meses_map[parte_limpa] not in meses_encontrados:
                            meses_encontrados.append(meses_map[parte_limpa])
                elif not grupo:
                    if any(k in m.group(0) for k in ['12', 'DOZE', 'MENSAL', 'TODOS']):
                        meses_encontrados = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
                        break
        if len(meses_encontrados) >= 12:
            break

    # Ordena meses e remove duplicatas mantendo ordem
    ordem_meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    meses_ordenados = sorted(set(meses_encontrados), key=lambda x: ordem_meses.index(x))
    if meses_ordenados:
        resultado["contribuicao_sindical_empregado_meses"] = ", ".join(meses_ordenados)
    else:
        resultado["contribuicao_sindical_empregado_meses"] = ""

    # ============================================================
    # 6. CONTRIBUIÇÃO SINDICAL PATRONAL
    # ============================================================
    if secao_patronal:
        palavras_chave_patronal = [
            r'CONTRIBUI[ÇC][ÃA]O\s*(?:NEGOCIAL|SINDICAL|ASSISTENCIAL)\s*PATRONAL',
            r'CONTRIBUI[ÇC][ÃA]O\s*PATRONAL',
            r'FOLHA\s*DE\s*PAGAMENTO',
            r'SOBRE\s*O\s*VALOR\s*TOTAL',
            r'EMPREGADORES\s*FILIADOS',
        ]
        val_pat, eh_pct_pat = _extrair_valor_percentual(
            secao_patronal, palavras_chave_patronal, max_val=100000
        )
        if val_pat is not None:
            resultado["contribuicao_sindical_patronal"] = val_pat

    return resultado


class Command(BaseCommand):
    help = (
        "Atualiza as datas de vigência (início, fim) e registro MTE "
        "dos DocumentoCCT já existentes no banco, extraindo do PDF."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sindicato-codigo",
            type=str,
            help="Filtra por código de sindicato específico.",
        )
        parser.add_argument(
            "--apenas-vazios",
            action="store_true",
            help="Só processa documentos que ainda não têm data_fim_vigencia ou data_registro_mte.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula a execução sem salvar no banco.",
        )
        parser.add_argument(
            "--limite",
            type=int,
            default=0,
            help="Limite de documentos a processar (0 = sem limite).",
        )

    def handle(self, *args, **options):
        sindicato_codigo = options.get("sindicato_codigo")
        apenas_vazios = options.get("apenas_vazios")
        dry_run = options.get("dry_run")
        limite = options.get("limite")

        queryset = DocumentoCCT.objects.filter(ativo=True).exclude(
            arquivo_pdf=""
        ).exclude(arquivo_pdf__isnull=True)

        if sindicato_codigo:
            queryset = queryset.filter(sindicato__codigo=sindicato_codigo)

        if apenas_vazios:
            queryset = queryset.filter(
                data_fim_vigencia__isnull=True
            ) | queryset.filter(data_registro_mte__isnull=True)

        total = queryset.count()
        if limite > 0:
            queryset = queryset[:limite]
            total = min(total, limite)

        self.stdout.write(self.style.NOTICE(
            f"Documentos a processar: {total}"
            + (" (DRY-RUN)" if dry_run else "")
        ))

        atualizados = 0
        sem_mudanca = 0
        erro_pdf = 0

        for idx, doc in enumerate(queryset, start=1):
            self.stdout.write(f"\n[{idx}/{total}] #{doc.pk} — {doc.sindicato} — {doc.tipo}")

            # Resolve caminho absoluto do PDF
            caminho_pdf = doc.arquivo_pdf
            if not os.path.isabs(caminho_pdf):
                from django.conf import settings
                caminho_pdf = str(Path(settings.BASE_DIR) / caminho_pdf)

            if not os.path.exists(caminho_pdf):
                self.stdout.write(self.style.WARNING(f"  PDF não encontrado: {caminho_pdf}"))
                continue

            # Extrai texto do PDF
            texto = extrair_texto_pdf(caminho_pdf)
            if not texto or texto.startswith("[ERRO"):
                self.stdout.write(self.style.WARNING(f"  Falha ao extrair texto do PDF."))
                erro_pdf += 1
                continue

            # Extrai dados do texto
            datas = extrair_datas_do_texto(texto)
            compl = extrair_dados_complementares_do_texto(texto)

            # Log do que foi encontrado
            encontrado = []
            if datas["data_inicio"]:
                encontrado.append(f"inicio={datas['data_inicio']}")
            if datas["data_fim"]:
                encontrado.append(f"fim={datas['data_fim']}")
            if datas["data_registro_mte"]:
                encontrado.append(f"registro_mte={datas['data_registro_mte']}")
            if compl["data_base"]:
                encontrado.append(f"data_base={compl['data_base']}")
            if compl["reajuste_percentual"] is not None:
                encontrado.append(f"reajuste={compl['reajuste_percentual']}%")
            if compl["contribuicao_sindical_empregado"] is not None:
                encontrado.append(f"contrib_empregado={compl['contribuicao_sindical_empregado']}")
            if compl["contribuicao_sindical_patronal"] is not None:
                encontrado.append(f"contrib_patronal={compl['contribuicao_sindical_patronal']}")
            if compl["trecho_contribuicao_empregado"]:
                encontrado.append(f"trecho_empregado=OK({len(compl['trecho_contribuicao_empregado'])} chars)")
            if compl["trecho_contribuicao_patronal"]:
                encontrado.append(f"trecho_patronal=OK({len(compl['trecho_contribuicao_patronal'])} chars)")

            if encontrado:
                self.stdout.write(f"  Encontrado: {', '.join(encontrado)}")
            else:
                self.stdout.write(self.style.WARNING(f"  Nenhuma informacao encontrada no texto."))

            # Verifica se houve mudanca real
            mudou = False
            campos_atualizar = []

            if datas["data_inicio"] and doc.data_inicio_vigencia != datas["data_inicio"]:
                if not dry_run:
                    doc.data_inicio_vigencia = datas["data_inicio"]
                campos_atualizar.append("data_inicio_vigencia")
                mudou = True

            if datas["data_fim"] and doc.data_fim_vigencia != datas["data_fim"]:
                if not dry_run:
                    doc.data_fim_vigencia = datas["data_fim"]
                campos_atualizar.append("data_fim_vigencia")
                mudou = True

            if datas["data_registro_mte"] and doc.data_registro_mte != datas["data_registro_mte"]:
                if not dry_run:
                    doc.data_registro_mte = datas["data_registro_mte"]
                campos_atualizar.append("data_registro_mte")
                mudou = True

            if compl["data_base"] and doc.data_base != compl["data_base"]:
                if not dry_run:
                    doc.data_base = compl["data_base"]
                campos_atualizar.append("data_base")
                mudou = True

            if compl["reajuste_percentual"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["reajuste_percentual"]))
                if doc.reajuste_percentual != novo_valor:
                    if not dry_run:
                        doc.reajuste_percentual = novo_valor
                    campos_atualizar.append("reajuste_percentual")
                    mudou = True

            if compl["contribuicao_sindical_empregado"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["contribuicao_sindical_empregado"]))
                if doc.contribuicao_sindical_empregado != novo_valor:
                    if not dry_run:
                        doc.contribuicao_sindical_empregado = novo_valor
                    campos_atualizar.append("contribuicao_sindical_empregado")
                    mudou = True

            if compl["contribuicao_sindical_patronal"] is not None:
                from decimal import Decimal
                novo_valor = Decimal(str(compl["contribuicao_sindical_patronal"]))
                if doc.contribuicao_sindical_patronal != novo_valor:
                    if not dry_run:
                        doc.contribuicao_sindical_patronal = novo_valor
                    campos_atualizar.append("contribuicao_sindical_patronal")
                    mudou = True

            if compl["trecho_contribuicao_empregado"] is not None:
                if doc.trecho_contribuicao_empregado != compl["trecho_contribuicao_empregado"]:
                    if not dry_run:
                        doc.trecho_contribuicao_empregado = compl["trecho_contribuicao_empregado"]
                    campos_atualizar.append("trecho_contribuicao_empregado")
                    mudou = True

            if compl["trecho_contribuicao_patronal"] is not None:
                if doc.trecho_contribuicao_patronal != compl["trecho_contribuicao_patronal"]:
                    if not dry_run:
                        doc.trecho_contribuicao_patronal = compl["trecho_contribuicao_patronal"]
                    campos_atualizar.append("trecho_contribuicao_patronal")
                    mudou = True

            if compl["contribuicao_sindical_empregado_meses"] is not None:
                if doc.contribuicao_sindical_empregado_meses != compl["contribuicao_sindical_empregado_meses"]:
                    if not dry_run:
                        doc.contribuicao_sindical_empregado_meses = compl["contribuicao_sindical_empregado_meses"]
                    campos_atualizar.append("contribuicao_sindical_empregado_meses")
                    mudou = True

            if mudou:
                if not dry_run:
                    doc.save(update_fields=campos_atualizar)
                self.stdout.write(self.style.SUCCESS(
                    f"  {'[DRY-RUN] ' if dry_run else ''}Atualizado: {', '.join(campos_atualizar)}"
                ))
                atualizados += 1
            else:
                sem_mudanca += 1

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.NOTICE("RESUMO:"))
        self.stdout.write(f"  Total processados: {total}")
        self.stdout.write(self.style.SUCCESS(f"  Com atualização:   {atualizados}"))
        self.stdout.write(f"  Sem mudança:       {sem_mudanca}")
        self.stdout.write(self.style.WARNING(f"  Erro no PDF:       {erro_pdf}"))
