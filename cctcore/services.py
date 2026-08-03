import os
import pdfplumber
from django.conf import settings
from pathlib import Path


def extrair_texto_pdf(caminho_pdf: str, max_paginas: int = 100) -> str:
    """Extrai texto de PDFs textuais, preservando páginas para evidência.

    PDFs digitalizados continuam exigindo OCR externo (OCRmyPDF/Tesseract);
    retornamos texto vazio para que o fluxo possa marcar o documento para revisão.
    """
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
