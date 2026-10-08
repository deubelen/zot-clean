#!/usr/bin/env python3
"""Pilot test bench (D237): the real `zc` on a synthetic library, without Zotero, account or network.

A bench is a folder that holds a Zotero data folder (`Zotero/zotero.sqlite`, `storage/` with small real PDFs), a
Zotero profile with Better BibTeX (`profil-zotero/`), the state of a fake zotero.org kept on disk
(`serveur.json`), what the fake metadata services know (`sources.json`), a `bin/zc` shim and a working folder
(`travail/`) made by the real `zc init`.

    python outils/pilote/banc.py create <bench> --library-language fr|en [--seed N]
    <bench>/bin/zc …                    the real zc, run through `banc.py run <bench> -- …`
    python outils/pilote/banc.py sync <bench>             Zotero's synchronization (zotero.sqlite catches up)
    python outils/pilote/banc.py zotero open|close <bench>
    python outils/pilote/banc.py status <bench>

`run` loads the fake server from `serveur.json`, plugs it into pyzotero (tests/fake_server.py), answers the key
check, plugs the fake metadata services (tests/fake_sources.py), reads Better BibTeX from the bench's profile,
takes « is Zotero running » from the bench's state, blocks every real network connection, runs
`zot_clean.cli.main` and saves the server state back. The library is written only by `sync` and the other user
gestures, never by `run`, as zotero.sqlite is never written by zc.
"""

