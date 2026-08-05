#!/bin/bash
set -euo pipefail

# Diretório de logs
LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/scraper-$(date +%Y%m%d-%H%M%S).log"

exec >> "$LOG_FILE" 2>&1

echo "========================================"
echo "Iniciando busca de CCTs — $(date)"
echo "========================================"

cd /app

# 1. Scraper: busca convenções para todos os sindicatos (headless)
python manage.py run_scraper --headless
SCRAPER_EXIT=$?

echo ""
echo "Scraper finalizado com exit code: $SCRAPER_EXIT"
echo "Hora: $(date)"

if [ $SCRAPER_EXIT -ne 0 ]; then
    echo "[ERRO] Scraper falhou. Análise não será executada."
    exit $SCRAPER_EXIT
fi

# 2. Análise: extrai datas, vigências, contribuições etc. de todos os PDFs
echo ""
echo "========================================"
echo "Iniciando análise/extração — $(date)"
echo "========================================"

python manage.py atualizar_vigencias
ANALISE_EXIT=$?

echo ""
echo "Análise finalizada com exit code: $ANALISE_EXIT"
echo "Hora: $(date)"

# 3. (Opcional) Reanálise com IA — descomente se quiser ativar
# echo ""
# echo "========================================"
# echo "Iniciando análise com IA — $(date)"
# echo "========================================"
# python manage.py reanalisar_ccts --com-ia
# IA_EXIT=$?
# echo "Análise IA finalizada com exit code: $IA_EXIT"

# Limpar logs antigos (manter 30 dias)
find "$LOG_DIR" -name "scraper-*.log" -type f -mtime +30 -delete 2>/dev/null || true

exit $ANALISE_EXIT
