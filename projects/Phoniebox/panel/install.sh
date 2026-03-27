#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/phoniebox-panel
SERVICE_DIR=/etc/systemd/system

sudo mkdir -p "$APP_DIR"
sudo cp -r ./* "$APP_DIR"/

sudo apt-get update
sudo apt-get install -y python3-flask network-manager avahi-daemon

sudo cp systemd/phoniebox-panel.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hotspot-fallback.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hotspot-fallback.timer "$SERVICE_DIR"/
sudo cp systemd/phoniebox-runtime-tick.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-runtime-tick.timer "$SERVICE_DIR"/

sudo systemctl daemon-reload
sudo systemctl enable phoniebox-panel.service
sudo systemctl enable phoniebox-hotspot-fallback.timer
sudo systemctl enable phoniebox-runtime-tick.timer

echo "Installation abgeschlossen."
echo "Panel: http://phoniebox.local:5080"