import argparse
import contextlib
import io
import itertools
import json
import os
import re
import shlex
import socket
import sqlite3
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for p in (HERE, REPO / 'tests'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
try:
    import zot_clean  # noqa: F401  (installed in the development environment)
except ImportError:
    sys.path.insert(0, str(REPO / 'src'))

import httpx2  # noqa: E402

from fake_server import FakeServer  # noqa: E402
from fake_sources import FakeServices  # noqa: E402

STATE, SERVER, SOURCES = 'banc.json', 'serveur.json', 'sources.json'
ZOTERO, PROFILES, WORK, BIN, GESTURES = 'Zotero', 'profil-zotero', 'travail', 'bin', 'gestes'
NETWORK_LOG = 'reseau-bloque.log'
ONLINE_FILES = 'zotero-org-fichiers'  # files stored on zotero.org only, by attachment key
API_KEY = 'BANC-PILOTE-CLE-FACTICE'
SCHEMA = REPO / 'tests' / 'donnees' / 'schema_zotero.sql'
KEY_START = 10 ** 7  # keys made by the fake server, far from those of the generated library
BBT_VERSION = '9.0.3'


def say(text: str) -> None:
    print(text, flush=True)


# --- Bench state ------------------------------------------------------------------------------------------------


def load_state(bench: Path) -> dict:
    path = bench / STATE
    if not path.is_file():
        raise SystemExit(f'{bench} is not a pilot bench (no {STATE}). Create one with `banc.py create`.')
    return json.loads(path.read_text(encoding='utf-8'))


def save_state(bench: Path, state: dict) -> None:
    _write_json(bench / STATE, state)


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


ITEM_META = {'key', 'version', 'itemType', 'dateAdded', 'dateModified', 'creators', 'tags', 'collections',
             'relations', 'deleted', 'parentItem'}
NON_REGULAR = {'attachment', 'note', 'annotation'}


class BenchServer(FakeServer):
    """The fake server of the tests, which also refuses, as zotero.org does, a field or a creator role that the
    item's type does not have, and keeps each item with exactly the fields of its type after a change of type."""

    def __init__(self, user: int, schema: dict[str, set[str]], roles: dict[str, set[str]]):
        super().__init__(user)
        self.schema, self.roles = schema, roles

    def _refusal(self, o: dict, store: dict) -> str:
        if refusal := super()._refusal(o, store):
            return refusal
        if store is not self.all_items:
            return ''
        current = self.all_items.get(o.get('key'), {})
        type_ = o.get('itemType') or current.get('itemType')
        if type_ in NON_REGULAR or type_ not in self.schema:
            return '' if type_ in NON_REGULAR or not type_ else f"'{type_}' is not a valid item type"
        merged = {**current, **o}
        for f, v in merged.items():
            if f not in ITEM_META and v not in ('', None) and f not in self.schema[type_]:
                return f"'{f}' is not a valid field for type '{type_}'"
        for c in merged.get('creators') or []:
            if c.get('creatorType') not in self.roles.get(type_, set()):
                return f"'{c.get('creatorType')}' is not a valid creator type for item type '{type_}'"
        return ''

    def _write(self, objects: list[dict], store: dict | None = None) -> httpx2.Response:
        r = super()._write(objects, store)
        if store is None:
            for o in objects:
                d = self.all_items.get(o.get('key', ''))
                if d and o.get('itemType') and d['itemType'] not in NON_REGULAR:
                    fields = self.schema.get(d['itemType'], set())
                    for f in [f for f in d if f not in ITEM_META and f not in fields]:
                        del d[f]
                    for f in fields:
                        d.setdefault(f, '')
        return r


def schema_of(zotero_dir: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    db = sqlite3.connect(zotero_dir / 'zotero.sqlite')
    try:
        fields = {t: set(f) for t, f in type_fields(db).items()}
        roles: dict[str, set[str]] = {}
        for t, r in db.execute('select t.typeName, c.creatorType from itemTypeCreatorTypes i join itemTypes t '
                               'using(itemTypeID) join creatorTypes c using(creatorTypeID)'):
            roles.setdefault(t, set()).add(r)
        return fields, roles
    finally:
        db.close()


def load_server(bench: Path) -> BenchServer:
    d = json.loads((bench / SERVER).read_text(encoding='utf-8'))
    s = BenchServer(d['user'], *schema_of(bench / ZOTERO))
    s.version = d['version']
    s.all_items, s.collections, s.searches, s.settings = d['items'], d['collections'], d['searches'], d['settings']
    s.files = set(d['files'])
    s.deleted = d['deleted']
    s._n = itertools.count(d['next_key'])
    return s


def save_server(bench: Path, s: FakeServer) -> None:
    _write_json(bench / SERVER, {
        'user': s.user, 'version': s.version, 'items': s.all_items, 'collections': s.collections,
        'searches': s.searches, 'settings': s.settings, 'files': sorted(s.files), 'deleted': s.deleted,
        'next_key': next(s._n)})


# --- Fake metadata services -------------------------------------------------------------------------------------

STOP = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'to', 'for', 'le', 'la', 'les', 'l', 'de', 'des', 'du', 'd', 'et',
        'en', 'un', 'une', 'au', 'aux'}


def _words(text: str) -> set[str]:
    import unicodedata
    text = unicodedata.normalize('NFKD', text.lower()).encode('ascii', 'ignore').decode()
    return {w for w in re.findall(r'[a-z0-9]+', text) if w not in STOP}


class BenchServices(FakeServices):
    """The fake services of the tests, whose searches answer only the records that match the request, as the
    real services rank their results (the tests' version returns the same list for any search)."""

    def __init__(self, data: dict):
        super().__init__()
        self.crossref, self.openalex = data['crossref'], data['openalex']
        self.handles = set(data['handles'])
        self.bnf, self.sudoc, self.openlibrary = data['bnf'], data['sudoc'], data['openlibrary']

    @staticmethod
    def _best(query: str, records, title_of, n: int = 5) -> list:
        q = _words(query)
        scored = []
        for r in records:
            t = _words(title_of(r))
            if t and len(t & q) / len(t) >= 0.6:
                scored.append((len(t & q) / len(t), r))
        return [r for _, r in sorted(scored, key=lambda x: -x[0])[:n]]

    def handle(self, req: httpx2.Request) -> httpx2.Response:
        host, path = req.url.host, urllib.parse.unquote(req.url.path)
        params = req.url.params
        if host == 'api.crossref.org' and path == '/works':
            self.requests.append(f'{host}{path}')
            found = self._best(params.get('query.bibliographic', ''), self.crossref.values(), lambda m: m['title'][0])
            return httpx2.Response(200, json={'message': {'items': found}})
        if host == 'api.openalex.org' and path == '/works':
            if any(c in params.get('search', '') for c in '?.:'):
                return httpx2.Response(400, json={'error': 'Invalid query parameters'})
            self.requests.append(f'{host}{path}')
            pool = list(self.openalex.values()) + [_as_openalex(m) for m in self.crossref.values()]
            return httpx2.Response(200, json={'results': self._best(params.get('search', ''), pool,
                                                                    lambda w: w['title'])})
        if host == 'catalogue.bnf.fr' and not params.get('query', '').startswith('bib.isbn adj'):
            from fake_sources import sru_response
            self.requests.append(f'{host}{path}')
            m = re.search(r'bib\.title all "([^"]*)"', params.get('query', ''))
            found = self._best(m.group(1) if m else '', self.bnf.values(), _unimarc_title, 10)
            return httpx2.Response(200, text=sru_response(found))
        if host == 'openlibrary.org' and path == '/search.json':
            self.requests.append(f'{host}{path}')
            found = self._best(params.get('title', ''), self.openlibrary.items(), lambda kv: kv[1]['title'])
            return httpx2.Response(200, json={'docs': [{
                'key': f'/works/{isbn}', 'title': d['title'],
                'author_name': [a['key'].removeprefix('/authors/') for a in d.get('authors', [])],
                'editions': {'numFound': 1, 'docs': [{'title': d['title'], 'publish_date': [d.get('publish_date', '')],
                                                      'isbn': d.get('isbn_13', []),
                                                      'publisher': d.get('publishers', [])}]}} for isbn, d in found]})
        return super().handle(req)


def _unimarc_title(record: str) -> str:
    m = re.search(r'tag="200".*?code="a">([^<]*)<', record, re.S)
    return m.group(1) if m else ''


def _as_openalex(m: dict) -> dict:
    """A Crossref record as OpenAlex describes the same work."""
    first, _, last = (m.get('page') or '').partition('-')
    return {'doi': f"https://doi.org/{m['DOI']}", 'title': m['title'][0], 'display_name': m['title'][0],
            'type': 'book-chapter' if m['type'] == 'book-chapter' else 'article',
            'publication_year': m['issued']['date-parts'][0][0],
            'authorships': [{'author': {'display_name': f"{a.get('given', '')} {a['family']}".strip()}}
                            for a in m.get('author', [])],
            'primary_location': {'source': {'display_name': (m.get('container-title') or [''])[0],
                                            'issn': m.get('ISSN', [])}},
            'biblio': {'volume': m.get('volume'), 'issue': m.get('issue'), 'first_page': first or None,
                       'last_page': last or None}, 'language': m.get('language')}


# --- Network safeguard ------------------------------------------------------------------------------------------


class _Patches:
    """Attributes replaced for the time of a run, put back afterwards (the bench's test runs in the pytest process)."""

    def __init__(self):
        self.saved: list[tuple[object, str, object]] = []

    def set(self, obj, name: str, value) -> None:
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self) -> None:
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)
        self.saved.clear()


