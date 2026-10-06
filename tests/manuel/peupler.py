"""Remplit le compte Zotero de test à partir de `fixtures.json` (D45, D54).

Usage, depuis la racine du dépôt :
    ZC_COMPTE_TEST=<identifiant du compte de test> uv run python tests/manuel/peupler.py --dossier <dossier de travail de test>

Le dossier de travail de test est créé par `zc init`, avec la clé du compte de
test. Le script refuse d'écrire si l'identifiant de la clé n'est pas celui de
`ZC_COMPTE_TEST`, ou si la bibliothèque n'est pas vide. Tout passe par l'API
web, qui donne des clés valides. Synchroniser ensuite le second profil Zotero.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from zot_clean import config, ecriture
from zot_clean.init import verifier_cle

FIXTURES = Path(__file__).with_name('fixtures.json')
PROPRES = 70  # fiches propres ajoutées aux fiches sales, pour une centaine en tout


def verifier_compte_test(env: dict[str, str], attendu: str | None, id_cle: int) -> None:
    """Garde-fou de développement : n'écrire que sur le compte de test déclaré."""
    if not attendu:
        raise SystemExit('ZC_COMPTE_TEST non défini. Donner l\'identifiant du compte de test.')
    if env.get('ZOTERO_USER_ID') != attendu or id_cle != int(attendu):
        raise SystemExit(f'La clé du .env est celle du compte {id_cle}, pas du compte de test {attendu}. Abandon.')


def pdf(texte: str) -> bytes:
    """Un PDF d'une page, valide, dont le contenu dépend de `texte`."""
    flux = f'BT /F1 18 Tf 72 720 Td ({texte}) Tj ET'.encode('latin-1')
    objets = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
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


def fiche_api(f: dict, collections: dict[str, str]) -> dict:
    champs = {k: v for k, v in f.items() if k not in ('ref', 'creators', 'collections', 'tags', 'pdf', 'pdf2',
                                                        'notes', 'annoter')}
    champs['creators'] = [{'creatorType': 'author', 'lastName': n, 'firstName': p} for n, p in f.get('creators', [])]
    champs['collections'] = [collections[c] for c in f.get('collections', [])]
    champs['tags'] = [{'tag': t, 'type': typ} for t, typ in f.get('tags', [])]
    return champs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--dossier', type=Path, required=True, help='dossier de travail du compte de test')
    args = p.parse_args()
    cfg = config.charger(args.dossier.resolve())
    env = config.lire_env(cfg.dossier_travail)
    info = verifier_cle(env.get('ZOTERO_API_KEY', ''))
    verifier_compte_test(env, os.environ.get('ZC_COMPTE_TEST'), info.utilisateur)
    client = ecriture.depuis_config(cfg)
    total = int(client._requete('GET', f'{client.prefixe}/items', params={'limit': 1}).headers['Total-Results'])
    if total:
        raise SystemExit(f'La bibliothèque de test contient déjà {total} élément(s). La vider dans Zotero d\'abord.')

    donnees = json.loads(FIXTURES.read_text(encoding='utf-8'))
    collections: dict[str, str] = {}
    for chemin in donnees['collections']:
        parent, _, nom = chemin.rpartition('/')
        [collections[chemin]] = client.creer([{'name': nom, 'parentCollection': collections[parent] if parent else False}],
                                             'collections')
    fiches = list(donnees['fiches'])
    fiches += [{'ref': f'propre-{i}', 'itemType': 'journalArticle', 'title': f'Article propre numéro {i}',
                'creators': [['Auteur', f'Prénom {i}']], 'date': str(1990 + i % 30),
                'DOI': f'10.9999/zc.propre.{i:03d}', 'collections': ['Fonds/Psychologie']} for i in range(PROPRES)]
    cles = dict(zip((f['ref'] for f in fiches), client.creer([fiche_api(f, collections) for f in fiches])))
    notes = [{'itemType': 'note', 'parentItem': cles[f['ref']], 'note': f'<p>{n}</p>'}
             for f in fiches for n in f.get('notes', [])]
    client.creer(notes)

    a_annoter = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in fiches:
            for champ in ('pdf', 'pdf2'):
                if contenu := f.get(champ):
                    fichier = Path(tmp) / f"{f['ref']}-{champ}.pdf"
                    fichier.write_bytes(pdf(f'zot-clean test {contenu}'))
                    res = client.zot.attachment_simple([str(fichier)], cles[f['ref']])
                    if res.get('failure'):
                        raise SystemExit(f"Envoi du PDF de {f['ref']} refusé : {res['failure']}")
                    if f.get('annoter') and champ == 'pdf':
                        a_annoter.append(next(iter(res.get('success', []) + res.get('unchanged', [])))['key'])
    client.creer([{'itemType': 'annotation', 'parentItem': k, 'annotationType': 'highlight',
                   'annotationText': 'zot-clean test', 'annotationComment': 'Annotation de test',
                   'annotationColor': '#ffd400', 'annotationPageLabel': '1',
                   'annotationSortIndex': '00000|000000|00000',
                   'annotationPosition': json.dumps({'pageIndex': 0, 'rects': [[72, 715, 250, 740]]})}
                  for k in a_annoter])
    print(f'{len(collections)} collections, {len(fiches)} fiches, {len(notes)} notes, '
          f'{len(a_annoter)} annotation(s) créées sur le compte {info.utilisateur}.')
    print('Synchroniser maintenant le profil Zotero de test, puis lancer `zc audit` dans le dossier de travail de test.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
