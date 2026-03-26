# Globale Regeln

Hier stehen Regeln, die in allen Projekten gelten sollen.

Grundregeln:
- Bevorzugte Sprache: Deutsch
- Serverzugriffe nur mit Rueckversicherung bei riskanten Aenderungen
- Backups vor groesseren Live-Eingriffen
- Doku und Handoffs immer aktualisieren
- Der Wissensspeicher liegt als Git-Repo unter dem Standardpfad `~/ccmem` oder unter Windows `C:\ccmem`

Arbeitskonventionen:
- `ccmem sync` bedeutet: lokalen Standardpfad fuer `ccmem` anlegen und das Repo klonen oder per `git pull --ff-only` aktualisieren.
- `ccmem start` bedeutet: lokalen Wissensspeicher lesen und als Kontext verwenden.
- `handoff` bedeutet: den aktuellen Stand fuer die naechste Sitzung in `sessions/` festhalten.
- `arbeit beendet` bedeutet: Handoff aktualisieren, relevante Aenderungen in `global/`, `projects/` oder `sessions/` einpflegen, alles committen und nach `origin/main` pushen.
- `arbeit beendet cleanup` bedeutet: wie `arbeit beendet`, danach die lokale `ccmem`-Arbeitskopie nur dann loeschen, wenn kein ungesicherter lokaler Stand mehr vorhanden ist.

Git-Regeln:
- Vor einer Arbeitssitzung nach Moeglichkeit `git pull` fuer `ccmem` ausfuehren.
- Am Sitzungsende nur sinnvolle, lesbare Commits erzeugen.
- Keine Secrets, Tokens oder Passwoerter im Wissensspeicher ablegen.
- Lokale projektspezifische Pfade im Wissensspeicher vermeiden oder klar als geraetespezifisch markieren.

Aktueller Stand:
- Verwende `ccmem start`, um in neuen Sessions auf diesen Wissensspeicher zu verweisen.