def block_network(patches: _Patches, log: Path) -> None:
    """Refuses every connection out of this process. An attempt is written to `log` (proof for the bench's test)
    and fails as a network outage would."""
    def refuse(where) -> None:
        with log.open('a', encoding='utf-8') as f:
            f.write(f'{datetime.now().isoformat(timespec="seconds")} {where}\n')
        raise OSError(f'network access blocked by the pilot bench ({where})')

    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    unix = getattr(socket, 'AF_UNIX', None)

    def connect(self, address):
        if self.family == unix:
            return original_connect(self, address)
        refuse(address)

    def connect_ex(self, address):
        if self.family == unix:
            return original_connect_ex(self, address)
        refuse(address)

    patches.set(socket.socket, 'connect', connect)
    patches.set(socket.socket, 'connect_ex', connect_ex)
    patches.set(socket, 'create_connection', lambda address, *a, **k: refuse(address))
    patches.set(socket, 'getaddrinfo', lambda host, *a, **k: refuse(host))


# --- Running zc -------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def bench_patches(bench: Path, server: FakeServer):
    """zot_clean as it runs on the bench: fake zotero.org, key accepted, fake metadata services, Better BibTeX read
    from the bench's profile, « is Zotero running » from the bench's state, no Time Machine, no network."""
    from zot_clean import api, backup, bbt, init, sources
    state = load_state(bench)
    patches = _Patches()
    try:
        block_network(patches, bench / NETWORK_LOG)
        original_from_config = api.from_config

        def from_config(cfg):
            client = original_from_config(cfg)  # same refusal as zc without a key in .env
            client.zot.client = httpx2.Client(transport=httpx2.MockTransport(server.handle))
            client._wait = lambda seconds: None
            return client
        patches.set(api, 'from_config', from_config)

        def check_key(key: str):
            if key != state['api_key']:
                raise init.KeyRejected('Clé refusée par Zotero (invalide ou révoquée).' if state['language'] == 'fr'
                                       else 'Key refused by Zotero (invalid or revoked).')
            return init.KeyInfo(server.user, 'pilote', True, True, True)
        patches.set(init, 'check_key', check_key)

        services = BenchServices(json.loads((bench / SOURCES).read_text(encoding='utf-8')))
        original_sources = sources.from_config
        patches.set(sources, 'from_config', lambda cfg, refresh=False, client_http=None, **kw: original_sources(
            cfg, refresh, client_http=services.client(), wait=lambda seconds: None, **kw))
        patches.set(bbt, 'profile_folders', lambda: [bench / PROFILES])
        patches.set(backup.make_backup, '__defaults__', (lambda: load_state(bench)['zotero_open'], None))
        patches.set(backup, '_tmutil', lambda command: None)
        yield
    finally:
        patches.restore()


@contextlib.contextmanager
def _stdin(text: str):
    saved, sys.stdin = sys.stdin, io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = saved


def run(bench: Path, args: list[str], stdin: str | None = None) -> int:
    """Runs `zc args` on the bench and returns its exit code. The fake server is saved back even after a failure."""
    bench = bench.resolve()
    server = load_server(bench)
    from zot_clean import cli
    try:
        with bench_patches(bench, server), (_stdin(stdin) if stdin is not None else contextlib.nullcontext()):
            try:
                return cli.main(args)
            except SystemExit as e:  # --help, --version, argparse errors, refusals outside a command
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
                    return 1
                return e.code or 0
    finally:
        save_server(bench, server)
        state = load_state(bench)
        if state.get('autosync') and state['zotero_open']:  # Zotero picks up the changes right away
            write_database(bench / ZOTERO, server)
            download(bench, server)


# --- Synchronization: zotero.sqlite catches up with the server --------------------------------------------------

LIBRARY_TABLES = ('itemData', 'itemDataValues', 'itemCreators', 'creators', 'itemTags', 'tags', 'collectionItems',
                  'itemAttachments', 'itemNotes', 'itemAnnotations', 'deletedItems', 'deletedCollections',
                  'deletedSearches', 'savedSearchConditions', 'savedSearches', 'syncedSettings', 'collections',
                  'items', 'itemRelations', 'collectionRelations')
NOT_FIELDS = {'key', 'version', 'itemType', 'dateAdded', 'dateModified', 'creators', 'tags', 'collections',
              'relations', 'deleted', 'parentItem', 'note', 'linkMode', 'contentType', 'charset', 'filename', 'md5',
              'mtime', 'path'}
LINK_MODES = {'imported_file': 0, 'imported_url': 1, 'linked_file': 2, 'linked_url': 3, 'embedded_image': 4}
ANNOTATION_TYPES = {'highlight': 1, 'note': 2, 'image': 3, 'ink': 4, 'underline': 5, 'text': 6}


def _sql_date(v: str) -> str:
    return (v or '2026-01-01T00:00:00Z').replace('T', ' ').rstrip('Z')


