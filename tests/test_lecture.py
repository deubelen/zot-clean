import sqlite3

import pytest

from zot_clean import lecture


def test_lit_fiches_collections_tags_et_pieces(zotero):
    fonds = zotero.collection('Fonds')
    philo = zotero.collection('Philosophie', fonds)
    f = zotero.fiche('Le titre', auteurs=('Martin', 'Leroy'), collections=(philo,), tags=('#norme', ('auto', 1)),
                     DOI='10.1/abc')
    zotero.pdf(f, 'Martin - 2020 - Le titre.pdf')
    zotero.note(f)
    b = lecture.lire(zotero.enregistrer())
    assert b.version_schema == 129
    (e,) = b.fiches
    assert e.titre == 'Le titre' and e.champs['DOI'] == '10.1/abc'
    assert [n for n, _ in e.createurs] == ['Martin', 'Leroy']
    assert sorted(e.tags) == [('#norme', 0), ('auto', 1)]
    assert b.chemin(next(iter(e.collections))) == 'Fonds/Philosophie'
    (p,) = b.pieces.values()
    assert p.parent == f and p.fichier.is_file()
    assert len(b.notes) == 1


def test_ignore_la_corbeille_et_les_groupes(zotero):
    zotero.corbeille(zotero.fiche('Supprimée'))
    zotero.db.execute("insert into libraries (libraryID, type, editable, filesEditable) values (2, 'group', 1, 1)")
    zotero.fiche('Dans un groupe', lib=2)
    zotero.fiche('Gardée')
    b = lecture.lire(zotero.enregistrer())
    assert [e.titre for e in b.fiches] == ['Gardée']


def test_releve_les_cles_invalides(zotero):
    zotero.fiche('Mauvaise clé', cle='abc_123')
    assert lecture.lire(zotero.enregistrer()).cles_invalides == ['abc_123']


def test_schema_inconnu_arrete_la_lecture(zotero):
    zotero.db.execute('alter table itemTags drop column type')
    with pytest.raises(lecture.SchemaInconnu, match='itemTags.type'):
        lecture.lire(zotero.enregistrer())


def test_la_base_d_origine_n_est_pas_modifiee(zotero):
    zotero.fiche('Une fiche')
    base = zotero.enregistrer()
    avant = base.read_bytes()
    lecture.lire(base)
    assert base.read_bytes() == avant
    assert sqlite3.connect(base).execute('select count(*) from items').fetchone()[0] == 1


def test_types_champs_de_base_et_roles(zotero):
    t = lecture.lire_types(zotero.enregistrer())
    assert 'DOI' in t.champs['bookSection'] and 'issue' not in t.champs['bookSection']
    assert t.equivalent('publicationTitle', 'journalArticle', 'bookSection') == 'bookTitle'
    assert t.equivalent('bookTitle', 'bookSection', 'conferencePaper') == 'proceedingsTitle'
    assert t.equivalent('issue', 'journalArticle', 'bookSection') is None
    assert 'editor' in t.roles['bookSection'] and 'editor' not in t.roles.get('thesis', set())


def test_couleurs_recherches_et_tags_des_enfants(zotero):
    f = zotero.fiche('Une fiche', tags=('lu',))
    pj = zotero.pdf(f, 'a.pdf', tags=('pdf',))
    a = zotero.annotation(pj, tags=('surligné',))
    zotero.note(f, tags=('à voir',))
    zotero.corbeille(zotero.fiche('Jetée', tags=('lu', ('auto', 1))))
    zotero.couleur('lu', '#FF0000')
    zotero.couleur('★ essentiel', '#00FF00')
    zotero.recherche('Mes lectures', 'lu')
    supprimee = zotero.recherche('Ancienne', 'vieux')
    zotero.db.execute('insert into deletedSearches (savedSearchID) values (?)', (supprimee,))
    b = lecture.lire(zotero.enregistrer())
    assert b.couleurs == [('lu', '#FF0000'), ('★ essentiel', '#00FF00')]
    assert b.recherches_tags == [('Mes lectures', 'is', 'lu')]
    assert b.annotation_de == {a: pj}
    assert sorted(n for e in b.elements.values() for n, _ in e.tags) == ['lu', 'pdf', 'surligné', 'à voir']
    assert b.tags_corbeille == {'lu': 1, 'auto': 1}



