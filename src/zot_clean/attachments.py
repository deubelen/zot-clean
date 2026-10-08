"""Identical PDFs (D125): copies of the same file attached to several items, or twice to the same one.

`find` spots the groups of copies and writes them to `suivi/pieces.toml`, where the agent and the user decide,
for each group, which copies go to the trash and which are reattached to another item. `make_plan` builds a
plan from it, applied by `zc apply` like the others. A copy that carries annotations or notes is never
trashed: if it sits on the wrong item, it is reattached to the right one.
"""

import tomllib
from collections import defaultdict
from dataclasses import dataclass, field

from zot_clean import privacy
from zot_clean.audit import write_toml, md5, type_name, pdfs_on_disk
from zot_clean.config import Config
from zot_clean.duplicates import _toml
from zot_clean.lang import L, plural
from zot_clean.api import Client
from zot_clean.reader import Library
from zot_clean.plans import Group, Operation, Plan

FILE = 'pieces.toml'
APPLY, KEEP = 'appliquer', 'garder'

def header() -> str:
    """Comment header of `suivi/pieces.toml`, in the language of the library. The keys and values it shows stay
    French (D209)."""
    return L(en="""\
# Identical PDFs found by `zc attachments find`, with the decisions made.
# This file can be read again and edited by hand or with the agent. `zc attachments find` updates it
# without losing the decisions, `zc attachments plan` prepares the plan of the groups to apply.
# Decisions are written with `zc attachments accept` (--trash, --move) and `zc attachments reject` (keep).
#
# decision  : "appliquer" (trash and reattach as indicated), "garder" (wanted copies, for example a chapter and
#             the whole book, not to be reported any more) or "" (to judge).
# corbeille : keys of the copies to trash. A copy that is annotated or carries a note is refused.
# rattacher : copy -> item, to move a copy (an annotated one, for example) to the right item.
# raison    : free note.
""", fr="""\
# PDF identiques repérés par `zc attachments find`, avec les décisions prises.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc attachments find` le met à jour
# sans perdre les décisions, `zc attachments plan` prépare le plan des groupes à appliquer.
# Les décisions s'écrivent avec `zc attachments accept` (--trash, --move) et `zc attachments reject` (garder).
#
# decision  : "appliquer" (mettre à la corbeille et rattacher comme indiqué), "garder" (copies voulues, par exemple
#             un chapitre et le livre entier, à ne plus signaler) ou "" (à juger).
# corbeille : clés des copies à mettre à la corbeille. Une copie annotée ou portant une note est refusée.
# rattacher : copie -> fiche, pour déplacer une copie (annotée, par exemple) vers la bonne fiche.
# raison    : note libre.
""")


@dataclass
class Entry:
    copies: list[str]
    decision: str = ''
    trash: list[str] = field(default_factory=list)
    move: dict = field(default_factory=dict)
    reason: str = ''


def load(cfg: Config) -> list[Entry]:
    path = cfg.tracking / FILE
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Fix the file, or delete it to start over.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.'))
    res = []
    for g in raw.get('pdf', []):
        e = Entry(list(g['copies']), g.get('decision', ''), list(g.get('corbeille', [])),
                   dict(g.get('rattacher', {})), g.get('raison', ''))
        if e.decision not in ('', APPLY, KEEP):
            copies = ', '.join(e.copies)
            raise SystemExit(L(en=f'{path}: unknown decision “{e.decision}” for {copies}.',
                               fr=f'{path} : décision inconnue « {e.decision} » pour {copies}.'))
        res.append(e)
    return res


def _annotated(b: Library, ids: dict[str, int], notes: set[int], key: str) -> int:
    """Number of annotations and notes carried by a copy, its own note included (D206)."""
    i = ids.get(key)
    return (b.annotations.get(i, 0) + (i in notes) + b.attachments[i].note) if i is not None else 0


