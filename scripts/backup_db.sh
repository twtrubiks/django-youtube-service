#!/bin/sh
set -e

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/backup_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "Starting database backup: ${BACKUP_FILE}"
pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"
echo "Backup completed: ${BACKUP_FILE}"

# Keep only the last 7 backups
ls -t "${BACKUP_DIR}"/backup_*.sql.gz 2>/dev/null | tail -n +8 | xargs rm -f
echo "Old backups cleaned up. Current backups:"
ls -lh "${BACKUP_DIR}"/backup_*.sql.gz 2>/dev/null
