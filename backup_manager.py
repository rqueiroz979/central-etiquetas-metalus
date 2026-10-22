import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath


SYSTEM_NAME = "Central de Etiquetas Metalus"
BACKUP_TYPE = "backup_geral"
COMPATIBLE_BACKUP_TYPES = {"backup_geral", "backup"}
MANIFEST_VERSION = 1
MANIFEST_ENTRY = "manifest.json"
CONFIG_ENTRY = "config.json"
DATA_DIR_ENTRY = "data/"
OUTPUT_DIR_ENTRY = "output/"
ALLOWED_TOP_LEVEL_FILES = {CONFIG_ENTRY, MANIFEST_ENTRY}
ALLOWED_DIR_PREFIXES = (DATA_DIR_ENTRY, OUTPUT_DIR_ENTRY)


def ensure_backup_dir(backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _safe_filename_prefix(reason: str) -> str:
    if reason == "pre_restore":
        return "pre_restore_backup_geral"
    return "backup_geral_central_etiquetas"


def _timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path_for_config(target_path: Path, app_root: Path) -> str:
    if _is_relative_to(target_path, app_root):
        return target_path.relative_to(app_root).as_posix()
    return str(target_path)


def _portable_target_path(raw_value, *, source_root: Path | None, app_root: Path, fallback: Path) -> Path:
    configured = Path(str(raw_value or "").strip()) if str(raw_value or "").strip() else fallback
    if configured.is_absolute():
        if source_root and _is_relative_to(configured, source_root):
            return app_root / configured.relative_to(source_root)
        return fallback
    return app_root / configured


def _current_target_path(raw_value, *, app_root: Path, fallback: Path) -> Path:
    configured = Path(str(raw_value or "").strip()) if str(raw_value or "").strip() else fallback
    if configured.is_absolute():
        return configured
    return app_root / configured


def _normalize_restore_config(restored_config: dict, manifest: dict, *, app_root: Path, default_db_path: Path, default_output_dir: Path):
    source_root_text = str(manifest.get("source_app_root") or "").strip()
    source_root = Path(source_root_text) if source_root_text else None
    normalized = dict(restored_config or {})

    target_db_path = _portable_target_path(
        normalized.get("db_path"),
        source_root=source_root,
        app_root=app_root,
        fallback=default_db_path,
    )
    target_output_dir = _portable_target_path(
        normalized.get("output_dir"),
        source_root=source_root,
        app_root=app_root,
        fallback=default_output_dir,
    )

    normalized["db_path"] = _path_for_config(target_db_path, app_root)
    normalized["output_dir"] = _path_for_config(target_output_dir, app_root)

    return normalized, target_db_path, target_output_dir


def _directory_has_files(source_dir: Path) -> bool:
    return source_dir.exists() and any(item.is_file() for item in source_dir.rglob("*"))


def _write_directory_placeholder(archive: zipfile.ZipFile, arc_dir: str):
    dir_name = arc_dir if arc_dir.endswith("/") else f"{arc_dir}/"
    archive.writestr(zipfile.ZipInfo(dir_name), b"")


def _add_directory_to_zip(archive: zipfile.ZipFile, source_dir: Path, arc_dir: str):
    _write_directory_placeholder(archive, arc_dir)
    if not source_dir.exists():
        return

    for item in sorted(source_dir.rglob("*")):
        relative_name = item.relative_to(source_dir).as_posix()
        arc_name = f"{arc_dir.rstrip('/')}/{relative_name}"
        if item.is_dir():
            _write_directory_placeholder(archive, arc_name)
        else:
            archive.write(item, arcname=arc_name)


def _build_manifest(*, app_root: Path, data_dir: Path, output_dir: Path, db_path: Path, config_exists: bool):
    empty_items = []
    if not _directory_has_files(data_dir):
        empty_items.append("data")
    if not _directory_has_files(output_dir):
        empty_items.append("output")

    manifest = {
        "sistema": SYSTEM_NAME,
        "tipo": BACKUP_TYPE,
        "versao_backup": MANIFEST_VERSION,
        "data_backup": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "descricao": "Backup geral do sistema, incluindo banco SQLite, PDFs gerados e configurações.",
        "itens": ["data", "output", "config.json"],
        "diretorios_vazios": empty_items,
        "source_app_root": str(app_root),
        "source_data_dir": str(data_dir),
        "source_output_dir": str(output_dir),
        "source_db_path": str(db_path),
    }
    if not config_exists:
        manifest["itens_ausentes"] = ["config.json"]
    return manifest


def create_backup(*, app_root: Path, backup_dir: Path, config_path: Path, data_dir: Path, output_dir: Path, db_path: Path, reason: str = "manual") -> Path:
    ensure_backup_dir(backup_dir)
    backup_name = f"{_safe_filename_prefix(reason)}_{_timestamp_for_filename()}.zip"
    backup_path = backup_dir / backup_name

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _add_directory_to_zip(archive, data_dir, DATA_DIR_ENTRY)
        _add_directory_to_zip(archive, output_dir, OUTPUT_DIR_ENTRY)
        if config_path.exists():
            archive.write(config_path, arcname=CONFIG_ENTRY)
        manifest = _build_manifest(
            app_root=app_root,
            data_dir=data_dir,
            output_dir=output_dir,
            db_path=db_path,
            config_exists=config_path.exists(),
        )
        archive.writestr(MANIFEST_ENTRY, json.dumps(manifest, ensure_ascii=False, indent=2))

    return backup_path


def list_backups(backup_dir: Path):
    ensure_backup_dir(backup_dir)
    backups = []
    for file_path in sorted(backup_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = file_path.stat()
        backups.append(
            {
                "name": file_path.name,
                "size_kb": max(1, int(round(stat.st_size / 1024))),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M"),
            }
        )
    return backups


def get_backup_file_path(backup_dir: Path, filename: str) -> Path | None:
    safe_name = Path(str(filename or "")).name
    if not safe_name or safe_name != filename or not safe_name.lower().endswith(".zip"):
        return None

    backup_path = ensure_backup_dir(backup_dir) / safe_name
    return backup_path if backup_path.exists() and backup_path.is_file() else None


def _normalize_zip_entry(name: str) -> str | None:
    normalized = str(name or "").replace("\\", "/").strip()
    if not normalized:
        return None

    path = PurePosixPath(normalized)
    first_part = path.parts[0] if path.parts else ""
    if path.is_absolute() or ".." in path.parts or ":" in first_part:
        return None

    if normalized.endswith("/"):
        return normalized
    return path.as_posix()


def validate_backup_zip(*, zip_bytes: bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            entries = {}
            for raw_name in archive.namelist():
                normalized_name = _normalize_zip_entry(raw_name)
                if normalized_name is None:
                    return False, "O backup possui caminhos inválidos.", None
                if normalized_name not in ALLOWED_TOP_LEVEL_FILES and not normalized_name.startswith(ALLOWED_DIR_PREFIXES):
                    return False, "O backup possui arquivos fora da estrutura permitida.", None
                entries[normalized_name] = archive.read(raw_name) if not normalized_name.endswith("/") else b""

            if MANIFEST_ENTRY not in entries:
                return False, "O backup selecionado não possui `manifest.json` válido.", None

            try:
                manifest = json.loads(entries[MANIFEST_ENTRY].decode("utf-8"))
            except Exception:
                return False, "O `manifest.json` do backup está inválido.", None

            if str(manifest.get("sistema") or "").strip() != SYSTEM_NAME:
                return False, "Este arquivo não pertence à Central de Etiquetas Metalus.", None

            if str(manifest.get("tipo") or "").strip() not in COMPATIBLE_BACKUP_TYPES:
                return False, "O tipo de backup não é compatível com esta restauração.", None

            manifest_items = manifest.get("itens") or []
            if not isinstance(manifest_items, list) or "data" not in manifest_items or "output" not in manifest_items:
                return False, "O `manifest.json` do backup não descreve um backup geral válido.", None

            return True, "", {"manifest": manifest, "entries": entries}
    except zipfile.BadZipFile:
        return False, "O arquivo enviado não é um `.zip` válido.", None
    except Exception:
        return False, "Não foi possível validar o backup informado.", None


def _write_stage_files(stage_root: Path, entries: dict):
    data_stage = stage_root / "data"
    output_stage = stage_root / "output"
    data_stage.mkdir(parents=True, exist_ok=True)
    output_stage.mkdir(parents=True, exist_ok=True)

    for name, content in entries.items():
        if name in ALLOWED_TOP_LEVEL_FILES:
            continue
        if name.endswith("/"):
            (stage_root / name.rstrip("/")).mkdir(parents=True, exist_ok=True)
            continue
        target_path = stage_root / Path(name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)

    config_bytes = entries.get(CONFIG_ENTRY)
    config_stage = None
    if config_bytes is not None:
        config_stage = stage_root / CONFIG_ENTRY
        config_stage.write_bytes(config_bytes)

    return config_stage


def restore_backup(*, zip_bytes: bytes, app_root: Path, backup_dir: Path, config_path: Path, current_config: dict, default_db_path: Path, default_output_dir: Path):
    is_valid, message, payload = validate_backup_zip(zip_bytes=zip_bytes)
    if not is_valid:
        return False, message

    manifest = payload["manifest"]
    entries = payload["entries"]

    restored_config = current_config
    config_bytes = entries.get(CONFIG_ENTRY)
    if config_bytes is not None:
        try:
            restored_config = json.loads(config_bytes.decode("utf-8"))
        except Exception:
            return False, "O `config.json` dentro do backup está inválido."

    normalized_config, target_db_path, target_output_dir = _normalize_restore_config(
        restored_config,
        manifest,
        app_root=app_root,
        default_db_path=default_db_path,
        default_output_dir=default_output_dir,
    )
    target_data_dir = target_db_path.parent
    current_db_path = _current_target_path(
        current_config.get("db_path") if current_config else None,
        app_root=app_root,
        fallback=default_db_path,
    )
    current_output_dir = _current_target_path(
        current_config.get("output_dir") if current_config else None,
        app_root=app_root,
        fallback=default_output_dir,
    )

    with tempfile.TemporaryDirectory(prefix="restore_backup_", dir=str(ensure_backup_dir(backup_dir))) as temp_dir:
        stage_root = Path(temp_dir) / "stage"
        stage_root.mkdir(parents=True, exist_ok=True)

        try:
            _write_stage_files(stage_root, entries)
            config_stage = stage_root / CONFIG_ENTRY if config_bytes is not None else None
            if config_stage is not None:
                config_stage.write_text(json.dumps(normalized_config, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return False, "Não foi possível preparar a restauração do backup."

        try:
            pre_restore_backup = create_backup(
                app_root=app_root,
                backup_dir=backup_dir,
                config_path=config_path,
                data_dir=current_db_path.parent,
                output_dir=current_output_dir,
                db_path=current_db_path,
                reason="pre_restore",
            )
        except Exception:
            return False, "Não foi possível criar o backup automático antes da restauração."

        moved_paths = []
        rollback_targets = []

        def move_existing(target: Path, temp_name: str):
            if not target.exists():
                return None
            backup_target = Path(temp_dir) / temp_name
            target.replace(backup_target)
            moved_paths.append((target, backup_target))
            return backup_target

        try:
            move_existing(target_data_dir, "old_data")
            move_existing(target_output_dir, "old_output")
            if config_stage is not None:
                move_existing(config_path, "old_config.json")

            target_data_dir.mkdir(parents=True, exist_ok=True)
            for item in (stage_root / "data").iterdir():
                destination = target_data_dir / item.name
                item.replace(destination)
            rollback_targets.append(target_data_dir)

            target_output_dir.mkdir(parents=True, exist_ok=True)
            for item in (stage_root / "output").iterdir():
                destination = target_output_dir / item.name
                item.replace(destination)
            rollback_targets.append(target_output_dir)

            if config_stage is not None:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_stage.replace(config_path)
                rollback_targets.append(config_path)

        except Exception:
            for created in reversed(rollback_targets):
                if created.is_dir():
                    shutil.rmtree(created, ignore_errors=True)
                elif created.exists():
                    created.unlink(missing_ok=True)

            for original_path, moved_path in reversed(moved_paths):
                if moved_path.exists():
                    moved_path.replace(original_path)

            return False, "Falha ao restaurar o backup selecionado."

        for _, moved_path in moved_paths:
            if moved_path.is_dir():
                shutil.rmtree(moved_path, ignore_errors=True)
            elif moved_path.exists():
                moved_path.unlink(missing_ok=True)

    return True, (
        "Backup restaurado com sucesso. Reinicie a Central de Etiquetas para aplicar todas as configurações. "
        f"Backup automático criado: {pre_restore_backup.name}"
    )