def write(cfg: Config, entries: list[Entry], b: Library) -> None:
    attachments = {p.key: p for p in b.attachments.values()}
    ids = {p.key: i for i, p in b.attachments.items()}
    notes = {p for p in b.notes.values() if p}
    hidden = privacy.hidden_keys(b, cfg)
    lines = [header()]
    for e in entries:
        lines.append('[[pdf]]')
        # The copies are identical: a single confidential item masks the whole group (D126).
        cache = any(k in hidden for k in e.copies)
        for k in e.copies:
            p = attachments.get(k)
            item = b.all_items.get(p.parent) if p else None
            if item:
                author = item.author or '?'
                n = _annotated(b, ids, notes, k)
                what = privacy.mask() if cache else f'{author} · {item.title[:80]}'
                lines.append(L(en=f'# {k} on {item.key} · {what} ({type_name(item.type)}',
                               fr=f'# {k} sur {item.key} · {what} ({type_name(item.type)}')
                             + (L(en=f', {n} annotation(s) or note(s)', fr=f', {n} annotation(s) ou note(s)')
                                if n else '') + ')')
        lines += [f'copies = {_toml(e.copies)}', f'decision = {_toml(e.decision)}',
                   f'corbeille = {_toml(e.trash)}', f'rattacher = {_toml(e.move)}',
                   f'raison = {_toml(e.reason)}', '']
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    write_toml(cfg.tracking / FILE, lines)


def decide(entries: list[Entry], b: Library, trash=(), move: dict | None = None, keep=(),
            reason: str = '') -> tuple[int, int]:
    """Decisions taken by command (D177, modelled on D172), instead of writing the file by hand. Each group is
    designated by the key of one of its copies. `trash` and `move` (copy -> item) say what to do with the copies
    of a group to apply, `keep` lists the groups whose copies are wanted. Only the groups still to be judged
    change. Returns the number of groups to apply and of groups kept."""
    move = move or {}
    to_judge = {k: e for e in entries if not e.decision for k in e.copies}
    known = {k for e in entries for k in e.copies}
    requested = [*trash, *move, *keep]
    if unknowns := [k for k in requested if k not in to_judge]:
        missing_keys = [k for k in unknowns if k not in known]
        decided = [k for k in unknowns if k in known]
        chunks = []
        if missing_keys:
            names = ', '.join(missing_keys)
            chunks.append(L(en=f'No group of {FILE} contains the copy {names}. Check the key (that of the '
                               f'attachment, not of the item), or run `zc attachments find` again.',
                            fr=f'Aucun groupe de {FILE} ne contient la copie {names}. Vérifier la clé '
                               f'(celle de la pièce jointe, non de la fiche), ou relancer `zc attachments find`.'))
        if decided:
            names = ', '.join(decided)
            chunks.append(L(en=f'The group of {names} is already decided. A decision that was made is changed by '
                               f'hand in the file.',
                            fr=f'Le groupe de {names} est déjà décidé. Une décision prise se change à la '
                               f'main dans le fichier.'))
        raise SystemExit(' '.join(chunks))
    if double := set(trash) & set(move):
        names = ', '.join(sorted(double))
        raise SystemExit(L(en=f'{names}: a same copy does not go both to the trash and to another item.',
                           fr=f'{names} : une même copie ne va pas à la fois à la corbeille et sur une '
                              f'autre fiche.'))
    ids = {p.key: i for i, p in b.attachments.items()}
    notes = {p for p in b.notes.values() if p}
    if annotated_keys := [k for k in trash if _annotated(b, ids, notes, k)]:
        names = ', '.join(annotated_keys)
        raise SystemExit(L(en=f'{names} carries annotations or notes and does not go to the trash. Reattach it to '
                              f'the right item instead (--move), and trash the other copy.',
                           fr=f"{names} porte des annotations ou des notes et ne va pas à la corbeille. "
                              f"La rattacher plutôt à la bonne fiche (--move), et mettre l'autre copie à la "
                              f"corbeille."))
    items = {e.key for e in b.items}
    if not_items := [f for f in move.values() if f not in items]:
        names = ', '.join(not_items)
        raise SystemExit(L(en=f'{names} is not an item of the library.',
                           fr=f"{names} n'est pas une fiche de la bibliothèque."))
    applied_entries = {id(to_judge[k]): to_judge[k] for k in [*trash, *move]}
    kept = {id(to_judge[k]): to_judge[k] for k in keep}
    if applied_entries.keys() & kept.keys():
        raise SystemExit(L(en='A same group cannot be both applied and kept.',
                           fr='Un même groupe ne peut pas être à la fois appliqué et gardé.'))
    for k in trash:
        if k not in to_judge[k].trash:
            to_judge[k].trash.append(k)
    for k, f in move.items():
        to_judge[k].move[k] = f
    for e in applied_entries.values():
        if set(e.copies) <= set(e.trash):
            names = ', '.join(e.copies)
            raise SystemExit(L(en=f'All the copies of {names} would go to the trash, one must be kept.',
                               fr=f'Toutes les copies de {names} iraient à la corbeille, il faut en garder '
                                  f'une.'))
        e.decision, e.reason = APPLY, reason or e.reason
    for e in kept.values():
        e.decision, e.reason = KEEP, reason or e.reason
    return len(applied_entries), len(kept)


