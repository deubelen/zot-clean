import json
from pathlib import Path

import pytest

from manual import populate


def test_test_account_safeguard():
    populate.check_test_account({'ZOTERO_USER_ID': '777'}, '777', 777)
    with pytest.raises(SystemExit, match='ZC_COMPTE_TEST'):
        populate.check_test_account({'ZOTERO_USER_ID': '777'}, None, 777)
    with pytest.raises(SystemExit, match='compte de test'):
        populate.check_test_account({'ZOTERO_USER_ID': '123'}, '777', 123)
    with pytest.raises(SystemExit, match='compte de test'):
        populate.check_test_account({'ZOTERO_USER_ID': '777'}, '777', 123)


def test_generated_pdf():
    a, b = populate.pdf('un'), populate.pdf('deux')
    assert a.startswith(b'%PDF-1.4') and a.rstrip().endswith(b'%%EOF') and a != b == populate.pdf('deux')
    xref = int(a.rsplit(b'startxref\n', 1)[1].split(b'\n')[0])
    assert a[xref:].startswith(b'xref')


def test_consistent_fixtures():
    d = json.loads(populate.FIXTURES.read_text(encoding='utf-8'))
    refs = [f['ref'] for f in d['fiches']]
    assert len(refs) == len(set(refs))
    assert all(c in d['collections'] for f in d['fiches'] for c in f.get('collections', []))
    assert all(p.rpartition('/')[0] in ('', *d['collections']) for p in d['collections'])


def test_probe_tools(zotero, tmp_path):
    from manual import probe_tools, probe_citation_keys, probe_filenames, probe_tags  # the probes import without error

    assert probe_tags.PHASES and probe_citation_keys.ITEMS and probe_filenames.CASES
    zotero.item('Une fiche', tags=(('porté', 1),))
    zotero.db.execute("insert into tags (tagID, name) values (999, 'orphelin')")
    zotero.db.execute("insert into syncedSettings (setting, libraryID, value) "
                      "values ('tagColors', 1, '[{\"name\": \"porté\", \"color\": \"#A28AE5\"}]')")
    database = zotero.save()
    assert probe_tools.tag_names(database) == {'porté', 'orphelin'}
    assert probe_tools.local_setting(database, 'tagColors') == [{'name': 'porté', 'color': '#A28AE5'}]
    assert probe_tools.local_setting(database, 'autre') is None

    (tmp_path / 'cle').mkdir()
    (tmp_path / 'cle' / 'Fichier présent.pdf').write_bytes(b'%PDF')
    (tmp_path / 'cle' / '.zotero-ft-cache').write_text('')
    assert probe_tools.visible_files(tmp_path / 'cle') == ['Fichier présent.pdf']
    assert probe_tools.visible_files(tmp_path / 'absent') == []
    assert probe_tools.same_name('Fichier présent.pdf', 'Fichier présent.pdf')
    assert not probe_tools.same_name('zc-sonde-casse.pdf', 'ZC-Sonde-Casse.pdf')
