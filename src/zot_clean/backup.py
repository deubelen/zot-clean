"""Backup of the Zotero folder before a bulk operation (D15, D40 to D42).

Zotero must be closed, which is checked through the process list.
Clone of the whole folder when the file system allows it (APFS, Btrfs,
XFS), otherwise copy of the database alone. Each backup is a subfolder of
`cfg.backups` with a descriptor file `sauvegarde.json`. Only the most
recent ones are kept. The backups folder is excluded from backup software
(D159), which would copy every clone in full.
"""

import json
import os
import platform
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from zot_clean import __version__, reader
from zot_clean.config import Config
from zot_clean.api import Refusal
from zot_clean.lang import L

MANIFEST = 'sauvegarde.json'
# Convention recognised by Borg (`exclude_caches`), restic and tar (`--exclude-caches`), https://bford.info/cachedir/
CACHEDIR = 'CACHEDIR.TAG'
SIGNATURE = 'Signature: 8a477f597d28d172789f06886806bc55'


def zotero_running() -> bool:
    """True if a Zotero process is running. Raises `Refusal` if this cannot be known."""
    try:
        if os.name == 'nt':
            r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq zotero.exe', '/NH'], capture_output=True, text=True,
                               timeout=30)
            if r.returncode != 0:
                raise OSError(r.stderr)
            return 'zotero.exe' in r.stdout.lower()
        # Depending on the installation (official archive, Flatpak), the process is called zotero or zotero-bin (D193).
        r = subprocess.run(['pgrep', '-i', '-x', 'zotero|zotero-bin'], capture_output=True, text=True, timeout=30)
        if r.returncode not in (0, 1):
            raise OSError(r.stderr)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        raise Refusal(L(en=f"Cannot check that Zotero is closed ({e}). Backup abandoned.",
                        fr=f"Impossible de vérifier que Zotero est fermé ({e}). Sauvegarde abandonnée.")) from None


@dataclass
class BackupInfo:
    folder: Path
    date: datetime
    method: str
    library_version: int
    size: int
    zotero_dir: Path | None = None  # backed-up folder, unknown in a hand-written descriptor


def _clone(source: Path, target: Path) -> bool:
    os_name = platform.system()
    if os_name == 'Darwin':
        command = ['cp', '-c', '-R', str(source), str(target)]
    elif os_name == 'Linux':
        command = ['cp', '-R', '--reflink=always', str(source), str(target)]
    else:
        return False
    try:
        ok = subprocess.run(command, capture_output=True).returncode == 0
    except OSError:
        ok = False
    if not ok and target.exists():
        shutil.rmtree(target)
    return ok


def _tmutil(command: list[str]) -> None:
    """Call to Time Machine, replaced in tests so as never to touch the machine settings."""
    subprocess.run(command, capture_output=True, timeout=30)


def exclude_from_backups(folder: Path, os_name: str | None = None, run_command=None) -> None:
    """Exclude `folder` from backup software (D159). `CACHEDIR.TAG` everywhere, Time Machine exclusion
    on macOS. These copies only last a few days and double that of the Zotero folder. Done once,
    when the `CACHEDIR.TAG` file is missing (the Time Machine exclusion follows the folder and `tmutil` takes
    several seconds). A failure does not prevent the backup."""
    tag = folder / CACHEDIR
    if tag.is_file():
        return
    comment = L(en='# zot-clean backups, excluded from backup software.',
                fr='# Sauvegardes de zot-clean, écartées des logiciels de sauvegarde.')
    tag.write_text(f'{SIGNATURE}\n{comment}\n', encoding='utf-8')
    if (os_name or platform.system()) == 'Darwin':
        try:
            (run_command or _tmutil)(['tmutil', 'addexclusion', str(folder)])
        except (OSError, subprocess.SubprocessError):
            pass


def _size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob('*') if f.is_file())


def make_backup(cfg: Config, is_open=zotero_running, now: datetime | None = None) -> BackupInfo:
    if is_open():
        raise Refusal(L(en='Zotero is open. Close it, then run `zc backup` again.',
                        fr='Zotero est ouvert. Le fermer, puis relancer `zc backup`.'))
    if not cfg.database.is_file():
        raise Refusal(L(en=f'Zotero database not found: {cfg.database}', fr=f'Base Zotero introuvable : {cfg.database}'))
    now = now or datetime.now().astimezone()
    cfg.backups.mkdir(parents=True, exist_ok=True)
    exclude_from_backups(cfg.backups)
    target = cfg.backups / f'{now:%Y-%m-%d_%H%M%S}'
    target.mkdir(parents=True, exist_ok=True)
    if _clone(cfg.zotero_dir, target / cfg.zotero_dir.name):
        method, database = 'clone', target / cfg.zotero_dir.name / cfg.database.name
    else:
        database = reader.copy_file(cfg.database, target)
        method = 'base'
    check_db = sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)
    try:
        if check_db.execute('pragma quick_check').fetchone()[0] != 'ok':
            raise Refusal(L(en=f'The copy of the database is damaged ({database}). Backup abandoned.',
                                fr=f'La copie de la base est endommagée ({database}). Sauvegarde abandonnée.'))
    finally:
        check_db.close()
    info = BackupInfo(target, now, method, reader.library_version(database), _size(target), cfg.zotero_dir)
    (target / MANIFEST).write_text(json.dumps({
        'date': now.isoformat(timespec='seconds'), 'methode': method, 'dossier_zotero': str(cfg.zotero_dir),
        'version_bibliotheque': info.library_version, 'taille': info.size, 'zc': __version__},
        ensure_ascii=False, indent=1), encoding='utf-8')
    # At least one, the one just made (`config.load` already refuses fewer).
    for former in list_backups(cfg)[max(1, cfg.backup.keep):]:
        shutil.rmtree(former.folder)
    return info


def list_backups(cfg: Config) -> list[BackupInfo]:
    """Backups made by zot-clean, from the most recent to the oldest."""
    res = []
    if cfg.backups.is_dir():
        for d in cfg.backups.iterdir():
            f = d / MANIFEST
            if f.is_file():
                j = json.loads(f.read_text(encoding='utf-8'))
                z = j.get('dossier_zotero')
                res.append(BackupInfo(d, datetime.fromisoformat(j['date']), j['methode'], j['version_bibliotheque'],
                                j['taille'], Path(z) if z else None))
    return sorted(res, key=lambda i: i.date, reverse=True)


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return a.expanduser().resolve() == b.expanduser().resolve()
    except OSError:
        return a == b


def latest(cfg: Config, now: datetime | None = None) -> BackupInfo | None:
    """Recent backup of the Zotero folder of the configuration. One of another folder (`[sauvegarde] dossier`
    shared by two libraries, `[zotero] dossier` changed since) does not count. A descriptor without a folder
    (hand-written) is accepted."""
    now = now or datetime.now().astimezone()
    for i in list_backups(cfg):
        if i.zotero_dir and not _same_folder(i.zotero_dir, cfg.zotero_dir):
            continue
        if now - i.date <= timedelta(hours=cfg.backup.delay_hours):
            return i
    return None
