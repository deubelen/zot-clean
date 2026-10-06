"""Sauvegarde du dossier Zotero avant une opération de masse (D15, D40 à D42).

Zotero doit être fermé, ce que l'on vérifie par la liste des processus.
Clone du dossier entier quand le système de fichiers le permet (APFS, Btrfs,
XFS), sinon copie de la base seule. Chaque sauvegarde est un sous-dossier de
`cfg.sauvegardes` avec un fichier descriptif `sauvegarde.json`. Seules les
plus récentes sont conservées. Le dossier des sauvegardes est écarté des
logiciels de sauvegarde (D159), qui recopieraient chaque clone en entier.
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

from zot_clean import __version__, lecture
from zot_clean.config import Config
from zot_clean.ecriture import Refus

DESCRIPTIF = 'sauvegarde.json'
# Convention reconnue par Borg (`exclude_caches`), restic et tar (`--exclude-caches`), https://bford.info/cachedir/
CACHEDIR = 'CACHEDIR.TAG'
SIGNATURE = 'Signature: 8a477f597d28d172789f06886806bc55'


def zotero_ouvert() -> bool:
    """Vrai si un processus Zotero tourne. Lève `Refus` si on ne peut pas le savoir."""
    try:
        if os.name == 'nt':
            r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq zotero.exe', '/NH'], capture_output=True, text=True,
                               timeout=30)
            if r.returncode != 0:
                raise OSError(r.stderr)
            return 'zotero.exe' in r.stdout.lower()
        # Selon l'installation (archive officielle, Flatpak), le processus s'appelle zotero ou zotero-bin (D193).
        r = subprocess.run(['pgrep', '-i', '-x', 'zotero|zotero-bin'], capture_output=True, text=True, timeout=30)
        if r.returncode not in (0, 1):
            raise OSError(r.stderr)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        raise Refus(f"Impossible de vérifier que Zotero est fermé ({e}). Sauvegarde abandonnée.") from None


@dataclass
class Info:
    dossier: Path
    date: datetime
    methode: str
    version_bibliotheque: int
    taille: int


def _cloner(source: Path, cible: Path) -> bool:
    systeme = platform.system()
    if systeme == 'Darwin':
        commande = ['cp', '-c', '-R', str(source), str(cible)]
    elif systeme == 'Linux':
        commande = ['cp', '-R', '--reflink=always', str(source), str(cible)]
    else:
        return False
    try:
        ok = subprocess.run(commande, capture_output=True).returncode == 0
    except OSError:
        ok = False
    if not ok and cible.exists():
        shutil.rmtree(cible)
    return ok


def _tmutil(commande: list[str]) -> None:
    """Appel à Time Machine, remplacé dans les tests pour ne jamais toucher aux réglages de la machine."""
    subprocess.run(commande, capture_output=True, timeout=30)


def exclure_des_sauvegardes(dossier: Path, systeme: str | None = None, executer=None) -> None:
    """Écarte `dossier` des logiciels de sauvegarde (D159). `CACHEDIR.TAG` partout, exclusion de Time Machine
    sur macOS. Ces copies ne durent que quelques jours et doublent celle du dossier Zotero. Fait une seule fois,
    quand le fichier `CACHEDIR.TAG` manque (l'exclusion de Time Machine suit le dossier et `tmutil` prend
    plusieurs secondes). Un échec n'empêche pas la sauvegarde."""
    tag = dossier / CACHEDIR
    if tag.is_file():
        return
    tag.write_text(f'{SIGNATURE}\n# Sauvegardes de zot-clean, écartées des logiciels de sauvegarde.\n',
                   encoding='utf-8')
    if (systeme or platform.system()) == 'Darwin':
        try:
            (executer or _tmutil)(['tmutil', 'addexclusion', str(dossier)])
        except (OSError, subprocess.SubprocessError):
            pass


def _taille(dossier: Path) -> int:
    return sum(f.stat().st_size for f in dossier.rglob('*') if f.is_file())


def sauvegarder(cfg: Config, ouvert=zotero_ouvert, maintenant: datetime | None = None) -> Info:
    if ouvert():
        raise Refus('Zotero est ouvert. Le fermer, puis relancer `zc sauvegarder`.')
    if not cfg.base.is_file():
        raise Refus(f'Base Zotero introuvable : {cfg.base}')
    maintenant = maintenant or datetime.now().astimezone()
    cfg.sauvegardes.mkdir(parents=True, exist_ok=True)
    exclure_des_sauvegardes(cfg.sauvegardes)
    cible = cfg.sauvegardes / f'{maintenant:%Y-%m-%d_%H%M%S}'
    cible.mkdir(parents=True, exist_ok=True)
    if _cloner(cfg.dossier_zotero, cible / cfg.dossier_zotero.name):
        methode, base = 'clone', cible / cfg.dossier_zotero.name / cfg.base.name
    else:
        base = lecture.copier(cfg.base, cible)
        methode = 'base'
    verif = sqlite3.connect(f'{base.as_uri()}?mode=ro', uri=True)
    try:
        if verif.execute('pragma quick_check').fetchone()[0] != 'ok':
            raise Refus(f'La copie de la base est endommagée ({base}). Sauvegarde abandonnée.')
    finally:
        verif.close()
    info = Info(cible, maintenant, methode, lecture.version_bibliotheque(base), _taille(cible))
    (cible / DESCRIPTIF).write_text(json.dumps({
        'date': maintenant.isoformat(timespec='seconds'), 'methode': methode, 'dossier_zotero': str(cfg.dossier_zotero),
        'version_bibliotheque': info.version_bibliotheque, 'taille': info.taille, 'zc': __version__},
        ensure_ascii=False, indent=1), encoding='utf-8')
    for ancienne in lister(cfg)[cfg.sauvegarde.conserver:]:
        shutil.rmtree(ancienne.dossier)
    return info


def lister(cfg: Config) -> list[Info]:
    """Sauvegardes faites par zot-clean, de la plus récente à la plus ancienne."""
    res = []
    if cfg.sauvegardes.is_dir():
        for d in cfg.sauvegardes.iterdir():
            f = d / DESCRIPTIF
            if f.is_file():
                j = json.loads(f.read_text(encoding='utf-8'))
                res.append(Info(d, datetime.fromisoformat(j['date']), j['methode'], j['version_bibliotheque'],
                                j['taille']))
    return sorted(res, key=lambda i: i.date, reverse=True)


def recente(cfg: Config, maintenant: datetime | None = None) -> Info | None:
    maintenant = maintenant or datetime.now().astimezone()
    for i in lister(cfg):
        if maintenant - i.date <= timedelta(hours=cfg.sauvegarde.delai_heures):
            return i
    return None
