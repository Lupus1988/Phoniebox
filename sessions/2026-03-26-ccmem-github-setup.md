# Session 2026-03-26

Projekt:
- ccmem
- EQWeb

Erledigt:
- Wissensspeicher von pfadgebundenem lokalen Ordner auf portables Git-Repo-Konzept umgestellt.
- Kurzbefehle `ccmem start`, `ccmem sync`, `handoff`, `arbeit beendet` und `arbeit beendet cleanup` in den Regeln festgelegt.
- Startdokument und globale Regeln fuer Linux/macOS und Windows mit Standardpfaden `~/ccmem` und `C:\ccmem` erweitert.
- Privates GitHub-Repo `Lupus1988/ccmem` angebunden und Initialstand dorthin gepusht.
- Self-Hosted-Gitea-Variante inklusive Container, Image und lokaler Daten wieder entfernt.
- Auf dem Homeserver einen eigenen SSH-Key fuer GitHub erzeugt und das lokale `ccmem`-Repo auf SSH-Remote umgestellt.
- Auf dem Windows-PC einen eigenen GitHub-SSH-Key angelegt, bei GitHub hinterlegt und den Zugriff erfolgreich getestet.
- Das lokale `C:\ccmem`-Repo auf diesem Windows-PC so konfiguriert, dass nur dieses Repo den geraetespezifischen Key verwendet.
- Das lokale Webpanel unter `C:\EQWeb` fuer die Equalizer-APO-Steuerung im DJ-Einsatz geprueft und bewertet.
- `C:\EQWeb\eq-web.ps1` so erweitert, dass Manifest, Service Worker und App-Icons korrekt referenziert und statische Dateien aus `wwwroot` ausgeliefert werden.
- Autosave- und Realtime-Verhalten im Panel gestrafft: Rendern per `requestAnimationFrame`, Speichern nur bei echten Aenderungen, sofortiges Speichern nach Drag-Ende.
- PWA-Dateien unter `C:\EQWeb\wwwroot` ueberarbeitet und PNG-App-Icons erzeugt.
- Lokalen Funktionstest gegen `http://192.168.0.248:8080` durchgefuehrt: Startseite, Manifest, Service Worker, API-State und Icons liefern erfolgreich aus.

Entscheidungen:
- Der gemeinsame Wissensspeicher liegt kuenftig in einem privaten GitHub-Repo statt auf einem selbst gehosteten Gitea-Server.
- Pro Geraet soll ein eigener SSH-Key fuer GitHub verwendet werden, statt Tokens dauerhaft zu nutzen.
- Fuer neue Geraete wird `ccmem` vor Arbeitsbeginn lokal in den Standardpfad geklont oder aktualisiert.
- Geraetespezifische SSH-Keys sollen nach Moeglichkeit repo-lokal gebunden werden, statt globale `github.com`-Regeln fuer alle Repos zu setzen.
- Fuer EQWeb soll das Bediengefuehl live bleiben; Optimierungen dürfen die direkte Rueckmeldung nicht verschlechtern.
- PWA-Unterstuetzung fuer EQWeb soll erhalten bleiben, auch wenn der finale Install-Prompt vom Browser-Sicherheitskontext abhaengt.

Offen:
- SSH-Verbindung des Homeservers zu GitHub nach Eintragen des Public Keys testen.
- Fuer weitere Geraete wie Raspberry Pi jeweils eigenen SSH-Key erzeugen und in GitHub hinterlegen.
- Echten Browser-Test auf Smartphone/Tablet fuer EQWeb durchfuehren: Installierbarkeit als PWA und Verhalten im mobilen Chrome pruefen.
- Falls Chrome die Installation trotz korrekter Assets nicht anbietet, den Secure-Context-/HTTP-vs-HTTPS-Punkt fuer EQWeb entscheiden.

Naechster Start:
- `ccmem start: lies C:\ccmem\START-HERE.md und arbeite mit diesem Wissensspeicher`
- Danach bei EQWeb den echten Mobiltest mit Smartphone/Tablet machen und je nach Ergebnis entweder PWA-Installpfad finalisieren oder den Bindungs-/HTTPS-Ansatz nachziehen.
