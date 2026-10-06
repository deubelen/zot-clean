"""zc voir (D127) : fiches montrées en entier, texte des PDF, filtre de confidentialité."""

from pathlib import Path

from zot_clean import lecture, voir
from zot_clean.config import Config


def pdf_avec_texte(texte: str) -> bytes:
    """Un PDF minimal mais valide, d'une page portant `texte`."""
    flux = f'BT /F1 12 Tf 72 720 Td ({texte}) Tj ET'.encode()
    objets = [b'<< /Type /Catalog /Pages 2 0 R >>',
              b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
              b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
              b'/Resources << /Font << /F1 5 0 R >> >> >>',
              b'<< /Length %d >>\nstream\n' % len(flux) + flux + b'\nendstream',
              b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    sortie, positions = bytearray(b'%PDF-1.4\n'), []
    for i, o in enumerate(objets, 1):
        positions.append(len(sortie))
        sortie += b'%d 0 obj\n' % i + o + b'\nendobj\n'
    xref = len(sortie)
    sortie += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objets) + 1)
    sortie += b''.join(b'%010d 00000 n \n' % p for p in positions)
    sortie += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objets) + 1, xref)
    return bytes(sortie)


def monde(zotero):
    theme = zotero.collection('Perception', zotero.collection('Fonds'))
    publique = zotero.fiche('Acquisition of color perception', auteurs=('Özgen',), date='2002',
                           collections=(theme,), tags=('#couleur',), DOI='10.1/x')
    pdf = zotero.pdf(publique, 'ozgen.pdf', pdf_avec_texte('Acquisition of color perception, E. Ozgen'))
    zotero.note(publique)
    secrete = zotero.fiche('Mon dossier médical', tags=('_privé',))
    pdf_secret = zotero.pdf(secrete, 'dossier.pdf', pdf_avec_texte('Diagnostic confidentiel'))
    abime = zotero.fiche('Un PDF abîmé')
    zotero.pdf(abime, 'abime.pdf', b'%PDF-1.4 pas un vrai PDF')
    b = lecture.lire(zotero.enregistrer())
    cles = {i: e.cle for i, e in b.elements.items()} | {i: p.cle for i, p in b.pieces.items()}
    return b, {n: cles[i] for n, i in (('publique', publique), ('pdf', pdf), ('secrete', secrete),
                                         ('pdf_secret', pdf_secret), ('abime', abime))}


def test_fiche_en_entier_et_texte_du_pdf(zotero):
    b, c = monde(zotero)
    texte = voir.decrire(b, Config(dossier_travail=Path('.')), [c['publique'], 'INCONNUE'])
    assert f"## {c['publique']} · Article de revue" in texte
    assert '- title : Acquisition of color perception' in texte and '- DOI : 10.1/x' in texte
    assert '- date : 2002' in texte and '- collections : Fonds/Perception' in texte and '#couleur' in texte
    assert '- notes : 1' in texte and 'E. Ozgen' in texte
    assert 'Aucune fiche ni pièce jointe de cette clé' in texte


def test_cle_de_piece_jointe_et_pdf_illisible(zotero):
    b, c = monde(zotero)
    texte = voir.decrire(b, Config(dossier_travail=Path('.')), [c['pdf'], c['abime']])
    assert f"## {c['publique']}" in texte and 'clé demandée' in texte
    assert '(texte illisible' in texte or '(aucun texte' in texte


def test_confidentialite(zotero):
    b, c = monde(zotero)
    cfg = Config(dossier_travail=Path('.'))
    texte = voir.decrire(b, cfg, [c['secrete'], c['pdf_secret']])
    assert 'médical' not in texte and 'Diagnostic' not in texte and '(fiche confidentielle)' in texte
    cfg.confidentialite.exclure_texte_integral = True
    texte = voir.decrire(b, cfg, [c['publique']])
    assert 'E. Ozgen' not in texte and 'exclu par la configuration' in texte


def test_texte_illisible_signale(zotero, tmp_path):
    chemin = tmp_path / 'brouille.pdf'
    chemin.write_bytes(pdf_avec_texte('!#$% &* )(*  + ,.-,0/213,54647,58:9#;=<,.8?><A1B/,C>ED=FHGI;JKFL4M4'))
    assert voir.texte_pdf(chemin) == '(texte illisible, polices du PDF mal encodées)'
    chemin.write_bytes(pdf_avec_texte('Un texte ordinaire, lisible, avec 3 chiffres et (quelques) signes.'))
    assert voir.texte_pdf(chemin).startswith('Un texte ordinaire')


def test_role_des_createurs(zotero):
    chapitre = zotero.fiche('Le goût de nécessité', type_='bookSection', auteurs=('Bourdieu',), editeurs=('Passeron',))
    b = lecture.lire(zotero.enregistrer())
    texte = voir.decrire(b, Config(dossier_travail=Path('.')), [b.elements[chapitre].cle])
    ligne = next(l for l in texte.splitlines() if l.startswith('- créateurs : '))
    assert ligne.count('(directeur)') == 1 and 'Passeron, A. (directeur)' in ligne and 'Bourdieu, A.' in ligne
    assert 'Bourdieu, A. (' not in ligne


def test_pdf_absent_du_disque_signale(zotero):
    """D168 : un PDF pas encore téléchargé est nommé, avec la façon de le faire venir."""
    f = zotero.fiche('Un article pas téléchargé')
    zotero.pdf(f, 'absent.pdf', None)
    b = lecture.lire(zotero.enregistrer())
    texte = voir.decrire(b, Config(dossier_travail=Path('.'), dossier_zotero=zotero.dossier), [b.elements[f].cle])
    assert '(fichier absent du disque)' in texte and '(fichier absent du disque, texte non lu)' in texte
    assert '**Attention.** 1 PDF de ces fiches est absent du disque' in texte
    assert '« Télécharger les fichiers »' in texte


def test_descendance_confidentielle_et_forme_du_tag(zotero):
    # D188 : une pièce jointe exclue sous une fiche publique n'est montrée que par sa clé, et les annotations d'une
    # fiche exclue sont masquées. D190 : `_Privé` vaut `_privé`.
    from zot_clean import filtre
    publique = zotero.fiche('Fiche publique')
    pj = zotero.pdf(publique, 'NOM_SECRET.pdf', contenu=pdf_avec_texte('TEXTE SECRET'))
    zotero.tags(pj, ['_Privé'])
    secrete = zotero.fiche('TITRE SECRET', tags=('_privé',))
    annotation = zotero.annotation(zotero.pdf(secrete, 'a.pdf'), tags=('DIAGNOSTIC',))
    b = lecture.lire(zotero.enregistrer())
    cfg = Config(dossier_travail=Path('.'), dossier_zotero=zotero.dossier)
    masquees = filtre.cles_masquees(b, cfg)
    assert b.elements[pj].cle in masquees and b.elements[annotation].cle in masquees
    sortie = voir.decrire(b, cfg, [b.elements[publique].cle])
    assert 'Fiche publique' in sortie and 'NOM_SECRET' not in sortie and 'TEXTE SECRET' not in sortie
    sortie = voir.decrire_tag(b, cfg, 'DIAGNOSTIC')
    assert 'TITRE SECRET' not in sortie and 'DIAGNOSTIC' not in sortie
