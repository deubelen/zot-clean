"""Reading of the library from a temporary copy of `zotero.sqlite` (D12).

The only module that knows Zotero's internal schema. The copy (database and `-wal`,
never the attached files) is made in a temporary folder, deleted after
reading. Before any query, we check that the tables and columns used
exist, to stop cleanly if a version of Zotero has changed the schema.
If Zotero writes to the database during the copy, the copy is redone (D185).
In the `share()` block, which the command line opens for each command,
reads share a single copy as long as Zotero does not write to the database.
Items and collections in the trash are ignored, together with what Zotero hides
with them, namely the attachments and notes of a record, the annotations of an
attachment and the subcollections of a collection (D186).
"""

import json
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from zot_clean.lang import L

PERSONAL_LIBRARY = 1
COPIES = 3  # copy attempts when Zotero writes to the database while it is being copied (D185)
PAUSE = 1.0

# Tables and columns read here. Any absence stops the read.
SCHEMA = {
    'items': {'itemID', 'itemTypeID', 'libraryID', 'key', 'synced', 'dateAdded', 'version'},
    'itemTypes': {'itemTypeID', 'typeName'},
    'fields': {'fieldID', 'fieldName'},
    'itemData': {'itemID', 'fieldID', 'valueID'},
    'itemDataValues': {'valueID', 'value'},
    'creators': {'creatorID', 'firstName', 'lastName'},
    'itemCreators': {'itemID', 'creatorID', 'creatorTypeID', 'orderIndex'},
    'collections': {'collectionID', 'collectionName', 'parentCollectionID', 'libraryID', 'key', 'synced'},
    'collectionItems': {'collectionID', 'itemID'},
    'tags': {'tagID', 'name'},
    'itemTags': {'itemID', 'tagID', 'type'},
    'itemAttachments': {'itemID', 'parentItemID', 'linkMode', 'contentType', 'path'},
    'itemNotes': {'itemID', 'parentItemID', 'note'},
    'deletedItems': {'itemID'},
    'deletedCollections': {'collectionID'},
    'version': {'schema', 'version'},
    'libraries': {'libraryID', 'version'},
    'itemAnnotations': {'itemID', 'parentItemID'},
    'itemTypeFields': {'itemTypeID', 'fieldID'},
    'baseFieldMappings': {'itemTypeID', 'baseFieldID', 'fieldID'},
    'itemTypeCreatorTypes': {'itemTypeID', 'creatorTypeID', 'primaryField'},
    'creatorTypes': {'creatorTypeID', 'creatorType'},
    'syncedSettings': {'setting', 'libraryID', 'value'},
    'savedSearches': {'savedSearchID', 'savedSearchName', 'libraryID', 'key'},
    'savedSearchConditions': {'savedSearchID', 'condition', 'operator', 'value'},
    'deletedSearches': {'savedSearchID'},
    'settings': {'setting', 'key', 'value'},
}

NON_ITEM_TYPES = {'note', 'attachment', 'annotation'}
MODE_IMPORTED, MODE_IMPORTED_URL, MODE_LINKED, MODE_LINK = 0, 1, 2, 3
VALID_KEY = re.compile(r'^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$')
NON_BASE_DATES = {'date', 'filingDate'}  # date fields stored in the database in the form « 2020-00-00 2020 »


class UnknownSchema(Exception):
    pass


@dataclass
class Account:
    """zotero.org account that the local database syncs with. Zotero remembers it at the first sync
    (`Zotero.Users.setCurrentUserID`, table `settings`, `setting = 'account'`), keeps it even if the account is
    unlinked, and then refuses to sync another one without emptying the database. `id` None: never synced."""
    id: int | None = None
    name: str = ''


@dataclass
class Collection:
    id: int
    key: str
    name: str
    parent: int | None
    synced: bool


@dataclass
class Attachment:
    id: int
    key: str
    parent: int | None
    mode: int
    content_type: str
    path: str
    file: Path | None  # location on disk, None if it cannot be resolved
    version: int = 0  # item version received from the server, 0 if it was never synced
    note: bool = False  # the attachment has a note of its own, stored by Zotero in `itemNotes` (D206)


