# Phoniebox

Zweck:
- Aufbau eines flexibel konfigurierbaren, Python-basierten Phoniebox-Panels als installierbares System.
- Ziel: einmal installieren, danach Reader, GPIO, LEDs, WLAN und Medien weitgehend nur noch ueber das Web-UI konfigurieren.

Wichtige Pfade:
- Projektordner: `/home/wolf/ccmem/projects/Phoniebox`
- Panel: `/home/wolf/ccmem/projects/Phoniebox/panel`
- Entwurf: `/home/wolf/ccmem/projects/Phoniebox/Designentwurf.pdf`
- Live-Standard fuer UI und Deploys: `~/ccmem/projects/Phoniebox/panel` ist die massgebliche Referenz fuer den laufenden Stand in `/opt/phoniebox-panel`.
- Zweite lokale Kopien wie `/home/wolf/Phoniebox/projects/Phoniebox/panel` duerfen nicht mehr als stillschweigende Design-Referenz behandelt werden; vor Deploys oder Repo-Sync zuerst auf den `ccmem`-Stand zurueckziehen.

Screenshot-Freigabe fuer Codex:
- Standard-Link fuer Screenshots waehrend der Arbeit: `https://knittel.tplinkdns.com/s/8EyYcbR9Kf7KJ3w`
- Die Freigabe ist eine oeffentliche Nextcloud-Ordnerfreigabe `Screenshots`.
- Zusaetzlicher Freigabeordner ab 2026-04-01: `https://knittel.tplinkdns.com/s/oy9yTW4yCxCk5Tt`
- Der neue Freigabeordner soll ebenfalls ueber WebDAV unter `https://knittel.tplinkdns.com/public.php/dav/files/oy9yTW4yCxCk5Tt/` gelesen werden.
- Bewaehrter Abruf: Dateiliste per `PROPFIND` auf `https://knittel.tplinkdns.com/public.php/dav/files/8EyYcbR9Kf7KJ3w/`, Einzeldateien danach direkt ueber denselben WebDAV-Pfad herunterladen.
- Verifiziert am 2026-03-30: Datei `Test screenshot.bmp` war ueber WebDAV abrufbar; die Datei war als `.bmp` benannt, enthielt aber tatsaechlich PNG-Bilddaten.
- Verifiziert am 2026-03-30: Auch `02.bmp`, `04.bmp` und `link entfernen.bmp` sind ueber WebDAV direkt lesbar; `file` meldet trotz `.bmp`-Endung PNG-Bilddaten.
- Praktischer Ablauf fuer UI-Abgleich:
  1. `curl -I -s https://knittel.tplinkdns.com/s/8EyYcbR9Kf7KJ3w`
  2. `curl -s -X PROPFIND -H 'Depth: 1' https://knittel.tplinkdns.com/public.php/dav/files/8EyYcbR9Kf7KJ3w/`
  3. Datei nach `/tmp/...` laden, z. B. `curl -s -o /tmp/04.bmp https://knittel.tplinkdns.com/public.php/dav/files/8EyYcbR9Kf7KJ3w/04.bmp`
  4. Mit `file /tmp/04.bmp` den echten Dateityp pruefen
  5. Danach die lokale Datei direkt als Bild oeffnen und daran das UI ausrichten

Stand vom 2026-03-29:
- Eigenes Python/Flask-Panel mit `Player`, `Bibliothek`, `Einstellungen` und `Setup` aufgebaut.
- WLAN-/Hotspot-Konzept inklusive Factory-Hotspot `Phonie-hotspot` und Zielname `phoniebox.local` integriert.
- RFID-Linking auf Popup-Flow umgestellt: `Jetzt Tag scannen`, naechster Tag wird verknuepft, Konflikte werden blockiert.
- Bibliothek arbeitet ordnerbasiert; Albumimport erzeugt automatisch `playlist.m3u`.
- Runtime-Kern fuer Player, Sleeptimer, RFID, Button-Events, GPIO-Simulation und LED-Status aufgebaut.
- Hardware-Abstraktionsschicht fuer USB-Reader, RC522 und PN532 (I2C/SPI/UART) vorbereitet.
- Tastenmapping per Drag-and-Drop fuer kurzen und langen Tastendruck vorbereitet.
- Playback-Abstraktion mit echtem Prozess-Backend erweitert: bevorzugt `mpg123`, alternativ `cvlc`, sonst `mock`.
- Reader-spezifisches Tag-Verhalten aus dem Setup ist jetzt primaere Runtime-Quelle.
- Diagnoseflaechen fuer GPIO-, RFID- und Tick-Simulation sowie Ereignisprotokoll vorhanden.
- Direkte Runtime-Steuerung ohne RFID erweitert: Alben lassen sich aus der Bibliothek laden, starten, seeken und in die Warteschlange legen.
- Audio-Setup zu einem universellen Hardware-Profil ausgebaut: Soundkarten-Erkennung, Audio-Ausgabemodus, bevorzugtes ALSA-Ziel, Mixer-Control, Startlautstaerke, I2S-Profile und Pi-Zero-2W-Hinweise.
- Audio-Systemartefakte werden aus dem Web-UI generiert: `asound.conf`, Boot-Snippet, Startlautstaerke-Skript und Zusammenfassung.
- Audio-Systemdeployment vorbereitet: Dateien koennen aus dem Panel aufs Zielsystem installiert werden, inklusive Startlautstaerke-Service und optional verwalteter `usercfg.txt`.
- Lokale Installation auf Host `Test` erfolgreich verifiziert: Deployment nach `/opt/phoniebox-panel`, Panel-Service unter `gunicorn`, Runtime-Timer aktiv, HTTP-Check auf Port 5080 erfolgreich.
- Frontend-Struktur nach Designentwurf neu ausgerichtet: horizontale Tabs, klarere Tabellen-/Board-Ansichten, Setup als zentrales Universal-Hardware-Panel.
- Player-UX weiter verfeinert: technische Statusanzeigen aus der Endnutzeransicht entfernt, dunkleres Theme, farblich beruhigte Aktivzustände, asynchrone Lautstärke-/Sleeptimer-Steuerung ohne Vollreload und Seek-Slider mit Live-Zeitblase.
- Automatisierte Offline-Tests fuer Runtime- und Audio-Systempfade vorhanden.
- Projekt nach privatem GitHub-Repo `git@github-ccmem:Lupus1988/Phoniebox.git` gepusht.

