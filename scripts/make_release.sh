#!/usr/bin/env bash
# Packages jobbot into a clean, shareable .zip — bot/ code and the public bot/resumes.py (generic
# "Frontend" example resume) as-is, but bot/config.py replaced with a single example profile, so
# whoever you send it to can run it immediately without seeing what YOU personally search for.
# Your own bot/config.py and bot/resumes_local.py (your real profiles/resume) are never touched
# or read.
#
# Usage:
#   ./scripts/make_release.sh
# Output:
#   dist/jobbot-example.zip
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=jobbot-example
rm -rf "dist/$OUT" "dist/$OUT.zip"
mkdir -p "dist/$OUT/bot"

cp jobbot.py README.md requirements.txt .gitignore "dist/$OUT/"
cp bot/__init__.py bot/net.py bot/i18n.py bot/logutil.py bot/matching.py bot/state.py \
   bot/telegram_api.py bot/resume.py bot/firebase_store.py bot/resumes.py "dist/$OUT/bot/"
cp -r bot/sources "dist/$OUT/bot/sources"
cp release_templates/config.example.py "dist/$OUT/bot/config.py"

(cd dist && zip -rq "$OUT.zip" "$OUT")
rm -rf "dist/$OUT"

echo "Packaged: dist/$OUT.zip"
echo "Contains: jobbot.py + bot/ (net.py, i18n.py, logutil.py, matching.py, state.py,"
echo "telegram_api.py, resume.py, firebase_store.py, sources/, resumes.py (generic example),"
echo "and a single example bot/config.py profile), README.md, requirements.txt, .gitignore."
echo "No real profiles, no real resume — your bot/config.py and bot/resumes_local.py stay untouched."
