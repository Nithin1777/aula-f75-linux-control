# AULA F75 & Mouse Control for Linux

Native Linux GTK4/Libadwaita GUI and CLI to configure:
1. **AULA F75** mechanical keyboard (`258a:010c`) over `/dev/hidraw*`
2. **Ant Esports GM320 / Instant A825** gaming mouse (`30fa:1440` / `30fa:1040`) over `/dev/hidraw*`

No Wine, Windows VM, or external `pip` packages required.

## Install

```bash
git clone https://github.com/Nithin1777/aula-f75-linux-control.git
cd aula-f75-linux-control
./install.sh
```

### System Dependencies (for the GUI)
The CLI uses Python 3's standard library only. For the GTK4/Libadwaita GUI, ensure PyGObject, GTK4, and Libadwaita are installed on `/usr/bin/python3`:
- **Fedora / Bazzite:** already preinstalled (`python3-gobject gtk4 libadwaita`)
- **Ubuntu / Debian:** `sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`
- **Arch Linux:** `sudo pacman -S python-gobject gtk4 libadwaita`

### Device Permissions (`udev`)
If you get permission denied on `/dev/hidraw*`, install the included udev rules and replug your devices:
```bash
sudo cp 99-aula-f75-and-gm320.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Keyboard Features (`258a:010c`)
- **Lighting Effects:** Built-in hardware effects (`0..17`, `32`), including reactive spreading effects (`ripple`, `ripple-row`, `reactive`), brightness (`0..9`), speed (`0..4`), Rainbow vs. single RGB color, and 7 customizable palette slots.
- **Per-Key RGB:** Interactive visual keyboard painter with drag-painting, presets (`fps`, `coding`, `cyberpunk`, `rainbow-rows`, `clear`), and custom RGB activation.
- **Keymap Remapping:** Inspect and remap **Base** and **Fn** layers with safety guards preserving the `Fn` key.
- **Backup & Config Watch:** Full JSON export/restore, automatic initial backup (`~/.local/share/aula-f75-control/initial_backup.json`), and a live `0x84` hex inspector.

## Mouse Features (`30fa:1440` — Ant Esports GM320 / Instant A825)
- **Lighting Modes:** All 14 hardware modes (`0..13`), speed (`0..5`), live RAM preview (`0x13`/`0x14`), and persistent flash save.
- **DPI Stages (1–6):** Toggle active stage, enable/disable stages, set DPI (`200..12800`), and customize each stage's RGB strip color.
- **Button Remapping:** Reassign buttons with Left-Click protection so the mouse cannot be left unclickable.
- **Safety Guarantees:** Flash header `0x00..0x07` (USB VID/PID) is strictly read-only and hard-blocked from writes; every 8-byte block write is verified by readback; an initial backup is saved automatically to `~/.local/share/aula-f75-control/mouse_initial_backup.json`.

## Usage

### Launch GUI
```bash
aula-f75-gui
```
Or launch **AULA F75 & Mouse Control** from your application menu.

### Keyboard CLI Examples
```bash
aula-f75 status
aula-f75 effects
aula-f75 color "#00ffff" --brightness 6
aula-f75 effect ripple --brightness 8 --speed 3 --color rainbow
aula-f75 perkey --preset fps
aula-f75 keymap show --layer base
aula-f75 backup ~/aula-f75-backup.json
```

### Mouse CLI Examples
```bash
aula-f75 mouse status
aula-f75 mouse modes
aula-f75 mouse color "#00ffff"
aula-f75 mouse led flowing-water --speed 2
aula-f75 mouse led light-on --color "#ff0066" --live --brightness 4
aula-f75 mouse dpi --active 2 --set 2=1600 --color 2="#00ffff"
aula-f75 mouse button top1 led-loop
aula-f75 mouse backup ~/mouse-backup.json
aula-f75 mouse restore ~/mouse-backup.json
```