def write_database(zotero_dir: Path, server: FakeServer) -> dict:
    """Rewrites the personal library of `zotero.sqlite` from the server state, as a finished synchronization
    leaves it. Items, collections and saved searches keep their local identifier. Imported files whose name changed
    on the server (step 8) are renamed on the disk, as Zotero does when it syncs. Returns what changed."""
    from conftest import FakeZotero
    from zot_clean.reader import date_multipart
    db = sqlite3.connect(zotero_dir / 'zotero.sqlite')
    try:
        line = db.execute('select version from libraries where libraryID = 1').fetchone()
        before = int(line[0]) if line else 0
        ids = {'items': dict(db.execute('select key, itemID from items')),
               'collections': dict(db.execute('select key, collectionID from collections')),
               'searches': dict(db.execute('select key, savedSearchID from savedSearches'))}
        local_names = {k: p.removeprefix('storage:') for k, p in db.execute(
            "select i.key, a.path from itemAttachments a join items i using(itemID) where a.path like 'storage:%'")}
        for table in LIBRARY_TABLES:
            db.execute(f'delete from {table}')
        z = FakeZotero.__new__(FakeZotero)  # its helpers for fields and tags, on this database
        z.db, z.folder, z._ids = db, zotero_dir, itertools.count(1)
        type_ids = dict(db.execute('select typeName, itemTypeID from itemTypes'))
        known = {name for (name,) in db.execute('select fieldName from fields')}
        roles = dict(db.execute('select creatorType, creatorTypeID from creatorTypes'))
        dates = {'date', 'filingDate'} | {name for (name,) in db.execute(
            "select f.fieldName from baseFieldMappings m join fields f on f.fieldID = m.fieldID "
            "join fields b on b.fieldID = m.baseFieldID where b.fieldName = 'date'")}

        def ident(kind: str, key: str) -> int:
            table = ids[kind]
            if key not in table:
                table[key] = max(table.values(), default=0) + 1
            return table[key]

        cols = sorted(server.collections.values(), key=lambda c: (c['version'], c['key']))
        for c in cols:
            ident('collections', c['key'])
        for c in cols:
            cid = ids['collections'][c['key']]
            parent = ids['collections'].get(c.get('parentCollection') or '')
            db.execute('insert into collections (collectionID, collectionName, parentCollectionID, libraryID, key, '
                       'version, synced) values (?, ?, ?, 1, ?, ?, 1)', (cid, c['name'], parent, c['key'], c['version']))
            if c.get('deleted'):
                db.execute('insert into deletedCollections (collectionID) values (?)', (cid,))

        items = sorted(server.all_items.values(), key=lambda d: (d.get('dateAdded', ''), d['key']))
        for d in items:
            ident('items', d['key'])
        creators: dict[tuple, int] = {}
        for d in items:
            iid = ids['items'][d['key']]
            db.execute('insert into items (itemID, itemTypeID, dateAdded, dateModified, clientDateModified, libraryID, '
                       'key, version, synced) values (?, ?, ?, ?, ?, 1, ?, ?, 1)',
                       (iid, type_ids[d['itemType']], _sql_date(d.get('dateAdded')),
                        _sql_date(d.get('dateModified') or d.get('dateAdded')),
                        _sql_date(d.get('dateModified') or d.get('dateAdded')), d['key'], d['version']))
            z._fields(iid, {k: date_multipart(str(v)) if k in dates else str(v) for k, v in d.items()
                            if k in known and k not in NOT_FIELDS and v not in ('', None)})
            for i, c in enumerate(d.get('creators') or []):
                person = (c.get('lastName', c.get('name', '')), c.get('firstName', ''), 1 if 'name' in c else 0)
                if person not in creators:
                    creators[person] = len(creators) + 1
                    db.execute('insert into creators (creatorID, lastName, firstName, fieldMode) values (?, ?, ?, ?)',
                               (creators[person], *person))
                db.execute('insert into itemCreators (itemID, creatorID, creatorTypeID, orderIndex) values (?, ?, ?, ?)',
                           (iid, creators[person], roles.get(c.get('creatorType', 'author'), roles['author']), i))
            z.tags(iid, [(t['tag'], int(t.get('type', 0))) for t in d.get('tags') or []])
            for ck in d.get('collections') or []:
                if ck in ids['collections']:
                    db.execute('insert or ignore into collectionItems (collectionID, itemID) values (?, ?)',
                               (ids['collections'][ck], iid))
            if d.get('deleted'):
                db.execute('insert into deletedItems (itemID) values (?)', (iid,))
            parent = ids['items'].get(d.get('parentItem') or '')
            if d['itemType'] == 'attachment':
                mode = LINK_MODES.get(d.get('linkMode', ''), 0)
                path = f"storage:{d['filename']}" if mode in (0, 1) and d.get('filename') else d.get('path') or ''
                db.execute('insert into itemAttachments (itemID, parentItemID, linkMode, contentType, path) '
                           'values (?, ?, ?, ?, ?)', (iid, parent, mode, d.get('contentType') or '', path))
                if d.get('note'):
                    db.execute('insert into itemNotes (itemID, parentItemID, note, title) values (?, null, ?, ?)',
                               (iid, f'<div class="zotero-note znv1">{d["note"]}</div>', ''))
            elif d['itemType'] == 'note':
                db.execute('insert into itemNotes (itemID, parentItemID, note, title) values (?, ?, ?, ?)',
                           (iid, parent, f'<div class="zotero-note znv1">{d.get("note", "")}</div>',
                            re.sub(r'<[^>]+>', ' ', d.get('note', '')).strip()[:80]))
            elif d['itemType'] == 'annotation':
                db.execute('insert into itemAnnotations (itemID, parentItemID, type, text, comment, color, pageLabel, '
                           'sortIndex, position, isExternal) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)',
                           (iid, parent or 0, ANNOTATION_TYPES.get(d.get('annotationType', ''), 1),
                            d.get('annotationText', ''), d.get('annotationComment', ''), d.get('annotationColor', ''),
                            d.get('annotationPageLabel', ''), d.get('annotationSortIndex', '0'),
                            d.get('annotationPosition', '{}')))

        for s in sorted(server.searches.values(), key=lambda s: s['key']):
            sid = ident('searches', s['key'])
            db.execute('insert into savedSearches (savedSearchID, savedSearchName, libraryID, key, version, synced) '
                       'values (?, ?, 1, ?, ?, 1)', (sid, s['name'], s['key'], s['version']))
            for i, c in enumerate(s.get('conditions') or []):
                db.execute('insert into savedSearchConditions (savedSearchID, searchConditionID, condition, operator, '
                           'value) values (?, ?, ?, ?, ?)', (sid, i, c.get('condition', ''), c.get('operator', ''),
                                                             c.get('value', '')))
            if s.get('deleted'):
                db.execute('insert into deletedSearches (savedSearchID) values (?)', (sid,))
        for name, d in server.settings.items():
            db.execute('insert into syncedSettings (setting, libraryID, value, version, synced) values (?, 1, ?, ?, 1)',
                       (name, json.dumps(d['value'], ensure_ascii=False), d['version']))
        db.execute("insert or replace into libraries (libraryID, type, editable, filesEditable, version) "
                   "values (1, 'user', 1, 1, ?)", (server.version,))
        db.execute("delete from settings where setting = 'account'")
        db.executemany("insert into settings (setting, key, value) values ('account', ?, ?)",
                       [('userID', server.user), ('username', 'pilote')])
        db.commit()
    finally:
        db.close()

    renamed = []
    for d in server.all_items.values():
        old, new = local_names.get(d['key']), d.get('filename')
        if d.get('itemType') == 'attachment' and old and new and old != new:
            folder = zotero_dir / 'storage' / d['key']
            if (folder / old).is_file() and not (folder / new).exists():
                (folder / old).rename(folder / new)
                renamed.append(d['key'])
    received = sum(1 for store in (server.all_items, server.collections, server.searches, server.settings)
                   for o in store.values() if o.get('version', 0) > before)
    return {'before': before, 'after': server.version, 'received': received, 'renamed': renamed}


