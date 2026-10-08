"""Sonde de l'API web pour les tags (D156, dernier point), sur le compte de test seulement.

Vérifie ce que l'étape 6 suppose, en quatre phases séparées par une synchronisation du profil de test :
1. un tag automatique réécrit avec `"type": 1` dans la liste complète d'une fiche reste automatique,
   et un tag réécrit sans `type` devient manuel ;
2. une annotation de PDF accepte la réécriture de ses tags par l'API ;
3. un tag coloré (réglage `tagColors`) dont on retire la dernière fiche garde sa couleur, et ce que
   Zotero en montre (question) ;
4. Zotero purge-t-il, après synchronisation, un tag que plus aucun élément ne porte (table `tags`).

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manual/probe_tags.py --dossier ~/zc-test --preparer
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

from manual.probe_tools import Probe, arguments  # noqa: E402

AUTO_KEPT = 'zc-sonde auto gardé'
AUTO_WITHOUT_TYPE = 'zc-sonde auto sans type'
MANUAL = 'zc-sonde manuel'
ADDED = 'zc-sonde ajouté'
COLORED = 'zc-sonde coloré'
ORPHAN = 'zc-sonde orphelin'
ANNOTATION = 'zc-sonde annotation'
ANNOTATION_REWRITTEN = 'zc-sonde annotation réécrite'
COLOR = '#A28AE5'

PHASES = {
    'preparer': 'crée les fiches, le PDF, l\'annotation et la couleur du tag',
    'ecrire': 'réécrit les tags par l\'API (après une synchronisation)',
    'verifier': 'compare la copie locale à ce qui est attendu (après une seconde synchronisation)',
    'nettoyer': 'supprime tout ce que la sonde a créé',
}


def api_tags(data: dict) -> dict[str, int]:
    return {t['tag']: int(t.get('type', 0)) for t in data.get('tags', [])}


def local_tags(lib, key: str) -> dict[str, int]:
    return dict(lib.by_key()[key].tags)


def prepare(s: Probe) -> int:
    state = s.new_state()
    item = {'itemType': 'journalArticle', 'creators': [{'creatorType': 'author', 'lastName': 'Sondeur',
                                                          'firstName': 'Zc'}], 'date': '2026'}
    t1, t2, t3, t4 = s.client.create([
        item | {'title': 'zc-sonde tags, automatique',
                 'tags': [{'tag': AUTO_KEPT, 'type': 1}, {'tag': AUTO_WITHOUT_TYPE, 'type': 1}, {'tag': MANUAL}]},
        item | {'title': 'zc-sonde tags, couleur', 'tags': [{'tag': COLORED}]},
        item | {'title': 'zc-sonde tags, orphelin', 'tags': [{'tag': ORPHAN}]},
        item | {'title': 'zc-sonde tags, annotation'},
    ])
    state.update(t1=t1, t2=t2, t3=t3, t4=t4)
    s.save(state)  # right now, so that --nettoyer finds the items again if the rest fails
    pdf = s.attach_pdf(t4, 'zc-sonde-tags.pdf')
    [annotation] = s.client.create([{
        'itemType': 'annotation', 'parentItem': pdf, 'annotationType': 'highlight',
        'annotationText': 'zc sonde tags', 'annotationComment': 'Annotation de la sonde des tags',
        'annotationColor': '#ffd400', 'annotationPageLabel': '1', 'annotationSortIndex': '00000|000000|00000',
        'annotationPosition': json.dumps({'pageIndex': 0, 'rects': [[72, 715, 250, 740]]}),
        'tags': [{'tag': ANNOTATION}]}])
    state.update(pdf=pdf, annotation=annotation)
    s.save(state)

    colors, _ = s.setting('tagColors')
    colors = [c for c in (colors or []) if c.get('name') != COLORED]
    s.write_setting('tagColors', colors + [{'name': COLORED, 'color': COLOR}])

    d = s.client.items([t1, annotation])
    s.check(api_tags(d[t1]).get(AUTO_KEPT) == 1 and api_tags(d[t1]).get(AUTO_WITHOUT_TYPE) == 1,
               'l\'API crée des tags automatiques', json.dumps(api_tags(d[t1]), ensure_ascii=False))
    s.check(ANNOTATION in api_tags(d[annotation]), 'l\'API crée une annotation avec un tag',
               json.dumps(api_tags(d[annotation]), ensure_ascii=False))
    colors, _ = s.setting('tagColors')
    s.check(any(c.get('name') == COLORED for c in colors or []), 'couleur ajoutée à tagColors',
               json.dumps(colors, ensure_ascii=False))
    state['version'] = s.client.server_version()
    s.save(state)
    s.question(f'Dans le sélecteur de tags (en bas à gauche), « {COLORED} » apparaît-il en couleur, en tête, '
               'avec la fiche « zc-sonde tags, couleur » ?')
    return s.outcome('synchroniser le profil de test dans Zotero, puis lancer la phase --ecrire.')


def write(s: Probe) -> int:
    state = s.state()
    if state.get('etape'):
        raise SystemExit('La phase --ecrire a déjà été faite. Synchroniser, puis lancer --verifier.')
    t1, t2, t3, annotation = state['t1'], state['t2'], state['t3'], state['annotation']
    lib = s.local_copy(state, [t1, t2, t3, state['t4'], state['pdf'], annotation])
    local_items = local_tags(lib, t1)
    s.check(local_items.get(AUTO_KEPT) == 1 and local_items.get(AUTO_WITHOUT_TYPE) == 1,
               'avant réécriture, Zotero a reçu les deux tags automatiques comme automatiques',
               json.dumps(local_items, ensure_ascii=False))
    s.check(ANNOTATION in local_tags(lib, annotation), 'avant réécriture, Zotero a reçu le tag de l\'annotation',
               json.dumps(local_tags(lib, annotation), ensure_ascii=False))

    res = s.write([
        # Full list: one automatic kept with its type, another without a type, one manual removed, one added.
        {'key': t1, 'tags': [{'tag': AUTO_KEPT, 'type': 1}, {'tag': AUTO_WITHOUT_TYPE}, {'tag': ADDED}]},
        {'key': annotation, 'tags': [{'tag': ANNOTATION_REWRITTEN}]},
        {'key': t2, 'tags': []},  # the only item of the coloured tag
        {'key': t3, 'tags': []},  # the only item of the tag that will become an orphan
    ])
    s.check(not res.failures, 'réécriture des quatre listes de tags acceptée',
               json.dumps(res.failures, ensure_ascii=False) if res.failures else 'aucun refus')
    d = s.client.items([t1, annotation])
    t = api_tags(d[t1])
    s.check(t.get(AUTO_KEPT) == 1, 'sur le serveur, le tag réécrit avec "type": 1 reste automatique',
               json.dumps(t, ensure_ascii=False))
    s.check(t.get(AUTO_WITHOUT_TYPE) == 0, 'sur le serveur, le tag réécrit sans type devient manuel',
               json.dumps(t, ensure_ascii=False))
    s.check(list(api_tags(d[annotation])) == [ANNOTATION_REWRITTEN],
               'sur le serveur, l\'annotation porte le tag réécrit', json.dumps(api_tags(d[annotation]), ensure_ascii=False))
    s.check(s.tag_on_server(COLORED) == 0, 'sur le serveur, plus aucun élément ne porte le tag coloré',
               f'{s.tag_on_server(COLORED)} élément(s)')
    colors, _ = s.setting('tagColors')
    s.check(any(c.get('name') == COLORED for c in colors or []),
               'la couleur reste dans tagColors quand le tag n\'a plus de fiche', json.dumps(colors, ensure_ascii=False))
    s.check(s.tag_on_server(ORPHAN) == 0, 'sur le serveur, le tag orphelin n\'existe plus',
               f'{s.tag_on_server(ORPHAN)} élément(s)')
    state.update(etape='ecrit', version=s.client.server_version())
    s.save(state)
    return s.outcome('synchroniser le profil de test dans Zotero, puis lancer la phase --verifier.')


def check(s: Probe) -> int:
    state = s.state()
    if state.get('etape') != 'ecrit':
        raise SystemExit('Lancer d\'abord la phase --ecrire.')
    t1, t2, t3, annotation = state['t1'], state['t2'], state['t3'], state['annotation']
    lib = s.local_copy(state, [t1, t2, t3, annotation])
    local_items = local_tags(lib, t1)
    seen = json.dumps(local_items, ensure_ascii=False)
    s.check(local_items.get(AUTO_KEPT) == 1, 'dans Zotero, le tag réécrit avec "type": 1 reste automatique', seen)
    s.check(local_items.get(AUTO_WITHOUT_TYPE) == 0, 'dans Zotero, le tag réécrit sans type est devenu manuel', seen)
    s.check(MANUAL not in local_items and local_items.get(ADDED) == 0, 'dans Zotero, le tag retiré est parti, l\'ajouté est là', seen)
    a = local_tags(lib, annotation)
    s.check(list(a) == [ANNOTATION_REWRITTEN], 'dans Zotero, l\'annotation porte le tag réécrit par l\'API',
               json.dumps(a, ensure_ascii=False))
    s.check(not local_tags(lib, t2) and not local_tags(lib, t3), 'dans Zotero, les deux fiches n\'ont plus de tag')

    names = s.local_tag_names()
    for name, what in ((ORPHAN, 'le tag orphelin'), (MANUAL, 'le tag manuel retiré de sa seule fiche')):
        s.check(name not in names, f'Zotero purge {what} de sa table tags',
                   'absent de la table tags' if name not in names else 'toujours dans la table tags, sans élément')
    print('constat  le tag coloré sans fiche est ' + ('toujours dans' if COLORED in names else 'absent de')
          + ' la table tags locale')
    colors = s.local_setting('tagColors')
    s.check(any(c.get('name') == COLORED for c in colors or []), 'la copie locale de tagColors garde la couleur',
               json.dumps(colors, ensure_ascii=False))

    s.question(f'Sélecteur de tags (en bas à gauche) de « Ma bibliothèque » : « {COLORED} » y apparaît-il encore, '
               'avec sa couleur ? Est-il grisé ? Un clic dessus montre-t-il une liste vide ?')
    s.question(f'Même sélecteur, menu « … » (ou clic droit sur le fond) avec « Afficher les tags automatiques » '
               f'coché : « {ORPHAN} » et « {MANUAL} » apparaissent-ils encore ?')
    s.question('Fiche « zc-sonde tags, automatique », section Tags : '
               f'« {AUTO_KEPT} » a-t-il l\'icône des tags automatiques (orange) et « {AUTO_WITHOUT_TYPE} » '
               'celle des tags manuels (bleue) ?')
    s.question('Ouvrir le PDF de « zc-sonde tags, annotation » : dans le panneau des annotations, le surlignage '
               f'porte-t-il le tag « {ANNOTATION_REWRITTEN} » et lui seul ?')
    s.question('Une erreur ou un conflit de synchronisation s\'est-il affiché pendant la sonde ?')
    return s.outcome('noter les réponses, puis lancer la phase --nettoyer.')


def clean(s: Probe) -> int:
    state = s.state()
    s.delete([state[k] for k in ('t1', 't2', 't3', 't4') if k in state])
    colors, _ = s.setting('tagColors')
    if colors and any(c.get('name') == COLORED for c in colors):
        s.write_setting('tagColors', [c for c in colors if c.get('name') != COLORED])
    leftovers = s.client.items([state[k] for k in ('t1', 't2', 't3', 't4', 'pdf', 'annotation') if k in state])
    colors, _ = s.setting('tagColors')
    s.check(not leftovers, 'fiches, PDF et annotation supprimés du serveur', f'{len(leftovers)} reste(nt)')
    s.check(not any(c.get('name') == COLORED for c in colors or []), 'couleur retirée de tagColors')
    if not leftovers:
        s.state_file.unlink()
    s.question('Après synchronisation, s\'il reste des tags « zc-sonde » dans le sélecteur, les supprimer par '
               'clic droit, « Supprimer le tag… ».')
    return s.outcome('synchroniser le profil de test dans Zotero.')


def main() -> int:
    args = arguments(__doc__, PHASES)
    s = Probe('tags', args.folder)
    return {'preparer': prepare, 'ecrire': write, 'verifier': check, 'nettoyer': clean}[args.phase](s)


if __name__ == '__main__':
    sys.exit(main())