@dataclass
class Item:
    id: int
    key: str
    type: str
    date_added: str
    synced: bool
    fields: dict[str, str] = field(default_factory=dict)
    creators: list[tuple[str, str]] = field(default_factory=list)  # (last name, first name)
    roles: list[str] = field(default_factory=list)  # role of each creator (author, editor, translator…)
    collections: set[int] = field(default_factory=set)
    tags: list[tuple[str, int]] = field(default_factory=list)  # (name, type), type 1 = automatic

    @property
    def title(self) -> str:
        return self.fields.get('title', '')

    @property
    def author(self) -> str:
        """Name of the first author. Failing that, that of the first creator (editor of a collective book, for
        example). The editor of a book is often entered before the author of the chapter."""
        for (name, _), role in zip(self.creators, self.roles):
            if role == 'author':
                return name
        return self.creators[0][0] if self.creators else ''

    @property
    def is_item(self) -> bool:
        return self.type not in NON_ITEM_TYPES


@dataclass
class Library:
    schema_version: int
    all_items: dict[int, Item]
    collections: dict[int, Collection]
    attachments: dict[int, Attachment]
    notes: dict[int, int | None]  # note -> parent
    invalid_keys: list[str]  # trash included, they block syncing
    annotations: dict[int, int] = field(default_factory=dict)  # attachment -> number of annotations made in Zotero
    version: int = 0  # latest library version received from the server by sync
    # Synced settings of the library (renaming template `attachmentRenameTemplate`, D148), decoded.
    settings: dict[str, object] = field(default_factory=dict)
    # Main role of each record type (author, artist…), which makes Zotero's first creator.
    main_creator: dict[str, str] = field(default_factory=dict)
    # For each type, the specific field of each base field (case: title -> caseName), like Zotero's getField.
    base_fields: dict[str, dict[str, str]] = field(default_factory=dict)
    annotation_of: dict[int, int] = field(default_factory=dict)  # annotation -> attachment
    colors: list[tuple[str, str]] = field(default_factory=list)  # colored tags (name, color), tag selector order
    # Conditions on a tag in saved searches: (name of the search, operator, value).
    tag_searches: list[tuple[str, str, str]] = field(default_factory=list)
    searches: dict[str, str] = field(default_factory=dict)  # key -> name of the saved searches
    trash_tags: dict[str, int] = field(default_factory=dict)  # tag -> trashed items that carry it
    # Fields known to this version of Zotero (`citationKey` only exists since Zotero 7, D145).
    known_fields: set[str] = field(default_factory=set)
    account: Account = field(default_factory=Account)  # synced zotero.org account, the one the key must target

    def by_key(self) -> dict[str, Item]:
        return {e.key: e for e in self.all_items.values()}

    def children(self) -> dict[str, list[str]]:
        """Keys of the attachments and notes of each record, and of the annotations of each attachment (D182)."""
        res: dict[str, list[str]] = {}
        links = [(p.key, p.parent) for p in self.attachments.values()]
        links += [(self.all_items[n].key, parent) for n, parent in self.notes.items() if n in self.all_items]
        links += [(self.all_items[a].key, attachment) for a, attachment in self.annotation_of.items() if a in self.all_items]
        for key, parent in links:
            if parent in self.all_items:
                res.setdefault(self.all_items[parent].key, []).append(key)
        return res

    @property
    def items(self) -> list[Item]:
        """References, without notes, attachments and annotations."""
        return [e for e in self.all_items.values() if e.is_item]

    def path(self, col_id: int) -> str:
        c = self.collections[col_id]
        return (self.path(c.parent) + '/' if c.parent else '') + c.name

    def depth(self, col_id: int) -> int:
        c = self.collections[col_id]
        return 1 if not c.parent else 1 + self.depth(c.parent)

    def root(self, col_id: int) -> int:
        c = self.collections[col_id]
        return col_id if not c.parent else self.root(c.parent)


def check_schema(db: sqlite3.Connection) -> int:
    gaps = []
    for table, columns in SCHEMA.items():
        present_keys = {r[1] for r in db.execute(f'pragma table_info("{table}")')}
        if not present_keys:
            gaps.append(table)
        else:
            gaps += [f'{table}.{c}' for c in sorted(columns - present_keys)]
    if gaps:
        raise UnknownSchema(L(en=f"Zotero schema not recognized, missing elements: {', '.join(gaps)}. "
                                 'Update zot-clean, or report the Zotero version in an issue.',
                              fr=f"Schéma de Zotero non reconnu, éléments absents : {', '.join(gaps)}. "
                                 'Mettre zot-clean à jour, ou signaler la version de Zotero dans une issue.'))
    line = db.execute("select version from version where schema = 'userdata'").fetchone()
    return int(line[0]) if line else 0