def sync(bench: Path, quiet: bool = False) -> int:
    bench = bench.resolve()
    state = load_state(bench)
    if not state['zotero_open']:
        say('Zotero est fermé : impossible de synchroniser. Ouvrir Zotero (`banc.py zotero open`), qui synchronise '
            'à son ouverture.')
        return 1
    server = load_server(bench)
    res = write_database(bench / ZOTERO, server)
    res['downloaded'] = download(bench, server)
    if not quiet:
        if res['before'] == res['after']:
            say(f"Synchronisation : rien de nouveau (version {res['after']}).")
        else:
            say(f"Synchronisation : {res['received']} objet(s) reçu(s), version locale {res['before']} -> "
                f"{res['after']}.")
        if res['renamed']:
            say(f"  {len(res['renamed'])} fichier(s) renommé(s) sur le disque : {', '.join(res['renamed'])}")
        if res['downloaded']:
            say(f"  {len(res['downloaded'])} fichier(s) téléchargé(s) : {', '.join(res['downloaded'])}")
    return 0


def download(bench: Path, server: FakeServer) -> list[str]:
    """Files stored on zotero.org and missing from the disk, downloaded at sync time when Zotero is set so
    (Settings › Sync, « Download files » at sync time). By default, as needed: they stay missing."""
    mode = read_prefs(_profile(bench)).get('extensions.zotero.sync.storage.downloadMode.personal', 'on-sync')
    if mode != 'on-sync':
        return []
    res = []
    for d in server.all_items.values():
        source = bench / ONLINE_FILES / d['key']
        if d.get('itemType') != 'attachment' or d.get('deleted') or not d.get('filename') or d['key'] not in server.files:
            continue
        target = bench / ZOTERO / 'storage' / d['key'] / d['filename']
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            res.append(d['key'])
    return res


# --- Zotero profile ---------------------------------------------------------------------------------------------


def write_profile(bench: Path, language: str) -> None:
    root = bench / PROFILES
    profile = root / 'Profiles' / 'pilote.default'
    profile.mkdir(parents=True, exist_ok=True)
    (root / 'profiles.ini').write_text('[General]\nStartWithLastProfile=1\n\n[Profile0]\nName=default\nIsRelative=1\n'
                                       'Path=Profiles/pilote.default\nDefault=1\n', encoding='utf-8')
    prefs = {'extensions.zotero.dataDir': str(bench / ZOTERO), 'extensions.zotero.useDataDir': True,
             'intl.locale.requested': 'fr-FR' if language == 'fr' else 'en-US',
             'extensions.zotero.sync.storage.downloadMode.personal': 'on-demand'}
    write_prefs(profile, prefs)
    (profile / 'extensions.json').write_text(json.dumps({'addons': [
        {'id': 'better-bibtex@iris-advies.com', 'version': BBT_VERSION, 'active': True, 'type': 'extension'}]},
        indent=1), encoding='utf-8')


def _profile(bench: Path) -> Path:
    return bench / PROFILES / 'Profiles' / 'pilote.default'


def read_prefs(profile: Path) -> dict:
    from zot_clean import bbt
    return bbt.read_prefs(profile)


def write_prefs(profile: Path, prefs: dict) -> None:
    lines = ['// Mozilla User Preferences (pilot bench)']
    lines += [f'user_pref({json.dumps(k)}, {json.dumps(v, ensure_ascii=False)});' for k, v in prefs.items()]
    (profile / 'prefs.js').write_text('\n'.join(lines) + '\n', encoding='utf-8')


# --- Creation ---------------------------------------------------------------------------------------------------


