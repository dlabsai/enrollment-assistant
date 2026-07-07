#!/bin/bash
set -euo pipefail

VOLUME_NAME="demo-va-postgres-data"
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
BACKUP_DIR=$(mkdir -p ../va-db-data-backups && cd ../va-db-data-backups && pwd)
BACKUP_FILE="${BACKUP_DIR}/postgres-data-${TIMESTAMP}.tgz"

if ! docker volume inspect "${VOLUME_NAME}" >/dev/null 2>&1; then
    echo "Docker volume '${VOLUME_NAME}' not found" >&2
    exit 1
fi

docker run --rm \
    -v "${VOLUME_NAME}:/volume:ro" \
    -v "${BACKUP_DIR}:/backup" \
    busybox \
    tar -czf "/backup/$(basename "${BACKUP_FILE}")" -C /volume .

echo "Created ${BACKUP_FILE}"
