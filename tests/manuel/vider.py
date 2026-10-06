"""Vide la bibliothèque du compte Zotero de test, pour la remplir à nouveau avec `peupler.py`.

Usage, depuis la racine du dépôt :
    ZC_COMPTE_TEST=<identifiant du compte de test> uv run python tests/manuel/vider.py --dossier <dossier de travail de test>

Refuse d'écrire si l'identifiant de la clé n'est pas celui de `ZC_COMPTE_TEST`. Supprime par l'API toutes les
fiches (corbeille comprise), les collections, les recherches enregistrées et les couleurs des tags. Synchroniser
ensuite le profil de test dans Zotero. Jamais sur un compte réel.
"""

import argparse
import os
from pathlib import Path

from peupler import verifier_compte_test
from zot_clean import config, ecriture
from zot_clean.init import verifier_cle


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--dossier', type=Path, required=True, help='dossier de travail du compte de test')
    args = p.parse_args()
    cfg = config.charger(args.dossier.resolve())
    env = config.lire_env(cfg.dossier_travail)
    info = verifier_cle(env.get('ZOTERO_API_KEY', ''))
    verifier_compte_test(env, os.environ.get('ZC_COMPTE_TEST'), info.utilisateur)
    client = ecriture.depuis_config(cfg)
    zot = client.zot
    prefixe = f'{zot.endpoint}/users/{info.utilisateur}'

    def supprimer(quoi: str, cles: list[str]) -> None:
        """DELETE par lots de 50, avec la version courante de la bibliothèque (celle que donne chaque réponse)."""
        for i in range(0, len(cles), 50):
            r = zot.client.request('DELETE', f'{prefixe}/{quoi}', params={quoi[:-1] + 'Key': ','.join(cles[i:i + 50])},
                                   headers=zot.default_headers()
                                   | {'If-Unmodified-Since-Version': str(client.version_serveur())})
            r.raise_for_status()

    tous = zot.everything(zot.items(includeTrashed=1))
    elements = [i['key'] for i in tous if not i['data'].get('parentItem')]
    supprimer('items', elements)
    enfants = [i['key'] for i in zot.everything(zot.items(includeTrashed=1))]
    supprimer('items', enfants)
    collections = [c['key'] for c in zot.everything(zot.collections())]
    supprimer('collections', collections)
    recherches = [r['key'] for r in zot.searches()]
    supprimer('searches', recherches)
    reglages = zot.settings()
    if 'tagColors' in reglages:
        r = zot.client.request('DELETE', f'{prefixe}/settings/tagColors',
                               headers=zot.default_headers()
                               | {'If-Unmodified-Since-Version': str(reglages['tagColors']['version'])})
        r.raise_for_status()
    reste = len(zot.items(limit=1, includeTrashed=1))
    print(f'{len(elements)} fiche(s) ou note(s) isolée(s), puis {len(enfants)} enfant(s) restant(s) supprimés, '
          f'{len(collections)} collection(s), {len(recherches)} recherche(s). Reste : {reste} élément(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
