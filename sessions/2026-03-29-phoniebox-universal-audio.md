# Session 2026-03-29

Projekt:
- Phoniebox

Erledigt:
- Playback von reinem Stub auf echtes Prozess-Backend erweitert (`mpg123` bevorzugt, `cvlc` alternativ, sonst `mock`).
- Runtime um direkte Album-Steuerung ohne RFID erweitert: laden, starten, seeken, Queue leeren, Runtime resetten.
- Bibliothek und Player-UI um Offline-Steuerung erweitert.
- Setup um universelles Audio-Profil erweitert: Ausgabemodus, bevorzugte Karte, Backend, Mixer-Control, Startlautstaerke, I2S-Profil, Pi-Zero-2W-Hinweise.
- Audio-Erkennung fuer ALSA-Karten und Playback-Devices eingebaut.
- Audio-Systemartefakte aus dem Panel generierbar gemacht: `asound.conf`, Boot-Snippet, Startlautstaerke-Skript, Zusammenfassung.
- Audio-Deployment aufs Zielsystem vorbereitet, inklusive `phoniebox-audio-init.service`.
- Installer um `alsa-utils`, `mpg123` und Audio-Init-Service erweitert.
- Tests fuer Runtime- und Audio-Systempfade aufgebaut; zuletzt 7 Tests gruen.
- Projekt in privates Repo `git@github-ccmem:Lupus1988/Phoniebox.git` auf `main` gepusht.

Entscheidungen:
- Zielbild bleibt: Endnutzer soll moeglichst nur installieren und danach alles im Web-UI konfigurieren.
- Audio-Hardware soll universell ueber Web-Profile abbildbar sein statt ueber manuelle Shell-Konfiguration.
- Fuer Pi Zero 2 W wird explizit mit externer USB- oder I2S-Soundkarte gerechnet.
- Systemnahe Audio-Dateien werden generiert und spaeter gezielt deployt, statt dass der Nutzer sie selbst schreiben muss.

Offen:
- Clean-Install auf neuem Pi testen.
- Reader-, GPIO- und LED-Deployment auf denselben Standard wie Audio bringen.
- Installer/Erststart weiter so haerten, dass der Web-UI-Flow ohne Nacharbeit funktioniert.
- UI weiter an den PDF-Entwurf annaehern.

Naechster Start:
- `ccmem start: lies ~/ccmem/START-HERE.md und arbeite mit diesem Wissensspeicher`
- Danach auf dem neuen Pi frischen Clone/Install testen und alle Stellen notieren, an denen noch Shell oder manuelle Systemarbeit noetig ist.
