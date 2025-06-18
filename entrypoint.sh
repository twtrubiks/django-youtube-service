#!/bin/sh

# 如果任何指令失敗，立即退出
set -e

echo 'Run migration'
python manage.py makemigrations
python manage.py migrate

echo "Running one-time setup (create_category)..."
python3 manage.py create_category
echo "Setup complete."

# echo 'Create Super User'
# python3 manage.py createsuperuser --noinput || echo "Super user already created"
# echo 'Collect Static'
# python3 manage.py collectstatic --noinput

# 執行傳遞給此腳本的任何指令
# "$@" 會獲取 Docker CMD 或 docker-compose command 中的指令
exec "$@"


