# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=buscacct.settings
ENV DJANGO_DEBUG=False
ENV DJANGO_ALLOWED_HOSTS=*

WORKDIR /app

# Instala dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    wget \
    gnupg \
    unzip \
    curl \
    tesseract-ocr \
    tesseract-ocr-por \
    poppler-utils \
    ghostscript \
    libreoffice-writer \
    libreoffice-common \
    # Dependências obrigatórias do Google Chrome em container
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-noto-core \
    fontconfig \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Instala Google Chrome (necessário para o scraper)
# Baixa o .deb e deixa o apt resolver dependências automaticamente — evita quebra quando nomes de pacotes mudam entre Debian releases
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q --timeout=30 https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb \
    && dpkg -i /tmp/chrome.deb || true \
    && apt-get update && apt-get install -f -y --no-install-recommends \
    && rm -f /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# O ChromeDriver é gerenciado automaticamente pelo webdriver-manager (já no requirements.txt)
# Não instalamos chromedriver manualmente pois as URLs antigas do Google foram descontinuadas

# Instala supercronic (cron para containers) — usado pelo serviço cron
ENV SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.48/supercronic-linux-amd64 \
    SUPERCRONIC_SHA1SUM=016b7c9aebfc8d9fd9526e8ba33b191fc524485f
RUN curl -fsSLO "$SUPERCRONIC_URL" \
    && echo "$SUPERCRONIC_SHA1SUM  supercronic-linux-amd64" | sha1sum -c - \
    && chmod +x supercronic-linux-amd64 \
    && mv supercronic-linux-amd64 /usr/local/bin/supercronic

# Instala dependências Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia o projeto
COPY . /app/

# Cria diretórios necessários
RUN mkdir -p /app/media /app/convencoes /app/dados /app/temp_dl

# Porta exposta
EXPOSE 8000

# Entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "buscacct.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
