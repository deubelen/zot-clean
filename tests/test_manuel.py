import json
from pathlib import Path

import pytest

from manuel import peupler


def test_garde_fou_du_compte_de_test():
    peupler.verifier_compte_test({'ZOTERO_USER_ID': '777'}, '777', 777)
    with pytest.raises(SystemExit, match='ZC_COMPTE_TEST'):
        peupler.verifier_compte_test({'ZOTERO_USER_ID': '777'}, None, 777)
    with pytest.raises(SystemExit, match='compte de test'):
        peupler.verifier_compte_test({'ZOTERO_USER_ID': '123'}, '777', 123)
    with pytest.raises(SystemExit, match='compte de test'):
        peupler.verifier_compte_test({'ZOTERO_USER_ID': '777'}, '777', 123)


def test_pdf_genere():
    a, b = peupler.pdf('un'), peupler.pdf('deux')
    assert a.startswith(b'%PDF-1.4') and a.rstrip().endswith(b'%%EOF') and a != b == peupler.pdf('deux')
    xref = int(a.rsplit(b'startxref\n', 1)[1].split(b'\n')[0])
    assert a[xref:].startswith(b'xref')


def test_fixtures_coherentes():
    d = json.loads(peupler.FIXTURES.read_text(encoding='utf-8'))
    refs = [f['ref'] for f in d['fiches']]
    assert len(refs) == len(set(refs))
    assert all(c in d['collections'] for f in d['fiches'] for c in f.get('collections', []))
    assert all(p.rpartition('/')[0] in ('', *d['collections']) for p in d['collections'])


def test_outils_des_sondes(zotero, tmp_path):
    from manuel import outils_sondes, sonde_cles, sonde_noms, sonde_tags  # les sondes s'importent sans erreur

    assert sonde_tags.PHASES and sonde_cles.FICHES and sonde_noms.CAS
    zotero.fiche('Une fiche', tags=(('porté', 1),))
    zotero.db.execute("insert into tags (tagID, name) values (999, 'orphelin')")
    zotero.db.execute("insert into syncedSettings (setting, libraryID, value) "
                      "values ('tagColors', 1, '[{\"name\": \"porté\", \"color\": \"#A28AE5\"}]')")
    base = zotero.enregistrer()
    assert outils_sondes.noms_de_tags(base) == {'porté', 'orphelin'}
    assert outils_sondes.reglage_local(base, 'tagColors') == [{'name': 'porté', 'color': '#A28AE5'}]
    assert outils_sondes.reglage_local(base, 'autre') is None

    (tmp_path / 'cle').mkdir()
    (tmp_path / 'cle' / 'Fichier présent.pdf').write_bytes(b'%PDF')
    (tmp_path / 'cle' / '.zotero-ft-cache').write_text('')
    assert outils_sondes.fichiers_visibles(tmp_path / 'cle') == ['Fichier présent.pdf']
    assert outils_sondes.fichiers_visibles(tmp_path / 'absent') == []
    assert outils_sondes.meme_nom('Fichier présent.pdf', 'Fichier présent.pdf')
    assert not outils_sondes.meme_nom('zc-sonde-casse.pdf', 'ZC-Sonde-Casse.pdf')
