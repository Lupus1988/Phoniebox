# Session 2026-03-25

Projekt:
- wg-server-panel

Erledigt:
- Lokales Repo unter `/home/wolf/wg-server-panel` auf `origin/main` aktualisiert.
- Live-Installation unter `/opt/wg-panel` aktualisiert.
- `gunicorn` in bestehende venv installiert.
- systemd-Unit fuer `wg-panel.service` aktualisiert und Dienst neu gestartet.
- Alte `app.py`-Backup-Dateien entfernt.
- Weitere Altlasten (`release/`, `templates/`, alte `server.json`-Backups) entfernt.

Ergebnis:
- `wg-panel.service` laeuft mit der neuen `gunicorn`-Konfiguration.

Offen:
- Optional HTTP-Endpunkt des Panels pruefen.

Backups:
- `/home/wolf/wg-panel-backup-20260325-233543.tar.gz`
- `/home/wolf/wg-panel-cleanup-backup-20260325-233709.tar.gz`
