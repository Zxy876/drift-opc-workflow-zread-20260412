#!/usr/bin/env bash
set -euo pipefail

: "${MINECRAFT_START_SCRIPT:?MINECRAFT_START_SCRIPT is required}"

if [[ ! -x "${MINECRAFT_START_SCRIPT}" ]]; then
  echo "Minecraft start script is not executable: ${MINECRAFT_START_SCRIPT}" >&2
  exit 1
fi

cd "$(dirname "${MINECRAFT_START_SCRIPT}")"
exec "${MINECRAFT_START_SCRIPT}"