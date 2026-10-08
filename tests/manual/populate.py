"""Remplit le compte Zotero de test à partir de `fixtures.json` (D45, D54).

Usage, depuis la racine du dépôt :
    ZC_COMPTE_TEST=<identifiant du compte de test> uv run python tests/manual/populate.py --dossier <dossier de travail de test>

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

from zot_clean import config, api
from zot_clean.init import check_key

FIXTURES = Path(__file__).with_name('fixtures.json')
CLEAN = 70  # clean items added to the dirty ones, for about a hundred in all


def check_test_account(env: dict[str, str], expected: str | None, key_id: int) -> None:
    """Development safeguard: write only to the declared test account."""
    if not expected:
        raise SystemExit('ZC_COMPTE_TEST non défini. Donner l\'identifiant du compte de test.')
    if env.get('ZOTERO_USER_ID') != expected or key_id != int(expected):
        raise SystemExit(f'La clé du .env est celle du compte {key_id}, pas du compte de test {expected}. Abandon.')


def pdf(text: str) -> bytes:
    """A valid one-page PDF whose content depends on `text`."""
    stream = f'BT /F1 18 Tf 72 720 Td ({text}) Tj ET'.encode('latin-1')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
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


def api_item(f: dict, collections: dict[str, str]) -> dict:
    fields = {k: v for k, v in f.items() if k not in ('ref', 'creators', 'collections', 'tags', 'pdf', 'pdf2',
                                                        'notes', 'annoter')}
    fields['creators'] = [{'creatorType': 'author', 'lastName': n, 'firstName': p} for n, p in f.get('creators', [])]
    fields['collections'] = [collections[c] for c in f.get('collections', [])]
    fields['tags'] = [{'tag': t, 'type': typ} for t, typ in f.get('tags', [])]
    return fields


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--dossier', dest='folder', metavar='DOSSIER', type=Path, required=True, help='dossier de travail du compte de test')
    args = p.parse_args()
    cfg = config.load(args.folder.resolve())
    env = config.read_env(cfg.workspace)
    info = check_key(env.get('ZOTERO_API_KEY', ''))
    check_test_account(env, os.environ.get('ZC_COMPTE_TEST'), info.user)
    client = api.from_config(cfg)
    total = int(client._request('GET', f'{client.prefix}/items', params={'limit': 1}).headers['Total-Results'])
    if total:
        raise SystemExit(f'La bibliothèque de test contient déjà {total} élément(s). La vider dans Zotero d\'abord.')

    data = json.loads(FIXTURES.read_text(encoding='utf-8'))
    collections: dict[str, str] = {}
    for path in data['collections']:
        parent, _, name = path.rpartition('/')
        [collections[path]] = client.create([{'name': name, 'parentCollection': collections[parent] if parent else False}],
                                             'collections')
    items = list(data['fiches'])
    items += [{'ref': f'propre-{i}', 'itemType': 'journalArticle', 'title': f'Article propre numéro {i}',
                'creators': [['Auteur', f'Prénom {i}']], 'date': str(1990 + i % 30),
                'DOI': f'10.9999/zc.propre.{i:03d}', 'collections': ['Fonds/Psychologie']} for i in range(CLEAN)]
    keys = dict(zip((f['ref'] for f in items), client.create([api_item(f, collections) for f in items])))
    notes = [{'itemType': 'note', 'parentItem': keys[f['ref']], 'note': f'<p>{n}</p>'}
             for f in items for n in f.get('notes', [])]
    client.create(notes)

    to_annotate = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in items:
            for field_name in ('pdf', 'pdf2'):
                if content := f.get(field_name):
                    file = Path(tmp) / f"{f['ref']}-{field_name}.pdf"
                    file.write_bytes(pdf(f'zot-clean test {content}'))
                    res = client.zot.attachment_simple([str(file)], keys[f['ref']])
                    if res.get('failure'):
                        raise SystemExit(f"Envoi du PDF de {f['ref']} refusé : {res['failure']}")
                    if f.get('annoter') and field_name == 'pdf':
                        to_annotate.append(next(iter(res.get('success', []) + res.get('unchanged', [])))['key'])
    client.create([{'itemType': 'annotation', 'parentItem': k, 'annotationType': 'highlight',
                   'annotationText': 'zot-clean test', 'annotationComment': 'Annotation de test',
                   'annotationColor': '#ffd400', 'annotationPageLabel': '1',
                   'annotationSortIndex': '00000|000000|00000',
                   'annotationPosition': json.dumps({'pageIndex': 0, 'rects': [[72, 715, 250, 740]]})}
                  for k in to_annotate])
    print(f'{len(collections)} collections, {len(items)} fiches, {len(notes)} notes, '
          f'{len(to_annotate)} annotation(s) créées sur le compte {info.user}.')
    print('Synchroniser maintenant le profil Zotero de test, puis lancer `zc audit` dans le dossier de travail de test.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
