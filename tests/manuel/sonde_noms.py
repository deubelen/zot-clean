"""Sonde du renommage des fichiers par l'API web (D147), sur le compte de test seulement.

Écrit par l'API un nouveau `filename` pour trois pièces jointes importées (PDF factices téléversés par la
sonde), puis vérifie après synchronisation ce que Zotero en fait sur le disque :
1. fichier présent sur le disque, nouveau nom avec espaces et accents ;
2. fichier présent, nom qui ne change que par la casse ;
3. fichier pas encore téléchargé (réglage « Télécharger les fichiers : au besoin » du profil de test).
Pour chacun, le fichier est-il renommé dans `storage/<clé>/`, `itemAttachments.path` vaut-il
`storage:<nouveau nom>`, Zotero n'a-t-il rien renvoyé au serveur, Zotero ouvre-t-il le fichier (question),
y a-t-il eu un conflit (question). Puis l'annulation remet les anciens noms, vérifiés de la même façon.

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manuel/sonde_noms.py --dossier ~/zc-test --preparer
    (régler « au besoin », synchroniser, ouvrir les PDF des deux premières fiches seulement)
    ... --ecrire
    (synchroniser)
    ... --verifier
    ... --annuler
    (synchroniser)
    ... --verifier
    ... --nettoyer

Les fiches de la sonde ont un titre qui commence par « zc-sonde noms ». --nettoyer les supprime pour de
bon, avec leurs PDF.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manuel.outils_sondes import Sonde, arguments, fichiers_visibles, meme_nom  # noqa: E402

# rôle -> (titre de la fiche, ancien nom, nouveau nom, fichier présent sur le disque avant le renommage)
CAS = {
    'present': ('zc-sonde noms, fichier présent', 'zc-sonde-present.pdf',
                'Sondeur - 2026 - Fichier présent renommé.pdf', True),
    'casse': ('zc-sonde noms, casse seule', 'zc-sonde-casse.pdf', 'ZC-Sonde-Casse.pdf', True),
    'absent': ('zc-sonde noms, fichier absent', 'zc-sonde-absent.pdf',
               'Sondeur - 2026 - Fichier absent renommé.pdf', False),
}
CHAMPS_FICHIER = ('filename', 'md5', 'mtime')

PHASES = {
    'preparer': 'crée trois fiches avec un PDF chacune',
    'ecrire': 'écrit les nouveaux noms par l\'API (après synchronisation)',
    'verifier': 'compare la copie locale et le disque aux noms attendus (après synchronisation)',
    'annuler': 'remet les anciens noms par l\'API (après la première vérification)',
    'nettoyer': 'supprime les fiches de la sonde et leurs PDF',
}


def preparer(s: Sonde) -> int:
    etat = s.nouvel_etat()
    fiches = s.client.creer([{'itemType': 'journalArticle', 'title': titre, 'date': '2026',
                              'creators': [{'creatorType': 'author', 'lastName': 'Sondeur', 'firstName': 'Zc'}]}
                             for titre, *_ in CAS.values()])
    etat['fiches'] = dict(zip(CAS, fiches))
    s.enregistrer(etat)  # dès maintenant, pour que --nettoyer retrouve les fiches si la suite échoue
    etat['pieces'] = {r: s.joindre_pdf(etat['fiches'][r], CAS[r][1]) for r in CAS}
    s.enregistrer(etat)
    d = s.client.fiches(list(etat['pieces'].values()))
    for r, k in etat['pieces'].items():
        s.verifier(d[k].get('filename') == CAS[r][1] and d[k].get('linkMode') == 'imported_file'
                   and s.client.fichier_en_ligne(k), f'PDF « {CAS[r][1]} » téléversé',
                   f"{d[k].get('linkMode')}, {d[k].get('filename')!r}")
    etat['version'] = s.client.version_serveur()
    s.enregistrer(etat)
    return s.bilan(
        'dans le profil de test, Réglages › Synchronisation › Synchronisation des fichiers, régler « Télécharger '
        'les fichiers » sur « au besoin ». Synchroniser. Ouvrir (double-clic) le PDF de « zc-sonde noms, fichier '
        'présent » et celui de « zc-sonde noms, casse seule », pour qu\'ils soient téléchargés, puis fermer leurs '
        'onglets. Ne pas ouvrir celui de « zc-sonde noms, fichier absent ». Lancer ensuite la phase --ecrire.')


def renommer(s: Sonde, etat: dict, vers: int, etape: str) -> None:
    """Écrit le nom d'indice `vers` de CAS (1 ancien, 2 nouveau) sur les trois pièces jointes."""
    p = etat['pieces']
    avant = s.client.fiches(list(p.values()))
    res = s.ecrire([{'key': p[r], 'filename': CAS[r][vers]} for r in CAS])
    s.verifier(not res.echecs, 'écriture des trois filename acceptée',
               json.dumps(res.echecs, ensure_ascii=False) if res.echecs else 'aucun refus')
    apres = s.client.fiches(list(p.values()))
    for r in CAS:
        a, b = avant[p[r]], apres[p[r]]
        s.verifier(b.get('filename') == CAS[r][vers], f'{r} : le serveur montre « {CAS[r][vers]} »',
                   repr(b.get('filename')))
        s.verifier(all(a.get(c) == b.get(c) for c in ('md5', 'mtime')) and s.client.fichier_en_ligne(p[r]),
                   f'{r} : md5 et mtime inchangés, fichier toujours sur zotero.org', f"md5 {b.get('md5')}")
    etat['apres_ecriture'] = {r: {c: apres[p[r]].get(c) for c in CHAMPS_FICHIER} | {'version': apres[p[r]]['version']}
                              for r in CAS}
    etat.update(etape=etape, version=s.client.version_serveur())
    s.enregistrer(etat)