def _state(*files: Path) -> tuple:
    return tuple((s.st_size, s.st_mtime_ns) if (s := _stat(f)) else None for f in files)


def _stat(f: Path):
    try:
        return f.stat()
    except FileNotFoundError:
        return None


def copy_file(database: Path, destination: Path) -> Path:
    """Copies the database and its `-wal` journal. An open Zotero may write between the two copies, or fold the journal
    into the database, and the copy would then lose the latest changes without error. If either file
    changed during the copy, it is redone (D185)."""
    return _copy(database, destination)[0]


def _copy(database: Path, destination: Path) -> tuple[Path, tuple]:
    """Like `copy_file`, with the state of the copied files (size and date of the database and the journal)."""
    if not database.is_file():
        raise FileNotFoundError(f'Base Zotero introuvable : {database}')
    copy = destination / database.name
    wal, wal_copy = database.with_name(database.name + '-wal'), copy.with_name(copy.name + '-wal')
    for trial in range(COPIES):
        if trial:
            time.sleep(PAUSE)
        before = _state(database, wal)
        shutil.copy2(database, copy)
        wal_copy.unlink(missing_ok=True)
        if wal.is_file():
            shutil.copy2(wal, wal_copy)
        if _state(database, wal) == before:
            return copy, before
    raise SystemExit(L(en='Zotero is writing to its database during the read (sync in progress?). Wait for the '
                          'sync to finish, then run the command again.',
                       fr='Zotero écrit dans sa base pendant la lecture (synchronisation en cours ?). Attendre la '
                          'fin de la synchronisation, puis relancer la commande.'))


# Copies shared during a `share()` block: temporary folder, and for each database, its copy and the state of the
# copied files. None outside such a block.
_shared: dict | None = None


@contextmanager
def share():
    """The reads made in this block (`read`, `read_types`, `sync_state`, `synced_account`) share a single
    copy of the database, instead of making one each. A 1 to 2 GB database used to be copied three
    or four times per command. The copy is redone as soon as the database or its journal has changed since, as if
    each read copied the database, and deleted at the end of the block."""
    global _shared
    if _shared is not None:  # block already opened above
        yield
        return
    with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
        _shared = {'dossier': Path(tmp), 'copies': {}}
        try:
            yield
        finally:
            _shared = None


@contextmanager
def _open(database: Path):
    """Connection to a copy of `database`, shared within a `share()` block, specific to this read otherwise."""
    if _shared is None:
        with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
            db = sqlite3.connect(copy_file(database, Path(tmp)))
            try:
                yield db
            finally:
                db.close()
        return
    copies = _shared['copies']
    key = database.resolve()
    if key not in copies:
        (folder := _shared['dossier'] / str(len(copies))).mkdir()
        copies[key] = _copy(database, folder)
    elif copies[key][1] != _state(database, database.with_name(database.name + '-wal')):  # Zotero has written since the copy
        copies[key] = _copy(database, copies[key][0].parent)
    db = sqlite3.connect(copies[key][0])
    try:
        yield db
    finally:
        db.close()


def read(database: Path, library: int = PERSONAL_LIBRARY) -> Library:
    """Reads a library (the personal one by default) from a temporary copy of `database`."""
    with _open(database) as db:
        return _read(db, library, database.parent / 'storage')


