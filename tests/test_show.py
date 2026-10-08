"""zc voir (D127): items shown in full, PDF text, privacy filter."""

from pathlib import Path

from zot_clean import reader, show
from zot_clean.config import Config
from zot_clean.lang import language


def pdf_with_text(text: str) -> bytes:
    """A minimal but valid one-page PDF carrying `text`."""
    stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
              b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
              b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
              b'/Resources << /Font << /F1 5 0 R >> >> >>',
              b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
              b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    output, positions = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objects, 1):
        positions.append(len(output))
        output += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    xref = len(output)
    output += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    output += b''.join(b'%010d 00000 n \n' % p for p in positions)
    output += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return bytes(output)


def world(zotero):
    theme = zotero.collection('Perception', zotero.collection('Fonds'))
    public_item = zotero.item('Acquisition of color perception', authors=('Özgen',), date='2002',
                           collections=(theme,), tags=('#couleur',), DOI='10.1/x')
    pdf = zotero.pdf(public_item, 'ozgen.pdf', pdf_with_text('Acquisition of color perception, E. Ozgen'))
    note = zotero.note(public_item)
    lone_note = zotero.note()
    secret_item = zotero.item('Mon dossier médical', tags=('_privé',))
    secret_pdf = zotero.pdf(secret_item, 'dossier.pdf', pdf_with_text('Diagnostic confidentiel'))
    damaged = zotero.item('Un PDF abîmé')
    zotero.pdf(damaged, 'abime.pdf', b'%PDF-1.4 pas un vrai PDF')
    b = reader.read(zotero.save())
    keys = {i: e.key for i, e in b.all_items.items()} | {i: p.key for i, p in b.attachments.items()}
    return b, {n: keys[i] for n, i in (('publique', public_item), ('pdf', pdf), ('secrete', secret_item),
                                         ('pdf_secret', secret_pdf), ('abime', damaged), ('note', note),
                                         ('note_isolee', lone_note))}


def test_whole_item_and_pdf_text(zotero):
    b, c = world(zotero)
    text = show.describe(b, Config(workspace=Path('.')), [c['publique'], 'INCONNUE'])
    assert f"## {c['publique']} · Article de revue" in text
    assert '- title : Acquisition of color perception' in text and '- DOI : 10.1/x' in text
    assert '- date : 2002' in text and '- collections : Fonds/Perception' in text and '#couleur' in text
    assert '- notes : 1' in text and 'E. Ozgen' in text
    assert 'Aucune fiche ni pièce jointe de cette clé' in text


def test_attachment_key_and_unreadable_pdf(zotero):
    b, c = world(zotero)
    text = show.describe(b, Config(workspace=Path('.')), [c['pdf'], c['abime']])
    assert f"## {c['publique']}" in text and 'clé demandée' in text
    assert '(texte illisible' in text or '(aucun texte' in text


def test_note_key_designates_its_item(zotero):
    b, c = world(zotero)
    text = show.describe(b, Config(workspace=Path('.')), [c['note'], c['publique'], c['note_isolee']])
    assert text.count(f"## {c['publique']} · Article de revue") == 1
    assert f"- notes : 1 ({c['note']}, clé demandée, texte jamais montré)" in text
    assert f"## {c['note_isolee']} · " in text and "Le texte d'une note n'est jamais montré." in text


def test_privacy(zotero):
    b, c = world(zotero)
    cfg = Config(workspace=Path('.'))
    text = show.describe(b, cfg, [c['secrete'], c['pdf_secret']])
    assert 'médical' not in text and 'Diagnostic' not in text and '(fiche confidentielle)' in text
    cfg.privacy.exclude_full_text = True
    text = show.describe(b, cfg, [c['publique']])
    assert 'E. Ozgen' not in text and 'exclu par la configuration' in text


def test_unreadable_text_reported(zotero, tmp_path):
    path = tmp_path / 'brouille.pdf'
    path.write_bytes(pdf_with_text('!#$% &* )(*  + ,.-,0/213,54647,58:9#;=<,.8?><A1B/,C>ED=FHGI;JKFL4M4'))
    assert show.pdf_text(path) == '(texte illisible, polices du PDF mal encodées)'
    path.write_bytes(pdf_with_text('Un texte ordinaire, lisible, avec 3 chiffres et (quelques) signes.'))
    assert show.pdf_text(path).startswith('Un texte ordinaire')


