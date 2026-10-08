"""Synthetic Zotero library for the tests (D29).

`zotero` provides a fake Zotero folder (database created from the real schema,
`storage/` folder) and methods to add collections, items, attachments
and notes to it. No personal data.
"""

import itertools
import shutil
import sqlite3
from pathlib import Path

import pytest

SCHEMA = Path(__file__).parent / 'donnees' / 'schema_zotero.sql'


@pytest.fixture(autouse=True)
def no_time_machine(monkeypatch):
    """The tests never touch the machine's Time Machine settings (D159)."""
    from zot_clean import backup
    monkeypatch.setattr(backup, '_tmutil', lambda command: None)
ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


class FakeZotero:
    def __init__(self, folder: Path, template: Path):
        self.folder = folder
        folder.mkdir(parents=True)
        self.database = folder / 'zotero.sqlite'
        # Copy of an empty database built once per session: recreating the schema at each test costs
        # several seconds on Windows, which syncs the disk after each statement.
        shutil.copyfile(template, self.database)
        self.db = sqlite3.connect(self.database)
        self._ids = itertools.count(1)
        self.account(4242)  # that of the fake server, `FakeServer().user`

    def _key(self, n: int) -> str:
        key = ''
        for _ in range(8):
            n, r = divmod(n, len(ALPHABET))
            key = ALPHABET[r] + key
        return key

    def _type(self, name: str) -> int:
        return self.db.execute('select itemTypeID from itemTypes where typeName = ?', (name,)).fetchone()[0]

    def _item(self, type_: str, key: str | None = None, synced: bool = True, lib: int = 1,
                 date_added: str = '2026-01-01') -> tuple[int, str]:
        iid = next(self._ids)
        key = key or self._key(iid)
        self.db.execute('insert into items (itemID, itemTypeID, libraryID, key, synced, dateAdded) '
                        'values (?, ?, ?, ?, ?, ?)', (iid, self._type(type_), lib, key, int(synced), date_added))
        return iid, key

    def _fields(self, iid: int, fields: dict[str, str]) -> None:
        for name, value in fields.items():
            if value:
                fid = self.db.execute('select fieldID from fields where fieldName = ?', (name,)).fetchone()[0]
                # Each value is stored only once, shared between items.
                line = self.db.execute('select valueID from itemDataValues where value = ?', (value,)).fetchone()
                vid = line[0] if line else next(self._ids)
                if not line:
                    self.db.execute('insert into itemDataValues (valueID, value) values (?, ?)', (vid, value))
                self.db.execute('insert into itemData values (?, ?, ?)', (iid, fid, vid))

    def collection(self, name: str, parent: int | None = None, key: str | None = None) -> int:
        cid = next(self._ids)
        self.db.execute('insert into collections (collectionID, collectionName, parentCollectionID, libraryID, key, synced) '
                        'values (?, ?, ?, 1, ?, 1)', (cid, name, parent, key or self._key(cid)))
        return cid

    def item(self, title: str, type_: str = 'journalArticle', authors: tuple[str, ...] = ('Durand',),
              date: str = '2020', collections: tuple[int, ...] = (), tags: tuple[tuple[str, int] | str, ...] = (),
              editors: tuple[str, ...] = (), creators: tuple[tuple[str, str, str], ...] = (), **fields) -> int:
        """`date` is stored as is: a lone year becomes a multipart date, as in Zotero.
        `creators`: (last name, first name, role) added after the editors and the authors."""
        iid, _ = self._item(type_, fields.pop('key', None), fields.pop('synced', True), fields.pop('lib', 1),
                               fields.pop('date_added', '2026-01-01'))
        if date and len(date) == 4 and date.isdigit():
            date = f'{date}-00-00 {date}'
        self._fields(iid, dict(fields, title=title, date=date))
        # Book editors entered before the authors, as Zotero often does for a chapter.
        listing = [(n, 'A.', 'editor') for n in editors] + [(n, 'A.', 'author') for n in authors] + list(creators)
        for i, (name, first_name, role) in enumerate(listing):
            cid = next(self._ids)
            rid = self.db.execute('select creatorTypeID from creatorTypes where creatorType = ?', (role,)).fetchone()[0]
            self.db.execute('insert into creators (creatorID, firstName, lastName) values (?, ?, ?)', (cid, first_name, name))
            self.db.execute('insert into itemCreators (itemID, creatorID, creatorTypeID, orderIndex) values (?, ?, ?, ?)',
                            (iid, cid, rid, i))
        for col in collections:
            self.db.execute('insert into collectionItems (collectionID, itemID) values (?, ?)', (col, iid))
        self.tags(iid, tags)
        return iid

    def tags(self, iid: int, tags) -> None:
        """Sets tags, each a name (manual) or a pair (name, type), 1 for automatic."""
        for tag in tags:
            name, typ = (tag, 0) if isinstance(tag, str) else tag
            line = self.db.execute('select tagID from tags where name = ?', (name,)).fetchone()
            tid = line[0] if line else next(self._ids)
            if not line:
                self.db.execute('insert into tags (tagID, name) values (?, ?)', (tid, name))
            self.db.execute('insert into itemTags values (?, ?, ?)', (iid, tid, typ))

    def color(self, name: str, color: str = '#990000') -> None:
        """Coloured tag, appended to the synchronised `tagColors` setting."""
        import json
        line = self.db.execute("select value from syncedSettings where setting = 'tagColors' and libraryID = 1").fetchone()
        value = json.loads(line[0]) if line else []
        value.append({'name': name, 'color': color})
        self.setting('tagColors', value)

    def search(self, name: str, tag: str, operator: str = 'is') -> int:
        """Saved search with a condition on a tag."""
        sid = next(self._ids)
        self.db.execute('insert into savedSearches (savedSearchID, savedSearchName, libraryID, key) values (?, ?, 1, ?)',
                        (sid, name, self._key(sid)))
        self.db.execute('insert into savedSearchConditions (savedSearchID, searchConditionID, condition, operator, value) '
                        "values (?, 0, 'tag', ?, ?)", (sid, operator, tag))
        return sid

    def pdf(self, parent: int, name: str, content: bytes | None = b'%PDF-1.4 factice', key: str | None = None,
            date_added: str = '2026-01-01', content_type: str = 'application/pdf', mode: int = 0, url: str = '',
            title: str = '', others: tuple[str, ...] = (), tags=(), note: str = '') -> int:
        """Attachment imported (`mode` 0), imported from a URL (1), linked (2) or link (3). `content=None`:
        file absent from the disk. `others`: other files placed in its `storage/<KEY>/` folder. `note`: the
        attachment's own note, which Zotero stores in `itemNotes` without a parent, wrapped like any note."""
        iid, key = self._item('attachment', key, date_added=date_added)
        self.tags(iid, tags)
        self.db.execute('insert into itemNotes (itemID, parentItemID, note) values (?, null, ?)',
                        (iid, f'<div class="zotero-note znv1">{note}</div>'))
        path = f'/Documents/{name}' if mode == 2 else ('' if mode == 3 else f'storage:{name}')
        self.db.execute('insert into itemAttachments (itemID, parentItemID, linkMode, contentType, path) '
                        'values (?, ?, ?, ?, ?)', (iid, parent, mode, content_type, path))
        self._fields(iid, {'url': url, 'title': title})
        if mode in (0, 1) and (content is not None or others):
            (self.folder / 'storage' / key).mkdir(parents=True)
            if content is not None:
                (self.folder / 'storage' / key / name).write_bytes(content)
            for other in others:
                (self.folder / 'storage' / key / other).write_bytes(b'autre')
        return iid

    def setting(self, name: str, value) -> None:
        """Synchronised library setting (`syncedSettings`), stored as JSON as Zotero does."""
        import json
        self.db.execute('insert or replace into syncedSettings (setting, libraryID, value, version, synced) '
                        'values (?, 1, ?, 0, 1)', (name, json.dumps(value)))

    def annotation(self, attachment: int, tags=(), key: str | None = None) -> int:
        iid, _ = self._item('annotation', key)
        self.tags(iid, tags)
        self.db.execute('insert into itemAnnotations (itemID, parentItemID, type, sortIndex, position, isExternal) '
                        "values (?, ?, 1, '0', '{}', 0)", (iid, attachment))
        return iid

    def note(self, parent: int | None = None, tags=(), key: str | None = None) -> int:
        iid, _ = self._item('note', key)
        self.tags(iid, tags)
        self.db.execute('insert into itemNotes (itemID, parentItemID, note) values (?, ?, ?)', (iid, parent, 'Note'))
        return iid

    def trash(self, iid: int):
        self.db.execute('insert into deletedItems (itemID) values (?)', (iid,))

    def sync(self, version: int) -> None:
        """Library version received from the server, as after a synchronisation."""
        self.db.execute('insert or replace into libraries (libraryID, type, editable, filesEditable, version) '
                        "values (1, 'user', 1, 1, ?)", (version,))

    def account(self, user: int | None, name: str = 'durand') -> None:
        """zotero.org account synchronised by the database, as Zotero keeps it at the first synchronisation
        (`settings`, `setting = 'account'`). None: database never synchronised."""
        self.db.execute("delete from settings where setting = 'account' and key in ('userID', 'username')")
        if user is not None:
            self.db.executemany("insert into settings values ('account', ?, ?)",
                                [('userID', user), ('username', name)])

    def save(self) -> Path:
        self.db.commit()
        return self.database


@pytest.fixture(scope='session')
def empty_database(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp('modele') / 'zotero.sqlite'
    db = sqlite3.connect(path)
    db.executescript('begin;' + SCHEMA.read_text(encoding='utf-8') + 'commit;')
    db.close()
    return path


@pytest.fixture
def zotero(tmp_path, empty_database):
    z = FakeZotero(tmp_path / 'Zotero', empty_database)
    yield z
    z.db.close()


@pytest.fixture(autouse=True)
def no_real_profile(monkeypatch):
    """No test reads the machine's Zotero profile. Better BibTeX is then looked for in the data folder
    (D145 fallback), except when a test provides its own profiles."""
    from zot_clean import bbt
    monkeypatch.setattr(bbt, 'profile_folders', lambda: [])
