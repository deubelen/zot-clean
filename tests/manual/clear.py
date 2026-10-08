"""Vide la bibliothèque du compte Zotero de test, pour la remplir à nouveau avec `populate.py`.

Usage, depuis la racine du dépôt :
    ZC_COMPTE_TEST=<identifiant du compte de test> uv run python tests/manual/clear.py --dossier <dossier de travail de test>

Refuse d'écrire si l'identifiant de la clé n'est pas celui de `ZC_COMPTE_TEST`. Supprime par l'API toutes les
fiches (corbeille comprise), les collections, les recherches enregistrées et les couleurs des tags. Synchroniser
ensuite le profil de test dans Zotero. Jamais sur un compte réel.
"""

import argparse
import os
from pathlib import Path

from populate import check_test_account
from zot_clean import config, api
from zot_clean.init import check_key


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--dossier', dest='folder', metavar='DOSSIER', type=Path, required=True, help='dossier de travail du compte de test')
    args = p.parse_args()
    cfg = config.load(args.folder.resolve())
    env = config.read_env(cfg.workspace)
    info = check_key(env.get('ZOTERO_API_KEY', ''))
    check_test_account(env, os.environ.get('ZC_COMPTE_TEST'), info.user)
    client = api.from_config(cfg)
    zot = client.zot
    prefix = f'{zot.endpoint}/users/{info.user}'

    def delete(what: str, keys: list[str]) -> None:
        """DELETE in batches of 50, with the current library version (the one each response gives)."""
        for i in range(0, len(keys), 50):
            r = zot.client.request('DELETE', f'{prefix}/{what}', params={what[:-1] + 'Key': ','.join(keys[i:i + 50])},
                                   headers=zot.default_headers()
                                   | {'If-Unmodified-Since-Version': str(client.server_version())})
            r.raise_for_status()

    all_entries = zot.everything(zot.items(includeTrashed=1))
    all_items = [i['key'] for i in all_entries if not i['data'].get('parentItem')]
    delete('items', all_items)
    children = [i['key'] for i in zot.everything(zot.items(includeTrashed=1))]
    delete('items', children)
    collections = [c['key'] for c in zot.everything(zot.collections())]
    delete('collections', collections)
    searches = [r['key'] for r in zot.searches()]
    delete('searches', searches)
    settings = zot.settings()
    if 'tagColors' in settings:
        r = zot.client.request('DELETE', f'{prefix}/settings/tagColors',
                               headers=zot.default_headers()
                               | {'If-Unmodified-Since-Version': str(settings['tagColors']['version'])})
        r.raise_for_status()
    rest = len(zot.items(limit=1, includeTrashed=1))
    print(f'{len(all_items)} fiche(s) ou note(s) isolée(s), puis {len(children)} enfant(s) restant(s) supprimés, '
          f'{len(collections)} collection(s), {len(searches)} recherche(s). Reste : {rest} élément(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
