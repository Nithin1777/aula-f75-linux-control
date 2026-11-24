#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"

chmod +x "${REPO_DIR}/aula-f75" "${REPO_DIR}/aula-f75-gui"
mkdir -p "${BIN_DIR}" "${APP_DIR}"

ln -sf "${REPO_DIR}/aula-f75" "${BIN_DIR}/aula-f75"
ln -sf "${REPO_DIR}/aula-f75-gui" "${BIN_DIR}/aula-f75-gui"

cat > "${APP_DIR}/aula-f75-control.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AULA F75 & Mouse Control
Comment=Configure AULA F75 keyboard and Ant Esports GM320 mouse RGB, DPI, and keymaps
Exec=${REPO_DIR}/aula-f75-gui
Icon=input-keyboard
Terminal=false
Categories=Utility;Settings;HardwareSettings;
Keywords=aula;f75;keyboard;mouse;antesports;gm320;rgb;dpi;lighting;keymap;
StartupNotify=true
EOF

echo "Installed CLI and GUI launchers to ${BIN_DIR} and ${APP_DIR}."
echo ""
echo "If you get permission denied accessing /dev/hidraw*, install the udev rules and replug:"
echo "  sudo cp \"${REPO_DIR}/99-aula-f75-and-gm320.rules\" /etc/udev/rules.d/"
echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