def test_report_des_changements_du_serveur(zotero):
    """D171 : une copie locale en retard reçoit ce que le serveur a reçu depuis, comme après une synchronisation."""
    from zot_clean.ecriture import Changements
    fonds = zotero.collection('Fonds', cle='FONDS222')
    vieux = zotero.collection('Vieux', cle='VIEUX222')
    f = zotero.fiche('Ancien titre', collections=(vieux,), tags=('auto',), cle='FICHE222', DOI='10.1/a')
    p = zotero.pdf(f, 'scan0001.pdf', cle='PIECE222')
    jetee = zotero.fiche('Jetée', tags=('#rare',), cle='JETEE222')
    zotero.fiche('Supprimée', cle='SUPPR222')
    zotero.reglage('tagColors', [])
    zotero.synchroniser(10)
    b = lecture.lire(zotero.enregistrer())
    ch = Changements(14, elements=[
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
    ], elements_supprimes=['SUPPR222'], reglages={'tagColors': [{'name': '#norme', 'color': '#FF0000'}]})
    lecture.reporter(b, ch, zotero.dossier / 'storage')
    assert b.version == 14
    assert {c.nom for c in b.collections.values()} == {'Fonds', 'Nouvelle'}
    nouvelle = next(cid for cid, c in b.collections.items() if c.cle == 'NOUVEL22')
    assert nouvelle < 0 and b.chemin(nouvelle) == 'Fonds/Nouvelle'
    e = b.par_cle()['FICHE222']
    assert e.id == f and e.type == 'book' and e.titre == 'Nouveau titre' and 'DOI' not in e.champs
    assert e.createurs == [('Dupont', 'A.'), ('Collectif', '')] and e.auteur == 'Collectif'
    assert e.tags == [('#norme', 0), ('auto', 1)] and {b.chemin(c) for c in e.collections} == {'Fonds', 'Fonds/Nouvelle'}
    assert e.ajout == '2026-01-01'  # date d'ajout locale gardée
    piece = b.pieces[p]
    assert piece.chemin == 'storage:Dupont - Nouveau titre.pdf' and piece.parent == f
    assert piece.fichier == zotero.dossier / 'storage' / 'PIECE222' / 'Dupont - Nouveau titre.pdf'
    assert list(b.notes.values()) == [f]
    assert 'JETEE222' not in b.par_cle() and 'SUPPR222' not in b.par_cle() and jetee not in b.elements
    assert b.tags_corbeille == {'#rare': 1}
    assert b.couleurs == [('#norme', '#FF0000')]


def test_copie_refaite_si_zotero_ecrit_pendant(zotero, tmp_path, monkeypatch):
    # D185 : Zotero écrit dans la base entre la copie de la base et celle de son journal. La copie est refaite.
    import os
    import shutil
    base = zotero.enregistrer()
    wal = base.with_name(base.name + '-wal')
    wal.write_bytes(b'journal')
    copies, copier = [], shutil.copy2
    monkeypatch.setattr(lecture, 'PAUSE', 0)

    def copie_pendant_une_ecriture(source, cible):
        copies.append(source)
        copier(source, cible)
        if len(copies) <= ecritures:
            os.utime(base, (1, 10 ** 9 + 10 * len(copies)))  # en secondes : Windows date au dixième de µs
    monkeypatch.setattr(lecture.shutil, 'copy2', copie_pendant_une_ecriture)
    ecritures = 1
    (tmp_path / 'a').mkdir()
    assert lecture.copier(base, tmp_path / 'a').is_file() and len(copies) == 4
    copies.clear()
    ecritures = 10
    (tmp_path / 'b').mkdir()
    with pytest.raises(SystemExit, match='synchronisation'):
        lecture.copier(base, tmp_path / 'b')


