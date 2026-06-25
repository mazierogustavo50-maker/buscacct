#!/bin/bash
set -e

echo "Aplicando migrações..."
python manage.py migrate --noinput

echo "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput

# Importa dados das planilhas se o banco estiver vazio
python manage.py shell -c "
from cctcore.models import Sindicato
if Sindicato.objects.count() == 0:
    print('Banco vazio — importando dados...')
    from django.core.management import call_command
    call_command('importar_dados')
else:
    print('Dados já importados (' + str(Sindicato.objects.count()) + ' sindicatos). Pulando importação.')
"

# Se não houver superusuário, cria um padrão
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('Superusuário criado: admin / admin123')
else:
    print('Superusuário já existe.')
"

echo "Iniciando aplicação..."
exec "$@"
