"""Sonde de l'API web pour les collections (D114, D122), sur le compte de test seulement.

Vérifie ce que le plan de rangement suppose :
1. une collection se crée avec une clé fournie par le client, ses sous-collections dans la même requête ;
2. une collection se renomme et se déplace (`name`, `parentCollection`) avec contrôle de version ;
3. une collection va à la corbeille (`deleted`) et en sort ;
4. une fiche entre dans une collection créée ainsi.
Les collections de la sonde sont ensuite supprimées pour de bon. Rien d'autre n'est touché.

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manuel/sonde_collections.py --dossier ~/zc-test
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manuel import peupler  # noqa: E402
from zot_clean import config, ecriture  # noqa: E402

ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


def cle() -> str:
    return ''.join(secrets.choice(ALPHABET) for _ in range(8))


def collection(client, k: str) -> dict:
    return client._requete('GET', f'{client.prefixe}/collections/{k}').json()


def ecrire_collections(client, objets: list[dict]) -> dict:
    return client._requete('POST', f'{client.prefixe}/collections', json=objets).json()


def supprimer(client, chemin: str, version: int) -> None:
    """Suppression définitive. `Client._requete` fixe ses propres en-têtes, on les complète ici."""
    en_tetes = client.zot.default_headers() | {'If-Unmodified-Since-Version': str(version)}
    r = client.zot.client.request('DELETE', client.zot.endpoint + chemin, headers=en_tetes)
    if r.status_code >= 400:
        raise RuntimeError(f'DELETE {chemin} : {r.status_code} {r.text[:200]}')


def verifier(condition: bool, message: str, resultats: list) -> None:
    resultats.append((condition, message))
    print(f"{'OK    ' if condition else 'ÉCHEC '} {message}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--dossier', type=Path, required=True, help='dossier de travail du compte de test')
    args = p.parse_args()
    cfg = config.charger(args.dossier.expanduser())
    env = config.lire_env(cfg.dossier_travail)
    info = peupler.verifier_cle(env.get('ZOTERO_API_KEY', ''))
    peupler.verifier_compte_test(env, os.environ.get('ZC_COMPTE_TEST'), info.utilisateur)
    client = ecriture.depuis_config(cfg)

    res: list = []
    a, b, c = cle(), cle(), cle()
    creees = [a, b, c]
    try:
        # 1. Création avec clés fournies, parent et enfant dans la même requête.
        d = ecrire_collections(client, [
            {'key': a, 'version': 0, 'name': 'zc-sonde parent', 'parentCollection': False},
            {'key': b, 'version': 0, 'name': 'zc-sonde enfant', 'parentCollection': a},
            {'key': c, 'version': 0, 'name': 'zc-sonde autre', 'parentCollection': False},
        ])
        verifier(not d.get('failed') and [d['success'][str(i)] for i in range(3)] == [a, b, c],
                 f"création avec clés fournies ({d.get('failed') or 'acceptée'})", res)
        verifier(collection(client, b)['data']['parentCollection'] == a, 'enfant créé sous son parent', res)

        # 2. Renommage et déplacement, avec la version.
        v = collection(client, b)['version']
        d = ecrire_collections(client, [{'key': b, 'version': v, 'name': 'zc-sonde renommée', 'parentCollection': c}])
        data = collection(client, b)['data']
        verifier(not d.get('failed') and data['name'] == 'zc-sonde renommée' and data['parentCollection'] == c,
                 'renommage et déplacement', res)
        d = ecrire_collections(client, [{'key': b, 'version': v, 'name': 'conflit attendu'}])
        verifier(bool(d.get('failed')), f"version périmée refusée ({d.get('failed')})", res)

        # 3. Corbeille et retour.
        v = collection(client, c)['version']
        d = ecrire_collections(client, [{'key': c, 'version': v, 'deleted': True}])
        data = collection(client, c)['data']
        verifier(not d.get('failed') and bool(data.get('deleted')), f"mise à la corbeille ({d.get('failed') or data.get('deleted')})", res)
        lues = client.collections([a, c])
        verifier(set(lues) == {a, c} and lues[c].get('deleted') is True,
                 'lecture groupée par clés, corbeille comprise (Client.collections)', res)
        v = collection(client, c)['version']
        d = ecrire_collections(client, [{'key': c, 'version': v, 'deleted': False}])
        verifier(not d.get('failed') and not collection(client, c)['data'].get('deleted'), 'sortie de la corbeille', res)

        # 4. Une fiche entre dans une collection créée avec une clé fournie.
        fiche = client.creer([{'itemType': 'note', 'note': '<p>zc-sonde</p>', 'collections': [a]}])[0]
        creees.append(fiche)
        verifier(a in client.fiches([fiche])[fiche]['collections'], 'fiche rangée dans la collection', res)
    finally:
        # Nettoyage définitif, fiche puis collections.
        if len(creees) > 3:
            v = client.fiches([creees[3]])[creees[3]]['version']
            supprimer(client, f'{client.prefixe}/items/{creees[3]}', v)
        for k in (b, a, c):
            try:
                v = collection(client, k)['version']
                supprimer(client, f'{client.prefixe}/collections/{k}', v)
            except Exception as e:  # une collection jamais créée n'a rien à nettoyer
                print(f'nettoyage de {k} : {e}')
    echecs = [m for ok, m in res if not ok]
    print(f"\n{len(res) - len(echecs)} vérification(s) sur {len(res)} réussie(s).")
    return 1 if echecs else 0


if __name__ == '__main__':
    sys.exit(main())
