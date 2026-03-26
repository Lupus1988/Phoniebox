# Codex Cloud Memory

Nutze diesen Ordner als gemeinsamen Wissensspeicher fuer neue Codex-Sessions.

Standardpfad:
- Linux/macOS: `~/ccmem`
- Windows: `C:\ccmem`

Bootstrap vor dem Start:
- Linux/macOS:
  `mkdir -p ~/ccmem && git -C ~/ccmem rev-parse --is-inside-work-tree >/dev/null 2>&1 && git -C ~/ccmem pull --ff-only || git clone https://github.com/Lupus1988/ccmem.git ~/ccmem`
- Windows PowerShell:
  `$p='C:\ccmem'; if (Test-Path "$p\\.git") { git -C $p pull --ff-only } else { if (!(Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }; git clone https://github.com/Lupus1988/ccmem.git $p }`

Portabler Startbefehl:
- Linux/macOS: `ccmem start: lies ~/ccmem/START-HERE.md und arbeite mit diesem Wissensspeicher`
- Windows: `ccmem start: lies C:\ccmem\START-HERE.md und arbeite mit diesem Wissensspeicher`

Bedeutung von `ccmem start`:
- Den lokalen Wissensspeicher unter dem Standardpfad verwenden.
- Diese Datei lesen.
- [`global/RULES.md`](/home/wolf/codex-cloud-bootstrap/global/RULES.md) lesen.
- Falls ein Projekt genannt wird, die passende Datei unter [`projects/`](/home/wolf/codex-cloud-bootstrap/projects) lesen.
- Den neuesten Eintrag unter [`sessions/`](/home/wolf/codex-cloud-bootstrap/sessions) beachten, falls vorhanden.

Reihenfolge fuer neue Sessions:
1. Diese Datei lesen.
2. [`global/RULES.md`](/home/wolf/codex-cloud-bootstrap/global/RULES.md) lesen.
3. Falls ein Projekt genannt wird, die passende Datei unter [`projects/`](/home/wolf/codex-cloud-bootstrap/projects) lesen.
4. Den neuesten Eintrag unter [`sessions/`](/home/wolf/codex-cloud-bootstrap/sessions) beachten, falls vorhanden.

Ordner:
- `global/`: Regeln und dauerhafte Arbeitsweisen.
- `projects/`: Projektspezifisches Wissen.
- `sessions/`: Handoffs und Status je Sitzung.
- `inbox/screenshots/`: Screenshots, die Codex auswerten soll.
- `templates/`: Vorlagen fuer neue Projekt- und Session-Dateien.

Pflegehinweis:
- Am Ende einer Sitzung kann Codex eine neue Session-Datei anlegen.
- Wichtige neue Regeln gehoeren nach `global/RULES.md`.
- Projektspezifische Entscheidungen gehoeren in die jeweilige Projektdatei.

Arbeitsbefehle:
- `ccmem sync`: Falls `ccmem` lokal noch nicht existiert, Repo in den Standardpfad klonen. Falls es existiert, per `git pull --ff-only` aktualisieren.
- `ccmem start`: Wissensspeicher laden.
- `handoff`: Eine Session-Zusammenfassung fuer `sessions/` vorbereiten oder aktualisieren.
- `arbeit beendet`: Handoff aktualisieren, relevante Wissensdateien pruefen, committen und nach `origin/main` pushen.
- `arbeit beendet cleanup`: Wie `arbeit beendet`, danach zusaetzlich die lokale `~/ccmem`-Arbeitskopie loeschen, wenn dies ohne Risiko moeglich und ausdruecklich gewuenscht ist.
