# Session 2026-03-26

Projekt:
- ccmem

Erledigt:
- Wissensspeicher von pfadgebundenem lokalen Ordner auf portables Git-Repo-Konzept umgestellt.
- Kurzbefehle `ccmem start`, `ccmem sync`, `handoff`, `arbeit beendet` und `arbeit beendet cleanup` in den Regeln festgelegt.
- Startdokument und globale Regeln fuer Linux/macOS und Windows mit Standardpfaden `~/ccmem` und `C:\ccmem` erweitert.
- Privates GitHub-Repo `Lupus1988/ccmem` angebunden und Initialstand dorthin gepusht.
- Self-Hosted-Gitea-Variante inklusive Container, Image und lokaler Daten wieder entfernt.
- Auf dem Homeserver einen eigenen SSH-Key fuer GitHub erzeugt und das lokale `ccmem`-Repo auf SSH-Remote umgestellt.

Entscheidungen:
- Der gemeinsame Wissensspeicher liegt kuenftig in einem privaten GitHub-Repo statt auf einem selbst gehosteten Gitea-Server.
- Pro Geraet soll ein eigener SSH-Key fuer GitHub verwendet werden, statt Tokens dauerhaft zu nutzen.
- Fuer neue Geraete wird `ccmem` vor Arbeitsbeginn lokal in den Standardpfad geklont oder aktualisiert.

Offen:
- SSH-Verbindung des Homeservers zu GitHub nach Eintragen des Public Keys testen.
- Fuer weitere Geraete wie Windows-PC oder Raspberry Pi jeweils eigenen SSH-Key erzeugen und in GitHub hinterlegen.
- Die heute angepassten Regeln und der Handoff muessen noch nach GitHub gepusht werden.

Naechster Start:
- `ccmem start: lies ~/ccmem/START-HERE.md und arbeite mit diesem Wissensspeicher`
- Danach SSH-Zugriff zu GitHub testen und bei Erfolg die Abschlussaenderungen pushen.