def _read(db: sqlite3.Connection, lib: int, storage: Path) -> Library:
    version = check_schema(db)
    all_items, versions = {}, {}
    for iid, key, typ, date_added, synced, v in db.execute(
            'select i.itemID, i.key, t.typeName, i.dateAdded, i.synced, i.version from items i join itemTypes t '
            'using(itemTypeID) where i.libraryID = ? and i.itemID not in (select itemID from deletedItems)', (lib,)):
        all_items[iid] = Item(iid, key, typ, date_added, bool(synced))
        versions[iid] = int(v or 0)
    for iid, name, val in db.execute(
            'select d.itemID, f.fieldName, v.value from itemData d join fields f using(fieldID) '
            'join itemDataValues v using(valueID)'):
        if iid in all_items:
            all_items[iid].fields[name] = str(val)
    for iid, name, first_name, role in db.execute(
            'select ic.itemID, c.lastName, c.firstName, ct.creatorType from itemCreators ic join creators c '
            'using(creatorID) left join creatorTypes ct using(creatorTypeID) order by ic.itemID, ic.orderIndex'):
        if iid in all_items:
            all_items[iid].creators.append((name or '', first_name or ''))
            all_items[iid].roles.append(role or '')
    for iid, name, typ in db.execute('select it.itemID, t.name, it.type from itemTags it join tags t using(tagID)'):
        if iid in all_items:
            all_items[iid].tags.append((name, typ))
    collections = {cid: Collection(cid, key, name, parent, bool(synced)) for cid, key, name, parent, synced in db.execute(
        'select collectionID, key, collectionName, parentCollectionID, synced from collections where libraryID = ? '
        'and collectionID not in (select collectionID from deletedCollections)',
        (lib,))}
    for cid, iid in db.execute('select collectionID, itemID from collectionItems'):
        if cid in collections and iid in all_items:
            all_items[iid].collections.add(cid)
    attachments = {}
    for iid, parent, mode, typ, path in db.execute(
            'select itemID, parentItemID, linkMode, contentType, path from itemAttachments'):
        if iid in all_items:
            attachments[iid] = Attachment(iid, all_items[iid].key, parent, mode, typ or '', path or '',
                                      _file(all_items[iid].key, mode, path or '', storage), versions[iid])
    # Zotero also stores in `itemNotes`, without a parent, the own note of an attachment (D206). Only real
    # notes go into `notes`, and an attachment with a note keeps it.
    notes = {}
    for iid, parent, text in db.execute('select itemID, parentItemID, note from itemNotes'):
        if iid in attachments:
            attachments[iid].note = nonempty_note(text)
        elif iid in all_items and all_items[iid].type == 'note':
            notes[iid] = parent
    invalid = [k for (k,) in db.execute('select key from items where libraryID = ?', (lib,))
                 if not VALID_KEY.match(k)]
    annotations: dict[int, int] = {}
    annotation_of: dict[int, int] = {}
    for iid, parent in db.execute('select itemID, parentItemID from itemAnnotations'):
        if parent in attachments:
            annotations[parent] = annotations.get(parent, 0) + 1
            if iid in all_items:
                annotation_of[iid] = parent
    line = db.execute('select version from libraries where libraryID = ?', (lib,)).fetchone()
    settings = {}
    for name, value in db.execute('select setting, value from syncedSettings where libraryID = ?', (lib,)):
        try:
            settings[name] = json.loads(value)
        except (TypeError, ValueError):
            settings[name] = value
    main = dict(db.execute(
        'select t.typeName, c.creatorType from itemTypeCreatorTypes i join itemTypes t using(itemTypeID) '
        'join creatorTypes c using(creatorTypeID) where i.primaryField = 1'))
    base_fields: dict[str, dict[str, str]] = {}
    for typ, database, specific in db.execute(
            'select t.typeName, fb.fieldName, fp.fieldName from baseFieldMappings m join itemTypes t '
            'using(itemTypeID) join fields fb on fb.fieldID = m.baseFieldID join fields fp on fp.fieldID = m.fieldID'):
        base_fields.setdefault(typ, {})[database] = specific
    b = Library(version, all_items, collections, attachments, notes, invalid, annotations,
                     int(line[0]) if line else 0, settings, main, base_fields, annotation_of)
    b.colors = _colors(settings.get('tagColors'))
    b.tag_searches = [(name, op or '', val or '') for name, op, val in db.execute(
        "select s.savedSearchName, c.operator, c.value from savedSearchConditions c join savedSearches s "
        "using(savedSearchID) where s.libraryID = ? and c.condition = 'tag' "
        "and s.savedSearchID not in (select savedSearchID from deletedSearches) order by s.savedSearchName", (lib,))]
    for name, n in db.execute(
            'select t.name, count(distinct it.itemID) from itemTags it join tags t using(tagID) join items i '
            'using(itemID) where i.libraryID = ? and it.itemID in (select itemID from deletedItems) group by t.name',
            (lib,)):
        b.trash_tags[name] = n
    b.searches = dict(db.execute('select key, savedSearchName from savedSearches where libraryID = ? and '
                                   'savedSearchID not in (select savedSearchID from deletedSearches)', (lib,)))
    b.known_fields = {name for (name,) in db.execute('select fieldName from fields')}
    b.account = _account(db)
    hide_with_trash(b)
    return b


