@echo off
echo Instalando dependencias...
python -m pip install -r requirements.txt
echo.
echo Executando o script de Web Scraping...
python scraper.py
pause
