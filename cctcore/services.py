import json
import os
import requests
import pdfplumber
from django.conf import settings
from pathlib import Path

from .models import ConfiguracaoSistema


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


def analisar_cct_com_ia(texto_cct: str, model_id: str = None) -> dict:
    """
    Envia o texto da CCT para a API OpenCode Go e retorna o resultado estruturado.
    """
    config = ConfiguracaoSistema.get_config()
    api_key = config.chave_api_opencode.strip() if config.chave_api_opencode else ""
    if not api_key:
        return {"erro": "Chave API OpenCode Go não configurada. Cadastre em Admin > Configuração do Sistema."}

    if not model_id:
        model_id = config.modelo_padrao_opencode or "kimi-k2.6"

    endpoint = "https://opencode.ai/zen/go/v1/chat/completions"

    prompt_sistema = (
        "Você é um assistente jurídico especialista em legislação trabalhista brasileira e "
        "convenções coletivas de trabalho (CCT). Analise o texto fornecido e extraia as "
        "informações solicitadas de forma estruturada. Responda SEMPRE em JSON válido."
    )

    # Usa o prompt configurável do admin; fallback para o padrão se estiver vazio
    prompt_template = config.prompt_analise_cct.strip() if config.prompt_analise_cct else ""
    if not prompt_template:
        prompt_template = (
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

    prompt_usuario = prompt_template.replace("{texto_cct}", texto_cct[:15000])

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": prompt_usuario},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    try:
        # Tenta com timeout maior e retry com backoff (timeout e erros 5xx)
        max_tentativas = 3
        timeout_segundos = 300  # 5 minutos
        resp = None

        for tentativa in range(1, max_tentativas + 1):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_segundos)
                # Retry em erros 5xx (503, 502, 504)
                if resp.status_code >= 500:
                    if tentativa < max_tentativas:
                        import time
                        time.sleep(tentativa * 10)  # Backoff: 10s, 20s
                        continue
                    # Última tentativa: propaga o erro
                    resp.raise_for_status()
                resp.raise_for_status()
                break  # Sucesso, sai do loop
            except requests.exceptions.Timeout:
                if tentativa < max_tentativas:
                    import time
                    time.sleep(tentativa * 5)  # Backoff: 5s, 10s
                    continue
                raise  # Última tentativa, propaga o erro

        data = resp.json()

        if "choices" not in data or not data["choices"]:
            return {"erro": "Resposta inesperada da API", "raw": data}

        content = data["choices"][0]["message"]["content"]

        # Tenta extrair JSON da resposta
        try:
            if "```json" in content:
                json_block = content.split("```json")[1].split("```")[0].strip()
                resultado = json.loads(json_block)
            elif "```" in content:
                json_block = content.split("```")[1].split("```")[0].strip()
                resultado = json.loads(json_block)
            else:
                resultado = json.loads(content)
        except json.JSONDecodeError:
            resultado = {"resumo": content, "json_invalido": True}

        return {"sucesso": True, "resultado": resultado, "modelo_usado": model_id}

    except requests.exceptions.Timeout:
        return {"erro": "Timeout ao chamar API OpenCode Go após 3 tentativas (5 min cada). Tente novamente mais tarde ou verifique sua conexão."}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else 0
        texto = e.response.text[:500] if e.response else ""
        if status == 503:
            return {"erro": f"API OpenCode Go indisponível (503 Service Unavailable). O servidor está sobrecarregado ou em manutenção. Tente novamente em alguns minutos."}
        elif status == 502:
            return {"erro": f"API OpenCode Go com erro de gateway (502 Bad Gateway). Tente novamente em alguns minutos."}
        elif status == 504:
            return {"erro": f"API OpenCode Go com timeout de gateway (504 Gateway Timeout). Tente novamente em alguns minutos."}
        elif status == 429:
            return {"erro": f"Muitas requisições à API (429 Rate Limited). Aguarde um momento e tente novamente."}
        elif status >= 500:
            return {"erro": f"Erro no servidor da API ({status}). Tente novamente em alguns minutos. Detalhes: {texto}"}
        else:
            return {"erro": f"Erro HTTP {status}: {texto}"}
    except Exception as e:
        return {"erro": f"Erro inesperado: {str(e)}"}
