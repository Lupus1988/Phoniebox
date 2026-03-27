# Phoniebox Panel

Python-basiertes Panel fuer eine kinderfreundliche Audio-Box nach dem Entwurf in `Designentwurf.pdf`.

Aktueller Stand:
- `Flask`-Panel mit den Bereichen `Player`, `Bibliothek`, `Einstellungen` und `Setup`
- persistente JSON-Konfiguration in `data/`
- RFID-Album-Zuordnung mit einfacher Kollisionspruefung
- Reader-, Tasten- und LED-Konfiguration
- WLAN-/Hotspot-Bereich mit gespeicherten Netzwerken und optionalem Live-Status ueber `nmcli`
- Factory-Default fuer Erststart: offener Hotspot `Phonie-hotspot`
- Hostname-/Browser-Namen-Konfiguration fuer spaetere lokale Erreichbarkeit
- Systemintegrationshelfer fuer `nmcli`, `hostnamectl` und Fallback-Hotspot-Zyklen
- Installationsskript und systemd-Servicevorlagen fuer lokalen Dauerbetrieb
- erster Runtime-Kern fuer Player, Sleeptimer, RFID-Events, Button-Events und LED-Status
- JSON-API fuer Laufzeitstatus und Simulations-Trigger
- Albumimport als Ordner-Upload mit automatischer `playlist.m3u`-Erzeugung

Start lokal:

```bash
cd /home/wolf/ccmem/projects/Phoniebox/panel
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Danach erreichbar unter:

`http://SERVER-IP:5080`

Hinweis:
- Das Panel speichert aktuell Soll-Konfigurationen.
- Netzwerk- und Hostname-Aenderungen koennen aus dem Setup auf das System angewendet werden.
- Dafuer braucht der Dienst spaeter passende Rechte fuer `sudo nmcli` und `sudo hostnamectl`.
- Reader-, GPIO- und Audio-Backend sind als Runtime-Stubs vorbereitet, aber noch nicht direkt an echte Hardwarebibliotheken angebunden.
- Fuer lokale Namen ist `phoniebox.local` per mDNS/Avahi der robuste Standard. `phonie.box` braucht zusaetzliche DNS- oder Router-Logik.

Runtime-API:
- `GET /api/runtime` liefert den aktuellen Laufzeitstatus.
- `POST /api/runtime/tick` fuehrt einen Tick aus, z. B. `{"elapsed": 1}`.
- `POST /api/runtime/rfid` simuliert einen Scan, z. B. `{"uid": "1234567890"}`.
- `POST /api/runtime/button` simuliert einen Tastendruck, z. B. `{"name": "Play/Pause", "press_type": "kurz"}`.

Medienworkflow:
- Neue Alben werden ueber die Bibliothek als kompletter Ordner importiert.
- Dateien landen unter `media/albums/<album-slug>/`.
- Nach dem Import wird automatisch `playlist.m3u` erzeugt.
- Der spaetere Player soll primär die Playlist lesen, nicht den Ordner live scannen.

Flexibles Hardware-Zielbild:
- Installation einmal deployen, danach Reader-, GPIO- und LED-Zuordnung vollständig im Web-UI.
- Reader-Auswahl aus einem Treiberkatalog statt Codeanpassung.
- GPIO-Pins fuer Tasten und LEDs per Dropdown konfigurierbar.
- Kontrollfenster fuer spaetere Tasterkennung ist vorbereitet und aktuell per GPIO-Simulation testbar.
- Gängige Reader-Pfade sind bereits als Profile vorgesehen: USB-Keyboard-Reader, RC522, PN532 ueber I2C/SPI/UART.
