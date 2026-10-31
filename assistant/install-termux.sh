#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "ARSIDER ASSISTANT // Termux bootstrap"
pkg update -y
pkg install -y python git ffmpeg openssh termux-services
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p data logs backups
if [ ! -f .env ]; then
  cp .env.example .env
fi
chmod 600 .env || true
chmod +x arsiderctl install-termux.sh

SERVICE_DIR="$PREFIX/var/service/arsider-assistant"
LOG_DIR="$PREFIX/var/log/sv/arsider-assistant"
mkdir -p "$SERVICE_DIR/log" "$LOG_DIR"
cat > "$SERVICE_DIR/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
cd "$HERE"
exec python run.py 2>&1
EOF
cat > "$SERVICE_DIR/log/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
exec svlogd -tt "$LOG_DIR"
EOF
chmod +x "$SERVICE_DIR/run" "$SERVICE_DIR/log/run"
touch "$SERVICE_DIR/down"

mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/arsider-assistant" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sv up arsider-assistant >/dev/null 2>&1 || true
EOF
chmod +x "$HOME/.termux/boot/arsider-assistant"

# Convenience command when the repo is kept in this directory.
ln -sf "$HERE/arsiderctl" "$PREFIX/bin/arsiderctl"

python -m unittest discover -s tests -v
printf 'status\n/on\ntrovami un pdf\n/stop\nquit\n' | python simulate.py >/dev/null

echo
echo "Core tests OK."
echo "1) Put only TELEGRAM_BOT_TOKEN into .env"
echo "2) Run: arsiderctl pair"
echo "3) From the two admin accounts send the shown /pair CODE"
echo "4) Run: arsiderctl health"
echo "5) Run: arsiderctl start"
echo
echo "The service stays disabled until step 5. No inbound network port is opened."
echo "For boot start, install/open the official Termux:Boot add-on once on Android."
