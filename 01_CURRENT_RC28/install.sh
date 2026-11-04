#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
sha256sum -c SHA256SUMS
python3 -B -m unittest discover -s tests -p 'test_rc28.py' -q
TARGET=/opt/sigenstor/scripts/phase3b-supervised-rc28
if [[ -e "$TARGET" ]]; then echo 'RC28 already present: refusing overwrite';exit 2;fi
mkdir -p "$TARGET"
cp -a controller accepted tests *.md SHA256SUMS "$TARGET"/
echo 'RC28 staged; manual commissioning-only preflight available. No services or Modbus writes.'