def write_shims(bench: Path) -> None:
    b = bench / BIN
    b.mkdir(exist_ok=True)
    py, script = sys.executable, str(Path(__file__).resolve())
    sh = b / 'zc'
    sh.write_text('#!/bin/sh\n# zc of the pilot bench: the real zot-clean, on a synthetic library, without network.\n'
                  f'exec {shlex.quote(py)} {shlex.quote(script)} run {shlex.quote(str(bench))} -- "$@"\n',
                  encoding='utf-8')
    sh.chmod(0o755)
    (b / 'zc.cmd').write_text(f'@echo off\r\n"{py}" "{script}" run "{bench}" -- %*\r\n', encoding='utf-8')
    # The user's gestures, bound to this bench, outside the PATH given to the agent: `gestes/banc sync`,
    # `gestes/banc zotero close`, `gestes/banc status`…
    g = bench / GESTURES
    g.mkdir(exist_ok=True)
    q = f'{shlex.quote(py)} {shlex.quote(script)}'
    sh = g / 'banc'
    sh.write_text('#!/bin/sh\n# Gestures of the user of this pilot bench (sync, zotero open|close|pref, edit, '
                  'new-collection, bbt-fill, add-items, status).\n'
                  'case "$1" in\n'
                  f'  zotero) a=$2; shift 2; exec {q} zotero "$a" {shlex.quote(str(bench))} "$@" ;;\n'
                  f'  *) c=$1; shift; exec {q} "$c" {shlex.quote(str(bench))} "$@" ;;\n'
                  'esac\n', encoding='utf-8')
    sh.chmod(0o755)


def type_fields(db: sqlite3.Connection) -> dict[str, list[str]]:
    res: dict[str, list[str]] = {}
    for t, f in db.execute('select t.typeName, f.fieldName from itemTypeFields i join itemTypes t using(itemTypeID) '
                           'join fields f using(fieldID) order by t.typeName, i.orderIndex'):
        res.setdefault(t, []).append(f)
    return res


def create(bench: Path, language: str, seed: int) -> int:
    import monde
    bench = bench.resolve()
    if bench.exists() and any(bench.iterdir()):
        raise SystemExit(f'{bench} exists and is not empty.')
    zotero_dir = bench / ZOTERO
    (zotero_dir / 'storage').mkdir(parents=True)
    db = sqlite3.connect(zotero_dir / 'zotero.sqlite')
    db.executescript('begin;' + SCHEMA.read_text(encoding='utf-8') + 'commit;')
    fields = type_fields(db)
    db.close()

    world = monde.generate(language, seed, fields)
    server = BenchServer(monde.USER, *schema_of(zotero_dir))
    server.version = world.version
    server.all_items, server.collections = world.items, world.collections
    for d in world.items.values():  # the generated library must be one zotero.org would accept
        if refusal := server._refusal({'key': d['key']}, server.all_items):
            raise RuntimeError(f"{d['key']}: {refusal}")
    server.settings, server.searches, server.files = world.settings, world.searches, set(world.files)
    server._n = itertools.count(KEY_START)
    save_server(bench, server)
    _write_json(bench / SOURCES, world.sources)
    for key, (name, content) in world.disk.items():
        if content is not None:
            (zotero_dir / 'storage' / key).mkdir()
            (zotero_dir / 'storage' / key / name).write_bytes(content)
    for key, content in world.online_only.items():
        (bench / ONLINE_FILES).mkdir(exist_ok=True)
        (bench / ONLINE_FILES / key).write_bytes(content)
    write_profile(bench, language)
    save_state(bench, {'language': language, 'seed': seed, 'zotero_open': True, 'api_key': API_KEY,
                       'created': datetime.now().isoformat(timespec='seconds'), 'added': 0})
    write_database(zotero_dir, server)
    write_shims(bench)

    work = bench / WORK
    work.mkdir()
    (work / '.env').write_text(f'ZOTERO_API_KEY={API_KEY}\nZOTERO_USER_ID={monde.USER}\n'
                               'OPENALEX_API_KEY=BANC-OPENALEX-FACTICE\n', encoding='utf-8')
    (work / '.env').chmod(0o600)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = run(bench, ['init', str(work), '--library-language', language, '--zotero-dir', str(zotero_dir)],
                   stdin='')
    if code:
        say(output.getvalue())
        raise SystemExit(f'zc init failed ({code}).')
    say(f'Banc créé : {bench}')
    status(bench)
    say(f'\nDossier de travail : {work}\nCommande zc : {bench / BIN / "zc"} (mettre {bench / BIN} en tête du PATH).')
    return 0


# --- User gestures besides the synchronization ------------------------------------------------------------------


def zotero(bench: Path, action: str, setting: str = '') -> int:
    bench = bench.resolve()
    state = load_state(bench)
    if action == 'autosync':
        if setting not in ('on', 'off'):
            raise SystemExit('usage: banc.py zotero autosync <bench> on|off')
        state['autosync'] = setting == 'on'
        save_state(bench, state)
        say('Zotero synchronise désormais après chaque commande zc (Zotero ouvert).' if state['autosync'] else
            'Zotero ne synchronise plus que sur demande (`sync`) et à son ouverture.')
        return 0
    if action == 'open':
        state['zotero_open'] = True
        save_state(bench, state)
        say('Zotero est ouvert.')
        return sync(bench)  # Zotero syncs when it starts
    state['zotero_open'] = False
    save_state(bench, state)
    say('Zotero est fermé.')
    return 0


