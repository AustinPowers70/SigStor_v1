#!/usr/bin/env bash
# Safe source-only snapshot from Thor. Does not call Modbus, restart services,
# read octopus secrets or copy production data/DBs. Review before using.
set -euo pipefail
OUT=/tmp/copy-paste
SRC=/opt/sigenstor/scripts
mkdir -p "$OUT"
if [[ ! -d "$SRC" ]]; then echo "Source directory unavailable: $SRC" >&2; exit 1; fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="$OUT/SigenStor_Thor_Source_${STAMP}.tar.gz"
LIST=$(mktemp "$OUT/source-list.XXXXXX")
trap 'rm -f "$LIST"' EXIT
cd /opt/sigenstor
# Strict extensions: excludes .txt/.json/.db/.sqlite/.env/.pem/.key/auth configs.
find scripts -type f \( -name '*.py' -o -name '*.ps1' -o -name '*.sh' -o -name '*.md' \) \
 -not -path '*/__pycache__/*' -not -iname '*key*' -not -iname '*secret*' \
 -not -iname '*password*' -not -iname '*credential*' -print0 > "$LIST"
tar --null -czf "$ARCHIVE" -T "$LIST"
echo "Created source-only archive: $ARCHIVE"
sha256sum "$ARCHIVE"
echo 'Review file list and source for embedded secrets before sharing with Claude.'