def test_ce_que_la_corbeille_cache(zotero):
    # D186 : Zotero cache avec un parent à la corbeille ses pièces jointes, notes et annotations, et les
    # sous-collections d'une collection.
    from zot_clean import audit
    from zot_clean.config import Config
    parent = zotero.collection('Parent')
    enfant = zotero.collection('Enfant', parent)
    petite = zotero.collection('Petite', enfant)
    gardee = zotero.collection('Gardée')
    f = zotero.fiche('Jetée', collections=(enfant,))
    pj = zotero.pdf(f, 'a.pdf', tags=('pdf',))
    zotero.annotation(pj)
    zotero.note(f)
    zotero.corbeille(f)
    reste = zotero.fiche('Restée', collections=(petite, gardee))
    zotero.db.execute('insert into deletedCollections (collectionID) values (?)', (parent,))
    base = zotero.enregistrer()
    b = lecture.lire(base)
    assert [c.nom for c in b.collections.values()] == ['Gardée']
    assert not b.pieces and not b.notes and not b.annotation_de and not b.annotations
    assert [e.titre for e in b.elements.values()] == ['Restée']
    assert b.elements[reste].collections == {gardee} and b.tags_corbeille == {'pdf': 1}
    audit.auditer(b, Config(dossier_travail=base.parent.parent / 'travail', dossier_zotero=base.parent))


def test_report_de_la_corbeille_et_des_suppressions(zotero):
    # D186 : le parent mis à la corbeille sur le serveur emporte ses enfants. D187 : réglages et recherches
    # supprimés, annotation passée d'un PDF à un autre.
    from zot_clean.ecriture import Changements
    f = zotero.fiche('Fiche', cle='FICHE333')
    pj = zotero.pdf(f, 'a.pdf', cle='PIECE333')
    zotero.annotation(pj, cle='ANNOT333')
    zotero.note(f, cle='NOTE3333')
    g = zotero.fiche('Autre', cle='AUTRE333')
    pj2 = zotero.pdf(g, 'b.pdf', cle='PIECE444')
    a2 = zotero.annotation(pj2, cle='ANNOT444')
    zotero.pdf(g, 'c.pdf', cle='PIECE555')
    zotero.reglage('tagColors', [{'name': 'lu', 'color': '#FF0000'}])
    zotero.recherche('Mes lectures', 'lu')
    zotero.recherche('Autre recherche', 'vu')
    zotero.synchroniser(10)
    b = lecture.lire(zotero.enregistrer())
    cles = {nom: cle for cle, nom in b.recherches.items()}
    ch = Changements(12, elements=[
        {'key': 'FICHE333', 'version': 11, 'itemType': 'journalArticle', 'title': 'Fiche', 'deleted': 1, 'tags': []},
        {'key': 'NOUVEL33', 'version': 12, 'itemType': 'note', 'parentItem': 'FICHE333', 'note': 'x', 'tags': []},
        {'key': 'ANNOT444', 'version': 12, 'itemType': 'annotation', 'parentItem': 'PIECE555', 'tags': []},
    ], reglages_supprimes=['tagColors'], recherches_supprimees=[cles['Mes lectures']],
        recherches=[{'key': cles['Autre recherche'], 'version': 12, 'name': 'Renommée',
                     'conditions': [{'condition': 'tag', 'operator': 'is', 'value': 'lu'}]}])
    lecture.reporter(b, ch, zotero.dossier / 'storage')
    assert sorted(e.cle for e in b.elements.values()) == ['ANNOT444', 'AUTRE333', 'PIECE444', 'PIECE555']
    pj5 = next(i for i, p in b.pieces.items() if p.cle == 'PIECE555')
    assert b.annotation_de == {a2: pj5} and b.annotations.get(pj2, 0) == 0 and b.annotations[pj5] == 1
    assert b.couleurs == [] and 'tagColors' not in b.reglages
    assert b.recherches_tags == [('Renommée', 'is', 'lu')]