def test_role_of_creators(zotero):
    chapter = zotero.item('Le goût de nécessité', type_='bookSection', authors=('Bourdieu',), editors=('Passeron',))
    b = reader.read(zotero.save())
    text = show.describe(b, Config(workspace=Path('.')), [b.all_items[chapter].key])
    line = next(l for l in text.splitlines() if l.startswith('- créateurs : '))
    assert line.count('(directeur)') == 1 and 'Passeron, A. (directeur)' in line and 'Bourdieu, A.' in line
    assert 'Bourdieu, A. (' not in line


def test_pdf_missing_from_disk_reported(zotero):
    """D168 : a PDF not yet downloaded is named, with the way to fetch it."""
    f = zotero.item('Un article pas téléchargé')
    zotero.pdf(f, 'absent.pdf', None)
    b = reader.read(zotero.save())
    text = show.describe(b, Config(workspace=Path('.'), zotero_dir=zotero.folder), [b.all_items[f].key])
    assert '(fichier absent du disque)' in text and '(fichier absent du disque, texte non lu)' in text
    assert '**Attention.** 1 PDF de ces fiches est absent du disque' in text
    assert '« Télécharger les fichiers »' in text


def test_confidential_descendants_and_tag_form(zotero):
    # D188 : an excluded attachment under a public item is shown only by its key, and the annotations of an
    # excluded item are hidden. D190 : `_Privé` equals `_privé`.
    from zot_clean import privacy
    public_item = zotero.item('Fiche publique')
    att = zotero.pdf(public_item, 'NOM_SECRET.pdf', content=pdf_with_text('TEXTE SECRET'))
    zotero.tags(att, ['_Privé'])
    secret_item = zotero.item('TITRE SECRET', tags=('_privé',))
    annotation = zotero.annotation(zotero.pdf(secret_item, 'a.pdf'), tags=('DIAGNOSTIC',))
    b = reader.read(zotero.save())
    cfg = Config(workspace=Path('.'), zotero_dir=zotero.folder)
    hidden = privacy.hidden_keys(b, cfg)
    assert b.all_items[att].key in hidden and b.all_items[annotation].key in hidden
    output = show.describe(b, cfg, [b.all_items[public_item].key])
    assert 'Fiche publique' in output and 'NOM_SECRET' not in output and 'TEXTE SECRET' not in output
    output = show.describe_tag(b, cfg, 'DIAGNOSTIC')
    assert 'TITRE SECRET' not in output and 'DIAGNOSTIC' not in output


def test_texts_in_english(zotero):
    b, c = world(zotero)
    with language('en'):
        text = show.describe(b, Config(workspace=Path('.')), [c['publique'], c['secrete'], 'INCONNUE'])
        assert f"## {c['publique']} · Journal Article" in text and '- creators: ' in text
        assert 'No item or attachment with this key outside the Zotero trash.' in text
        assert '- title: Acquisition' in text and '- DOI: 10.1/x' in text and ' : ' not in text.split('###')[0]
        assert 'Excluded by the privacy filter. Ask the user to look at it in Zotero.' in text
        assert '(confidential item)' in text and f"### Attachment {c['pdf']} · ozgen.pdf" in text


def test_line_breaks_of_the_pdf_separate_words(zotero, tmp_path):
    """Pilot bench: « médecins de » at the end of a line and « province » on the next were shown « deprovince »."""
    path = tmp_path / 'deux-lignes.pdf'
    path.write_bytes(pdf_with_text('Aupres des medecins de) Tj 0 -14 Td (province et de Paris'))
    assert show.pdf_text(path) == 'Aupres des medecins de province et de Paris'


def test_two_attachments_of_one_item_show_it_once(zotero):
    b, c = world(zotero)
    text = show.describe(b, Config(workspace=Path('.')), [c['pdf'], c['publique'], c['pdf']])
    assert text.count(f"## {c['publique']}") == 1 and 'clé demandée' in text