def ecrire(s: Sonde) -> int:
    etat = s.etat()
    if etat.get('etape'):
        raise SystemExit('La phase --ecrire a déjà été faite. Synchroniser, puis lancer --verifier.')
    p = etat['pieces']
    bib = s.copie_locale(etat, list(etat['fiches'].values()) + list(p.values()))
    pieces = {pj.cle: pj for pj in bib.pieces.values()}
    for r, (_, ancien, _, present) in CAS.items():
        sur_disque = fichiers_visibles(s.stockage(p[r]))
        s.verifier(pieces[p[r]].chemin == f'storage:{ancien}', f'{r} : Zotero a reçu la pièce jointe',
                   pieces[p[r]].chemin)
        if present and sur_disque != [ancien]:
            raise SystemExit(f'Le PDF de « {CAS[r][0]} » n\'est pas sur le disque ({sur_disque}). L\'ouvrir dans '
                             'Zotero pour le télécharger, puis relancer --ecrire.')
        if not present:
            s.verifier(not sur_disque, f'{r} : le fichier n\'est pas encore téléchargé',
                       ', '.join(sur_disque) or 'dossier vide ou absent')
    renommer(s, etat, 2, 'renomme')
    return s.bilan('synchroniser le profil de test dans Zotero, puis lancer la phase --verifier.')


