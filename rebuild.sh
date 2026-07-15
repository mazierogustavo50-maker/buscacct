#!/bin/bash
set -e

echo "=== Parando containers... ==="
docker-compose down

echo ""
echo "=== Rebuildando imagem SEM cache... ==="
docker-compose build --no-cache

echo ""
echo "=== Subindo containers... ==="
docker-compose up -d

echo ""
echo "=== Pronto! Containers em execução: ==="
docker-compose ps