Ergaenzung vom 2026-03-30:
- Wissensspeicher fuer externe Screenshots erweitert: oeffentliche Nextcloud-Freigabe `https://knittel.tplinkdns.com/s/8EyYcbR9Kf7KJ3w` ist als Standardweg fuer UI-Screenshots vermerkt; Dateiliste und Einzeldateien lassen sich ueber den WebDAV-Pfad unter `https://knittel.tplinkdns.com/public.php/dav/files/8EyYcbR9Kf7KJ3w/` abrufen.
- Player-UI fuer Smartphone und Desktop weiter getrennt verfeinert: kombinierter seekbarer Zeitstrahl, runder Cover-Fortschrittsring, symbolische Transportsteuerung, kompaktere Mobile-Ansicht und Utility-Zeile fuer Lautstaerke/Sleeptimer.
- Lautstaerke-Steuerung erweitert: `Stumm` arbeitet jetzt als echter Toggle mit Rueckkehr auf die vorherige Lautstaerke; stummer Zustand wird in der UI ausgegraut und durchgestrichen markiert.
- Bibliothek fuer Desktop stark umgebaut: reduzierte Albumuebersicht mit Spalten `Alben`, `Status`, `Tag-ID`, `Aktionen`, klickbare Link-/Unlink-Symbole, zentrierte Spaltenkoepfe und schlankere Karten.
- Bibliothek-Workflows zu Popup-Flows umgebaut: `+ Neues Album` statt statischer Import-Kachel, leere Alben sind moeglich; `Bearbeiten` oeffnet Titel-hinzufuegen/-entfernen; RFID-Linking arbeitet ueber Bestaetigung, 15s Scanfenster und Erfolgsdialog.

Besondere Regeln:
- Gleicher GPIO ist erlaubt, wenn `kurz` und `lang` unterschiedliche Funktionen haben.
- Gleiche Funktion darf im selben Drucktyp nicht mehrfach vergeben werden.
- Reader-reservierte Pins sollen aus der UI gefiltert bleiben.
- Medien sollen spaeter bevorzugt ueber Playlist-Dateien statt live ueber Ordnerscans abgespielt werden.
- Sichtbare UI-Aenderungen moeglichst direkt nach der Anpassung nach `/opt/phoniebox-panel` deployen und `phoniebox-panel.service` neu starten, damit der Nutzer das Ergebnis sofort im Browser pruefen kann.
- Wenn Design oder Live-Panel einmal nachweislich gut sind, gilt dieser Live-Stand in `~/ccmem/projects/Phoniebox/panel` als Stammstandard; abweichende lokale Arbeitskopien muessen vor weiteren Aenderungen daran angeglichen werden.
- Installer-Stand ab 2026-04-01: fuer Raspberry Pi werden bei der Installation nach Moeglichkeit `I2C`, `SPI` und `UART` per `raspi-config` automatisch aktiviert; Bluetooth wird deaktiviert und per `rfkill` geblockt, HDMI wird ueber einen eigenen systemd-Dienst abgeschaltet.

Naechste sinnvolle Schritte:
- Clean-Install auf einem frischen zweiten Pi durchtesten.
- Reader-, GPIO- und LED-Adapter auf denselben Universal-/Deploy-Ansatz ziehen.
- Installer und Erststart weiter haerten, bis der Endnutzer moeglichst nur noch das Web-UI braucht.
- UI/Layout noch naeher an den PDF-Entwurf heranbringen.
- Reader-Profile und Validierung weiter haerten.
