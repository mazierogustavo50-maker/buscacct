import os
import json
import re
import pdfplumber
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.conf import settings
from pathlib import Path
import requests


# ============================================================================
# EXTRAÇÃO DE TEXTO DO PDF
# ============================================================================

def extrair_texto_pdf(caminho_pdf: str, max_paginas: int = 30) -> str:
    """Extrai texto de um PDF usando pdfplumber."""
    if not caminho_pdf:
        return ""
    if os.path.isabs(caminho_pdf):
        caminho = Path(caminho_pdf)
    else:
        caminho = Path(settings.BASE_DIR) / caminho_pdf

    if not caminho.exists():
        return ""

    texto_paginas = []
    try:
        with pdfplumber.open(str(caminho)) as pdf:
            for i, page in enumerate(pdf.pages[:max_paginas]):
                txt = page.extract_text()
                if txt:
                    texto_paginas.append(f"--- Página {i + 1} ---\n{txt}")
    except Exception as e:
        return f"[ERRO ao ler PDF: {e}]"

    return "\n\n".join(texto_paginas)


# ============================================================================
# ANÁLISE COM IA (OpenCode / API compatível com OpenAI)
# ============================================================================

def _parse_decimal(valor, max_digits=10, decimal_places=2):
    """Converte string/numero para Decimal, retornando None em caso de erro."""
    if valor is None or valor == "":
        return None
    try:
        # Remove símbolos de percentual
        if isinstance(valor, str):
            valor = valor.replace("%", "").replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
            # Se tinha vírgula como separador decimal, agora está com ponto
            # Se tinha ponto como separador de milhar, já foi removido acima (perigoso)
            # Re-aproxima: se há mais de um ponto, os anteriores eram milhar
            partes = valor.split(".")
            if len(partes) > 2:
                valor = "".join(partes[:-1]) + "." + partes[-1]
        d = Decimal(str(valor))
        # Limita casas decimais
        d = d.quantize(Decimal("0." + "0" * decimal_places))
        return d
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_date(valor):
    """Converte string de data para date."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(valor).strip(), fmt).date()
        except ValueError:
            continue
    return None


def analisar_cct_com_ia(texto_cct: str, config=None, timeout: int = 300):
    """
    Envia o texto da CCT para a API de IA e retorna dict estruturado.

    Retorna dict com:
      - sucesso (bool)
      - dados (dict com campos extraídos) ou erro (str)
    """
    if not texto_cct or len(texto_cct) < 100:
        return {"sucesso": False, "erro": "Texto da CCT muito curto ou vazio."}

    from cctcore.models import ConfiguracaoSistema

    if config is None:
        config = ConfiguracaoSistema.get_config()

    if not config.chave_api_opencode:
        return {"sucesso": False, "erro": "Chave API OpenCode não configurada. Configure em Configurações do Sistema no Admin."}

    # Endpoint padrão OpenCode (OpenAI-compatible)
    api_url = getattr(settings, "OPENCODE_API_URL", "https://api.opencode.run/v1/chat/completions")
    modelo = config.modelo_padrao_opencode or "kimi-k2.6"

    prompt = config.prompt_analise_cct or (
        "Analise a seguinte Convenção Coletiva de Trabalho (CCT) e extraia:\n"
        "1. data_base (data-base da negociação)\n"
        "2. vigencia_inicio (início da vigência)\n"
        "3. vigencia_fim (fim da vigência)\n"
        "4. reajuste_percentual (percentual de reajuste salarial, se houver)\n"
        "5. contribuicao_sindical_empregado (valor ou percentual da contribuição sindical/negocial dos empregados)\n"
        "6. contribuicao_sindical_patronal (valor ou percentual da contribuição patronal, se houver)\n"
        "7. pisos_salariais (lista de funções e seus respectivos pisos salariais)\n"
        "8. beneficios (lista de benefícios mencionados com breve descrição)\n"
        "9. jornada (informações sobre jornada de trabalho, se houver algo específico)\n"
        "10. aviso_previo (regras de aviso prévio, se houver algo específico)\n"
        "11. multa (regras de multa, se houver algo específico)\n"
        "12. outras_clausulas_relevantes (outras cláusulas que considerar importantes)\n\n"
        "Responda em JSON com EXATAMENTE essas chaves. Use null quando não encontrar a informação. "
        "No campo 'resumo', faça um breve resumo de 3 a 5 linhas da CCT.\n\n"
        "TEXTO DA CCT:\n{texto_cct}"
    )
    prompt = prompt.replace("{texto_cct}", texto_cct[:15000])  # limita tamanho

    headers = {
        "Authorization": f"Bearer {config.chave_api_opencode}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": "Você é um assistente especialista em legislação trabalhista brasileira. Extraia dados de Convenções Coletivas de Trabalho (CCT) e responda SEMPRE em JSON válido."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        # Extrai conteúdo da resposta
        choices = data.get("choices", [])
        if not choices:
            return {"sucesso": False, "erro": "Resposta vazia da API."}

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return {"sucesso": False, "erro": "Conteúdo vazio na resposta da API."}

        # Parse JSON
        try:
            resultado = json.loads(content)
        except json.JSONDecodeError:
            # Tenta extrair JSON de bloco markdown
            match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if match:
                try:
                    resultado = json.loads(match.group(1))
                except json.JSONDecodeError as e2:
                    return {"sucesso": False, "erro": f"JSON inválido na resposta: {e2}\nConteúdo: {content[:500]}"}
            else:
                # Tenta encontrar objeto JSON solto
                match2 = re.search(r'\{.*\}', content, re.DOTALL)
                if match2:
                    try:
                        resultado = json.loads(match2.group(0))
                    except json.JSONDecodeError as e3:
                        return {"sucesso": False, "erro": f"JSON inválido na resposta: {e3}\nConteúdo: {content[:500]}"}
                else:
                    return {"sucesso": False, "erro": f"Nenhum JSON encontrado na resposta.\nConteúdo: {content[:500]}"}

        # Normaliza campos
        normalizado = {
            "data_base": _parse_date(resultado.get("data_base")),
            "vigencia_inicio": _parse_date(resultado.get("vigencia_inicio")),
            "vigencia_fim": _parse_date(resultado.get("vigencia_fim")),
            "reajuste_percentual": _parse_decimal(resultado.get("reajuste_percentual"), max_digits=7, decimal_places=4),
            "contribuicao_sindical_empregado": _parse_decimal(resultado.get("contribuicao_sindical_empregado"), max_digits=10, decimal_places=2),
            "contribuicao_sindical_patronal": _parse_decimal(resultado.get("contribuicao_sindical_patronal"), max_digits=10, decimal_places=2),
            "pisos_salariais": resultado.get("pisos_salariais") if resultado.get("pisos_salariais") else [],
            "beneficios": resultado.get("beneficios") if resultado.get("beneficios") else [],
            "jornada": resultado.get("jornada") if resultado.get("jornada") else None,
            "aviso_previo": resultado.get("aviso_previo") if resultado.get("aviso_previo") else None,
            "multa": resultado.get("multa") if resultado.get("multa") else None,
            "outras_clausulas_relevantes": resultado.get("outras_clausulas_relevantes") if resultado.get("outras_clausulas_relevantes") else None,
            "resumo": resultado.get("resumo") if resultado.get("resumo") else "",
        }

        return {"sucesso": True, "dados": normalizado}

    except requests.exceptions.Timeout:
        return {"sucesso": False, "erro": "Timeout na API de IA. Tente novamente ou aumente o timeout."}
    except requests.exceptions.RequestException as e:
        return {"sucesso": False, "erro": f"Erro na requisição à API: {e}"}
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro inesperado: {e}"}