def nonempty_note(text) -> bool:
    """A note without text stays wrapped by Zotero in `<div class="zotero-note znv1"></div>`."""
    return bool(re.sub(r'<[^>]*>|&nbsp;|\s', '', text or ''))


def hide_with_trash(b: Library) -> None:
    """Removes what Zotero hides with a parent in the trash (D186): attachments and notes of a record,
    annotations of an attachment, subcollections of a collection. Their tags count with those of the trash,
    since deleting a tag through the API removes it there too."""
    def drop(iid: int) -> None:
        e = b.all_items.pop(iid)
        for name, _ in e.tags:
            b.trash_tags[name] = b.trash_tags.get(name, 0) + 1
        b.attachments.pop(iid, None)
        b.notes.pop(iid, None)
        b.annotations.pop(iid, None)
        if (attachment := b.annotation_of.pop(iid, None)) is not None and b.annotations.get(attachment):
            b.annotations[attachment] -= 1

    for iid in [i for i, p in b.attachments.items() if p.parent is not None and p.parent not in b.all_items]:
        drop(iid)
    for iid in [i for i, parent in b.notes.items() if parent is not None and parent not in b.all_items]:
        drop(iid)
    for iid in [a for a, attachment in b.annotation_of.items() if attachment not in b.attachments]:
        drop(iid)
    for attachment in [p for p in b.annotations if p not in b.attachments]:
        del b.annotations[attachment]
    while orphans := [c for c, col in b.collections.items()
                         if col.parent is not None and col.parent not in b.collections]:
        for c in orphans:
            del b.collections[c]
            for e in b.all_items.values():
                e.collections.discard(c)


def multipart(v: str) -> bool:
    """Date in the form of Zotero's database (« 2020-00-00 2020 »), and not an SQL date and time."""
    if re.fullmatch(r'-?[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01]) ([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?', v):
        return False
    return bool(re.match(r'[0-9]{4}-(0[0-9]|1[0-2])-(0[0-9]|[12][0-9]|3[01]) ', v))


def date_multipart(v: str) -> str:
    """Date written by the API put in the form of Zotero's database (« 2020-00-00 2020 »), for the year."""
    if not v or multipart(v):
        return v
    if m := re.match(r'(\d{4})-(\d{1,2})(?:-(\d{1,2}))?\b', v):
        return f'{m.group(1)}-{m.group(2).zfill(2)}-{(m.group(3) or "0").zfill(2)} {v}'
    if m := re.search(r'(?<!\d)(\d{4})(?!\d)', v):
        return f'{m.group(1)}-00-00 {v}'
    return v


def date_as_entered(v: str) -> str:
    """Date as the user entered it and Zotero shows it (« 2020 » for « 2020-00-00 2020 »), to display a date read
    from the database."""
    return v.split(' ', 1)[1] if v and multipart(v) else v


API_MODES = {'imported_file': MODE_IMPORTED, 'imported_url': MODE_IMPORTED_URL, 'linked_file': MODE_LINKED,
             'linked_url': MODE_LINK, 'embedded_image': 4}


