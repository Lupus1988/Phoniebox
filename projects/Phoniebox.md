# Phoniebox

Zweck:
- Aufbau eines flexibel konfigurierbaren, Python-basierten Phoniebox-Panels als installierbares System.
- Ziel: einmal installieren, danach Reader, GPIO, LEDs, WLAN und Medien weitgehend nur noch ueber das Web-UI konfigurieren.

Wichtige Pfade:
- Projektordner: `/home/wolf/ccmem/projects/Phoniebox`
- Panel: `/home/wolf/ccmem/projects/Phoniebox/panel`
- Entwurf: `/home/wolf/ccmem/projects/Phoniebox/Designentwurf.pdf`

Stand vom 2026-03-28:
- Eigenes Python/Flask-Panel mit `Player`, `Bibliothek`, `Einstellungen` und `Setup` aufgebaut.
- WLAN-/Hotspot-Konzept inklusive Factory-Hotspot `Phonie-hotspot` und Zielname `phoniebox.local` integriert.
- RFID-Linking auf Popup-Flow umgestellt: `Jetzt Tag scannen`, naechster Tag wird verknuepft, Konflikte werden blockiert.
- Bibliothek arbeitet ordnerbasiert; Albumimport erzeugt automatisch `playlist.m3u`.
- Runtime-Kern fuer Player, Sleeptimer, RFID, Button-Events, GPIO-Simulation und LED-Status aufgebaut.
- Hardware-Abstraktionsschicht fuer USB-Reader, RC522 und PN532 (I2C/SPI/UART) vorbereitet.
- Tastenmapping per Drag-and-Drop fuer kurzen und langen Tastendruck vorbereitet.
- Playback-Abstraktion mit aktuellem `mock`-Backend eingebaut; spaeter sollen echte Backends wie `mpg123` oder `cvlc` darunter angeschlossen werden.
- Reader-spezifisches Tag-Verhalten aus dem Setup ist jetzt primaere Runtime-Quelle.
- Diagnoseflaechen fuer GPIO-, RFID- und Tick-Simulation sowie Ereignisprotokoll vorhanden.

Besondere Regeln:
- Gleicher GPIO ist erlaubt, wenn `kurz` und `lang` unterschiedliche Funktionen haben.
- Gleiche Funktion darf im selben Drucktyp nicht mehrfach vergeben werden.
- Reader-reservierte Pins sollen aus der UI gefiltert bleiben.
- Medien sollen spaeter bevorzugt ueber Playlist-Dateien statt live ueber Ordnerscans abgespielt werden.

Naechste sinnvolle Schritte:
- Echtes Playback-Backend unter `runtime/playback.py` einbauen.
- Spaeter echte Reader-, GPIO- und LED-Adapter auf die bestehende Runtime schalten.
- UI/Layout noch naeher an den PDF-Entwurf heranbringen.
- Reader-Profile und Validierung weiter haerten.
