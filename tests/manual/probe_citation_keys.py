"""Sonde des clés de citation avec Better BibTeX (D146, dernier point), sur le compte de test seulement.

Suppose Better BibTeX (version 8 ou plus, pour Zotero 8 ou plus) installé et actif dans le profil Zotero
de test, avec ses réglages par défaut (remplissage des clés manquantes après 2 secondes). Sans lui, la
phase --ecrire s'arrête en le disant.

Vérifie, en quatre phases séparées par des synchronisations du profil de test :
1. une clé reçue avec une fiche créée par l'API est gardée par BBT ;
2. BBT remplit la clé d'une fiche reçue sans clé ;
3. une clé `citationKey` écrite par l'API sur une fiche qui en avait une est gardée par BBT ;
4. une clé vidée par l'API est remplie de nouveau par BBT ;
5. deux fiches qui reçoivent la même clé : BBT laisse-t-il le double ;
6. une ligne `tex.ids: ancienneCle` dans Extra : que fait l'export BibLaTeX (question) ;
7. l'installation de BBT a-t-elle créé un dossier `better-bibtex/` (constat et question).

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manual/probe_citation_keys.py --dossier ~/zc-test --preparer
    (synchroniser, attendre dix secondes, synchroniser encore)
    ... --ecrire
    (synchroniser, attendre dix secondes, synchroniser encore)
    ... --verifier
    ... --nettoyer

Les fiches de la sonde ont un titre qui commence par « zc-sonde clés ». --nettoyer les supprime pour de bon.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual.probe_tools import Probe, arguments  # noqa: E402

CREATED = 'zcSondeCreee'
WRITTEN = 'zcSondeEcrite'
DOUBLE = 'zcSondeDouble'
ALIAS = 'zcSondeAlias'
OLD = 'zcSondeAncienne'
IDS_LINE = f'tex.ids: {OLD}'
WAIT = 'synchroniser le profil de test dans Zotero, attendre une dizaine de secondes (BBT remplit les clés), ' \
           'synchroniser encore pour envoyer ces clés, puis lancer la phase --{}.'

# role -> (title, author, key given at creation)
ITEMS = {
    'creee': ('zc-sonde clés, créée avec sa clé', 'Abeille', CREATED),
    'ecrite': ('zc-sonde clés, clé écrite par l\'API', 'Bouleau', ''),
    'videe': ('zc-sonde clés, clé vidée par l\'API', 'Castor', ''),
    'double1': ('zc-sonde clés, premier double', 'Dauphin', ''),
    'double2': ('zc-sonde clés, second double', 'Écureuil', ''),
    'alias': ('zc-sonde clés, alias dans Extra', 'Faucon', ALIAS),
}

PHASES = {
    'preparer': 'crée six fiches, dont deux avec une clé',
    'ecrire': 'écrit, vide et double des clés par l\'API (après synchronisation)',
    'verifier': 'compare la copie locale à ce qui est attendu (après synchronisation)',
    'nettoyer': 'supprime les fiches de la sonde',
}


def local_key(lib, k: str) -> str:
    return lib.by_key()[k].fields.get('citationKey', '')


def prepare(s: Probe) -> int:
    state = s.new_state()
    objects = []
    for i, (role, (title, author, key)) in enumerate(ITEMS.items()):
        o = {'itemType': 'journalArticle', 'title': title, 'date': str(2001 + i),
             'creators': [{'creatorType': 'author', 'lastName': author, 'firstName': 'Zc'}]}
        if key:
            o['citationKey'] = key
        if role == 'alias':
            o['extra'] = IDS_LINE
        objects.append(o)
    state['fiches'] = dict(zip(ITEMS, s.client.create(objects)))
    s.save(state)
    d = s.client.items(list(state['fiches'].values()))
    f = state['fiches']
    s.check(d[f['creee']].get('citationKey') == CREATED and d[f['alias']].get('citationKey') == ALIAS,
               'l\'API accepte citationKey à la création',
               f"{d[f['creee']].get('citationKey')!r}, {d[f['alias']].get('citationKey')!r}")
    s.check(d[f['alias']].get('extra') == IDS_LINE, 'Extra porte la ligne tex.ids', repr(d[f['alias']].get('extra')))
    state['version'] = s.client.server_version()
    s.save(state)
    return s.outcome(WAIT.format('ecrire'))


def write(s: Probe) -> int:
    state = s.state()
    if state.get('etape'):
        raise SystemExit('La phase --ecrire a déjà été faite. Synchroniser, puis lancer --verifier.')
    f = state['fiches']
    lib = s.local_copy(state, list(f.values()))
    s.check(local_key(lib, f['creee']) == CREATED, 'BBT garde la clé reçue avec une fiche nouvelle',
               repr(local_key(lib, f['creee'])))
    filled = {r: local_key(lib, f[r]) for r in ('ecrite', 'videe', 'double1', 'double2')}
    if not s.check(all(filled.values()), 'BBT remplit la clé des fiches reçues sans clé',
                      json.dumps(filled, ensure_ascii=False)):
        raise SystemExit('Des fiches n\'ont pas de clé : BBT est absent, inactif ou n\'a pas eu le temps. '
                         'Vérifier BBT dans le profil de test (Outils, Extensions), attendre, synchroniser, relancer.')
    server = s.client.items([f[r] for r in filled])
    not_sent = [r for r in filled if server[f[r]].get('citationKey') != filled[r]]
    if not_sent:
        raise SystemExit(f'Les clés remplies par BBT ne sont pas encore sur le serveur ({", ".join(not_sent)}). '
                         'Synchroniser encore, puis relancer.')
    state['cles_bbt'] = filled

    res = s.write([{'key': f['ecrite'], 'citationKey': WRITTEN}, {'key': f['videe'], 'citationKey': ''},
                    {'key': f['double1'], 'citationKey': DOUBLE}, {'key': f['double2'], 'citationKey': DOUBLE}])
    s.check(not res.failures, 'écriture des quatre clés acceptée',
               json.dumps(res.failures, ensure_ascii=False) if res.failures else 'aucun refus')
    d = s.client.items([f[r] for r in filled])
    seen = {r: d[f[r]].get('citationKey') for r in filled}
    s.check(seen == {'ecrite': WRITTEN, 'videe': '', 'double1': DOUBLE, 'double2': DOUBLE},
               'le serveur montre les clés écrites, la clé vide et le double', json.dumps(seen, ensure_ascii=False))
    state.update(etape='ecrit', version=s.client.server_version())
    s.save(state)
    return s.outcome(WAIT.format('verifier'))


def check(s: Probe) -> int:
    state = s.state()
    if state.get('etape') != 'ecrit':
        raise SystemExit('Lancer d\'abord la phase --ecrire.')
    f = state['fiches']
    lib = s.local_copy(state, list(f.values()))
    server = s.client.items(list(f.values()))
    local = {r: local_key(lib, k) for r, k in f.items()}
    print('Clés dans Zotero : ' + json.dumps(local, ensure_ascii=False))
    s.check(local['ecrite'] == WRITTEN, 'BBT garde une clé écrite par l\'API sur une fiche qui en avait une',
               f"{local['ecrite']!r}, celle de BBT était {state['cles_bbt']['ecrite']!r}")
    s.check(bool(local['videe']), 'BBT remplit une clé vidée par l\'API',
               f"{local['videe']!r}, avant {state['cles_bbt']['videe']!r}, sur le serveur "
               f"{server[f['videe']].get('citationKey')!r}")
    s.check(local['double1'] == local['double2'] == DOUBLE,
               'BBT laisse en place le double reçu par synchronisation (zc doit le départager, D144)',
               f"{local['double1']!r} et {local['double2']!r}")
    s.check(local['creee'] == CREATED and local['alias'] == ALIAS, 'les clés des fiches non touchées n\'ont pas bougé',
               f"{local['creee']!r}, {local['alias']!r}")
    extra = lib.by_key()[f['alias']].fields.get('extra', '')
    s.check(IDS_LINE in extra, 'BBT laisse la ligne tex.ids dans Extra', repr(extra))
    bbt_folder = s.cfg.zotero_dir / 'better-bibtex'
    print(f"constat  dossier {bbt_folder} : {'présent' if bbt_folder.is_dir() else 'absent'}")

    s.question('Clic droit sur « zc-sonde clés, alias dans Extra », « Exporter la fiche… », format « Better BibLaTeX », '
               f'ouvrir le fichier .bib : l\'entrée @{ALIAS} contient-elle « ids = {{{OLD}}} » ? '
               'Recopier le champ ids tel quel, ou dire s\'il manque. Même question avec « Better BibTeX ».')
    s.question('Les deux fiches « zc-sonde clés, … double » : BBT a-t-il signalé le double (message, '
               'marque dans la colonne « Clé de citation ») ? Après une synchronisation de plus, l\'une des deux '
               'clés a-t-elle changé (relancer --verifier pour le voir) ?')
    s.question(f'Le dossier better-bibtex/ est {"présent" if bbt_folder.is_dir() else "absent"} dans le dossier '
               'de données du profil de test. BBT a-t-il été installé neuf dans ce profil (jamais de version 7 '
               'avant) ? Si oui, cela dit si une installation neuve crée ce dossier.')
    s.question('Une erreur ou un conflit de synchronisation s\'est-il affiché pendant la sonde ?')
    return s.outcome('noter les réponses, puis lancer la phase --nettoyer.')


def clean(s: Probe) -> int:
    state = s.state()
    keys = list(state.get('fiches', {}).values())
    s.delete(keys)
    leftovers = s.client.items(keys)
    s.check(not leftovers, 'fiches de la sonde supprimées du serveur', f'{len(leftovers)} reste(nt)')
    if not leftovers:
        s.state_file.unlink()
    return s.outcome('synchroniser le profil de test dans Zotero.')


def main() -> int:
    args = arguments(__doc__, PHASES)
    s = Probe('cles', args.folder)
    return {'preparer': prepare, 'ecrire': write, 'verifier': check, 'nettoyer': clean}[args.phase](s)


if __name__ == '__main__':
    sys.exit(main())
