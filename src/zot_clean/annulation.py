"""Annulation d'une écriture journalisée (D16, D39, D48).

`zc annuler` ne touche pas Zotero, il produit un plan d'annulation, appliqué
ensuite par `zc appliquer` comme tout autre plan (essai, sauvegarde, journal),
et donc lui-même annulable. Les groupes sont rejoués du dernier au premier, et les opérations de
chacun à l'envers. Un plan
d'annulation est partiel (D39), un champ modifié depuis l'opération est laissé
tel quel et signalé, les autres sont restaurés. Un groupe dont un élément a
disparu (corbeille vidée) n'est pas annulable du tout (D48). Une collection
créée par le plan est mise à la corbeille de Zotero (D114, D117), sauf si elle a
changé de nom ou de place, ou contient encore une fiche ou une sous-collection,
une fois défait le reste du plan (D183). Le rapport ne
montre que la clé et les noms des champs d'une fiche confidentielle (D126).

Une écriture inscrite au journal sans confirmation de Zotero (D178) est défaite
comme les autres. Si elle n'a pas eu lieu, ses champs ont encore leur valeur
d'avant et l'annulation n'y touche pas. Une collection qu'elle devait créer et
qui n'existe pas est simplement ignorée.
"""

import json
from pathlib import Path

from zot_clean import filtre, journal as jl, plans
from zot_clean.audit import nom_type
from zot_clean.config import Config
from zot_clean.ecriture import Client
from zot_clean.plans import Groupe, Operation, Plan


def journaux_vises(chemin: Path, cfg: Config) -> list[Path]:
    """Le journal donné, ou tous les journaux d'un plan (essai, suite, reprises)."""
    if chemin.suffix == '.jsonl':
        return [chemin]
    plan = plans.charger(chemin)
    res = [r.chemin for r in jl.du_plan(cfg.journal, plan.empreinte)]
    if not res:
        raise SystemExit(f"Aucun journal pour le plan {chemin.name}, il n'a jamais été appliqué.")
    return res


def planifier(journaux: list[Path], client: Client, masquees: set[str] | None = None) -> tuple[Plan, str]:
    """`masquees` : clés des fiches confidentielles. None, faute de pouvoir lire la base, masque toutes les fiches."""
    lignes, bibliotheques = [], set()
    for chemin in journaux:
        contenu = jl.lire(chemin)
        if contenu and contenu[0].get('type') == 'en-tete':
            bibliotheques.add(contenu[0].get('bibliotheque'))
        lignes += [l for l in contenu if l['type'] == 'element']
    if len(bibliotheques) != 1:
        raise SystemExit('Journaux illisibles ou de comptes différents.')
    incertaines = list(jl.en_suspens(journaux).values())
    lignes += incertaines
    existants = client.fiches([l['cle'] for l in lignes if l.get('genre', 'items') == 'items'])
    existants |= client.collections([l['cle'] for l in lignes if l.get('genre') == 'collections'])
    existants |= client.reglages([l['cle'] for l in lignes if l.get('genre') == 'settings'])
    lignes = [l for l in lignes if not (l['type'] == 'intention' and l.get('cree') and l['cle'] not in existants)]
    par_groupe: dict[str, list[dict]] = {}
    for l in lignes:
        par_groupe.setdefault(l['groupe'], []).append(l)
    for ls in par_groupe.values():
        ls.sort(key=lambda l: l['rang'])  # une écriture incertaine reprend sa place dans le groupe

    groupes, impossibles = [], []
    # Les groupes aussi sont rejoués du dernier au premier : une sous-collection sort d'une collection créée
    # par le plan avant que celle-ci aille à la corbeille (D114).
    for gid, ls in reversed(par_groupe.items()):
        manquants = sorted({l['cle'] for l in ls} - set(existants))
        if manquants:
            impossibles.append((gid, manquants))
            continue
        ops = [_inverse(l, i) for i, l in enumerate(reversed(ls))]
        groupes.append(Groupe(gid, f'annulation du groupe {gid}', ops))
    noms = [c.name for c in journaux]
    plan = Plan('annulation', bibliotheques.pop(), groupes, partiel=True, annule=noms,
                description=f"Annulation de {', '.join(noms)}.")
    return plan, _rapport(plan, impossibles, existants, masquees, len(incertaines))


