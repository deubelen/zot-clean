"""Sonde de l'API web pour les collections (D114, D122), sur le compte de test seulement.

Vérifie ce que le plan de rangement suppose :
1. une collection se crée avec une clé fournie par le client, ses sous-collections dans la même requête ;
2. une collection se renomme et se déplace (`name`, `parentCollection`) avec contrôle de version ;
3. une collection va à la corbeille (`deleted`) et en sort ;
4. une fiche entre dans une collection créée ainsi.
Les collections de la sonde sont ensuite supprimées pour de bon. Rien d'autre n'est touché.

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manual/probe_collections.py --dossier ~/zc-test
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual import populate  # noqa: E402
from zot_clean import config, api  # noqa: E402

ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


def key() -> str:
    return ''.join(secrets.choice(ALPHABET) for _ in range(8))


def collection(client, k: str) -> dict:
    return client._request('GET', f'{client.prefix}/collections/{k}').json()


def write_collections(client, objects: list[dict]) -> dict:
    return client._request('POST', f'{client.prefix}/collections', json=objects).json()


def delete(client, path: str, version: int) -> None:
    """Permanent deletion. `Client._request` sets its own headers, they are completed here."""
    headers = client.zot.default_headers() | {'If-Unmodified-Since-Version': str(version)}
    r = client.zot.client.request('DELETE', client.zot.endpoint + path, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f'DELETE {path} : {r.status_code} {r.text[:200]}')


def check(condition: bool, message: str, results: list) -> None:
    results.append((condition, message))
    print(f"{'OK    ' if condition else 'ÉCHEC '} {message}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--dossier', dest='folder', metavar='DOSSIER', type=Path, required=True, help='dossier de travail du compte de test')
    args = p.parse_args()
    cfg = config.load(args.folder.expanduser())
    env = config.read_env(cfg.workspace)
    info = populate.check_key(env.get('ZOTERO_API_KEY', ''))
    populate.check_test_account(env, os.environ.get('ZC_COMPTE_TEST'), info.user)
    client = api.from_config(cfg)

    res: list = []
    a, b, c = key(), key(), key()
    newly_created = [a, b, c]
    try:
        # 1. Creation with supplied keys, parent and child in the same request.
        d = write_collections(client, [
            {'key': a, 'version': 0, 'name': 'zc-sonde parent', 'parentCollection': False},
            {'key': b, 'version': 0, 'name': 'zc-sonde enfant', 'parentCollection': a},
            {'key': c, 'version': 0, 'name': 'zc-sonde autre', 'parentCollection': False},
        ])
        check(not d.get('failed') and [d['success'][str(i)] for i in range(3)] == [a, b, c],
                 f"création avec clés fournies ({d.get('failed') or 'acceptée'})", res)
        check(collection(client, b)['data']['parentCollection'] == a, 'enfant créé sous son parent', res)

        # 2. Renaming and moving, with the version.
        v = collection(client, b)['version']
        d = write_collections(client, [{'key': b, 'version': v, 'name': 'zc-sonde renommée', 'parentCollection': c}])
        data = collection(client, b)['data']
        check(not d.get('failed') and data['name'] == 'zc-sonde renommée' and data['parentCollection'] == c,
                 'renommage et déplacement', res)
        d = write_collections(client, [{'key': b, 'version': v, 'name': 'conflit attendu'}])
        check(bool(d.get('failed')), f"version périmée refusée ({d.get('failed')})", res)

        # 3. Trash and back.
        v = collection(client, c)['version']
        d = write_collections(client, [{'key': c, 'version': v, 'deleted': True}])
        data = collection(client, c)['data']
        check(not d.get('failed') and bool(data.get('deleted')), f"mise à la corbeille ({d.get('failed') or data.get('deleted')})", res)
        fetched = client.collections([a, c])
        check(set(fetched) == {a, c} and fetched[c].get('deleted') is True,
                 'lecture groupée par clés, corbeille comprise (Client.collections)', res)
        v = collection(client, c)['version']
        d = write_collections(client, [{'key': c, 'version': v, 'deleted': False}])
        check(not d.get('failed') and not collection(client, c)['data'].get('deleted'), 'sortie de la corbeille', res)

        # 4. An item enters a collection created with a supplied key.
        item = client.create([{'itemType': 'note', 'note': '<p>zc-sonde</p>', 'collections': [a]}])[0]
        newly_created.append(item)
        check(a in client.items([item])[item]['collections'], 'fiche rangée dans la collection', res)
    finally:
        # Permanent cleanup, item then collections.
        if len(newly_created) > 3:
            v = client.items([newly_created[3]])[newly_created[3]]['version']
            delete(client, f'{client.prefix}/items/{newly_created[3]}', v)
        for k in (b, a, c):
            try:
                v = collection(client, k)['version']
                delete(client, f'{client.prefix}/collections/{k}', v)
            except Exception as e:  # a collection never created has nothing to clean
                print(f'nettoyage de {k} : {e}')
    failures = [m for ok, m in res if not ok]
    print(f"\n{len(res) - len(failures)} vérification(s) sur {len(res)} réussie(s).")
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
