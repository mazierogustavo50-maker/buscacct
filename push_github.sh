#!/bin/bash
# Script para fazer push do projeto para o GitHub
# Uso: GITHUB_TOKEN=seu_token ./push_github.sh

set -e

if [ -z "$GITHUB_TOKEN" ]; then
    echo "ERRO: Defina a variavel GITHUB_TOKEN com seu Personal Access Token do GitHub."
    echo "Exemplo: GITHUB_TOKEN=ghp_xxxxxxxxxxxx ./push_github.sh"
    exit 1
fi

cd "$(dirname "$0")"

# Configura remote com autenticação por token
REMOTE_URL="https://${GITHUB_TOKEN}@github.com/mazierogustavo50-maker/buscacct.git"

# Remove remote antigo se existir
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"

# Faz o push
git push -u origin main

echo "Push realizado com sucesso!"