def _require_open(bench: Path) -> None:
    if not load_state(bench)['zotero_open']:
        raise SystemExit('Zotero est fermé : ce geste se fait dans Zotero. Ouvrir Zotero (`banc.py zotero open`).')


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def edit(bench: Path, key: str, assignments: list[str]) -> int:
    """The user changes an item or a collection in Zotero, which syncs it."""
    bench = bench.resolve()
    _require_open(bench)
    server = load_server(bench)
    fields = {}
    for a in assignments:
        name, sep, value = a.partition('=')
        if not sep:
            raise SystemExit(f'{a}: expected field=value')
        fields[name] = _value(value)
    if key in server.all_items:
        server.modify(key, **fields)
    elif key in server.collections:
        server.version += 1
        server.collections[key].update(fields, version=server.version)
    else:
        raise SystemExit(f'{key}: no such item or collection.')
    save_server(bench, server)
    say(f'{key} modifié dans Zotero.')
    return sync(bench)


def new_collection(bench: Path, name: str, parent: str | None) -> int:
    """The user creates a collection in Zotero (the Inbox, for example), which syncs it."""
    import monde
    bench = bench.resolve()
    _require_open(bench)
    server = load_server(bench)
    if parent and parent not in server.collections:
        raise SystemExit(f'{parent}: no such collection.')
    w = monde.World(load_state(bench)['language'], len(server.collections), {})
    w.used_keys = set(server.all_items) | set(server.collections)
    key = server.collection(name, parent, key=w.key())
    save_server(bench, server)
    say(f'Collection « {name} » créée dans Zotero ({key}).')
    return sync(bench)


def bbt_fill(bench: Path) -> int:
    """Better BibTeX fills the empty citation keys (auth.lower + shorttitle(3,3) + year), then Zotero syncs."""
    import monde
    bench = bench.resolve()
    _require_open(bench)
    server = load_server(bench)
    taken = {d.get('citationKey', '').lower() for d in server.all_items.values() if d.get('citationKey')}
    n = 0
    for d in sorted(server.all_items.values(), key=lambda d: d.get('dateAdded', '')):
        if d['itemType'] in ('attachment', 'note', 'annotation') or d.get('deleted') or d.get('citationKey'):
            continue
        if 'citationKey' not in d:
            continue
        if pinned := re.search(r'^\s*citation\s*key\s*:\s*(\S+)\s*$', d.get('extra', ''), re.I | re.M):
            server.modify(d['key'], citationKey=pinned.group(1))
            taken.add(pinned.group(1).lower())
            n += 1
            continue
        year = re.search(r'\d{4}', d.get('date', ''))
        w = monde.Work(d['itemType'], d.get('title', ''), [(c.get('lastName', c.get('name', '')), '')
                                                         for c in d.get('creators', [])
                                                         if c.get('creatorType') == 'author'] or
                       [(c.get('lastName', c.get('name', '')), '') for c in d.get('creators', [])],
                       int(year.group()) if year else 0, '')
        base = monde.citation_key(w, year.group() if year else '')
        key, suffix = base, iter('abcdefghijklmnopqrstuvwxyz')
        while key.lower() in taken:
            key = base + next(suffix)
        taken.add(key.lower())
        server.modify(d['key'], citationKey=key)
        n += 1
    save_server(bench, server)
    say(f'Better BibTeX : {n} clé(s) de citation remplie(s).')
    return sync(bench)


def pref(bench: Path, name: str, value: str) -> int:
    """A setting changed in Zotero's settings (prefs.js of the profile)."""
    bench = bench.resolve()
    profile = _profile(bench)
    prefs = read_prefs(profile)
    prefs[name] = _value(value)
    write_prefs(profile, prefs)
    say(f'Réglage de Zotero {name} = {prefs[name]!r}.')
    return 0


def add_items(bench: Path, n: int) -> int:
    """New references saved with Zotero's connector, into the Inbox if it exists (otherwise outside any collection),
    with the automatic tags of the database and a PDF named by Zotero. Zotero syncs them."""
    import random
    import monde
    bench = bench.resolve()
    _require_open(bench)
    state = load_state(bench)
    server = load_server(bench)
    language = state['language']
    rng = random.Random(state['seed'] * 1000 + state['added'])
    fields = type_fields(sqlite3.connect(bench / ZOTERO / 'zotero.sqlite'))
    w = monde.World(language, state['seed'] * 1000 + state['added'], fields)
    w.used_keys = set(server.all_items) | set(server.collections)
    w.version = server.version
    w.titles = {d.get('title', '') for d in server.all_items.values()}
    inbox = next((k for k, c in server.collections.items() if c['name'] == 'Inbox' and not c.get('parentCollection')
                  and not c.get('deleted')), None)
    sources = json.loads((bench / SOURCES).read_text(encoding='utf-8'))
    w.sources = sources
    automatic = read_prefs(_profile(bench)).get('extensions.zotero.automaticTags', True) is not False
    for _ in range(n):
        theme = rng.choice(monde.THEMES[language])
        t, f = w.title(theme)
        work = monde.Work('journalArticle', t, w.people(), rng.randint(2024, 2026), theme['id'],
                          monde.ABSTRACT[language].format(**f), theme['journals'][0][0], theme['journals'][0][1],
                          str(rng.randint(40, 70)), str(rng.randint(1, 4)), f'{rng.randint(1, 90)}-{rng.randint(91, 140)}')
        work.doi = w.doi(theme, work.year)
        w.publish(work)
        k = w.item('journalArticle', monde.item_fields(work, language) | {'abstractNote': ''}, monde.creators_of(work),
                   [(a, 1) for a in theme['auto'][:3]] if automatic else [], [inbox] if inbox else [], recent=True)
        w.attachment(k, monde.template_name(work, language), monde.pdf_for(work, language), title='Full Text PDF')
    for key, d in w.items.items():
        server.all_items[key] = d
    server.files |= w.files
    server.version = w.version
    for key, (name, content) in w.disk.items():
        (bench / ZOTERO / 'storage' / key).mkdir(parents=True, exist_ok=True)
        (bench / ZOTERO / 'storage' / key / name).write_bytes(content)
    save_server(bench, server)
    _write_json(bench / SOURCES, w.sources)
    state['added'] += 1
    save_state(bench, state)
    where = 'Inbox' if inbox else ('hors de toute collection' if language == 'fr' else 'outside any collection')
    say(f'{n} référence(s) enregistrée(s) avec le connecteur ({where}).')
    return sync(bench)


