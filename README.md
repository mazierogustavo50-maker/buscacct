# Busca CCT – Mediador CCT

Sistema Django + SQLite para buscar, gerenciar e visualizar Convenções Coletivas de Trabalho (CCT) e Termos Aditivos baixados do [Mediador MTE](https://www3.mte.gov.br/sistemas/mediador).

## ✨ Funcionalidades

- **Dashboard** com estatísticas e gráficos
- **Gestão de Sindicatos** com CNPJ, código e nome
- **Gestão de Empresas** e vínculos com sindicatos
- **Documentos CCT/TA-CCT** com filtros, busca e download
- **Scraper integrado** (Selenium) para busca automática no Mediador MTE
- **Importação de dados** via planilhas Excel
- Interface web responsiva com **Bootstrap 5**

## 🚀 Execução com Docker

```bash
docker-compose up --build
```

Acesse: http://localhost:8000/

Admin: http://localhost:8000/admin/  
Usuário padrão: `admin` / `admin123`

## 💻 Execução local

```bash
# Instale as dependências
pip install -r requirements.txt

# Aplique as migrações
python manage.py migrate

# Importe os dados das planilhas
python manage.py importar_dados

# Crie um superusuário (opcional)
python manage.py createsuperuser

# Rode o servidor
python manage.py runserver
```

## 🔧 Comandos úteis

```bash
# Rodar o scraper manualmente
python manage.py run_scraper

# Rodar para um sindicato específico
python manage.py run_scraper --sindicato-codigo 356

# Modo headless
python manage.py run_scraper --headless
```

## 📁 Estrutura

```
mediadorcct/
├── buscacct/              # Projeto Django
├── cctcore/               # Modelos e importação de dados
├── cctbuscador/           # Scraper (Selenium)
├── cctdashboard/          # Views e templates web
├── convencoes/            # PDFs baixados
├── dados/                 # Planilhas e exports
├── templates/             # Templates HTML
└── static/                # CSS, JS
```

## 📝 Licença

Projeto interno – uso profissional.
