"""Sonde de l'API web pour les tags (D156, dernier point), sur le compte de test seulement.

Vérifie ce que l'étape 6 suppose, en quatre phases séparées par une synchronisation du profil de test :
1. un tag automatique réécrit avec `"type": 1` dans la liste complète d'une fiche reste automatique,
   et un tag réécrit sans `type` devient manuel ;
2. une annotation de PDF accepte la réécriture de ses tags par l'API ;
3. un tag coloré (réglage `tagColors`) dont on retire la dernière fiche garde sa couleur, et ce que
   Zotero en montre (question) ;
4. Zotero purge-t-il, après synchronisation, un tag que plus aucun élément ne porte (table `tags`).

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manuel/sonde_tags.py --dossier ~/zc-test --preparer
    (synchroniser le profil de test dans Zotero)
    ... --ecrire
    (synchroniser)
    ... --verifier
    ... --nettoyer

Les fiches de la sonde ont un titre qui commence par « zc-sonde tags ». --nettoyer les supprime pour de
bon, avec leur PDF et leur annotation, et retire la couleur ajoutée à `tagColors`.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manuel.outils_sondes import Sonde, arguments  # noqa: E402

AUTO_GARDE = 'zc-sonde auto gardé'
AUTO_SANS_TYPE = 'zc-sonde auto sans type'
MANUEL = 'zc-sonde manuel'
AJOUTE = 'zc-sonde ajouté'
COLORE = 'zc-sonde coloré'
ORPHELIN = 'zc-sonde orphelin'
ANNOTATION = 'zc-sonde annotation'
ANNOTATION_REECRITE = 'zc-sonde annotation réécrite'
COULEUR = '#A28AE5'

PHASES = {
    'preparer': 'crée les fiches, le PDF, l\'annotation et la couleur du tag',
    'ecrire': 'réécrit les tags par l\'API (après une synchronisation)',
    'verifier': 'compare la copie locale à ce qui est attendu (après une seconde synchronisation)',
    'nettoyer': 'supprime tout ce que la sonde a créé',
}


def tags_api(data: dict) -> dict[str, int]:
    return {t['tag']: int(t.get('type', 0)) for t in data.get('tags', [])}


def tags_locaux(bib, cle: str) -> dict[str, int]:
    return dict(bib.par_cle()[cle].tags)


def preparer(s: Sonde) -> int:
    etat = s.nouvel_etat()
    fiche = {'itemType': 'journalArticle', 'creators': [{'creatorType': 'author', 'lastName': 'Sondeur',
                                                          'firstName': 'Zc'}], 'date': '2026'}
    t1, t2, t3, t4 = s.client.creer([
        fiche | {'title': 'zc-sonde tags, automatique',
                 'tags': [{'tag': AUTO_GARDE, 'type': 1}, {'tag': AUTO_SANS_TYPE, 'type': 1}, {'tag': MANUEL}]},
        fiche | {'title': 'zc-sonde tags, couleur', 'tags': [{'tag': COLORE}]},
        fiche | {'title': 'zc-sonde tags, orphelin', 'tags': [{'tag': ORPHELIN}]},
        fiche | {'title': 'zc-sonde tags, annotation'},
    ])
    etat.update(t1=t1, t2=t2, t3=t3, t4=t4)
    s.enregistrer(etat)  # dès maintenant, pour que --nettoyer retrouve les fiches si la suite échoue
    pdf = s.joindre_pdf(t4, 'zc-sonde-tags.pdf')
    [annotation] = s.client.creer([{
        'itemType': 'annotation', 'parentItem': pdf, 'annotationType': 'highlight',
        'annotationText': 'zc sonde tags', 'annotationComment': 'Annotation de la sonde des tags',
        'annotationColor': '#ffd400', 'annotationPageLabel': '1', 'annotationSortIndex': '00000|000000|00000',
        'annotationPosition': json.dumps({'pageIndex': 0, 'rects': [[72, 715, 250, 740]]}),
        'tags': [{'tag': ANNOTATION}]}])
    etat.update(pdf=pdf, annotation=annotation)
    s.enregistrer(etat)

    couleurs, _ = s.reglage('tagColors')
    couleurs = [c for c in (couleurs or []) if c.get('name') != COLORE]
    s.ecrire_reglage('tagColors', couleurs + [{'name': COLORE, 'color': COULEUR}])

    d = s.client.fiches([t1, annotation])
    s.verifier(tags_api(d[t1]).get(AUTO_GARDE) == 1 and tags_api(d[t1]).get(AUTO_SANS_TYPE) == 1,
               'l\'API crée des tags automatiques', json.dumps(tags_api(d[t1]), ensure_ascii=False))
    s.verifier(ANNOTATION in tags_api(d[annotation]), 'l\'API crée une annotation avec un tag',
               json.dumps(tags_api(d[annotation]), ensure_ascii=False))
    couleurs, _ = s.reglage('tagColors')
    s.verifier(any(c.get('name') == COLORE for c in couleurs or []), 'couleur ajoutée à tagColors',
               json.dumps(couleurs, ensure_ascii=False))
    etat['version'] = s.client.version_serveur()
    s.enregistrer(etat)
    s.question(f'Dans le sélecteur de tags (en bas à gauche), « {COLORE} » apparaît-il en couleur, en tête, '
               'avec la fiche « zc-sonde tags, couleur » ?')
    return s.bilan('synchroniser le profil de test dans Zotero, puis lancer la phase --ecrire.')


def ecrire(s: Sonde) -> int:
    etat = s.etat()
    if etat.get('etape'):
        raise SystemExit('La phase --ecrire a déjà été faite. Synchroniser, puis lancer --verifier.')
    t1, t2, t3, annotation = etat['t1'], etat['t2'], etat['t3'], etat['annotation']
    bib = s.copie_locale(etat, [t1, t2, t3, etat['t4'], etat['pdf'], annotation])
    locaux = tags_locaux(bib, t1)
    s.verifier(locaux.get(AUTO_GARDE) == 1 and locaux.get(AUTO_SANS_TYPE) == 1,
               'avant réécriture, Zotero a reçu les deux tags automatiques comme automatiques',
               json.dumps(locaux, ensure_ascii=False))
    s.verifier(ANNOTATION in tags_locaux(bib, annotation), 'avant réécriture, Zotero a reçu le tag de l\'annotation',
               json.dumps(tags_locaux(bib, annotation), ensure_ascii=False))

    res = s.ecrire([
        # Liste complète : un automatique gardé avec son type, un autre sans type, un manuel retiré, un ajouté.
        {'key': t1, 'tags': [{'tag': AUTO_GARDE, 'type': 1}, {'tag': AUTO_SANS_TYPE}, {'tag': AJOUTE}]},
        {'key': annotation, 'tags': [{'tag': ANNOTATION_REECRITE}]},
        {'key': t2, 'tags': []},  # la seule fiche du tag coloré
        {'key': t3, 'tags': []},  # la seule fiche du tag qui deviendra orphelin
    ])
    s.verifier(not res.echecs, 'réécriture des quatre listes de tags acceptée',
               json.dumps(res.echecs, ensure_ascii=False) if res.echecs else 'aucun refus')
    d = s.client.fiches([t1, annotation])
    t = tags_api(d[t1])
    s.verifier(t.get(AUTO_GARDE) == 1, 'sur le serveur, le tag réécrit avec "type": 1 reste automatique',
               json.dumps(t, ensure_ascii=False))
    s.verifier(t.get(AUTO_SANS_TYPE) == 0, 'sur le serveur, le tag réécrit sans type devient manuel',
               json.dumps(t, ensure_ascii=False))
    s.verifier(list(tags_api(d[annotation])) == [ANNOTATION_REECRITE],
               'sur le serveur, l\'annotation porte le tag réécrit', json.dumps(tags_api(d[annotation]), ensure_ascii=False))
    s.verifier(s.tag_sur_serveur(COLORE) == 0, 'sur le serveur, plus aucun élément ne porte le tag coloré',
               f'{s.tag_sur_serveur(COLORE)} élément(s)')
    couleurs, _ = s.reglage('tagColors')
    s.verifier(any(c.get('name') == COLORE for c in couleurs or []),
               'la couleur reste dans tagColors quand le tag n\'a plus de fiche', json.dumps(couleurs, ensure_ascii=False))
    s.verifier(s.tag_sur_serveur(ORPHELIN) == 0, 'sur le serveur, le tag orphelin n\'existe plus',
               f'{s.tag_sur_serveur(ORPHELIN)} élément(s)')
    etat.update(etape='ecrit', version=s.client.version_serveur())
    s.enregistrer(etat)
    return s.bilan('synchroniser le profil de test dans Zotero, puis lancer la phase --verifier.')


def verifier(s: Sonde) -> int:
    etat = s.etat()
    if etat.get('etape') != 'ecrit':
        raise SystemExit('Lancer d\'abord la phase --ecrire.')
    t1, t2, t3, annotation = etat['t1'], etat['t2'], etat['t3'], etat['annotation']
    bib = s.copie_locale(etat, [t1, t2, t3, annotation])
    locaux = tags_locaux(bib, t1)
    vu = json.dumps(locaux, ensure_ascii=False)
    s.verifier(locaux.get(AUTO_GARDE) == 1, 'dans Zotero, le tag réécrit avec "type": 1 reste automatique', vu)
    s.verifier(locaux.get(AUTO_SANS_TYPE) == 0, 'dans Zotero, le tag réécrit sans type est devenu manuel', vu)
    s.verifier(MANUEL not in locaux and locaux.get(AJOUTE) == 0, 'dans Zotero, le tag retiré est parti, l\'ajouté est là', vu)
    a = tags_locaux(bib, annotation)
    s.verifier(list(a) == [ANNOTATION_REECRITE], 'dans Zotero, l\'annotation porte le tag réécrit par l\'API',
               json.dumps(a, ensure_ascii=False))
    s.verifier(not tags_locaux(bib, t2) and not tags_locaux(bib, t3), 'dans Zotero, les deux fiches n\'ont plus de tag')

    noms = s.noms_de_tags_locaux()
    for nom, quoi in ((ORPHELIN, 'le tag orphelin'), (MANUEL, 'le tag manuel retiré de sa seule fiche')):
        s.verifier(nom not in noms, f'Zotero purge {quoi} de sa table tags',
                   'absent de la table tags' if nom not in noms else 'toujours dans la table tags, sans élément')
    print('constat  le tag coloré sans fiche est ' + ('toujours dans' if COLORE in noms else 'absent de')
          + ' la table tags locale')
    couleurs = s.reglage_local('tagColors')
    s.verifier(any(c.get('name') == COLORE for c in couleurs or []), 'la copie locale de tagColors garde la couleur',
               json.dumps(couleurs, ensure_ascii=False))

    s.question(f'Sélecteur de tags (en bas à gauche) de « Ma bibliothèque » : « {COLORE} » y apparaît-il encore, '
               'avec sa couleur ? Est-il grisé ? Un clic dessus montre-t-il une liste vide ?')
    s.question(f'Même sélecteur, menu « … » (ou clic droit sur le fond) avec « Afficher les tags automatiques » '
               f'coché : « {ORPHELIN} » et « {MANUEL} » apparaissent-ils encore ?')
    s.question('Fiche « zc-sonde tags, automatique », section Tags : '
               f'« {AUTO_GARDE} » a-t-il l\'icône des tags automatiques (orange) et « {AUTO_SANS_TYPE} » '
               'celle des tags manuels (bleue) ?')
    s.question('Ouvrir le PDF de « zc-sonde tags, annotation » : dans le panneau des annotations, le surlignage '
               f'porte-t-il le tag « {ANNOTATION_REECRITE} » et lui seul ?')
    s.question('Une erreur ou un conflit de synchronisation s\'est-il affiché pendant la sonde ?')
    return s.bilan('noter les réponses, puis lancer la phase --nettoyer.')


def nettoyer(s: Sonde) -> int:
    etat = s.etat()
    s.supprimer([etat[k] for k in ('t1', 't2', 't3', 't4') if k in etat])
    couleurs, _ = s.reglage('tagColors')
    if couleurs and any(c.get('name') == COLORE for c in couleurs):
        s.ecrire_reglage('tagColors', [c for c in couleurs if c.get('name') != COLORE])
    restes = s.client.fiches([etat[k] for k in ('t1', 't2', 't3', 't4', 'pdf', 'annotation') if k in etat])
    couleurs, _ = s.reglage('tagColors')
    s.verifier(not restes, 'fiches, PDF et annotation supprimés du serveur', f'{len(restes)} reste(nt)')
    s.verifier(not any(c.get('name') == COLORE for c in couleurs or []), 'couleur retirée de tagColors')
    if not restes:
        s.fichier_etat.unlink()
    s.question('Après synchronisation, s\'il reste des tags « zc-sonde » dans le sélecteur, les supprimer par '
               'clic droit, « Supprimer le tag… ».')
    return s.bilan('synchroniser le profil de test dans Zotero.')


def main() -> int:
    args = arguments(__doc__, PHASES)
    s = Sonde('tags', args.dossier)
    return {'preparer': preparer, 'ecrire': ecrire, 'verifier': verifier, 'nettoyer': nettoyer}[args.phase](s)


if __name__ == '__main__':
    sys.exit(main())