def identical_groups(b: Library) -> list[list[str]]:
    """Keys of the copies of each PDF present several times, on different items or on the same one."""
    by_size = defaultdict(list)
    for p in pdfs_on_disk(b):
        if p.parent in b.all_items:
            by_size[p.file.stat().st_size].append(p)
    by_fingerprint = defaultdict(list)
    for same in by_size.values():
        if len(same) > 1:
            for p in same:
                by_fingerprint[md5(p.file)].append(p.key)
    return sorted(sorted(g) for g in by_fingerprint.values() if len(g) > 1)


def find(b: Library, cfg: Config) -> list[Entry]:
    old_ones = {frozenset(e.copies): e for e in load(cfg)}
    entries = [old_ones.get(frozenset(g)) or Entry(g) for g in identical_groups(b)]
    entries.sort(key=lambda e: e.decision != '')
    write(cfg, entries, b)
    return entries


def warning(b: Library, cfg: Config, entries: list[Entry]) -> str:
    """What `find` could not see or does not settle itself. The PDFs missing from the disk, never compared
    (D168), and the items that share a PDF without appearing in `suivi/doublons.toml`. `zc duplicates find`
    proposes them there (D125), with its other clues, rather than this file, which sees only a PDF."""
    from zot_clean import bbt
    from zot_clean.audit import missing_reminder
    from zot_clean.duplicates import load_tracking
    parent = {p.key: b.all_items[p.parent].key for p in b.attachments.values() if p.parent in b.all_items}
    groups = [set(g.keys) for g in load_tracking(cfg)]
    outside = 0
    for e in entries:
        items = {parent[k] for k in e.copies if k in parent}
        if not e.decision and len(items) > 1 and not any(items <= g for g in groups):
            outside += 1
    chunks = []
    if outside:
        shared = L(en='shared', fr='partagés') if outside > 1 else L(en='shared', fr='partagé')
        chunks.append(L(en=f'{outside} PDF {shared} by different items that are not in suivi/doublons.toml yet. '
                           f'Run `zc duplicates find` again, which proposes these items as duplicates to judge, '
                           f'and merge them first if they are.',
                        fr=f"{outside} PDF {shared} par des fiches différentes qui ne figurent pas "
                           f"encore dans suivi/doublons.toml. Relancer `zc duplicates find`, qui propose ces "
                           f"fiches comme doublons à juger, et les fusionner d'abord si c'en sont."))
    if reminder := missing_reminder(b, bbt.file_storage(cfg.zotero_dir), at_sync=bbt.downloads_at_sync(cfg.zotero_dir)):
        chunks.append(reminder)
    return ' '.join(chunks)


def make_plan(cfg: Config, client: Client, b: Library) -> tuple[Plan, str]:
    entries = [e for e in load(cfg) if e.decision == APPLY]
    ids = {p.key: i for i, p in b.attachments.items()}
    notes = {p for p in b.notes.values() if p}
    hidden = privacy.hidden_keys(b, cfg)
    data = client.items(sorted({k for e in entries for k in e.copies} | {f for e in entries
                                                                            for f in e.move.values()}))
    groups, refusal, details = [], [], []
    for e in entries:
        if cause := _refusal(e, data, b, ids, notes):
            refusal.append((e, cause))
            continue
        ops = [Operation(k, {'deleted': False}, {'deleted': True}, nature='corbeille', children=[])
               for k in e.trash]  # copy without annotation in the plan, which must stay so (D182)
        ops += [Operation(k, {'parentItem': data[k]['parentItem']}, {'parentItem': f}, nature='rattacher')
                for k, f in e.move.items() if data[k].get('parentItem') != f]
        if not ops:
            continue
        gid = str(len(groups) + 1)
        cache = any(k in hidden for k in e.copies + list(e.move.values()))
        title = privacy.mask() if cache else data[e.copies[0]].get('title', '')
        groups.append(Group(gid, title[:80], ops))
        details.append(_detail(gid, e, data, title))
    # The description is only shown (`zc apply`), never read back: it follows the language of the library.
    plan = Plan('pieces', client.user, groups,
                description=L(en=f'Identical PDFs, {len(groups)} group(s).',
                              fr=f'PDF identiques, {len(groups)} groupe(s).'))
    return plan, _report(plan, refusal, details, sum(1 for e in load(cfg) if not e.decision))


