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
- Fuer C:\EQWeb eine Desktop-Verknuepfung C:\Users\Wolf\Desktop\EQ Panel.lnk angelegt, die den Start als Administrator ausloest.
- Nach einer UI-Regression den funktionierenden 3-Lab-Stand fuer EQWeb wiederhergestellt und fehlende Profil-/Visual-EQ-Funktionen zurueckgebracht.
- Den Laufzeitfehler um Get-UsableIPv4Addresses behoben, sodass das Panel wieder korrekt rendert.
- Smartphone- und Tablet-Ansichten in EQWeb aufgeraeumt: erklaerende Ueberschrift-/Hilfetexte entfernt, Bedienflaechen kompakter gelassen.
- Ein sauberes Backup des funktionsfaehigen EQWeb-Stands erstellt: C:\EQWeb\backups\EQWeb-backup-20260326-214242.zip.
- Root- und Server-Zertifikate fuer einen HTTPS/PWA-Versuch vorbereitet (C:\EQWeb\certs\EQWeb-Local-Root-CA.cer), den HTTPS-Umbau aber wegen bestehender HTTP.sys-/URL-Registrierungskonflikte nicht produktiv uebernommen.
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
- Falls EQWeb spaeter als echte PWA installierbar sein soll, HTTPS nicht mehr direkt ueber den eingebauten HttpListener erzwingen, sondern bestehende HTTP.sys-Konflikte gezielt aufraeumen oder einen separaten Reverse-Proxy/HTTPS-Frontend-Weg waehlen.
- Optional die mobile EQWeb-Oberflaeche weiter visuell verdichten, falls auf Smartphone/Tablet noch mehr Platz fuer Regler gewonnen werden soll.
Naechster Start:
- ccmem start: lies C:\ccmem\START-HERE.md und arbeite mit diesem Wissensspeicher
- Danach bei EQWeb entweder nur weitere Mobile-UI-Feinarbeit machen oder den HTTPS/PWA-Pfad ueber Reverse Proxy bzw. bereinigte HTTP.sys-Registrierungen sauber neu ansetzen.
