# wg-server-panel

Zweck:
- Verwaltung eines WireGuard-Server-Panels.

Wichtige Pfade:
- Repo: `/home/wolf/wg-server-panel`
- Live-Installation: `/opt/wg-panel`

Stand vom 2026-03-25:
- Lokales Repo auf GitHub-Stand aktualisiert.
- Live-Installation in `/opt/wg-panel` auf aktuellen Repo-Stand gebracht.
- `wg-panel.service` auf `gunicorn`-Start umgestellt.
- Alte `app.py`-Backups und weitere Altlasten in `/opt/wg-panel` bereinigt.

Backups:
- `/home/wolf/wg-panel-backup-20260325-233543.tar.gz`
- `/home/wolf/wg-panel-cleanup-backup-20260325-233709.tar.gz`

Naechste sinnvolle Schritte:
- HTTP-Funktion des Panels pruefen.
- Installationsablauf weiter standardisieren.
- Projektwissen hier fortlaufend aktualisieren.
