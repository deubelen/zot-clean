"""Undo of a journaled write (D16, D39, D48).

`zc undo` does not touch Zotero, it produces an undo plan, then applied
by `zc apply` like any other plan (trial, backup, journal), and so itself
undoable. Groups are replayed from last to first, and the operations of
each one in reverse. An undo plan is partial (D39), a field modified since the
operation is left as it is and flagged, the others are restored. A group in
which an element has vanished (trash emptied) cannot be undone at all (D48). A
collection created by the plan is moved to the Zotero trash (D114, D117),
unless it has changed name or place, or still contains an item or a
subcollection, once the rest of the plan is undone (D183). The report shows
only the key and the field names of a confidential item (D126).

A write recorded in the journal without confirmation from Zotero (D178) is
undone like the others. If it did not happen, its fields still have their
previous value and the undo does not touch them. A collection it was meant to
create that does not exist is simply ignored.
"""

import json
from pathlib import Path

from zot_clean import privacy, journal as jl, plans
from zot_clean.audit import type_name
from zot_clean.config import Config
from zot_clean.api import Client
from zot_clean.lang import L
from zot_clean.plans import Group, Operation, Plan


def targeted_journals(path: Path, cfg: Config) -> list[Path]:
    """The given journal, or all the journals of a plan (trial, rest, resumptions)."""
    if path.suffix == '.jsonl':
        return [path]
    plan = plans.load(path)
    res = [r.path for r in jl.for_plan(cfg.journal, plan.fingerprint)]
    if not res:
        raise SystemExit(L(en=f"No journal for the plan {path.name}, it was never applied.",
                           fr=f"Aucun journal pour le plan {path.name}, il n'a jamais été appliqué."))
    return res


def make_plan(journals: list[Path], client: Client, hidden: set[str] | None = None) -> tuple[Plan, str]:
    """`hidden`: keys of confidential items. None, for lack of being able to read the database, hides all items."""
    lines, libraries = [], set()
    for path in journals:
        content = jl.read(path)
        if content and content[0].get('type') == 'en-tete':
            libraries.add(content[0].get('bibliotheque'))
        lines += [l for l in content if l['type'] == 'element']
    if len(libraries) != 1:
        raise SystemExit(L(en='Unreadable journals, or journals of different accounts.',
                           fr='Journaux illisibles ou de comptes différents.'))
    uncertain = list(jl.pending(journals).values())
    lines += uncertain
    existing_items = client.items([l['cle'] for l in lines if l.get('genre', 'items') == 'items'])
    existing_items |= client.collections([l['cle'] for l in lines if l.get('genre') == 'collections'])
    existing_items |= client.settings([l['cle'] for l in lines if l.get('genre') == 'settings'])
    lines = [l for l in lines if not (l['type'] == 'intention' and l.get('cree') and l['cle'] not in existing_items)]
    by_group: dict[str, list[dict]] = {}
    for l in lines:
        by_group.setdefault(l['groupe'], []).append(l)
    for ls in by_group.values():
        ls.sort(key=lambda l: l['rang'])  # an uncertain write takes its place back in the group

    groups, impossible = [], []
    # Groups too are replayed from last to first: a subcollection leaves a collection created
    # by the plan before that one goes to the trash (D114).
    for gid, ls in reversed(by_group.items()):
        missing = sorted({l['cle'] for l in ls} - set(existing_items))
        if missing:
            impossible.append((gid, missing))
            continue
        ops = [_inverse(l, i) for i, l in enumerate(reversed(ls))]
        groups.append(Group(gid, L(en=f'undo of group {gid}', fr=f'annulation du groupe {gid}'), ops))
    names = [c.name for c in journals]
    plan = Plan('annulation', libraries.pop(), groups, partial=True, undoes=names,
                description=L(en=f"Undo of {', '.join(names)}.", fr=f"Annulation de {', '.join(names)}."))
    return plan, _report(plan, impossible, existing_items, hidden, len(uncertain))


def _inverse(l: dict, rank: int) -> Operation:
    kind = l.get('genre', 'items')
    if l.get('cree'):  # kept if it changed name or place, or received something else since (D183)
        return Operation(l['cle'], before={'deleted': False}, after={'deleted': True}, rank=rank, nature='annulation',
                         kind=kind, children=[], requires=dict(l['ecrit']))
    return Operation(l['cle'], before=l['ecrit'], after={c: plans.raw_value(l['avant'], c) for c in l['ecrit']},
                     rank=rank, nature='annulation', kind=kind)