def apply_changes(b: Library, ch, storage: Path) -> None:
    """Applies to `b`, read from a lagging local copy, the changes the server has received since (D171),
    as returned by `api.Client.changes`. `b` becomes the state of the server, as if Zotero had
    synced. A new object gets a negative identifier, unknown to the local database."""
    col_ids = {c.key: cid for cid, c in b.collections.items()}
    ids = {e.key: iid for iid, e in b.all_items.items()}
    new_ones = (-n for n in range(1, 10 ** 9))

    def drop_collection(key: str) -> None:
        """Together with its subcollections, which Zotero trashes along with it."""
        if (cid := col_ids.pop(key, None)) is None:
            return
        del b.collections[cid]
        for e in b.all_items.values():
            e.collections.discard(cid)
        for under in [c.key for c in b.collections.values() if c.parent == cid]:
            drop_collection(under)

    def drop_item(key: str) -> None:
        if (iid := ids.pop(key, None)) is None:
            return
        e = b.all_items.pop(iid)
        b.attachments.pop(iid, None)
        b.notes.pop(iid, None)
        if (attachment := b.annotation_of.pop(iid, None)) is not None and b.annotations.get(attachment):
            b.annotations[attachment] -= 1
        return e

    for key in ch.deleted_collections:
        drop_collection(key)
    parents = {}
    for d in ch.collections:
        if d.get('deleted'):
            drop_collection(d['key'])
            continue
        cid = col_ids.setdefault(d['key'], next(new_ones))
        b.collections[cid] = Collection(cid, d['key'], d.get('name', ''), None, True)
        parents[cid] = d.get('parentCollection') or None
    for cid, parent in parents.items():
        b.collections[cid].parent = col_ids.get(parent, 0) if parent else None  # 0: parent in the trash

    for key in ch.deleted_items:
        drop_item(key)
    received = []
    for d in ch.all_items:
        if d.get('deleted'):
            if e := drop_item(d['key']):
                for name, _ in e.tags:
                    b.trash_tags[name] = b.trash_tags.get(name, 0) + 1
            continue
        iid = ids.setdefault(d['key'], next(new_ones))
        old = b.all_items.get(iid)
        e = Item(iid, d['key'], d['itemType'], old.date_added if old else
                    str(d.get('dateAdded', '')).replace('T', ' ').rstrip('Z'), True)
        dates = NON_BASE_DATES | {b.base_fields.get(e.type, {}).get('date', 'date')}
        e.fields = {k: date_multipart(str(v)) if k in dates else str(v) for k, v in d.items()
                    if k in b.known_fields and v not in ('', None)}
        for c in d.get('creators') or []:
            e.creators.append((c.get('lastName', c.get('name', '')), c.get('firstName', '')))
            e.roles.append(c.get('creatorType', ''))
        e.tags = [(t['tag'], int(t.get('type', 0))) for t in d.get('tags') or []]
        e.collections = {col_ids[k] for k in d.get('collections') or [] if k in col_ids}
        b.all_items[iid] = e
        received.append((iid, d))
    for iid, d in received:
        parent = ids.get(d.get('parentItem') or '')
        if d.get('parentItem') and parent is None:  # parent in the trash or deleted: hidden with it (D186)
            for name, _ in drop_item(d['key']).tags:
                b.trash_tags[name] = b.trash_tags.get(name, 0) + 1
            continue
        if d['itemType'] == 'attachment':
            mode = API_MODES.get(d.get('linkMode', ''), -1)
            if mode in (MODE_IMPORTED, MODE_IMPORTED_URL):
                path = f"storage:{d['filename']}" if d.get('filename') else ''
            else:
                path = d.get('path') or ''
            b.attachments[iid] = Attachment(iid, d['key'], parent, mode, d.get('contentType') or '', path,
                                        _file(d['key'], mode, path, storage), int(d.get('version') or 0),
                                        nonempty_note(d.get('note')))
        elif d['itemType'] == 'note':
            b.notes[iid] = parent
        elif d['itemType'] == 'annotation' and parent is not None and b.annotation_of.get(iid) != parent:
            if (former := b.annotation_of.get(iid)) is not None and b.annotations.get(former):
                b.annotations[former] -= 1
            b.annotation_of[iid] = parent
            b.annotations[parent] = b.annotations.get(parent, 0) + 1

    for name in ch.deleted_settings:
        b.settings.pop(name, None)
    for name, value in ch.settings.items():
        b.settings[name] = value
    b.colors = _colors(b.settings.get('tagColors'))
    for key in ch.deleted_searches:
        _remove_search(b, key)
    for d in ch.searches:
        _remove_search(b, d['key'])
        if not d.get('deleted'):
            b.searches[d['key']] = d.get('name', '')
            b.tag_searches += [(d.get('name', ''), c.get('operator', ''), c.get('value', ''))
                                  for c in d.get('conditions') or [] if c.get('condition') == 'tag']
    b.tag_searches.sort(key=lambda r: r[0])
    hide_with_trash(b)
    b.version = max(b.version, ch.version)


def _remove_search(b: Library, key: str) -> None:
    if (name := b.searches.pop(key, None)) is not None:
        b.tag_searches = [r for r in b.tag_searches if r[0] != name]


