@echo off
chcp 65001 > nul
title Language App - Локальный сервер + Туннель

echo ======================================================================
echo   Запуск языкового приложения с доступом для телефона
echo ======================================================================
echo.

echo [1/2] Запускаю Streamlit сервер...
start "Streamlit Server" /min cmd /c "streamlit run project.py --server.port 8501 --server.headless true"

echo [2/2] Подключаю защищённый HTTPS туннель Cloudflare...
echo.
echo Ищи строчку с ссылкой вида: https://xxxx.trycloudflare.com
echo ======================================================================
echo.

.\cloudflared.exe tunnel --url http://localhost:8501

pause
