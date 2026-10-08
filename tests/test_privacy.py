from pathlib import Path

from zot_clean import privacy, reader
from zot_clean.config import Config
from zot_clean.lang import language


def test_excluded_tags_and_collections(zotero):
    subjects = zotero.collection('Fonds')
    private = zotero.collection('Privé', subjects)
    under = zotero.collection('Dossiers', private)
    other = zotero.collection('Autre')
    a = zotero.item('Taguée', tags=('_privé',))
    b_ = zotero.item('Dans une sous-collection', collections=(under,))
    c = zotero.item('Ailleurs', collections=(other, subjects))
    b = reader.read(zotero.save())
    cfg = Config(workspace=Path('.'))
    cfg.privacy.excluded_collections = ['Fonds/Privé']
    assert privacy.excluded_items(b, cfg) == {a, b_}
    cfg.privacy.excluded_collections = ['Autre']
    cfg.privacy.excluded_tags = []
    assert privacy.excluded_items(b, cfg) == {c}


def test_keys_hidden_with_attachments_and_notes(zotero):
    secret_item = zotero.item('Secrète', tags=('_privé',))
    pdf = zotero.pdf(secret_item, 'Secrète.pdf')
    note = zotero.note(secret_item)
    other = zotero.item('Publique')
    zotero.pdf(other, 'Publique.pdf')
    b = reader.read(zotero.save())
    keys = {e.id: e.key for e in b.all_items.values()} | {i: p.key for i, p in b.attachments.items()}
    assert privacy.hidden_keys(b, Config(workspace=Path('.'))) == {keys[secret_item], keys[pdf], keys[note]}


def test_mask_in_both_languages():
    assert privacy.mask() == '(fiche confidentielle)'
    with language('en'):
        assert privacy.mask() == '(confidential item)'
