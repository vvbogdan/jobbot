#!/usr/bin/env bash
# Packages jobbot into a clean, shareable .zip — bot code and the public resumes.py (generic
# "Frontend" example resume) as-is, but config.py replaced with a single example profile, so
# whoever you send it to can run it immediately without seeing what YOU personally search for.
# Your own config.py and resumes_local.py (your real profiles/resume) are never touched or read.
#
# Usage:
#   ./scripts/make_release.sh
# Output:
#   dist/jobbot-example.zip
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=jobbot-example
rm -rf "dist/$OUT" "dist/$OUT.zip"
mkdir -p "dist/$OUT"

cp jobbot.py i18n.py resumes.py README.md requirements.txt .gitignore "dist/$OUT/"
cp release_templates/config.example.py "dist/$OUT/config.py"

(cd dist && zip -rq "$OUT.zip" "$OUT")
rm -rf "dist/$OUT"

echo "Packaged: dist/$OUT.zip"
echo "Contains only: jobbot.py, i18n.py, resumes.py (generic example), README.md,"
echo "requirements.txt, .gitignore, and a single example config.py profile."
echo "No real profiles, no real resume — your config.py and resumes_local.py stay untouched."
