# Phoniebox

Python-basiertes Web-Panel fuer eine flexible Audio-Box auf Raspberry Pi, mit Fokus auf sauberem Out-of-the-box-Setup fuer Pi Zero 2 W und aehnliche Targets.

Enthalten:
- `Flask`-Panel mit `Player`, `Bibliothek`, `Einstellungen` und `Setup`
- Installer fuer `/opt/phoniebox-panel` inklusive Virtualenv, systemd-Diensten und Timern
- WLAN-/Hotspot-Bootstrap fuer frische Pi-Installationen
- Audio-, RFID-, GPIO- und LED-Konfiguration ueber das Web-UI
- Ordnerbasierter Albumimport mit `playlist.m3u`
- Tests fuer App-Routen, Runtime, Audio-Deployment und Netzwerk-Bootstrap

## Schnellstart auf dem Pi

```bash
git clone git@github.com:Lupus1988/Phoniebox.git
cd Phoniebox
sudo bash ./install.sh
```

Danach ist das Panel standardmaessig unter `http://phoniebox.local:5080` erreichbar.

Der Installer:
- sichert vorhandene `data/`- und `media/`-Inhalte
- ersetzt den Anwendungscode in `/opt/phoniebox-panel` sauber
- legt eine Python-Virtualenv an und installiert die Python-Abhaengigkeiten
- installiert die systemd-Dienste und Timer
- bereitet WLAN-Client- und Hotspot-Profile fuer den Erststart vor
- deaktiviert Bluetooth, blockiert es per `rfkill` und schaltet HDMI ab
- aktiviert auf Raspberry Pi nach Moeglichkeit `I2C` und `SPI`; `UART` bleibt standardmaessig unberuehrt und wird nur bei Bedarf fuer passende Reader manuell aktiviert

## Lokale Entwicklung

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Dann erreichbar unter `http://SERVER-IP:5080`.

Automatische Tests:

```bash
python3 -m unittest discover -s tests
```

## Werkzustand

Ein frischer Clone enthaelt absichtlich keine Laufzeitdaten und keine Demo-Alben im Git-Stand. Fehlende JSON-Dateien in `data/` werden beim ersten Start automatisch mit Factory-Defaults erzeugt.

Standardverhalten fuer neue Installationen:
- WLAN-Modus startet mit `hotspot_only`
- Hotspot-SSID ist `Phonie-hotspot`
- gespeicherte WLAN-Netze sind anfangs leer
- Bibliothek startet leer
- Player und Runtime starten eingeschaltet, aber ohne laufende Wiedergabe

## Hinweise

- Fuer `phoniebox.local` wird `avahi-daemon` verwendet.
- Das Audio-Backend bevorzugt `mpg123`, faellt sonst auf Alternativen oder `mock` zurueck.
- Reader-Profile fuer `USB`, `RC522` und `PN532` ueber `I2C`, `SPI` und `UART` sind vorbereitet.
- Wichtiger Reader-Befund aus dem Generaltest auf Pi Zero 2 W: Ein frisches System mit aktiviertem SPI erkennt den `RC522` im nackten `spidev`-Test korrekt (`VersionReg = 0x92`). Der spaetere Ausfall liess sich im Repro enger auf Installations-/Boot-Zustaende rund um den Serial-/UART-Pfad eingrenzen, nicht auf `32-bit` gegen `64-bit` als Grundursache.
- Der Designentwurf liegt unter `docs/Designentwurf.pdf`.