def _colors(value) -> list[tuple[str, str]]:
    """Colored tags, synced setting `tagColors` (ordered list of {name, color}, 9 at most)."""
    if not isinstance(value, list):
        return []
    return [(str(c['name']), str(c.get('color', ''))) for c in value if isinstance(c, dict) and c.get('name')]


@dataclass
class ItemTypes:
    """Fields and roles allowed by each record type, and base fields (D85)."""
    fields: dict[str, set[str]]
    database: dict[str, dict[str, str]]  # type -> {specific: base}, e.g. bookTitle -> publicationTitle
    roles: dict[str, set[str]]

    def equivalent(self, field_name: str, from_: str, to: str) -> str | None:
        """Field of type `to` that corresponds to `field_name` of type `from_`, or None."""
        common = self.database.get(from_, {}).get(field_name, field_name)
        if common in self.fields.get(to, set()):
            return common
        return next((specific for specific, b in self.database.get(to, {}).items() if b == common), None)


def read_types(database: Path) -> ItemTypes:
    with _open(database) as db:
        check_schema(db)
        fields: dict[str, set[str]] = {}
        for typ, field_name in db.execute('select t.typeName, f.fieldName from itemTypeFields i '
                                     'join itemTypes t using(itemTypeID) join fields f using(fieldID)'):
            fields.setdefault(typ, set()).add(field_name)
        bases: dict[str, dict[str, str]] = {}
        for typ, b, specific in db.execute(
                'select t.typeName, fb.fieldName, fp.fieldName from baseFieldMappings m join itemTypes t '
                'using(itemTypeID) join fields fb on fb.fieldID = m.baseFieldID '
                'join fields fp on fp.fieldID = m.fieldID'):
            bases.setdefault(typ, {})[specific] = b
        roles: dict[str, set[str]] = {}
        for typ, role in db.execute('select t.typeName, c.creatorType from itemTypeCreatorTypes i '
                                    'join itemTypes t using(itemTypeID) join creatorTypes c using(creatorTypeID)'):
            roles.setdefault(typ, set()).add(role)
        return ItemTypes(fields, bases, roles)


def sync_state(database: Path, library: int = PERSONAL_LIBRARY) -> tuple[list[str], int, int]:
    """Invalid keys (trash included), number of items and collections not yet synced excluding
    annotations, and number of annotations not yet synced (often blocked, with no effect on the records)."""
    with _open(database) as db:
        check_schema(db)
        invalid = [k for (k,) in db.execute('select key from items where libraryID = ?', (library,))
                     if not VALID_KEY.match(k)]
        annotations = db.execute(
            "select count(*) from items i join itemTypes t using(itemTypeID) where i.libraryID = ? "
            "and i.synced = 0 and t.typeName = 'annotation'", (library,)).fetchone()[0]
        unsynced = sum(db.execute(f'select count(*) from {t} where libraryID = ? and synced = 0',
                                  (library,)).fetchone()[0] for t in ('items', 'collections'))
        return invalid, unsynced - annotations, annotations


def synced_account(database: Path) -> Account:
    """zotero.org account that the database syncs with, for a command that does not read the whole library."""
    with _open(database) as db:
        check_schema(db)
        return _account(db)


def _account(db: sqlite3.Connection) -> Account:
    settings = dict(db.execute("select key, value from settings where setting = 'account'"))
    try:
        ident = int(settings.get('userID') or 0)
    except (TypeError, ValueError):
        ident = 0
    return Account(ident or None, str(settings.get('username') or ''))


def library_version(database: Path, library: int = PERSONAL_LIBRARY) -> int:
    """Sync version of the library, read from `database` opened read-only.

    To be called only on a copy (backup), never on Zotero's database."""
    db = sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)
    try:
        line = db.execute('select version from libraries where libraryID = ?', (library,)).fetchone()
        return int(line[0]) if line else 0
    finally:
        db.close()


def _file(key: str, mode: int, path: str, storage: Path) -> Path | None:
    if mode in (MODE_IMPORTED, MODE_IMPORTED_URL) and path.startswith('storage:'):
        return storage / key / path[len('storage:'):]
    if mode == MODE_LINKED and path and not path.startswith('attachments:'):
        return Path(path)
    # Linked files relative to the base folder of attachments: a Zotero setting not read here.
    return None
