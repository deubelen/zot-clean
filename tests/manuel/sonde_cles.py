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

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manuel/sonde_cles.py --dossier ~/zc-test --preparer
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

from manuel.outils_sondes import Sonde, arguments  # noqa: E402

CREEE = 'zcSondeCreee'
ECRITE = 'zcSondeEcrite'
DOUBLE = 'zcSondeDouble'
ALIAS = 'zcSondeAlias'
ANCIENNE = 'zcSondeAncienne'
LIGNE_IDS = f'tex.ids: {ANCIENNE}'
ATTENDRE = 'synchroniser le profil de test dans Zotero, attendre une dizaine de secondes (BBT remplit les clés), ' \
           'synchroniser encore pour envoyer ces clés, puis lancer la phase --{}.'

# rôle -> (titre, auteur, clé donnée à la création)
FICHES = {
    'creee': ('zc-sonde clés, créée avec sa clé', 'Abeille', CREEE),
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


def cle_locale(bib, k: str) -> str:
    return bib.par_cle()[k].champs.get('citationKey', '')


def preparer(s: Sonde) -> int:
    etat = s.nouvel_etat()
    objets = []
    for i, (role, (titre, auteur, cle)) in enumerate(FICHES.items()):
        o = {'itemType': 'journalArticle', 'title': titre, 'date': str(2001 + i),
             'creators': [{'creatorType': 'author', 'lastName': auteur, 'firstName': 'Zc'}]}
        if cle:
            o['citationKey'] = cle
        if role == 'alias':
            o['extra'] = LIGNE_IDS
        objets.append(o)
    etat['fiches'] = dict(zip(FICHES, s.client.creer(objets)))
    s.enregistrer(etat)
    d = s.client.fiches(list(etat['fiches'].values()))
    f = etat['fiches']
    s.verifier(d[f['creee']].get('citationKey') == CREEE and d[f['alias']].get('citationKey') == ALIAS,
               'l\'API accepte citationKey à la création',
               f"{d[f['creee']].get('citationKey')!r}, {d[f['alias']].get('citationKey')!r}")
    s.verifier(d[f['alias']].get('extra') == LIGNE_IDS, 'Extra porte la ligne tex.ids', repr(d[f['alias']].get('extra')))
    etat['version'] = s.client.version_serveur()
    s.enregistrer(etat)
    return s.bilan(ATTENDRE.format('ecrire'))


def ecrire(s: Sonde) -> int:
    etat = s.etat()
    if etat.get('etape'):
        raise SystemExit('La phase --ecrire a déjà été faite. Synchroniser, puis lancer --verifier.')
    f = etat['fiches']
    bib = s.copie_locale(etat, list(f.values()))
    s.verifier(cle_locale(bib, f['creee']) == CREEE, 'BBT garde la clé reçue avec une fiche nouvelle',
               repr(cle_locale(bib, f['creee'])))
    remplies = {r: cle_locale(bib, f[r]) for r in ('ecrite', 'videe', 'double1', 'double2')}
    if not s.verifier(all(remplies.values()), 'BBT remplit la clé des fiches reçues sans clé',
                      json.dumps(remplies, ensure_ascii=False)):
        raise SystemExit('Des fiches n\'ont pas de clé : BBT est absent, inactif ou n\'a pas eu le temps. '
                         'Vérifier BBT dans le profil de test (Outils, Extensions), attendre, synchroniser, relancer.')
    serveur = s.client.fiches([f[r] for r in remplies])
    pas_envoyees = [r for r in remplies if serveur[f[r]].get('citationKey') != remplies[r]]
    if pas_envoyees:
        raise SystemExit(f'Les clés remplies par BBT ne sont pas encore sur le serveur ({", ".join(pas_envoyees)}). '
                         'Synchroniser encore, puis relancer.')
    etat['cles_bbt'] = remplies

    res = s.ecrire([{'key': f['ecrite'], 'citationKey': ECRITE}, {'key': f['videe'], 'citationKey': ''},
                    {'key': f['double1'], 'citationKey': DOUBLE}, {'key': f['double2'], 'citationKey': DOUBLE}])
    s.verifier(not res.echecs, 'écriture des quatre clés acceptée',
               json.dumps(res.echecs, ensure_ascii=False) if res.echecs else 'aucun refus')
    d = s.client.fiches([f[r] for r in remplies])
    vu = {r: d[f[r]].get('citationKey') for r in remplies}
    s.verifier(vu == {'ecrite': ECRITE, 'videe': '', 'double1': DOUBLE, 'double2': DOUBLE},
               'le serveur montre les clés écrites, la clé vide et le double', json.dumps(vu, ensure_ascii=False))
    etat.update(etape='ecrit', version=s.client.version_serveur())
    s.enregistrer(etat)
    return s.bilan(ATTENDRE.format('verifier'))


def verifier(s: Sonde) -> int:
    etat = s.etat()
    if etat.get('etape') != 'ecrit':
        raise SystemExit('Lancer d\'abord la phase --ecrire.')
    f = etat['fiches']
    bib = s.copie_locale(etat, list(f.values()))
    serveur = s.client.fiches(list(f.values()))
    local = {r: cle_locale(bib, k) for r, k in f.items()}
    print('Clés dans Zotero : ' + json.dumps(local, ensure_ascii=False))
    s.verifier(local['ecrite'] == ECRITE, 'BBT garde une clé écrite par l\'API sur une fiche qui en avait une',
               f"{local['ecrite']!r}, celle de BBT était {etat['cles_bbt']['ecrite']!r}")
    s.verifier(bool(local['videe']), 'BBT remplit une clé vidée par l\'API',
               f"{local['videe']!r}, avant {etat['cles_bbt']['videe']!r}, sur le serveur "
               f"{serveur[f['videe']].get('citationKey')!r}")
    s.verifier(local['double1'] == local['double2'] == DOUBLE,
               'BBT laisse en place le double reçu par synchronisation (zc doit le départager, D144)',
               f"{local['double1']!r} et {local['double2']!r}")
    s.verifier(local['creee'] == CREEE and local['alias'] == ALIAS, 'les clés des fiches non touchées n\'ont pas bougé',
               f"{local['creee']!r}, {local['alias']!r}")
    extra = bib.par_cle()[f['alias']].champs.get('extra', '')
    s.verifier(LIGNE_IDS in extra, 'BBT laisse la ligne tex.ids dans Extra', repr(extra))
    dossier_bbt = s.cfg.dossier_zotero / 'better-bibtex'
    print(f"constat  dossier {dossier_bbt} : {'présent' if dossier_bbt.is_dir() else 'absent'}")

    s.question('Clic droit sur « zc-sonde clés, alias dans Extra », « Exporter la fiche… », format « Better BibLaTeX », '
               f'ouvrir le fichier .bib : l\'entrée @{ALIAS} contient-elle « ids = {{{ANCIENNE}}} » ? '
               'Recopier le champ ids tel quel, ou dire s\'il manque. Même question avec « Better BibTeX ».')
    s.question('Les deux fiches « zc-sonde clés, … double » : BBT a-t-il signalé le double (message, '
               'marque dans la colonne « Clé de citation ») ? Après une synchronisation de plus, l\'une des deux '
               'clés a-t-elle changé (relancer --verifier pour le voir) ?')
    s.question(f'Le dossier better-bibtex/ est {"présent" if dossier_bbt.is_dir() else "absent"} dans le dossier '
               'de données du profil de test. BBT a-t-il été installé neuf dans ce profil (jamais de version 7 '
               'avant) ? Si oui, cela dit si une installation neuve crée ce dossier.')
    s.question('Une erreur ou un conflit de synchronisation s\'est-il affiché pendant la sonde ?')
    return s.bilan('noter les réponses, puis lancer la phase --nettoyer.')


def nettoyer(s: Sonde) -> int:
    etat = s.etat()
    cles = list(etat.get('fiches', {}).values())
    s.supprimer(cles)
    restes = s.client.fiches(cles)
    s.verifier(not restes, 'fiches de la sonde supprimées du serveur', f'{len(restes)} reste(nt)')
    if not restes:
        s.fichier_etat.unlink()
    return s.bilan('synchroniser le profil de test dans Zotero.')


def main() -> int:
    args = arguments(__doc__, PHASES)
    s = Sonde('cles', args.dossier)
    return {'preparer': preparer, 'ecrire': ecrire, 'verifier': verifier, 'nettoyer': nettoyer}[args.phase](s)


if __name__ == '__main__':
    sys.exit(main())
