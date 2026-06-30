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
    libreoffice-writer \
    libreoffice-common \
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
