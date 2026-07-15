# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=buscacct.settings
ENV DJANGO_DEBUG=False
ENV DJANGO_ALLOWED_HOSTS=*
# Faz requests/curl usarem os certificados do sistema (incluindo ICP-Brasil instalados abaixo)
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

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

# Instala certificados ICP-Brasil (AC SERPRO etc.) para que requests/curl reconheçam sites do governo
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/local/share/ca-certificates/icp-brasil \
    && wget -q --timeout=30 "https://acraiz.icpbrasil.gov.br/credenciadas/CertificadosAC-ICP-Brasil/ACcompactado.zip" -O /tmp/icpbrasil.zip || true \
    && if [ -f /tmp/icpbrasil.zip ]; then \
         unzip -o /tmp/icpbrasil.zip -d /usr/local/share/ca-certificates/icp-brasil/ 2>/dev/null || true; \
         rm -f /tmp/icpbrasil.zip; \
       fi \
    && wget -q --timeout=30 "https://www.serpro.gov.br/links-fixos-superiores/validator/certificate-chain/acserproar46.crt" -O /usr/local/share/ca-certificates/icp-brasil/acserproar46.crt || true \
    && update-ca-certificates || true

# Instala dependências Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia o projeto
COPY . /app/

# Coleta arquivos estáticos
RUN python manage.py collectstatic --noinput

# Cria diretórios necessários
RUN mkdir -p /app/media /app/convencoes /app/dados /app/temp_dl

# Porta exposta
EXPOSE 8000

# Entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "buscacct.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
