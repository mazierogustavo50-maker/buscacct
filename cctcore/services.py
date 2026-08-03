import json
import os
import pdfplumber
import requests
import shutil
import subprocess
import tempfile
from pathlib import Path
from django.conf import settings


def extrair_texto_pdf(caminho_pdf: str, max_paginas: int = 0) -> str:
    """Extrai todas as páginas de PDFs textuais, preservando evidências."""
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
            paginas = pdf.pages if not max_paginas or max_paginas < 1 else pdf.pages[:max_paginas]
            for i, page in enumerate(paginas):
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    txt = ""
                if txt:
                    texto_paginas.append(f"--- Página {i + 1} ---\n{txt}")
    except Exception as e:
        return f"[ERRO ao ler PDF: {e}]"

    return "\n\n".join(texto_paginas)


def garantir_ocr_pdf(caminho_pdf: str, modo: str = "auto", idioma: str = "por+eng") -> str:
    """Garante PDF pesquisável. Retorna o mesmo caminho ou uma cópia com sufixo _ocr."""
    if not caminho_pdf or modo == "nunca":
        return caminho_pdf
    caminho = Path(caminho_pdf)
    if not caminho.exists() or caminho.suffix.lower() != ".pdf":
        return caminho_pdf
    texto_atual = extrair_texto_pdf(str(caminho), max_paginas=3)
    precisa = modo == "sempre" or len("".join(texto_atual.split())) < 80
    if not precisa:
        return caminho_pdf
    ocr_path = caminho.with_name(f"{caminho.stem}_ocr.pdf")
    if ocr_path.exists() and ocr_path.stat().st_mtime >= caminho.stat().st_mtime and modo != "sempre":
        return str(ocr_path)
    comando = shutil.which("ocrmypdf")
    if not comando:
        comando = shutil.which("ocrmypdf.exe")
    if not comando:
        raise RuntimeError("OCR indisponível: instale o OCRmyPDF e o Tesseract com idioma por.")
    temporario = Path(tempfile.mkstemp(suffix=".pdf")[1])
    try:
        resultado = subprocess.run(
            [comando, "--skip-text" if modo == "auto" else "--force-ocr", "-l", idioma,
             "--deskew", "--clean", str(caminho), str(temporario)],
            capture_output=True, text=True, timeout=600,
        )
        if resultado.returncode != 0 or not temporario.exists() or temporario.stat().st_size == 0:
            raise RuntimeError((resultado.stderr or resultado.stdout or "OCR falhou")[-1000:])
        os.replace(temporario, ocr_path)
        return str(ocr_path)
    finally:
        if temporario.exists():
            temporario.unlink(missing_ok=True)


def analisar_cct_com_ia(texto: str) -> dict:
    """Analisa uma CCT via API compatível com OpenAI/OpenCode Go."""
    api_key = os.getenv("OPENCODE_GO_API_KEY", "").strip()
    base_url = os.getenv("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
    model = os.getenv("OPENCODE_GO_MODEL", "kimi-k2.6").strip()
    try:
        from cctcore.models import ConfiguracaoSistema
        configuracao = ConfiguracaoSistema.objects.first()
        if configuracao:
            api_key = configuracao.chave_api_opencode.strip() or api_key
            model = configuracao.modelo_padrao_opencode.strip() or model
    except Exception:
        pass
    if not api_key:
        return {"erro": "OPENCODE_GO_API_KEY não configurada; IA não executada."}
    texto = (texto or "").strip()
    if not texto:
        return {"erro": "Texto da CCT vazio; não é possível analisar."}
    prompt = (
        "Você é especialista em convenções coletivas brasileiras. Retorne somente JSON válido. "
        "Extraia apenas informações comprovadas no texto. Meses devem ser números de 1 a 12; "
        "mensalmente/12x ao ano significa todos os meses. Não confunda patronal com empregado. "
        "Chaves: data_base, vigencia_inicio, vigencia_fim, reajuste_percentual, "
        "contribuicao_sindical_empregado, contribuicao_sindical_patronal, "
        "contribuicao_sindical_empregado_meses, evidencia_meses_empregado, evidencia_empregado, "
        "evidencia_patronal, resumo. Use null quando ausente.\n\nTEXTO:\n" + texto[:180000]
    )
    try:
        resposta = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": "Responda apenas JSON."},
                               {"role": "user", "content": prompt}]},
            timeout=120,
        )
        resposta.raise_for_status()
        conteudo = resposta.json()["choices"][0]["message"]["content"]
        if isinstance(conteudo, list):
            conteudo = "".join(p.get("text", "") for p in conteudo if isinstance(p, dict))
        return {"resultado": json.loads(conteudo)}
    except Exception as exc:
        return {"erro": f"Falha na API OpenCode Go ({model}): {exc}"}
