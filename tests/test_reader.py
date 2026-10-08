import sqlite3

import pytest

from zot_clean import reader


def test_reads_items_collections_tags_and_attachments(zotero):
    subjects = zotero.collection('Fonds')
    philo = zotero.collection('Philosophie', subjects)
    f = zotero.item('Le titre', authors=('Martin', 'Leroy'), collections=(philo,), tags=('#norme', ('auto', 1)),
                     DOI='10.1/abc')
    zotero.pdf(f, 'Martin - 2020 - Le titre.pdf')
    zotero.note(f)
    b = reader.read(zotero.save())
    assert b.schema_version == 129
    (e,) = b.items
    assert e.title == 'Le titre' and e.fields['DOI'] == '10.1/abc'
    assert [n for n, _ in e.creators] == ['Martin', 'Leroy']
    assert sorted(e.tags) == [('#norme', 0), ('auto', 1)]
    assert b.path(next(iter(e.collections))) == 'Fonds/Philosophie'
    (p,) = b.attachments.values()
    assert p.parent == f and p.file.is_file()
    assert len(b.notes) == 1


def test_ignores_trash_and_groups(zotero):
    zotero.trash(zotero.item('Supprimée'))
    zotero.db.execute("insert into libraries (libraryID, type, editable, filesEditable) values (2, 'group', 1, 1)")
    zotero.item('Dans un groupe', lib=2)
    zotero.item('Gardée')
    b = reader.read(zotero.save())
    assert [e.title for e in b.items] == ['Gardée']


def test_lists_invalid_keys(zotero):
    zotero.item('Mauvaise clé', key='abc_123')
    assert reader.read(zotero.save()).invalid_keys == ['abc_123']


def test_unknown_schema_stops_reading(zotero):
    zotero.db.execute('alter table itemTags drop column type')
    with pytest.raises(reader.UnknownSchema, match='itemTags.type'):
        reader.read(zotero.save())


def test_original_database_not_modified(zotero):
    zotero.item('Une fiche')
    database = zotero.save()
    before = database.read_bytes()
    reader.read(database)
    assert database.read_bytes() == before
    assert sqlite3.connect(database).execute('select count(*) from items').fetchone()[0] == 1


def test_types_base_fields_and_roles(zotero):
    t = reader.read_types(zotero.save())
    assert 'DOI' in t.fields['bookSection'] and 'issue' not in t.fields['bookSection']
    assert t.equivalent('publicationTitle', 'journalArticle', 'bookSection') == 'bookTitle'
    assert t.equivalent('bookTitle', 'bookSection', 'conferencePaper') == 'proceedingsTitle'
    assert t.equivalent('issue', 'journalArticle', 'bookSection') is None
    assert 'editor' in t.roles['bookSection'] and 'editor' not in t.roles.get('thesis', set())


def test_colors_searches_and_children_tags(zotero):
    f = zotero.item('Une fiche', tags=('lu',))
    att = zotero.pdf(f, 'a.pdf', tags=('pdf',))
    a = zotero.annotation(att, tags=('surligné',))
    zotero.note(f, tags=('à voir',))
    zotero.trash(zotero.item('Jetée', tags=('lu', ('auto', 1))))
    zotero.color('lu', '#FF0000')
    zotero.color('★ essentiel', '#00FF00')
    zotero.search('Mes lectures', 'lu')
    deleted_search = zotero.search('Ancienne', 'vieux')
    zotero.db.execute('insert into deletedSearches (savedSearchID) values (?)', (deleted_search,))
    b = reader.read(zotero.save())
    assert b.colors == [('lu', '#FF0000'), ('★ essentiel', '#00FF00')]
    assert b.tag_searches == [('Mes lectures', 'is', 'lu')]
    assert b.annotation_of == {a: att}
    assert sorted(n for e in b.all_items.values() for n, _ in e.tags) == ['lu', 'pdf', 'surligné', 'à voir']
    assert b.trash_tags == {'lu': 1, 'auto': 1}