def verifier(s: Sonde) -> int:
    etat = s.etat()
    etape = etat.get('etape')
    if etape not in ('renomme', 'annule'):
        raise SystemExit('Lancer d\'abord la phase --ecrire.')
    vers = 2 if etape == 'renomme' else 1
    print(f"Vérification après {'le renommage' if vers == 2 else 'l’annulation'}.")
    p = etat['pieces']
    bib = s.copie_locale(etat, list(p.values()), exiger_envoi=False)
    pieces = {pj.cle: pj for pj in bib.pieces.values()}
    serveur = s.client.fiches(list(p.values()))
    en_attente = [r for r in CAS if not bib.par_cle()[p[r]].synced]
    s.verifier(not en_attente, 'Zotero n\'a aucun changement local en attente d\'envoi sur ces pièces jointes',
               ', '.join(en_attente) or 'rien en attente')
    for r, (titre, ancien, nouveau, _) in CAS.items():
        attendu, autre = (nouveau, ancien) if vers == 2 else (ancien, nouveau)
        chemin = pieces[p[r]].chemin
        s.verifier(meme_nom(chemin, f'storage:{attendu}'), f'{r} : itemAttachments.path vaut storage:{attendu}',
                   chemin)
        sur_disque = fichiers_visibles(s.stockage(p[r]))
        if r == 'absent' and not sur_disque:
            s.verifier(True, f'{r} : fichier toujours absent du disque, rien à renommer', 'dossier vide ou absent')
        else:
            s.verifier(len(sur_disque) == 1 and meme_nom(sur_disque[0], attendu),
                       f'{r} : un seul fichier sur le disque, nommé « {attendu} », casse comprise',
                       ', '.join(sur_disque) or 'aucun fichier')
            s.verifier(not any(meme_nom(f, autre) for f in sur_disque), f'{r} : plus de fichier « {autre} »',
                       ', '.join(sur_disque))
        ecrit, actuel = etat['apres_ecriture'][r], serveur[p[r]]
        change = {c: actuel.get(c) for c in CHAMPS_FICHIER if actuel.get(c) != ecrit.get(c)}
        s.verifier(actuel['version'] == ecrit['version'] and not change,
                   f'{r} : Zotero n\'a rien renvoyé au serveur sur cette pièce jointe',
                   f"version {ecrit['version']} -> {actuel['version']}" + (f', {json.dumps(change, ensure_ascii=False)}'
                                                                           if change else ''))

    s.question('Double-cliquer sur le PDF de « zc-sonde noms, fichier présent », puis sur celui de « zc-sonde noms, '
               'casse seule » : chacun s\'ouvre-t-il dans le lecteur de Zotero, sans message d\'erreur ?')
    s.question('Double-cliquer sur le PDF de « zc-sonde noms, fichier absent » : Zotero le télécharge-t-il et '
               'l\'ouvre-t-il ? Relancer ensuite --verifier, qui contrôle alors le nom du fichier téléchargé.')
    s.question('Une erreur ou un conflit de synchronisation s\'est-il affiché (fenêtre de conflit, point '
               'd\'exclamation sur le bouton de synchronisation) ?')
    s.question('Dans le panneau de droite de chaque pièce jointe, le nom de fichier affiché est-il le nom '
               f'attendu (« {CAS["present"][vers]} », « {CAS["casse"][vers]} », « {CAS["absent"][vers]} ») ?')
    suite = ('noter les réponses, puis lancer la phase --annuler.' if vers == 2 else
             'noter les réponses, puis lancer la phase --nettoyer, et remettre « Télécharger les fichiers » '
             'sur « à la synchronisation » dans le profil de test.')
    return s.bilan(suite)


def annuler(s: Sonde) -> int:
    etat = s.etat()
    if etat.get('etape') != 'renomme':
        raise SystemExit('L\'annulation suit la phase --ecrire et sa vérification.')
    s.copie_locale(etat, list(etat['pieces'].values()))
    renommer(s, etat, 1, 'annule')
    return s.bilan('synchroniser le profil de test dans Zotero, puis relancer la phase --verifier.')


def nettoyer(s: Sonde) -> int:
    etat = s.etat()
    cles = list(etat.get('fiches', {}).values())
    s.supprimer(cles)
    restes = s.client.fiches(cles + list(etat.get('pieces', {}).values()))
    s.verifier(not restes, 'fiches et PDF de la sonde supprimés du serveur', f'{len(restes)} reste(nt)')
    if not restes:
        s.fichier_etat.unlink()
    return s.bilan('synchroniser le profil de test dans Zotero, et remettre « Télécharger les fichiers » sur '
                   '« à la synchronisation » si ce n\'est pas fait.')


def main() -> int:
    args = arguments(__doc__, PHASES)
    s = Sonde('noms', args.dossier)
    return {'preparer': preparer, 'ecrire': ecrire, 'verifier': verifier, 'annuler': annuler,
            'nettoyer': nettoyer}[args.phase](s)


if __name__ == '__main__':
    sys.exit(main())
