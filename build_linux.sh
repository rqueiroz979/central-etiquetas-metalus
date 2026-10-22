#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
mkdir -p "$APP_DIR/build/package-data"
"$BUILD_ENV/bin/python" -c "from pathlib import Path; import shutil; files=list(Path('.').glob('*.ods')); assert len(files) == 1, files; shutil.copy2(files[0], Path('build/package-data/template.ods'))"

"$BUILD_ENV/bin/python" -m PyInstaller \
    --clean --noconfirm --onefile --name central-etiquetas-metalus \
    --distpath "$APP_DIR/dist/linux-bin" \
    --workpath "$APP_DIR/build/linux-work" \
    --specpath "$APP_DIR/build/linux-spec" \
    --collect-all reportlab --collect-all ezodf --collect-all lxml \
    --add-data "$APP_DIR/templates:templates" \
    --add-data "$APP_DIR/static:static" \
    --add-data "$APP_DIR/config.json:." \
    --add-data "$APP_DIR/build/package-data/template.ods:." \
    "$APP_DIR/app.py"

PACKAGE_ROOT="$(mktemp -d)"
trap 'rm -rf "$PACKAGE_ROOT"' EXIT
install -Dm755 "$APP_DIR/dist/linux-bin/central-etiquetas-metalus" \
    "$PACKAGE_ROOT/opt/central-etiquetas-metalus/central-etiquetas-metalus"
install -Dm755 /dev/stdin "$PACKAGE_ROOT/usr/bin/central-etiquetas-metalus" <<'EOF'
#!/bin/sh
exec /opt/central-etiquetas-metalus/central-etiquetas-metalus "$@"
EOF
install -Dm644 "$APP_DIR/static/logo-metalus.png" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/256x256/apps/central-etiquetas-metalus.png"
install -Dm644 /dev/stdin \
    "$PACKAGE_ROOT/usr/share/applications/central-etiquetas-metalus.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Central de Etiquetas Metalus
Comment=Gerar e administrar etiquetas
Exec=central-etiquetas-metalus
Icon=central-etiquetas-metalus
Terminal=true
Categories=Office;
EOF
install -Dm644 /dev/stdin "$PACKAGE_ROOT/DEBIAN/control" <<EOF
Package: central-etiquetas-metalus
Version: 1.0.0
Section: office
Priority: optional
Architecture: $PACKAGE_ARCH
Depends: libc6, libstdc++6, xdg-utils
Maintainer: Metalus
Description: Aplicativo local para gerar e administrar etiquetas
EOF

mkdir -p "$APP_DIR/dist/linux"
OUTPUT_DEB="$APP_DIR/dist/linux/central-etiquetas-metalus_1.0.0_${PACKAGE_ARCH}.deb"
dpkg-deb --build --root-owner-group "$PACKAGE_ROOT" "$OUTPUT_DEB"
echo "Package created at $OUTPUT_DEB"