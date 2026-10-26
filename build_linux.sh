#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$APP_DIR/ALMOXARIFADO_OFFLINE"
cd "$APP_DIR"

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "Install dpkg-dev on the Linux build computer before building." >&2
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "Python 3.10 or newer is required on the build computer." >&2
    exit 1
fi

PACKAGE_ARCH="$(dpkg --print-architecture)"
BUILD_ENV="$APP_DIR/.build-linux"
if [[ ! -x "$BUILD_ENV/bin/python" ]]; then
    python3 -m venv "$BUILD_ENV"
fi
"$BUILD_ENV/bin/python" -m pip install --upgrade pip
"$BUILD_ENV/bin/python" -m pip install -r requirements-build.txt

"$BUILD_ENV/bin/python" -m PyInstaller \
    --clean --noconfirm --onedir --name ALMOXARIFADO \
    --distpath "$APP_DIR/dist/linux-bin" \
    --workpath "$APP_DIR/build/linux-work" \
    --specpath "$APP_DIR/build/linux-spec" \
    --paths "$SOURCE_DIR" \
    --collect-all reportlab \
    --hidden-import PySide6.QtPdf \
    --hidden-import PySide6.QtPdfWidgets \
    --hidden-import PySide6.QtPrintSupport \
    --add-data "$SOURCE_DIR/static:static" \
    --add-data "$SOURCE_DIR/config.json:." \
    "$SOURCE_DIR/qt_app.py"

PACKAGE_ROOT="$(mktemp -d)"
trap 'rm -rf "$PACKAGE_ROOT"' EXIT
install -d "$PACKAGE_ROOT/opt/almoxarifado"
cp -a "$APP_DIR/dist/linux-bin/ALMOXARIFADO/." "$PACKAGE_ROOT/opt/almoxarifado/"
install -Dm755 /dev/stdin "$PACKAGE_ROOT/usr/bin/almoxarifado" <<'EOF'
#!/bin/sh
exec /opt/almoxarifado/ALMOXARIFADO "$@"
EOF
install -Dm644 "$SOURCE_DIR/static/logo-metalus.png" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/256x256/apps/almoxarifado.png"
install -Dm644 /dev/stdin \
    "$PACKAGE_ROOT/usr/share/applications/almoxarifado.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Almoxarifado
Comment=Gerar etiquetas de almoxarifado
Exec=almoxarifado
Icon=almoxarifado
Terminal=false
Categories=Office;
EOF
install -Dm644 /dev/stdin "$PACKAGE_ROOT/DEBIAN/control" <<EOF
Package: almoxarifado-metalus
Version: 1.0.0
Section: office
Priority: optional
Architecture: $PACKAGE_ARCH
Depends: libc6, libstdc++6, libcups2, libdbus-1-3, libegl1, libfontconfig1, libfreetype6, libgl1, libglib2.0-0, libsm6, libx11-6, libx11-xcb1, libxcb-cursor0, libxcb-glx0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render0, libxcb-render-util0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-util1, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, libxext6, libxi6, libxkbcommon0, libxkbcommon-x11-0, libxrender1, xdg-utils
Maintainer: Metalus
Description: Aplicativo desktop para gerar etiquetas de almoxarifado
EOF

mkdir -p "$APP_DIR/dist/linux"
OUTPUT_DEB="$APP_DIR/dist/linux/almoxarifado-metalus_1.0.0_${PACKAGE_ARCH}.deb"
dpkg-deb --build --root-owner-group "$PACKAGE_ROOT" "$OUTPUT_DEB"
echo "Package created at $OUTPUT_DEB"