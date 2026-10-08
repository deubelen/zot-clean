"""Better BibTeX and file syncing, read from the Zotero profile (D145, D157).

The only module that knows the Zotero profile and the Better BibTeX (BBT)
files, as `reader.py` does for the database schema. The profiles folder
depends on the system. Its `profiles.ini` lists the profiles, and the
`prefs.js` of each one names the data folder it serves. In the chosen profile,
`extensions.json` gives the version and state of BBT, and `prefs.js` its
settings, read with a regular expression without executing anything. A
preference missing from `prefs.js` keeps the BBT default value.

When no profile serves the data folder (moved profile, unexpected system),
detection falls back to looking for a `better-bibtex/` folder or a
`better-bibtex*.sqlite` database in the data folder, with no version or
settings, and says so (`source`). Nothing is ever written to the profile.

The same `prefs.js` says where Zotero syncs the files of the personal library
(zotero.org, WebDAV or nowhere), which the audit uses to talk about missing
files (D157).
"""

import configparser
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from zot_clean.lang import L

BBT_ID = 'better-bibtex@iris-advies.com'
PREFIX = 'extensions.zotero.translators.better-bibtex.'
PROFILE, DATA_FOLDER = 'profil', 'dossier de données'

# Default values of BBT 9 (the extension's `prefs.js` file), used when the profile says nothing.
BBT_FORMULA = 'auth.lower + shorttitle(3,3) + year'
FILL_AFTER_BBT = 2.0
# Formula of the default method (D24). It lives in BBT and is not copied into config.toml (D145),
# it only serves to flag a different formula, without making it a problem.
METHOD_FORMULA = 'auth.lower + shorttitle(3, 3) + year'
# File syncing (D157). UNKNOWN when no profile serves the data folder.
ZOTERO_ORG, WEBDAV, NONE, UNKNOWN = 'zotero.org', 'webdav', 'aucune', ''
# First BBT version that stores keys in Zotero's native field (D145).
VERSION_MIN = 8

_PREF = re.compile(r'^\s*user_pref\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(.*?)\s*\)\s*;\s*$', re.M)


@dataclass
class State:
    installed: bool = False  # extension present, even if disabled
    active: bool = False
    version: str = ''
    formula: str = BBT_FORMULA
    fill_after: float = FILL_AFTER_BBT  # seconds before BBT fills an empty key, 0 = on demand
    regenerates: bool = False  # BBT regenerates an item's key on every edit (resetKeyOnChange)
    casing: bool = False  # BBT tells case apart when judging two identical keys
    source: str = ''  # PROFILE or DATA_FOLDER (fallback)
    profile: Path | None = None

    @property
    def present(self) -> bool:
        """An installed but disabled BBT counts as absent (D145)."""
        return self.installed and self.active

    @property
    def major(self) -> int | None:
        m = re.match(r'\d+', self.version)
        return int(m.group()) if m else None

    @property
    def too_old(self) -> bool:
        return self.major is not None and self.major < VERSION_MIN

    @property
    def method_formula(self) -> bool:
        return ''.join(self.formula.split()) == ''.join(METHOD_FORMULA.split())


def profile_paths(os_name: str, personal: Path, appdata: str | None = None) -> list[Path]:
    """Folders that may contain the Zotero `profiles.ini`, depending on the system."""
    if os_name == 'darwin':
        return [personal / 'Library' / 'Application Support' / 'Zotero']
    if os_name.startswith('win'):
        root = Path(appdata) if appdata else personal / 'AppData' / 'Roaming'
        return [root / 'Zotero' / 'Zotero']
    # Linux and other Unixes, with the Flatpak installation.
    return [personal / '.zotero' / 'zotero', personal / '.var' / 'app' / 'org.zotero.Zotero' / '.zotero' / 'zotero']


def profile_folders() -> list[Path]:
    return profile_paths(sys.platform, Path.home(), os.environ.get('APPDATA'))


def profiles(root: Path) -> list[Path]:
    """Profiles listed by `root/profiles.ini`, the default profile first."""
    ini = root / 'profiles.ini'
    if not ini.is_file():
        return []
    reader = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        reader.read_string(ini.read_text(encoding='utf-8', errors='replace'))
    except configparser.Error:
        return []
    found_list = []
    for name in reader.sections():
        s = reader[name]
        if not name.lower().startswith('profile') or not s.get('path'):
            continue
        path = root / s['path'] if s.get('isrelative', '1') == '1' else Path(s['path'])
        found_list.append((s.get('default') != '1', path))
    return [c for _, c in sorted(found_list, key=lambda t: t[0])]


def _value(raw: str):
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"')
    if raw in ('true', 'false'):
        return raw == 'true'
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def read_prefs(profile: Path) -> dict:
    """The `user_pref(...)` preferences of `prefs.js`, without executing anything."""
    path = profile / 'prefs.js'
    if not path.is_file():
        return {}
    text = path.read_text(encoding='utf-8', errors='replace')
    return {m.group(1): _value(m.group(2)) for m in _PREF.finditer(text)}


def _normal(p: Path) -> str:
    return os.path.normcase(str(Path(p).expanduser().resolve()))


def data_folder(prefs: dict, personal: Path) -> Path:
    """Data folder served by a profile: `dataDir` when `useDataDir` is true, otherwise `~/Zotero`."""
    if prefs.get('extensions.zotero.useDataDir') is True and prefs.get('extensions.zotero.dataDir'):
        return Path(str(prefs['extensions.zotero.dataDir']))
    return personal / 'Zotero'