def test_carry_over_of_server_changes(zotero):
    """D171: a stale local copy receives what the server got since, as after a synchronisation."""
    from zot_clean.api import Changes
    subjects = zotero.collection('Fonds', key='FONDS222')
    stale = zotero.collection('Vieux', key='VIEUX222')
    f = zotero.item('Ancien titre', collections=(stale,), tags=('auto',), key='FICHE222', DOI='10.1/a')
    p = zotero.pdf(f, 'scan0001.pdf', key='PIECE222')
    discarded = zotero.item('Jetée', tags=('#rare',), key='JETEE222')
    zotero.item('Supprimée', key='SUPPR222')
    zotero.setting('tagColors', [])
    zotero.sync(10)
    b = reader.read(zotero.save())
    ch = Changes(14, all_items=[
        {'key': 'FICHE222', 'version': 12, 'itemType': 'book', 'title': 'Nouveau titre', 'DOI': '', 'ISBN': '',
         'creators': [{'creatorType': 'editor', 'firstName': 'A.', 'lastName': 'Dupont'},
                      {'creatorType': 'author', 'name': 'Collectif'}],
         'tags': [{'tag': '#norme'}, {'tag': 'auto', 'type': 1}], 'collections': ['FONDS222', 'NOUVEL22'],
         'dateAdded': '2026-01-01T00:00:00Z'},
        {'key': 'PIECE222', 'version': 13, 'itemType': 'attachment', 'parentItem': 'FICHE222',
         'linkMode': 'imported_file', 'contentType': 'application/pdf', 'filename': 'Dupont - Nouveau titre.pdf',
         'title': 'PDF', 'tags': []},
        {'key': 'NOTE2222', 'version': 13, 'itemType': 'note', 'parentItem': 'FICHE222', 'note': '<p>x</p>',
         'tags': []},
        {'key': 'JETEE222', 'version': 14, 'itemType': 'journalArticle', 'title': 'Jetée', 'deleted': 1,
         'tags': [{'tag': '#rare'}], 'collections': []},
    ], collections=[
        {'key': 'NOUVEL22', 'version': 11, 'name': 'Nouvelle', 'parentCollection': 'FONDS222'},
        {'key': 'VIEUX222', 'version': 12, 'name': 'Vieux', 'parentCollection': False, 'deleted': True},
    ], deleted_items=['SUPPR222'], settings={'tagColors': [{'name': '#norme', 'color': '#FF0000'}]})
    reader.apply_changes(b, ch, zotero.folder / 'storage')
    assert b.version == 14
    assert {c.name for c in b.collections.values()} == {'Fonds', 'Nouvelle'}
    new = next(cid for cid, c in b.collections.items() if c.key == 'NOUVEL22')
    assert new < 0 and b.path(new) == 'Fonds/Nouvelle'
    e = b.by_key()['FICHE222']
    assert e.id == f and e.type == 'book' and e.title == 'Nouveau titre' and 'DOI' not in e.fields
    assert e.creators == [('Dupont', 'A.'), ('Collectif', '')] and e.author == 'Collectif'
    assert e.tags == [('#norme', 0), ('auto', 1)] and {b.path(c) for c in e.collections} == {'Fonds', 'Fonds/Nouvelle'}
    assert e.date_added == '2026-01-01'  # local date added kept
    attachment = b.attachments[p]
    assert attachment.path == 'storage:Dupont - Nouveau titre.pdf' and attachment.parent == f
    assert attachment.file == zotero.folder / 'storage' / 'PIECE222' / 'Dupont - Nouveau titre.pdf'
    assert list(b.notes.values()) == [f]
    assert 'JETEE222' not in b.by_key() and 'SUPPR222' not in b.by_key() and discarded not in b.all_items
    assert b.trash_tags == {'#rare': 1}
    assert b.colors == [('#norme', '#FF0000')]


def test_copy_redone_if_zotero_writes_meanwhile(zotero, tmp_path, monkeypatch):
    # D185: Zotero writes to the database between the copy of the database and that of its journal. The copy is redone.
    import os
    import shutil
    database = zotero.save()
    wal = database.with_name(database.name + '-wal')
    wal.write_bytes(b'journal')
    copies, copy_file = [], shutil.copy2
    monkeypatch.setattr(reader, 'PAUSE', 0)

    def copy_during_write(source, target):
        copies.append(source)
        copy_file(source, target)
        if len(copies) <= write_count:
            os.utime(database, (1, 10 ** 9 + 10 * len(copies)))  # in seconds: Windows dates to a tenth of a µs
    monkeypatch.setattr(reader.shutil, 'copy2', copy_during_write)
    write_count = 1
    (tmp_path / 'a').mkdir()
    assert reader.copy_file(database, tmp_path / 'a').is_file() and len(copies) == 4
    copies.clear()
    write_count = 10
    (tmp_path / 'b').mkdir()
    with pytest.raises(SystemExit, match='synchronisation'):
        reader.copy_file(database, tmp_path / 'b')


def test_what_the_trash_hides(zotero):
    # D186: Zotero hides, with a parent in the trash, its attachments, notes and annotations, and the
    # subcollections of a collection.
    from zot_clean import audit
    from zot_clean.config import Config
    parent = zotero.collection('Parent')
    child = zotero.collection('Enfant', parent)
    little = zotero.collection('Petite', child)
    kept_item = zotero.collection('Gardée')
    f = zotero.item('Jetée', collections=(child,))
    att = zotero.pdf(f, 'a.pdf', tags=('pdf',))
    zotero.annotation(att)
    zotero.note(f)
    zotero.trash(f)
    rest = zotero.item('Restée', collections=(little, kept_item))
    zotero.db.execute('insert into deletedCollections (collectionID) values (?)', (parent,))
    database = zotero.save()
    b = reader.read(database)
    assert [c.name for c in b.collections.values()] == ['Gardée']
    assert not b.attachments and not b.notes and not b.annotation_of and not b.annotations
    assert [e.title for e in b.all_items.values()] == ['Restée']
    assert b.all_items[rest].collections == {kept_item} and b.trash_tags == {'pdf': 1}
    audit.run_audit(b, Config(workspace=database.parent.parent / 'travail', zotero_dir=database.parent))


