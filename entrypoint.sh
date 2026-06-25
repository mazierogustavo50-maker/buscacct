#!/bin/bash
set -e

echo "Aplicando migrações..."
python manage.py migrate --noinput

echo "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput

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
