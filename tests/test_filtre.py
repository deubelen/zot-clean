from pathlib import Path

from zot_clean import filtre, lecture
from zot_clean.config import Config


def test_tags_et_collections_exclus(zotero):
    fonds = zotero.collection('Fonds')
    prive = zotero.collection('Privé', fonds)
    sous = zotero.collection('Dossiers', prive)
    autre = zotero.collection('Autre')
    a = zotero.fiche('Taguée', tags=('_privé',))
    b_ = zotero.fiche('Dans une sous-collection', collections=(sous,))
    c = zotero.fiche('Ailleurs', collections=(autre, fonds))
    b = lecture.lire(zotero.enregistrer())
    cfg = Config(dossier_travail=Path('.'))
    cfg.confidentialite.collections_exclues = ['Fonds/Privé']
    assert filtre.exclues(b, cfg) == {a, b_}
    cfg.confidentialite.collections_exclues = ['Autre']
    cfg.confidentialite.tags_exclus = []
    assert filtre.exclues(b, cfg) == {c}


def test_cles_masquees_avec_pieces_et_notes(zotero):
    secrete = zotero.fiche('Secrète', tags=('_privé',))
    pdf = zotero.pdf(secrete, 'Secrète.pdf')
    note = zotero.note(secrete)
    autre = zotero.fiche('Publique')
    zotero.pdf(autre, 'Publique.pdf')
    b = lecture.lire(zotero.enregistrer())
    cles = {e.id: e.cle for e in b.elements.values()} | {i: p.cle for i, p in b.pieces.items()}
    assert filtre.cles_masquees(b, Config(dossier_travail=Path('.'))) == {cles[secrete], cles[pdf], cles[note]}