def _report(plan: Plan, impossible: list, existing_items: dict, hidden: set[str] | None = None,
             uncertain: int = 0) -> str:
    r = [L(en='# Undo plan', fr="# Plan d'annulation"), '', plan.description, '',
         L(en=f'{len(plan.groups)} group(s) to undo, {plan.n_operations} operation(s). A field modified since the '
              'operation will be left as it is and flagged, the others will be restored.',
           fr=f'{len(plan.groups)} groupe(s) à annuler, {plan.n_operations} opération(s). Un champ modifié depuis '
              "l'opération sera laissé tel quel et signalé, les autres seront restaurés."), '']
    if uncertain:
        r += [L(en=f"{uncertain} write(s) were sent without Zotero confirming the result (connection lost, "
                   "command interrupted). They are undone if they happened, and left alone otherwise.",
                fr=f"{uncertain} écriture(s) sont parties sans que Zotero en confirme le résultat (connexion coupée, "
                   "commande interrompue). Elles sont défaites si elles ont eu lieu, et laissées sinon."), '']
    if impossible:
        r += [L(en='## Groups that cannot be undone', fr='## Groupes non annulables'), '',
              L(en="An item of these groups no longer exists (trash emptied, permanent deletion). Nothing will be "
                   "touched in them. The complete earlier state stays in the journal, and the backup lets you "
                   "recover the rest.",
                fr="Un élément de ces groupes n'existe plus (corbeille vidée, suppression définitive). Rien n'y sera "
                   "touché. L'état complet d'avant reste dans le journal, et la sauvegarde permet de retrouver le reste."),
              '']
        r += [L(en=f"- group {g}: {', '.join(m)}", fr=f"- groupe {g} : {', '.join(m)}") for g, m in impossible] + ['']
    r += [L(en='## Details', fr='## Détail'), '']
    for g in plan.groups:
        r.append(L(en=f'### Group {g.id}', fr=f'### Groupe {g.id}'))
        for op in g.operations:
            e = existing_items.get(op.key, {})
            cache = op.kind == 'items' and (hidden is None or op.key in hidden)
            title = privacy.mask() if cache else L(en='note', fr='note') if e.get('itemType') == 'note' \
                else L(en=f'“{_title(e)}”', fr=f'« {_title(e)} »')
            r.append(L(en=f"- {op.key} {title}: {', '.join(_phrase(c, v, cache) for c, v in op.after.items())}",
                       fr=f"- {op.key} {title} : {', '.join(_phrase(c, v, cache) for c, v in op.after.items())}"))
        r.append('')
    return '\n'.join(r)


def _field_names() -> dict[str, str]:
    return {'title': L(en='the title', fr='le titre'), 'date': L(en='the date', fr='la date'),
            'DOI': L(en='the DOI', fr='le DOI'), 'ISBN': L(en='the ISBN', fr="l'ISBN"),
            'creators': L(en='the authors', fr='les auteurs'), 'publicationTitle': L(en='the journal', fr='la revue'),
            'bookTitle': L(en='the book title', fr="le titre de l'ouvrage"),
            'abstractNote': L(en='the abstract', fr='le résumé'), 'extra': L(en='the extra field', fr='le champ extra'),
            'itemType': L(en='the type', fr='le type')}


def _title(e: dict) -> str:
    if e.get('key') == 'tagColors':
        return L(en='tag colors', fr='couleurs des tags')
    text = e.get('title') or e.get('name') or ''  # never the text of a note (D191)
    return ' '.join(text.split())[:70] or L(en='(untitled)', fr='(sans titre)')


def _phrase(field_name: str, value, cache: bool = False) -> str:
    """What the undo restores, in plain words. No value for a confidential item (D126)."""
    if field_name == 'deleted':
        return L(en='goes to the trash', fr='va à la corbeille') if value else \
            L(en='comes out of the trash', fr='sort de la corbeille')
    if field_name == 'parentItem':
        return L(en=f'goes back under item {value}', fr=f'revient sur la fiche {value}')
    if field_name == 'parentCollection':
        return L(en=f'goes back under collection {value}', fr=f'revient sous la collection {value}') if value else \
            L(en='goes back to the root', fr='revient à la racine')
    if field_name == 'value':  # synced setting (D175)
        return L(en='go back to their earlier state', fr="reprennent leur état d'avant") if value else \
            L(en='are removed', fr='sont retirées')
    if field_name == 'name':
        return L(en=f'gets its old name back "{value}"', fr=f'reprend son ancien nom « {value} »')
    if field_name == 'tags' and not cache and isinstance(value, list):
        # Verification pilots: « retrouve ses tags d'avant » sixty times told the user nothing (D242).
        names = [d.get('tag', '') for d in value if isinstance(d, dict)]
        listed = ', '.join(L(en=f'“{n}”', fr=f'« {n} »') for n in names[:8]) + (' …' if len(names) > 8 else '')
        return L(en=f'gets its earlier tags back: {listed}', fr=f"retrouve ses tags d'avant : {listed}") if names else \
            L(en='gets back its earlier state, without tags', fr="retrouve son état d'avant, sans tags")
    if field_name in ('collections', 'tags', 'relations'):
        return {'collections': L(en='gets its earlier collections back', fr="retrouve ses collections d'avant"),
                'tags': L(en='gets its earlier tags back', fr="retrouve ses tags d'avant"),
                'relations': L(en='gets its earlier links back', fr="retrouve ses liens d'avant")}[field_name]
    name = _field_names().get(field_name, L(en=f'the field {field_name}', fr=f'le champ {field_name}'))
    if cache:
        return L(en=f'{name} is restored', fr=f'{name} est rétabli')
    if value in ('', [], {}, None):
        return L(en=f'{name} becomes empty again', fr=f'{name} redevient vide')
    if field_name == 'itemType':
        return L(en=f'{name} goes back to "{type_name(value)}"', fr=f'{name} redevient « {type_name(value)} »')
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return L(en=f'{name} goes back to "{text[:60]}"', fr=f'{name} redevient « {text[:60]} »')
