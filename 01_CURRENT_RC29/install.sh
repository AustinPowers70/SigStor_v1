#!/usr/bin/env bash
# RC29 install: stages files only. NO services touched, NO Modbus access, NO latch changes.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
sha256sum -c --quiet SHA256SUMS
python3 -B -m unittest discover -s tests -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc29
if [[ -e "$TARGET" ]]; then echo 'RC29 already present: refusing overwrite'; exit 2; fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC29 staged at '"$TARGET"'. NO_WRITES_ON_INSTALL. Latch untouched. Next: --status then --review.'
