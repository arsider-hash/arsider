#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

echo "ARSIDER ASSISTANT // Termux bootstrap"
pkg update -y
pkg install -y python git ffmpeg openssh

mkdir -p data logs
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "Created .env. Add TELEGRAM_BOT_TOKEN and exactly two ADMIN_IDS before running."
fi

python -m unittest discover -s tests -v

echo
echo "Core OK. Start later with: python run.py"
echo "Optional for long-running use: termux-wake-lock"
