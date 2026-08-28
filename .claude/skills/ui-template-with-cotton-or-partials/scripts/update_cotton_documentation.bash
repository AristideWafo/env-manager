#!/usr/bin/env bash
set -euo pipefail

DOCUMENTATION_DIRECTORY="$(cd "$(dirname "$0")/.." && pwd)/documentation"

COTTON_DIRECTORY="${DOCUMENTATION_DIRECTORY}/django-cotton/"

[[ -z "${COTTON_DIRECTORY}" ]] && { echo "Error: COTTON_DIRECTORY is empty"; exit 1; }

STAMP="${COTTON_DIRECTORY}/.last_updated"

if [ ! -f "${STAMP}" ] || [ "$(find "${STAMP}" -mtime +14 2>/dev/null)" ]; then
  echo "Updating Cotton documentation in ${COTTON_DIRECTORY}"

  TEMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TEMP_DIR}"' EXIT

  git clone --depth 1 https://github.com/wrabit/django-cotton "${TEMP_DIR}/django-cotton"

  rm -rf "${COTTON_DIRECTORY}"
  mkdir -p "${COTTON_DIRECTORY}"
  mv "${TEMP_DIR}/django-cotton/docs/"* "${COTTON_DIRECTORY}/"

  touch "${STAMP}"

  echo "Cotton documentation updated successfully"
else
  echo "Cotton documentation is up to date in ${COTTON_DIRECTORY}"
fi
