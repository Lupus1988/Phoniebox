#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/phoniebox-panel
SERVICE_DIR=/etc/systemd/system
BIN_DIR=/usr/local/bin
VENV_DIR="$APP_DIR/.venv"
SOURCE_DIR=$(cd "$(dirname "$0")" && pwd)
BACKUP_DIR=$(mktemp -d)

cleanup() {
  rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT

echo "Installiere Phoniebox Panel nach $APP_DIR"

if [ -d "$APP_DIR/data" ]; then
  echo "Sichere bestehende Daten"
  sudo mkdir -p "$BACKUP_DIR/data"
  sudo cp -a "$APP_DIR/data"/. "$BACKUP_DIR/data"/
fi

if [ -d "$APP_DIR/media" ]; then
  echo "Sichere bestehende Medien"
  sudo mkdir -p "$BACKUP_DIR/media"
  sudo cp -a "$APP_DIR/media"/. "$BACKUP_DIR/media"/
fi

sudo mkdir -p "$APP_DIR" "$BIN_DIR"
sudo cp -a "$SOURCE_DIR"/. "$APP_DIR"/

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip network-manager avahi-daemon alsa-utils mpg123

sudo cp systemd/phoniebox-panel.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-audio-init.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hotspot-fallback.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hotspot-fallback.timer "$SERVICE_DIR"/
sudo cp systemd/phoniebox-runtime-tick.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-runtime-tick.timer "$SERVICE_DIR"/

sudo python3 -m venv "$VENV_DIR"
sudo "$VENV_DIR/bin/pip" install --upgrade pip
sudo "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo "$VENV_DIR/bin/python" -c "import sys; sys.path.insert(0, '$APP_DIR'); from app import ensure_data_files; ensure_data_files()"

if [ -d "$BACKUP_DIR/data" ]; then
  echo "Stelle bestehende Daten wieder her"
  sudo mkdir -p "$APP_DIR/data"
  sudo cp -a "$BACKUP_DIR/data"/. "$APP_DIR/data"/
fi

if [ -d "$BACKUP_DIR/media" ]; then
  echo "Stelle bestehende Medien wieder her"
  sudo mkdir -p "$APP_DIR/media"
  sudo cp -a "$BACKUP_DIR/media"/. "$APP_DIR/media"/
fi

if [ ! -f "$BIN_DIR/phoniebox-set-startup-volume.sh" ]; then
  sudo tee "$BIN_DIR/phoniebox-set-startup-volume.sh" >/dev/null <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  sudo chmod 755 "$BIN_DIR/phoniebox-set-startup-volume.sh"
fi

sudo systemctl daemon-reload
sudo systemctl enable phoniebox-panel.service
sudo systemctl enable phoniebox-audio-init.service
sudo systemctl enable phoniebox-hotspot-fallback.timer
sudo systemctl enable phoniebox-runtime-tick.timer
sudo systemctl restart phoniebox-panel.service
sudo systemctl restart phoniebox-hotspot-fallback.timer
sudo systemctl restart phoniebox-runtime-tick.timer

echo "Installation abgeschlossen."
echo "Panel: http://phoniebox.local:5080"