def profile_for_dir(zotero_dir: Path, roots: list[Path] | None = None,
                      personal: Path | None = None) -> Path | None:
    roots = profile_folders() if roots is None else roots
    personal = personal or Path.home()
    target = _normal(zotero_dir)
    for root in roots:
        for profile in profiles(root):
            if _normal(data_folder(read_prefs(profile), personal)) == target:
                return profile
    return None


def _extension(profile: Path) -> dict | None:
    path = profile / 'extensions.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return next((a for a in data.get('addons', []) if a.get('id') == BBT_ID), None)


def _number(v, default: float) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def detect(zotero_dir: Path, roots: list[Path] | None = None, personal: Path | None = None) -> State:
    """State of BBT for the data folder `zotero_dir` (D145)."""
    profile = profile_for_dir(zotero_dir, roots, personal)
    if profile is None:
        found = (zotero_dir / 'better-bibtex').exists() or any(zotero_dir.glob('better-bibtex*.sqlite'))
        return State(installed=found, active=found, source=DATA_FOLDER)
    ext = _extension(profile)
    if ext is None:
        return State(source=PROFILE, profile=profile)
    prefs = read_prefs(profile)

    def pref(name, default):
        return prefs.get(PREFIX + name, default)

    formula = pref('citekeyFormat', BBT_FORMULA)
    return State(installed=True, active=ext.get('active') is True, version=str(ext.get('version', '')),
                formula=(formula if isinstance(formula, str) and formula.strip() else BBT_FORMULA).strip(),
                fill_after=_number(pref('fillKeyAfter', FILL_AFTER_BBT), FILL_AFTER_BBT),
                regenerates=pref('resetKeyOnChange', False) is True,
                casing=pref('citekeyCaseInsensitive', True) is False,
                source=PROFILE, profile=profile)


def file_storage(zotero_dir: Path, roots: list[Path] | None = None,
                      personal: Path | None = None) -> str:
    """Where Zotero syncs the files of the personal library (D157). A preference missing from
    `prefs.js` keeps the Zotero default value (sync on, through zotero.org)."""
    profile = profile_for_dir(zotero_dir, roots, personal)
    if profile is None:
        return UNKNOWN
    prefs = read_prefs(profile)
    if prefs.get('extensions.zotero.sync.storage.enabled', True) is False:
        return NONE
    return WEBDAV if prefs.get('extensions.zotero.sync.storage.protocol', 'zotero') == 'webdav' else ZOTERO_ORG


def downloads_at_sync(zotero_dir: Path, roots: list[Path] | None = None, personal: Path | None = None) -> bool:
    """Does Zotero already download the files of the personal library at sync time? Then the files still missing
    after a sync are on no server either (pilot bench, D242). False when the profile does not say."""
    profile = profile_for_dir(zotero_dir, roots, personal)
    if profile is None:
        return False
    return read_prefs(profile).get('extensions.zotero.sync.storage.downloadMode.personal') == 'on-sync'


def zotero_language(zotero_dir: Path, roots: list[Path] | None = None, personal: Path | None = None) -> str:
    """Language of the Zotero interface (« fr », « en »...), empty if the profile does not say. `intl.locale.requested`
    when the user chose it in Zotero, otherwise the first language of `intl.accept_languages`, which Zotero
    sets from the system language."""
    profile = profile_for_dir(zotero_dir, roots, personal)
    if profile is None:
        return ''
    prefs = read_prefs(profile)
    for name in ('intl.locale.requested', 'intl.accept_languages'):
        if isinstance(v := prefs.get(name), str) and v.strip():
            return v.split(',')[0].strip().split('-')[0].lower()
    return ''


def describe(state: State) -> str:
    """One sentence about BBT, for `zc init` and the audit."""
    if state.source == DATA_FOLDER:
        if state.present:
            return L(en='Better BibTeX detected by its folder in the data folder (Zotero profile not found, version '
                        'and settings unknown).',
                     fr='Better BibTeX détecté par son dossier dans le dossier de données (profil de Zotero '
                        'introuvable, version et réglages inconnus).')
        return L(en='Better BibTeX not detected (Zotero profile not found).',
                 fr='Better BibTeX non détecté (profil de Zotero introuvable).')
    if not state.installed:
        return L(en='Better BibTeX absent from the Zotero profile.', fr='Better BibTeX absent du profil de Zotero.')
    if not state.active:
        return L(en=f'Better BibTeX {state.version} installed but disabled in Zotero, counted as absent.',
                 fr=f'Better BibTeX {state.version} installé mais désactivé dans Zotero, compté comme absent.')
    text = L(en=f'Better BibTeX {state.version} active, formula "{state.formula}".',
             fr=f'Better BibTeX {state.version} actif, formule « {state.formula} ».')
    if state.too_old:
        text += L(en=f' This version is too old, the citation keys step needs Better BibTeX {VERSION_MIN} and at '
                     'least Zotero 8, which store keys in Zotero\'s native field.',
                  fr=f" Cette version est trop ancienne, l'étape des clés de citation demande Better BibTeX "
                     f'{VERSION_MIN} et Zotero 8 au moins, qui rangent les clés dans le champ natif de Zotero.')
    return text


def automatic_tags(zotero_dir: Path, roots: list[Path] | None = None,
                      personal: Path | None = None) -> bool | None:
    """Zotero setting « Automatically tag items with keywords and subject headings » (D155),
    true by default, written to `prefs.js` only if it differs. None when no profile serves the data
    folder. The connector setting, specific to the browser, cannot be read here."""
    profile = profile_for_dir(zotero_dir, roots, personal)
    if profile is None:
        return None
    return read_prefs(profile).get('extensions.zotero.automaticTags', True) is not False
