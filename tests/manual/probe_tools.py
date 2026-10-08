"""Outils communs aux sondes en plusieurs phases (tags, clés de citation, noms des fichiers).

Une sonde écrit par l'API sur le compte de test, l'utilisateur synchronise le profil de test dans Zotero,
puis la sonde relit la copie locale de `zotero.sqlite` (par `zot_clean.lecture`), le dossier `storage/` et
l'API. L'état d'une phase à l'autre (clés créées, valeurs attendues, version du serveur) est gardé dans
`<dossier de travail>/sondes/<nom>.json`. Chaque vérification affiche « réussi » ou « échoué » avec ce
qui a été observé. Ce qui ne se voit que dans Zotero est posé en question, à la fin de la sortie.
"""

import argparse
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual import populate  # noqa: E402
from zot_clean import config, api, reader  # noqa: E402

SYNC_PROMPT = ('Synchroniser le profil de test dans Zotero (bouton de synchronisation en haut à droite), '
                'attendre la fin, puis relancer.')


def arguments(doc: str, phases: dict[str, str]) -> argparse.Namespace:
    """`--dossier` and a mandatory phase among `phases` (name -> help)."""
    p = argparse.ArgumentParser(description=doc.splitlines()[0], epilog=doc.split('\n\n', 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dossier', dest='folder', metavar='DOSSIER', type=Path, required=True, help='dossier de travail du compte de test (~/zc-test)')
    g = p.add_mutually_exclusive_group(required=True)
    for name, help_text in phases.items():
        g.add_argument(f'--{name}', dest='phase', action='store_const', const=name, help=help_text)
    return p.parse_args()


class Probe:
    def __init__(self, name: str, folder: Path):
        self.name = name
        self.cfg = config.load(folder.expanduser().resolve())
        env = config.read_env(self.cfg.workspace)
        info = populate.check_key(env.get('ZOTERO_API_KEY', ''))
        populate.check_test_account(env, os.environ.get('ZC_COMPTE_TEST'), info.user)
        self.client = api.from_config(self.cfg)
        self.state_file = self.cfg.workspace / 'sondes' / f'{name}.json'
        self.results: list[tuple[bool, str]] = []
        self.questions: list[str] = []

    # --- state from one phase to the next ---

    def state(self) -> dict:
        if not self.state_file.is_file():
            raise SystemExit(f'Aucun état de la sonde dans {self.state_file}. Lancer d\'abord la phase --preparer.')
        return json.loads(self.state_file.read_text(encoding='utf-8'))

    def save(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    def new_state(self) -> dict:
        if self.state_file.is_file():
            raise SystemExit(f'{self.state_file} existe déjà : une sonde précédente n\'a pas été nettoyée. '
                             'Lancer --nettoyer d\'abord.')
        return {}

    # --- output ---

    def check(self, condition: bool, message: str, observed: str = '') -> bool:
        self.results.append((condition, message))
        print(f"{'réussi ' if condition else 'échoué '} {message}" + (f' (observé : {observed})' if observed else ''))
        return condition

    def question(self, text: str) -> None:
        self.questions.append(text)

    def outcome(self, follow_up: str = '') -> int:
        if self.questions:
            print('\nÀ regarder dans Zotero, réponses à noter :')
            for i, q in enumerate(self.questions, 1):
                print(f'  Q{i}. {q}')
        failures = [m for ok, m in self.results if not ok]
        if self.results:
            print(f'\n{len(self.results) - len(failures)} vérification(s) sur {len(self.results)} réussie(s).')
        if follow_up:
            print(f'\nEnsuite : {follow_up}')
        return 1 if failures else 0

    # --- API ---

    def request(self, method: str, path: str, headers: dict | None = None, allowed: tuple[int, ...] = (), **kw):
        """Request with headers in addition to those of pyzotero (`Client._request` sets its own)."""
        h = self.client.zot.default_headers() | (headers or {})
        r = self.client.zot.client.request(method, self.client.zot.endpoint + path, headers=h, **kw)
        if r.status_code >= 400 and r.status_code not in allowed:
            raise RuntimeError(f'{method} {path} : {r.status_code} {r.text[:300]}')
        return r

    def write(self, objects: list[dict]) -> api.Result:
        """Modifies items, with their current version read just before."""
        current = self.client.items([o['key'] for o in objects])
        return self.client.write([o | {'version': current[o['key']]['version']} for o in objects])

    def attach_pdf(self, parent: str, filename: str) -> str:
        """Uploads a small probe-specific PDF as `filename`, attached to `parent`. Returns the key."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / filename
            f.write_bytes(populate.pdf(f'zc sonde {self.name} {secrets.token_hex(6)}'))
            res = self.client.zot.attachment_simple([str(f)], parent)
        if res.get('failure'):
            raise SystemExit(f'Envoi du PDF {filename} refusé : {res["failure"]}')
        return next(iter(res.get('success', []) + res.get('unchanged', [])))['key']

    def tag_on_server(self, name: str) -> int:
        """Number of items carrying this tag on the server, 0 if it no longer exists."""
        r = self.request('GET', f'{self.client.prefix}/tags/{quote(name, safe="")}', allowed=(404,))
        if r.status_code == 404 or not r.json():
            return 0
        return sum(int(t.get('meta', {}).get('numItems', 0)) for t in r.json())

    def setting(self, name: str) -> tuple[object, int]:
        """Value and version of a synchronised setting (`tagColors`…), (None, 0) if it does not exist."""
        r = self.request('GET', f'{self.client.prefix}/settings/{name}', allowed=(404,))
        if r.status_code == 404:
            return None, 0
        d = r.json()
        return d.get('value'), int(d.get('version', 0))

    def write_setting(self, name: str, value) -> None:
        """Writes a synchronised setting, or deletes it if `value` is empty."""
        version = {'If-Unmodified-Since-Version': str(self.client.server_version())}
        if value:
            self.request('POST', f'{self.client.prefix}/settings', version, json={name: {'value': value}})
        else:
            self.request('DELETE', f'{self.client.prefix}/settings/{name}', version, allowed=(404,))

    def delete(self, items: list[str]) -> None:
        """Permanent deletion of the items and their descendants (annotations, attachments, notes),
        from the deepest up to the items, each with its version read just before."""
        for item in items:
            order = []
            if item in self.client.items([item]):
                for child in self.client.children(item):
                    if child.get('itemType') == 'attachment':
                        order += [a['key'] for a in self.client.children(child['key'])]
                    order.append(child['key'])
            for key in order + [item]:
                current = self.client.items([key])
                if key not in current:
                    continue
                self.request('DELETE', f'{self.client.prefix}/items/{key}',
                             {'If-Unmodified-Since-Version': str(current[key]['version'])}, allowed=(404,))

    # --- local copy ---

    def local_copy(self, state: dict, keys: list[str], require_upload: bool = True) -> reader.Library:
        """Reads the local copy and stops if Zotero has not yet received the probe's latest writes,
        or, with `require_upload`, if it has local changes not yet sent on these items (they would cause a
        conflict with the next write)."""
        lib = reader.read(self.cfg.database)
        local_items = lib.by_key()
        missing_locally = [k for k in keys if k not in local_items]
        if lib.version < state.get('version', 0) or missing_locally:
            raise SystemExit(f'La copie locale n\'a pas reçu les dernières écritures (version locale {lib.version}, '
                             f'attendue {state.get("version", 0)} au moins, {len(missing_locally)} élément(s) absent(s)). '
                             + SYNC_PROMPT)
        unsent = [k for k in keys if not local_items[k].synced]
        if require_upload and unsent:
            raise SystemExit(f'{len(unsent)} élément(s) de la sonde ont des changements locaux pas encore '
                             f'envoyés au serveur ({", ".join(unsent)}). ' + SYNC_PROMPT)
        return lib

    def storage(self, key: str) -> Path:
        return self.cfg.zotero_dir / 'storage' / key

    def local_tag_names(self) -> set[str]:
        return tag_names(self.cfg.database)

    def local_setting(self, name: str) -> object:
        return local_setting(self.cfg.database, name)


def tag_names(database: Path) -> set[str]:
    """All the names of the `tags` table, including those no item carries any more.

    `reader.read` sees only the carried tags (through `itemTags`), hence this direct read, reserved for
    the probes."""
    with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
        db = sqlite3.connect(reader.copy_file(database, Path(tmp)))
        try:
            reader.check_schema(db)
            return {n for (n,) in db.execute('select name from tags')}
        finally:
            db.close()


def local_setting(database: Path, name: str, library: int = reader.PERSONAL_LIBRARY) -> object:
    """Value of a synchronised setting in the local copy (`syncedSettings`), None if it is not there."""
    with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
        db = sqlite3.connect(reader.copy_file(database, Path(tmp)))
        try:
            line = db.execute('select value from syncedSettings where setting = ? and libraryID = ?',
                               (name, library)).fetchone()
        except sqlite3.OperationalError:
            return None
        finally:
            db.close()
    return json.loads(line[0]) if line else None


def visible_files(folder: Path) -> list[str]:
    """Names of the files of a `storage/` folder, without Zotero's hidden files (`.zotero-ft-cache`…),
    in the case and Unicode form of the disk."""
    if not folder.is_dir():
        return []
    return sorted(f.name for f in folder.iterdir() if f.is_file() and not f.name.startswith('.'))


def same_name(a: str, b: str) -> bool:
    """Same name, case included, whatever the Unicode form (macOS sometimes decomposes accents)."""
    return unicodedata.normalize('NFC', a) == unicodedata.normalize('NFC', b)