# --- Status -----------------------------------------------------------------------------------------------------


def status(bench: Path) -> int:
    bench = bench.resolve()
    state = load_state(bench)
    server = load_server(bench)
    live = [d for d in server.all_items.values() if not d.get('deleted')]
    regular = [d for d in live if d['itemType'] not in ('attachment', 'note', 'annotation')]
    count = {t: sum(1 for d in live if d['itemType'] == t) for t in ('attachment', 'note', 'annotation')}
    tags = {t['tag'] for d in live for t in d.get('tags', [])}
    cols = [c for c in server.collections.values() if not c.get('deleted')]
    db = sqlite3.connect(bench / ZOTERO / 'zotero.sqlite')
    try:
        local = db.execute('select version from libraries where libraryID = 1').fetchone()[0]
    finally:
        db.close()
    say(f"Bibliothèque ({state['language']}, graine {state['seed']}) : {len(regular)} fiches, "
        f"{count['attachment']} pièces jointes, {count['note']} notes, {count['annotation']} annotations, "
        f"{len(cols)} collections, {len(tags)} tags, "
        f"{sum(1 for d in server.all_items.values() if d.get('deleted'))} élément(s) dans la corbeille.")
    say(f"Zotero : {'ouvert' if state['zotero_open'] else 'fermé'}. Version sur zotero.org {server.version}, "
        f"dans zotero.sqlite {local}" + (' (à synchroniser).' if server.version > local else ' (à jour).'))
    backups = bench / f'{ZOTERO}-sauvegardes'
    n = len([d for d in backups.iterdir() if d.is_dir()]) if backups.is_dir() else 0
    plans = bench / WORK / 'plans'
    say(f"Sauvegardes : {n}. Plans : {len(list(plans.glob('*.json'))) if plans.is_dir() else 0}.")
    log = bench / NETWORK_LOG
    if log.is_file():
        say(f'Accès réseau bloqués : {len(log.read_text(encoding="utf-8").splitlines())} (voir {log}).')
    return 0


# --- Command line -----------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['run']:  # everything after `--` goes to zc as it is
        if len(argv) < 2:
            raise SystemExit('usage: banc.py run <bench> -- <zc arguments>')
        rest = argv[2:]
        return run(Path(argv[1]), rest[1:] if rest[:1] == ['--'] else rest)
    p = argparse.ArgumentParser(prog='banc.py', description='Pilot test bench (D237): the real zc on a synthetic '
                                                            'library, without Zotero, account or network.')
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('create', help='create a bench (library, fake zotero.org, profile, working folder)')
    c.add_argument('bench', type=Path)
    c.add_argument('--library-language', choices=('fr', 'en'), required=True)
    c.add_argument('--seed', type=int, default=1)
    sub.add_parser('run', help='run zc on the bench: banc.py run <bench> -- <zc arguments>')
    s = sub.add_parser('sync', help="play Zotero's synchronization (zotero.sqlite and file names catch up)")
    s.add_argument('bench', type=Path)
    z = sub.add_parser('zotero', help='open or close Zotero (opening syncs), or change one of its settings')
    z.add_argument('action', choices=('open', 'close', 'pref', 'autosync'))
    z.add_argument('bench', type=Path)
    z.add_argument('setting', nargs='*', help='for pref: name and value (JSON or text); for autosync: on or off')
    st = sub.add_parser('status', help='short summary of the bench')
    st.add_argument('bench', type=Path)
    e = sub.add_parser('edit', help='change an item or a collection in Zotero: KEY field=value… (value in JSON or text)')
    e.add_argument('bench', type=Path)
    e.add_argument('key')
    e.add_argument('assignments', nargs='+')
    n = sub.add_parser('new-collection', help='create a collection in Zotero (the Inbox, for example)')
    n.add_argument('bench', type=Path)
    n.add_argument('name')
    n.add_argument('--parent', help='key of the parent collection')
    b = sub.add_parser('bbt-fill', help='Better BibTeX fills the missing citation keys')
    b.add_argument('bench', type=Path)
    a = sub.add_parser('add-items', help='save new references with the connector (Inbox, or outside any collection)')
    a.add_argument('bench', type=Path)
    a.add_argument('-n', type=int, default=3)
    args = p.parse_args(argv)
    if args.command == 'create':
        return create(args.bench, args.library_language, args.seed)
    if args.command == 'sync':
        return sync(args.bench)
    if args.command == 'zotero':
        if args.action == 'pref':
            if len(args.setting) != 2:
                raise SystemExit('usage: banc.py zotero pref <bench> <name> <value>')
            return pref(args.bench, *args.setting)
        return zotero(args.bench, args.action, *args.setting[:1])
    if args.command == 'status':
        return status(args.bench)
    if args.command == 'edit':
        return edit(args.bench, args.key, args.assignments)
    if args.command == 'new-collection':
        return new_collection(args.bench, args.name, args.parent)
    if args.command == 'bbt-fill':
        return bbt_fill(args.bench)
    if args.command == 'add-items':
        return add_items(args.bench, args.n)
    return 1


if __name__ == '__main__':
    sys.exit(main())
