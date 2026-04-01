# Session 2026-04-01

Projekt:
- Phoniebox

Erledigt:
- Standby als definierter "Aus"-Zustand der Box weiter ausgebaut.
- Power-Routinen fuer Ein- und Ausschalten ueber lange Tastendrucke konfigurierbar gemacht.
- Sleeptimer auf LED-Logik mit 1/3, 2/3, 3/3 abgestimmt und bei Ablauf auf Fade-out mit anschliessendem Standby umgestellt.
- Neue Setup-Kachel fuer Ein-/Ausschaltroutinen mit Info-Popups eingebaut und mehrfach UI-feingeschliffen.
- Neue Tastenfunktion `Wifi on/off` eingebaut.
- Neue LED-Funktion `wifi_on` eingebaut; aktive WLAN-LED pulsiert weich.
- In `Setup > WLAN/Hotspot` Checkbox `Wifi ueber Taste zuschalten` ergaenzt.
- WLAN-Policy in der Runtime umgesetzt: ohne Checkbox ist WLAN im aktiven Zustand immer an; mit Checkbox laesst es sich per Taste toggeln; im Standby wird WLAN deaktiviert.
- Beim Standby wird der RFID-Dienst gestoppt; beim Einschalten wieder gestartet.
- Installer erweitert: deaktiviert Bluetooth, blockiert Bluetooth per `rfkill`, installiert und aktiviert einen HDMI-Off-Dienst.
- Installer erweitert: versucht auf Raspberry Pi per `raspi-config` automatisch `I2C`, `SPI` und `UART` zu aktivieren.
- Anschlussplaene fuer Audio/Reader auf echte Umlaute umgestellt.
- `Settings > Player`: Feld `Startlautstaerke` jetzt wirklich deaktiviert und ausgegraut, solange die Checkbox fuer Startlautstaerke aus ist.

Verifiziert:
- Voller lokaler Testlauf erfolgreich: `python3 -m unittest discover -s /home/wolf/ccmem/projects/Phoniebox/panel/tests`
- Syntax-Checks erfolgreich fuer geaenderte Python-Dateien.
- Live-Deploy nach `/opt/phoniebox-panel` mehrfach erfolgt; `phoniebox-panel.service`, `phoniebox-leds.service` und `phoniebox-gpio-poll.service` laufen.
- `phoniebox-hdmi-off.service` ist live `enabled` und `active`.
- `bluetooth.service` ist live `disabled`; `rfkill` zeigt Bluetooth `Soft blocked: yes`.
- Setup-Seite liefert live die neuen Power-/Wifi-UI-Elemente.

Wichtige Einordnung:
- Der Software- und Installer-Stand ist jetzt deutlich naeher an einem echten Generaltest auf Pi Zero 2 W.
- Fuer `USB-Reader + USB/I2S-Audio + GPIO/LEDs + WLAN` ist der Stand lokal und live konsistent vorbereitet.
- Fuer echte Hardware-Generalfreigabe fehlen weiterhin reale End-to-End-Tests auf Pi Zero 2 W, insbesondere fuer `RC522`, `PN532 (I2C/SPI/UART)`, Power-Hold-Routinen mit realen Tastern, PWM-LEDs und Fade-out/Standby unter echter Audio-Hardware.

Wissensspeicher:
- Neuer zusaetzlicher Nextcloud-Freigabeordner vermerkt: `https://knittel.tplinkdns.com/s/oy9yTW4yCxCk5Tt`
- WebDAV-Pfad dazu: `https://knittel.tplinkdns.com/public.php/dav/files/oy9yTW4yCxCk5Tt/`

Naechster sinnvoller Test:
- Frisches Raspberry Pi OS Lite auf Pi Zero 2 W installieren.
- `install.sh` laufen lassen.
- USB-Audio, USB-Reader, Power-Taste, Wifi-Taste, Sleeptimer-LEDs und Standby-Routinen real pruefen.
- Danach Reader-Matrix mit `RC522`, `PN532_I2C`, `PN532_SPI`, `PN532_UART` auf echter Hardware einzeln gegenpruefen.
