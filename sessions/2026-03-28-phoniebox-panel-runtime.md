# Session 2026-03-28

Projekt:
- Phoniebox

Erledigt:
- Wissensspeicher um ein neues Projekt `Phoniebox` erweitert.
- Python/Flask-Panel unter `projects/Phoniebox/panel` aufgebaut.
- Seiten `Player`, `Bibliothek`, `Einstellungen` und `Setup` entlang des PDF-Entwurfs angelegt.
- Factory-Hotspot `Phonie-hotspot` und Zielname `phoniebox.local` vorbereitet.
- WLAN-/Hotspot-Systemintegration via `nmcli`/`hostnamectl` und systemd-Dateien vorbereitet.
- Bibliothek auf ordnerbasierten Import umgestellt; pro Album wird `playlist.m3u` erzeugt.
- RFID-Linking auf scanbasierten Popup-Flow umgestellt, Konflikte bei bereits verlinkten Tags werden blockiert.
- Runtime-Kern fuer Player, Sleeptimer, RFID, GPIO-Simulation, LED-Status und Ereignislog aufgebaut.
- Hardware-Abstraktionsschicht fuer gaengige Readerprofile und GPIO-/LED-/Audio-Readiness eingebaut.
- Drag-and-Drop-Mapping fuer kurze und lange Tastendruecke vorbereitet.
- Playback-Abstraktion mit aktuellem `mock`-Backend eingebaut.
- Reader-spezifisches Tag-Verhalten aus dem Setup zur primaeren Runtime-Quelle gemacht.
- Diagnoseflaechen fuer GPIO-, RFID- und Tick-Simulation eingebaut.

Entscheidungen:
- Das Projekt wird Python-basiert statt PHP-basiert weitergefuehrt.
- Die Box soll spaeter als installierbares System funktionieren, ohne Codeanpassungen fuer Reader-/GPIO-/LED-Konfiguration.
- Reader-Verhalten fuer `Tag lesen` und `Tag entfernen` wird im Setup am Readerprofil gefuehrt.
- Albumimport soll ueber Ordner erfolgen; der Player soll bevorzugt ueber erzeugte Playlist-Dateien arbeiten.
- Gleiches GPIO fuer `kurz` und `lang` ist erlaubt; gleiche Funktion im selben Drucktyp nicht.

Offen:
- Echtes Playback-Backend unter `runtime/playback.py` einbauen.
- Spaeter echte Reader-, GPIO- und LED-Adapter auf die bestehende Runtime schalten.
- UI/Layout noch naeher an den PDF-Entwurf heranbringen.
- Reader-/Pinvalidierung und Diagnose weiter verfeinern.
- Eventuell globale und readerspezifische Einstellungen noch klarer voneinander trennen.

Naechster Start:
- `ccmem start: lies ~/ccmem/START-HERE.md und arbeite mit diesem Wissensspeicher`
- Danach im Projekt `Phoniebox` weitermachen, zuerst echtes Playback-Backend anschliessen und danach Diagnose/Reader-Adapter weiter ausbauen.
