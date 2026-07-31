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
        r'VIGEN[CGÇ][IA]*\s*(?:DE)?\s*(\d{2}[/-]\d{2}[/-]\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{2}[/-]\d{2}[/-]\d{4})',
        texto_upper
    )
    if m:
        resultado["data_inicio"] = parse_data_br(m.group(1))
        resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1b: "VIGÊNCIA: DD/MM/AAAA - DD/MM/AAAA"
    if not resultado["data_inicio"]:
        m = re.search(
            r'VIGEN[CGÇ][IA]*\s*[:\-]\s*(\d{2}[/-]\d{2}[/-]\d{4})\s*(?:A|AT[EÉ]|–|-)\s*(\d{2}[/-]\d{2}[/-]\d{4})',
            texto_upper
        )
        if m:
            resultado["data_inicio"] = parse_data_br(m.group(1))
            resultado["data_fim"] = parse_data_br(m.group(2))

    # Estratégia 1c: "PERÍODO DE VIGÊNCIA" ou "PRAZO DE VIGÊNCIA"
    if not resultado["data_inicio"]:
        m = re.search(
            r'(?:PER[IÍ]ODO|PRAZO)\s*DE\s*VIGEN[CGÇ][IA]*.*?([\d]{2}[/-][\d]{2}[/-][\d]{4}).*?(?:A|AT[EÉ]|–|-).*?([\d]{2}[/-][\d]{2}[/-][\d]{4})',
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
    Retorna dict com as chaves acima.
    """
    resultado = {
        "data_base": None,
        "reajuste_percentual": None,
        "contribuicao_sindical_empregado": None,
        "contribuicao_sindical_patronal": None,
        "contribuicao_sindical_empregado_meses": None,
    }
    if not texto or len(texto) < 50:
        return resultado

    texto_upper = texto.upper()

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
    # 3. CONTRIBUIÇÃO SINDICAL / NEGOCIAL EMPREGADO
    # ============================================================
    padroes_empregado = [
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:SINDICAL|NEGOCIAL|ASSISTENCIAL)\s*(?:DOS?\s*)?(?:EMPREGADOS?|TRABALHADORES?|EMPREGADO)\s*.*?([\d.,]+)\s*%',
        r'TAXA\s*ASSISTENCIAL\s*(?:DOS?\s*)?(?:EMPREGADOS?|TRABALHADORES?)\s*.*?([\d.,]+)\s*%',
        r'MENSALIDADE\s*(?:SINDICAL)?\s*(?:DOS?\s*)?(?:EMPREGADOS?|TRABALHADORES?)\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*NEGOCIAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*SINDICAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*(?:SINDICAL|NEGOCIAL)\s*.*?R\$\s*([\d.,]+)',
        r'TAXA\s*ASSISTENCIAL\s*.*?R\$\s*([\d.,]+)',
        # NOVOS PADRÕES
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*NEGOCIAL\s*PROFISSIONAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*NEGOCIAL\s*PROFISSIONAL\s*.*?R\$\s*([\d.,]+)',
        r'TAXA\s*NEGOCIAL\s*.*?([\d.,]+)\s*%',
        r'TAXA\s*NEGOCIAL\s*.*?R\$\s*([\d.,]+)',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*.*?R\$\s*([\d.,]+)',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*PROFISSIONAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*PROFISSIONAL\s*.*?R\$\s*([\d.,]+)',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*PROFISSIONAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*PROFISSIONAL\s*.*?R\$\s*([\d.,]+)',
        r'DESCONTADOS?\s*DO\s*EMPREGADO.*?([\d.,]+)\s*%',
        r'DESCONTADOS?\s*DO\s*EMPREGADO.*?R\$\s*([\d.,]+)',
        r'DEVIDA\s*POR\s*TODOS\s*OS\s*EMPREGADOS.*?([\d.,]+)\s*%',
        r'DEVIDA\s*POR\s*TODOS\s*OS\s*EMPREGADOS.*?R\$\s*([\d.,]+)',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*CONFEDERATIVA\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*CONFEDERATIVA\s*.*?R\$\s*([\d.,]+)',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*(?:SINDICAL)?\s*DOS?\s*EMPREGADOS?\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[\u00c7C][\u00c3A]O\s*ASSISTENCIAL\s*(?:SINDICAL)?\s*DOS?\s*EMPREGADOS?\s*.*?R\$\s*([\d.,]+)',
        r'TAXA\s*CONFEDERATIVA\s*.*?([\d.,]+)\s*%',
        r'TAXA\s*CONFEDERATIVA\s*.*?R\$\s*([\d.,]+)',
    ]
    for padrao in padroes_empregado:
        m = re.search(padrao, texto_upper, re.DOTALL)
        if m:
            try:
                val_str = m.group(1).strip().replace(".", "").replace(",", ".")
                val = float(val_str)
                if 0 < val < 10000:
                    resultado["contribuicao_sindical_empregado"] = val
                    break
            except (ValueError, AttributeError):
                continue

    # ============================================================
    # 3b. MESES DE DESCONTO DA CONTRIBUIÇÃO
    # ============================================================
    # Procura menção a meses específicos de desconto
    meses_map = {
        'JANEIRO': 'JAN', 'FEVEREIRO': 'FEV', 'MARCO': 'MAR', 'ABRIL': 'ABR',
        'MAIO': 'MAI', 'JUNHO': 'JUN', 'JULHO': 'JUL', 'AGOSTO': 'AGO',
        'SETEMBRO': 'SET', 'OUTUBRO': 'OUT', 'NOVEMBRO': 'NOV', 'DEZEMBRO': 'DEZ',
        'JAN': 'JAN', 'FEV': 'FEV', 'MAR': 'MAR', 'ABR': 'ABR', 'MAI': 'MAI',
        'JUN': 'JUN', 'JUL': 'JUL', 'AGO': 'AGO', 'SET': 'SET', 'OUT': 'OUT',
        'NOV': 'NOV', 'DEZ': 'DEZ',
    }
    meses_encontrados = []

    # Estratégia 3b.1: "desconto no mês de XXXXX" ou "descontada em XXXXX"
    padroes_meses = [
        r'(?:DESCONTO|DESCONTADA|COBRAN[\u00c7C]A|ARRECADA[\u00c7C][\u00c3A]O)\s*(?:NO|NA|EM)\s*M[\u00caE]S\s*DE\s*(\w+)',
        r'(?:DESCONTO|DESCONTADA|COBRAN[\u00c7C]A)\s*(?:NO|NA|EM)\s*(\w+)',
        r'COBRAN[\u00c7C]A\s*ESPECIAL\s*(?:NO|NA|EM)\s*(\w+)',
        r'COBRAN[\u00c7C]A\s*(?:NEGOCIAL|SINDICAL|ASSISTENCIAL)\s*(?:NO|NA|EM)\s*(\w+)',
        r'VERBA\s*DESCONTADA\s*(?:NO|NA|EM)\s*(\w+)',
        r'IMPORT[\u00c2A]NCIA\s*DESCONTADA\s*(?:NO|NA|EM)\s*(\w+)',
        r'RETEN[\u00c7C][\u00c3A]O\s*(?:NO|NA|EM)\s*(\w+)',
        r'ARRECADA[\u00c7C][\u00c3A]O\s*(?:NO|NA|EM)\s*(\w+)',
        r'DESCONTAR\s*(?:NO|NA|EM)\s*(\w+)',
        r'COBRAR\s*(?:NO|NA|EM)\s*(\w+)',
        # Padrão de lista: "nos meses de JANEIRO, MARCO, MAIO e AGOSTO"
        r'(?:NOS?\s*M[\u00caE]S(?:ES)?\s*DE)\s*(.+?)(?:\.|;|,)',
        r'(?:DESCONTO|DESCONTADA)\s*NOS?\s*M[\u00caE]S(?:ES)?\s*DE\s*(.+?)(?:\.|;|,)',
        r'(?:COBRAN[\u00c7C]A)\s*NOS?\s*M[\u00caE]S(?:ES)?\s*DE\s*(.+?)(?:\.|;|,)',
        # Padrão: "mensal" = 12x
        r'12\s*(?:PARCELAS?|VEZES?|X|PRESTA[\u00c7C][\u00d5O]ES?)',
        r'DOZE\s*(?:PARCELAS?|VEZES?|PRESTA[\u00c7C][\u00d5O]ES?)',
        r'MENSALMENTE|MENSAL',
        r'TODOS\s*OS\s*M[\u00caE]S(?:ES)?',
    ]
    for padrao in padroes_meses:
        m = re.search(padrao, texto_upper, re.DOTALL)
        if m:
            grupo = m.group(1).strip() if m.lastindex else None
            # Se for padrão de lista de meses (captura grupo genérico)
            if grupo and ('E' in grupo or ',' in grupo or 'E' in grupo):
                # Quebra por vírgula, 'E', 'OU'
                partes = re.split(r',|\s+E\s+|\s+OU\s+', grupo)
                for parte in partes:
                    parte_limpa = parte.strip().upper()
                    # Remove acentos
                    parte_limpa = re.sub(r'[\u00c1\u00c0\u00c2\u00c3\u00c4\u00e1\u00e0\u00e2\u00e3\u00e4]', 'A', parte_limpa)
                    parte_limpa = re.sub(r'[\u00c9\u00c8\u00ca\u00cb\u00e9\u00e8\u00ea\u00eb]', 'E', parte_limpa)
                    parte_limpa = re.sub(r'[\u00cd\u00cc\u00ce\u00cf\u00ed\u00ec\u00ee\u00ef]', 'I', parte_limpa)
                    parte_limpa = re.sub(r'[\u00d3\u00d2\u00d4\u00d5\u00d6\u00f3\u00f2\u00f4\u00f5\u00f6]', 'O', parte_limpa)
                    parte_limpa = re.sub(r'[\u00da\u00d9\u00db\u00dc\u00fa\u00f9\u00fb\u00fc]', 'U', parte_limpa)
                    parte_limpa = re.sub(r'[\u00c7\u00e7]', 'C', parte_limpa)
                    parte_limpa = re.sub(r'[^A-Z]', '', parte_limpa)
                    if parte_limpa in meses_map:
                        meses_encontrados.append(meses_map[parte_limpa])
            elif grupo:
                # Mês único
                parte_limpa = re.sub(r'[\u00c1\u00c0\u00c2\u00c3\u00c4\u00e1\u00e0\u00e2\u00e3\u00e4]', 'A', grupo.upper())
                parte_limpa = re.sub(r'[\u00c9\u00c8\u00ca\u00cb\u00e9\u00e8\u00ea\u00eb]', 'E', parte_limpa)
                parte_limpa = re.sub(r'[\u00cd\u00cc\u00ce\u00cf\u00ed\u00ec\u00ee\u00ef]', 'I', parte_limpa)
                parte_limpa = re.sub(r'[\u00d3\u00d2\u00d4\u00d5\u00d6\u00f3\u00f2\u00f4\u00f5\u00f6]', 'O', parte_limpa)
                parte_limpa = re.sub(r'[\u00da\u00d9\u00db\u00dc\u00fa\u00f9\u00fb\u00fc]', 'U', parte_limpa)
                parte_limpa = re.sub(r'[\u00c7\u00e7]', 'C', parte_limpa)
                parte_limpa = re.sub(r'[^A-Z]', '', parte_limpa)
                if parte_limpa in meses_map:
                    meses_encontrados.append(meses_map[parte_limpa])
            elif not grupo and ('12' in m.group(0) or 'DOZE' in m.group(0) or 'MENSAL' in m.group(0) or 'TODOS' in m.group(0)):
                # 12x ao ano = todos os meses
                meses_encontrados = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
                break

    # Também procura nomes de meses espalhados no texto em contexto de contribuição
    if not meses_encontrados:
        # Procura por "CONTRIBUIÇÃO" seguido de até 500 chars e depois um mês
        matches = re.finditer(r'CONTRIBUI[\u00c7C][\u00c3A]O.*?', texto_upper)
        for match in matches:
            inicio = match.start()
            trecho = texto_upper[inicio:inicio+600]
            for mes_nome, mes_sigla in meses_map.items():
                if mes_nome in trecho and mes_sigla not in meses_encontrados:
                    meses_encontrados.append(mes_sigla)

    # Ordena meses e remove duplicatas mantendo ordem
    ordem_meses = ['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']
    meses_ordenados = sorted(set(meses_encontrados), key=lambda x: ordem_meses.index(x))
    if meses_ordenados:
        resultado["contribuicao_sindical_empregado_meses"] = ", ".join(meses_ordenados)
    else:
        resultado["contribuicao_sindical_empregado_meses"] = None

    # ============================================================
    # 4. CONTRIBUIÇÃO SINDICAL PATRONAL
    # ============================================================
    padroes_patronal = [
        r'CONTRIBUI[ÇC][ÃA]O\s*(?:SINDICAL|NEGOCIAL|ASSISTENCIAL)\s*(?:DOS?\s*)?(?:PATRONAL|PATRONAIS|EMPREGADORES?|EMPRESAS?)\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[ÇC][ÃA]O\s*PATRONAL\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[ÇC][ÃA]O\s*(?:SINDICAL|NEGOCIAL)\s*(?:DO\s*)?(?:EMPREGADOR|PATR[ÃA]O)\s*.*?([\d.,]+)\s*%',
        r'CONTRIBUI[ÇC][ÃA]O\s*(?:SINDICAL|NEGOCIAL)\s*(?:DO\s*)?EMPREGADOR\s*.*?R\$\s*([\d.,]+)',
        r'CONTRIBUI[ÇC][ÃA]O\s*PATRONAL\s*.*?R\$\s*([\d.,]+)',
    ]
    for padrao in padroes_patronal:
        m = re.search(padrao, texto_upper, re.DOTALL)
        if m:
            try:
                val_str = m.group(1).strip().replace(".", "").replace(",", ".")
                val = float(val_str)
                if 0 < val < 100000:
                    resultado["contribuicao_sindical_patronal"] = val
                    break
            except (ValueError, AttributeError):
                continue

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
            texto = extrair_texto_pdf(caminho_pdf, max_paginas=10)
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
