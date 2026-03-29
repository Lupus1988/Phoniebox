# Phoniebox

Zweck:
- Aufbau eines flexibel konfigurierbaren, Python-basierten Phoniebox-Panels als installierbares System.
- Ziel: einmal installieren, danach Reader, GPIO, LEDs, WLAN und Medien weitgehend nur noch ueber das Web-UI konfigurieren.

Wichtige Pfade:
- Projektordner: `/home/wolf/ccmem/projects/Phoniebox`
- Panel: `/home/wolf/ccmem/projects/Phoniebox/panel`
- Entwurf: `/home/wolf/ccmem/projects/Phoniebox/Designentwurf.pdf`

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
- Automatisierte Offline-Tests fuer Runtime- und Audio-Systempfade vorhanden.
- Projekt nach privatem GitHub-Repo `git@github-ccmem:Lupus1988/Phoniebox.git` gepusht.

Besondere Regeln:
- Gleicher GPIO ist erlaubt, wenn `kurz` und `lang` unterschiedliche Funktionen haben.
- Gleiche Funktion darf im selben Drucktyp nicht mehrfach vergeben werden.
- Reader-reservierte Pins sollen aus der UI gefiltert bleiben.
- Medien sollen spaeter bevorzugt ueber Playlist-Dateien statt live ueber Ordnerscans abgespielt werden.

Naechste sinnvolle Schritte:
- Clean-Install auf einem frischen zweiten Pi durchtesten.
- Reader-, GPIO- und LED-Adapter auf denselben Universal-/Deploy-Ansatz ziehen.
- Installer und Erststart weiter haerten, bis der Endnutzer moeglichst nur noch das Web-UI braucht.
- UI/Layout noch naeher an den PDF-Entwurf heranbringen.
- Reader-Profile und Validierung weiter haerten.
