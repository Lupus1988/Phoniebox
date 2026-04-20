#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/phoniebox-panel
SERVICE_DIR=/etc/systemd/system
BIN_DIR=/usr/local/bin
VENV_DIR="$APP_DIR/.venv"
SOURCE_DIR=$(cd "$(dirname "$0")" && pwd)
BACKUP_DIR=$(mktemp -d)

cleanup() {
  sudo rm -rf "$BACKUP_DIR"
}
trap cleanup EXIT

ensure_boot_config_setting() {
  local config_file=""
  local candidate
  for candidate in /boot/firmware/config.txt /boot/config.txt; do
    if sudo test -f "$candidate"; then
      config_file="$candidate"
      break
    fi
  done
  [ -n "$config_file" ] || return 0

  if ! sudo grep -qxF "$1" "$config_file"; then
    printf '%s\n' "$1" | sudo tee -a "$config_file" >/dev/null
  fi
}

ensure_panel_env_file() {
  local env_file=/etc/default/phoniebox-panel
  local current_secret=""
  if sudo test -f "$env_file"; then
    current_secret=$(sudo sed -n 's/^PHONIEBOX_SECRET_KEY=//p' "$env_file" | tail -n 1 | tr -d '"' | tr -d "'" | tr -d '[:space:]')
  fi
  if [ -n "$current_secret" ]; then
    return 0
  fi

  local generated_secret
  generated_secret=$(python3 - <<'EOF'
import secrets
print(secrets.token_hex(32))
EOF
)

  sudo install -d -m 755 /etc/default
  sudo tee "$env_file" >/dev/null <<EOF
PHONIEBOX_SECRET_KEY="$generated_secret"
PHONIEBOX_HOST=0.0.0.0
PHONIEBOX_PORT=80
EOF
  sudo chmod 600 "$env_file"
}

has_remote_shell() {
  if [ -n "${SSH_CONNECTION:-}" ] || [ -n "${SSH_CLIENT:-}" ] || [ -n "${SSH_TTY:-}" ]; then
    return 0
  fi
  who -m 2>/dev/null | grep -qE '\([[:alnum:].:%-]+\)$'
}

ensure_hardware_groups() {
  local -a groups=(gpio spi input)
  local -a users=()
  local candidate
  for candidate in \
    "${SUDO_USER:-}" \
    "${USER:-}" \
    "${LOGNAME:-}" \
    "$(logname 2>/dev/null || true)" \
    "$(who -m 2>/dev/null | awk '{print $1}' || true)" \
    "$(id -un 2>/dev/null || true)"; do
    [ -n "$candidate" ] || continue
    [ "$candidate" = "root" ] && continue
    case " ${users[*]} " in
      *" $candidate "*) continue ;;
    esac
    users+=("$candidate")
  done

  while IFS=: read -r username _ uid _ _ home shell; do
    [ -n "$username" ] || continue
    [ "$username" = "root" ] && continue
    [ "${uid:-0}" -ge 1000 ] || continue
    case "$shell" in
      */false|*/nologin|"") continue ;;
    esac
    case "$home" in
      /home/*) ;;
      *) continue ;;
    esac
    case " ${users[*]} " in
      *" $username "*) continue ;;
    esac
    users+=("$username")
  done < <(getent passwd)

  [ ${#users[@]} -gt 0 ] || return 0

  local user group
  for user in "${users[@]}"; do
    id "$user" >/dev/null 2>&1 || continue
    for group in "${groups[@]}"; do
      getent group "$group" >/dev/null 2>&1 || continue
      if id -nG "$user" | grep -qw "$group"; then
        continue
      fi
      echo "Füge Benutzer $user der Gruppe $group hinzu"
      sudo usermod -a -G "$group" "$user"
    done
  done
}

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

sudo rm -rf "$APP_DIR"
sudo mkdir -p "$APP_DIR" "$BIN_DIR"
sudo cp -a "$SOURCE_DIR"/. "$APP_DIR"/

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip python3-lgpio network-manager avahi-daemon alsa-utils mpv mpg123
ensure_hardware_groups
ensure_panel_env_file

# Reader-specific buses are enabled by the setup workflow when the user actually installs
# a concrete reader. Avoid broad hardware mutations during base installation.

sudo cp systemd/phoniebox-panel.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-audio-init.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-audio-watchdog.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-gpio-poll.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-leds.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-rfid.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hotspot-fallback.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hotspot-fallback.timer "$SERVICE_DIR"/
sudo cp systemd/phoniebox-network-bootstrap.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-runtime-tick.service "$SERVICE_DIR"/
sudo cp systemd/phoniebox-runtime-tick.timer "$SERVICE_DIR"/
sudo cp systemd/phoniebox-hdmi-off.service "$SERVICE_DIR"/

sudo python3 -m venv "$VENV_DIR"
sudo "$VENV_DIR/bin/pip" install --upgrade pip
sudo "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
# Some upstream packages still pull the legacy RPi.GPIO wheel, which breaks GPIO on newer Pi kernels.
sudo "$VENV_DIR/bin/pip" uninstall -y RPi.GPIO || true
sudo "$VENV_DIR/bin/pip" install --upgrade rpi-lgpio
PY_MINOR=$(python3 - <<'EOF'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
EOF
)
sudo tee "$VENV_DIR/lib/python${PY_MINOR}/site-packages/phoniebox-system-site.pth" >/dev/null <<EOF
/usr/local/lib/python${PY_MINOR}/dist-packages
/usr/lib/python3/dist-packages
/usr/lib/python${PY_MINOR}/dist-packages
EOF
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
sudo systemctl enable NetworkManager.service
sudo systemctl disable --now bluetooth.service 2>/dev/null || true
sudo systemctl disable --now hciuart.service 2>/dev/null || true
ensure_boot_config_setting "dtoverlay=disable-bt"
ensure_boot_config_setting "hdmi_ignore_hotplug=1"
ensure_boot_config_setting "display_auto_detect=0"
if command -v rfkill >/dev/null 2>&1; then
  sudo rfkill block bluetooth || true
fi
sudo systemctl enable phoniebox-panel.service
sudo systemctl enable phoniebox-audio-init.service
sudo systemctl enable phoniebox-audio-watchdog.service
sudo systemctl enable phoniebox-gpio-poll.service
sudo systemctl enable phoniebox-leds.service
sudo systemctl enable phoniebox-rfid.service
sudo systemctl enable phoniebox-hdmi-off.service
sudo systemctl enable phoniebox-network-bootstrap.service
sudo systemctl enable phoniebox-hotspot-fallback.timer
sudo systemctl disable --now phoniebox-runtime-tick.timer 2>/dev/null || true
sudo systemctl enable phoniebox-runtime-tick.service
sudo "$VENV_DIR/bin/python" "$APP_DIR/scripts/bootstrap_network.py" --seed-only || true
sudo systemctl restart phoniebox-panel.service
sudo systemctl restart phoniebox-audio-watchdog.service
sudo systemctl restart phoniebox-gpio-poll.service
sudo systemctl restart phoniebox-leds.service
sudo systemctl restart phoniebox-rfid.service
sudo systemctl restart phoniebox-hdmi-off.service
if has_remote_shell; then
  echo "Aktive Remote-Sitzung erkannt: Netzwerkprofil nur vorbereitet, nicht live umgeschaltet."
else
  sudo systemctl restart phoniebox-network-bootstrap.service || true
fi
sudo systemctl restart phoniebox-hotspot-fallback.timer
sudo systemctl restart phoniebox-runtime-tick.service

echo "Installation abgeschlossen."
echo "Panel: http://phoniebox.local"