def test_carry_over_of_trash_and_deletions(zotero):
    # D186: the parent trashed on the server takes its children with it. D187: settings and searches
    # deleted, annotation moved from one PDF to another.
    from zot_clean.api import Changes
    f = zotero.item('Fiche', key='FICHE333')
    att = zotero.pdf(f, 'a.pdf', key='PIECE333')
    zotero.annotation(att, key='ANNOT333')
    zotero.note(f, key='NOTE3333')
    g = zotero.item('Autre', key='AUTRE333')
    att2 = zotero.pdf(g, 'b.pdf', key='PIECE444')
    a2 = zotero.annotation(att2, key='ANNOT444')
    zotero.pdf(g, 'c.pdf', key='PIECE555')
    zotero.setting('tagColors', [{'name': 'lu', 'color': '#FF0000'}])
    zotero.search('Mes lectures', 'lu')
    zotero.search('Autre recherche', 'vu')
    zotero.sync(10)
    b = reader.read(zotero.save())
    keys = {name: key for key, name in b.searches.items()}
    ch = Changes(12, all_items=[
        {'key': 'FICHE333', 'version': 11, 'itemType': 'journalArticle', 'title': 'Fiche', 'deleted': 1, 'tags': []},
        {'key': 'NOUVEL33', 'version': 12, 'itemType': 'note', 'parentItem': 'FICHE333', 'note': 'x', 'tags': []},
        {'key': 'ANNOT444', 'version': 12, 'itemType': 'annotation', 'parentItem': 'PIECE555', 'tags': []},
    ], deleted_settings=['tagColors'], deleted_searches=[keys['Mes lectures']],
        searches=[{'key': keys['Autre recherche'], 'version': 12, 'name': 'Renommée',
                     'conditions': [{'condition': 'tag', 'operator': 'is', 'value': 'lu'}]}])
    reader.apply_changes(b, ch, zotero.folder / 'storage')
    assert sorted(e.key for e in b.all_items.values()) == ['ANNOT444', 'AUTRE333', 'PIECE444', 'PIECE555']
    att5 = next(i for i, p in b.attachments.items() if p.key == 'PIECE555')
    assert b.annotation_of == {a2: att5} and b.annotations.get(att2, 0) == 0 and b.annotations[att5] == 1
    assert b.colors == [] and 'tagColors' not in b.settings
    assert b.tag_searches == [('Renommée', 'is', 'lu')]


def test_single_copy_per_command(zotero, monkeypatch):
    # In a `share()` block, reads share one copy of the database, redone only if Zotero has written
    # to the database since. Outside such a block, each read makes its own.
    import os
    import shutil
    database = zotero.save()
    copies, copy_file = [], shutil.copy2

    def counting_copy(source, target):
        copies.append(source)
        copy_file(source, target)
    monkeypatch.setattr(reader.shutil, 'copy2', counting_copy)
    with reader.share():
        reader.sync_state(database)
        reader.read(database)
        reader.read_types(database)
        with reader.share():
            assert reader.read(database).items == []
        assert len(copies) == 1
        folder = reader._shared['dossier']
        zotero.item('Ajoutée par Zotero pendant la commande')
        zotero.save()
        os.utime(database, (1, 10 ** 9))  # date changed by several seconds: Windows dates to a tenth of a µs
        assert [e.title for e in reader.read(database).items] == ['Ajoutée par Zotero pendant la commande']
        assert len(copies) == 2
        reader.read_types(database)
        assert len(copies) == 2
    assert not folder.exists() and reader._shared is None
    reader.read(database)
    reader.read(database)
    assert len(copies) == 4


def test_synced_account(zotero):
    """zotero.org account kept by Zotero at the first synchronisation (`settings`, `setting = 'account'`)."""
    zotero.account(777, 'durand')
    database = zotero.save()
    assert reader.synced_account(database) == reader.Account(777, 'durand') == reader.read(database).account
    zotero.account(None)
    zotero.save()
    assert reader.synced_account(database) == reader.Account() and reader.Account().id is None


def test_own_note_of_attachment(zotero):
    # D206: Zotero stores the note of an attachment in `itemNotes`, without a parent. It is not a standalone note.
    f = zotero.item('Fiche')
    has_note = zotero.pdf(f, 'a.pdf', note='<p>Lu en 2024</p>')
    empty = zotero.pdf(f, 'b.pdf')
    note = zotero.note(f)
    b = reader.read(zotero.save())
    assert b.notes == {note: f}
    assert b.attachments[has_note].note and not b.attachments[empty].note


def test_unknown_schema_message_in_english(zotero):
    from zot_clean.lang import language
    zotero.db.execute("alter table itemTags drop column type")
    with language("en"):
        with pytest.raises(reader.UnknownSchema, match="Zotero schema not recognized, missing elements: itemTags.type"):
            reader.read(zotero.save())


def test_date_as_entered():
    """A date read from the database is shown as Zotero shows it (pilot bench)."""
    assert reader.date_as_entered('2028-00-00 2028') == '2028'
    assert reader.date_as_entered('1998-03-00 March 1998') == 'March 1998'
    assert reader.date_as_entered('2020') == '2020' and reader.date_as_entered('') == ''