def _refusal(e: Entry, data: dict, b: Library, ids: dict, notes: set) -> str:
    unknowns = [k for k in e.trash + list(e.move) if k not in e.copies]
    if unknowns:
        names = ', '.join(unknowns)
        return L(en=f'{names} is not one of the copies of the group', fr=f'{names} ne fait pas partie des copies du groupe')
    if set(e.trash) & set(e.move):
        return L(en='a same copy is both trashed and reattached',
                 fr='une même copie est à la fois mise à la corbeille et rattachée')
    if set(e.copies) <= set(e.trash):
        return L(en='all the copies would go to the trash, one must be kept',
                 fr='toutes les copies iraient à la corbeille, il faut en garder une')
    missing = [k for k in e.copies + list(e.move.values()) if k not in data]
    if missing:
        names = ', '.join(missing)
        return L(en=f'not found on the server: {names}', fr=f'introuvable(s) sur le serveur : {names}')
    if any(data[k].get('deleted') for k in e.trash):
        return L(en='a copy is already in the trash', fr='une copie est déjà à la corbeille')
    annotated_keys = [k for k in e.trash if _annotated(b, ids, notes, k)]
    if annotated_keys:
        names = ', '.join(annotated_keys)
        return L(en=f'{names} carries annotations or notes and does not go to the trash. Reattach it to the right '
                    f'item instead, and trash the other copy',
                 fr=f"{names} porte des annotations ou des notes et ne va pas à la corbeille. "
                    f"La rattacher plutôt à la bonne fiche, et mettre l'autre copie à la corbeille")
    not_items = [f for f in e.move.values() if data[f].get('itemType') in ('attachment', 'note')]
    if not_items:
        names = ', '.join(not_items)
        return L(en=f'{names} is not an item', fr=f"{names} n'est pas une fiche")
    return ''


def _detail(gid: str, e: Entry, data: dict, title: str) -> list[str]:
    r = [L(en=f'### Group {gid}. {title[:90]}', fr=f'### Groupe {gid}. {title[:90]}'), '']
    r += [L(en=f"- trash {k} (copy on {data[k].get('parentItem')})",
            fr=f"- corbeille {k} (copie sur {data[k].get('parentItem')})") for k in e.trash]
    r += [L(en=f"- reattach {k}: {data[k].get('parentItem')} → {f}",
            fr=f"- rattacher {k} : {data[k].get('parentItem')} → {f}") for k, f in e.move.items()]
    r += [L(en=f'- reason: {e.reason}', fr=f'- raison : {e.reason}')] if e.reason else []
    return r + ['']


def _report(plan: Plan, refusal: list, details: list, to_judge: int) -> str:
    n_groups, n_operations = len(plan.groups), plan.n_operations
    out = [L(en='# Identical PDFs', fr='# PDF identiques'), '',
           L(en=f'{n_groups} group(s), {n_operations} operation(s). The copies sent to the trash stay there 30 days '
                f'(Zotero default setting), long enough to go back with `zc undo`.',
             fr=f'{n_groups} groupe(s), {n_operations} opération(s). Les copies mises à la corbeille y '
                f'restent 30 jours (réglage par défaut de Zotero), le temps de revenir en arrière avec `zc undo`.')]
    if to_judge:
        out += ['', L(en=f'{to_judge} group(s) still without a decision in `suivi/{FILE}`.',
                      fr=f'{to_judge} groupe(s) encore sans décision dans `suivi/{FILE}`.')]
    if refusal:
        out += ['', L(en='## Groups set aside', fr='## Groupes écartés'), '']
        out += [L(en=f"- {', '.join(e.copies)}: {cause}.", fr=f"- {', '.join(e.copies)} : {cause}.")
                for e, cause in refusal]
    out += ['', L(en='## Detail', fr='## Détail'), '']
    for d in details:
        out += d
    return '\n'.join(out) + '\n'