def _inverse(l: dict, rang: int) -> Operation:
    genre = l.get('genre', 'items')
    if l.get('cree'):  # gardée si elle a changé de nom ou de place, ou reçu autre chose depuis (D183)
        return Operation(l['cle'], avant={'deleted': False}, apres={'deleted': True}, rang=rang, nature='annulation',
                         genre=genre, enfants=[], exige=dict(l['ecrit']))
    return Operation(l['cle'], avant=l['ecrit'], apres={c: plans.brute(l['avant'], c) for c in l['ecrit']},
                     rang=rang, nature='annulation', genre=genre)


def _rapport(plan: Plan, impossibles: list, existants: dict, masquees: set[str] | None = None,
             incertaines: int = 0) -> str:
    r = [f'# Plan d\'annulation', '', plan.description, '',
         f'{len(plan.groupes)} groupe(s) à annuler, {plan.nb_operations} opération(s). Un champ modifié depuis '
         "l'opération sera laissé tel quel et signalé, les autres seront restaurés.", '']
    if incertaines:
        r += [f"{incertaines} écriture(s) sont parties sans que Zotero en confirme le résultat (connexion coupée, "
              "commande interrompue). Elles sont défaites si elles ont eu lieu, et laissées sinon.", '']
    if impossibles:
        r += ['## Groupes non annulables', '',
              "Un élément de ces groupes n'existe plus (corbeille vidée, suppression définitive). Rien n'y sera "
              "touché. L'état complet d'avant reste dans le journal, et la sauvegarde permet de retrouver le reste.",
              '']
        r += [f"- groupe {g} : {', '.join(m)}" for g, m in impossibles] + ['']
    r += ['## Détail', '']
    for g in plan.groupes:
        r.append(f'### Groupe {g.id}')
        for op in g.operations:
            e = existants.get(op.cle, {})
            cache = op.genre == 'items' and (masquees is None or op.cle in masquees)
            titre = filtre.MASQUE if cache else 'note' if e.get('itemType') == 'note' else f'« {_titre(e)} »'
            r.append(f"- {op.cle} {titre} : {', '.join(_phrase(c, v, cache) for c, v in op.apres.items())}")
        r.append('')
    return '\n'.join(r)


CHAMPS = {'title': 'le titre', 'date': 'la date', 'DOI': 'le DOI', 'ISBN': "l'ISBN", 'creators': 'les auteurs',
          'publicationTitle': 'la revue', 'bookTitle': "le titre de l'ouvrage", 'abstractNote': 'le résumé',
          'extra': 'le champ extra', 'itemType': 'le type'}


def _titre(e: dict) -> str:
    if e.get('key') == 'tagColors':
        return 'couleurs des tags'
    texte = e.get('title') or e.get('name') or ''  # jamais le texte d'une note (D191)
    return ' '.join(texte.split())[:70] or '(sans titre)'


def _phrase(champ: str, valeur, cache: bool = False) -> str:
    """Ce que l'annulation rétablit, en clair. Sans valeur pour une fiche confidentielle (D126)."""
    if champ == 'deleted':
        return 'va à la corbeille' if valeur else 'sort de la corbeille'
    if champ == 'parentItem':
        return f'revient sur la fiche {valeur}'
    if champ == 'parentCollection':
        return f'revient sous la collection {valeur}' if valeur else 'revient à la racine'
    if champ == 'value':  # réglage synchronisé (D175)
        return 'reprennent leur état d\'avant' if valeur else 'sont retirées'
    if champ == 'name':
        return f'reprend son ancien nom « {valeur} »'
    if champ in ('collections', 'tags', 'relations'):
        return {'collections': "retrouve ses collections d'avant", 'tags': "retrouve ses tags d'avant",
                'relations': "retrouve ses liens d'avant"}[champ]
    nom = CHAMPS.get(champ, f'le champ {champ}')
    if cache:
        return f'{nom} est rétabli'
    if valeur in ('', [], {}, None):
        return f'{nom} redevient vide'
    if champ == 'itemType':
        return f'{nom} redevient « {nom_type(valeur)} »'
    texte = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    return f'{nom} redevient « {texte[:60]} »'
