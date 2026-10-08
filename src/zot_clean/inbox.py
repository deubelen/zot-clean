"""Sorting of new references, ongoing management (D135).

The references to sort are those of the Inbox and those that have no place
in the subjects, whether outside any collection or arrived directly
in a project. `preparer` looks, for
them alone, for duplicates, identifiers, types, completions and
neighbouring themes. The cases to judge go into the tracking files of steps
2, 3 and 5 (`doublons.toml`, `metadonnees.toml`, `rangement.toml`), and a
report guides the agent. `planifier` draws a single plan from them, with the collections to
create (new theme added to `plan.md`), the merges, then, item by item,
the type change, the fields, the collections and the tags. The tags
follow the accepted rules of `suivi/tags.toml` (D155): automatic tags
and imported keywords removed, variants and states brought back to their form. New
manual tags outside the families are only reported.
The reused steps keep their rules (D62, D86, D116, D131, D134), the
sorting only limits their examination to these references.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from zot_clean import duplicates, privacy, subjects as f, metadata as md, filing as r, tags as tg
from zot_clean import filenames
from zot_clean import citation_keys
from zot_clean.audit import year, type_name
from zot_clean.config import Config
from zot_clean.lang import L, plural
from zot_clean.api import Client
from zot_clean.reader import Library, Item, ItemTypes
from zot_clean.plans import Group, Operation, Plan
from zot_clean.sources import Services, norm

STEP = 'inbox'
CONTAINERS = ('publicationTitle', 'bookTitle', 'proceedingsTitle')

# Rank of the renaming of the main file (D149), after the type (0), the fields (1), the filing (2) and the tags (3).
NAME_RANK = 5


@dataclass
class ToSort:
    item: Item
    origin: str  # key of the Inbox collection to leave, empty for an item outside the Inbox (filed in addition)
    where: list[str]  # paths of the current collections


def _situation(a: ToSort, cfg: Config) -> str:
    """Where a reference to sort is, for the report: Inbox, outside any collection, project or elsewhere."""
    if a.origin:
        return 'inbox'
    if not a.where:
        return 'aucune'
    if any(c == p or c.startswith(p + '/') for c in a.where for p in cfg.method.projects):
        return 'projet'
    return 'ailleurs'


def no_filing(cfg: Config) -> str:
    """Why the sorting cannot file, empty if it can (subjects root set, plan.md written)."""
    if cause := f.refusal(cfg):
        return cause
    return '' if (cfg.workspace / f.OUTLINE).is_file() else L(
        en="plan.md does not exist yet (cleanup step 4).", fr="plan.md n'existe pas encore (étape 4 du nettoyage).")


def to_sort(b: Library, cfg: Config) -> list[ToSort]:
    """Items of the Inbox, and items filed today outside the subjects (except those excluded by the filter and those
    left outside the subjects by decision, D176)."""
    return to_sort_and_left_out(b, cfg)[0]


def to_sort_and_left_out(b: Library, cfg: Config) -> tuple[list[ToSort], list[ToSort]]:
    """The items to sort, and apart those that would be so without having been left outside the subjects by decision."""
    e = r._State(b)
    inbox = e.root(cfg.method.inbox) if cfg.method.inbox else None
    subjects = e.root(cfg.method.subjects) if cfg.method.subjects and not no_filing(cfg) else None
    excluded_items = privacy.excluded_items(b, cfg)
    left_out = r.load_left_out(b, cfg) if subjects is not None else set()
    res, set_aside = [], []
    for el in b.items:
        keys = [e.key[c] for c in el.collections]
        inside = [k for k in keys if inbox and e.under(k, inbox)]
        outside_subjects = subjects is not None and el.id not in excluded_items and not any(e.under(k, subjects) for k in keys)
        if inside or outside_subjects:
            a = ToSort(el, inside[0] if inside else '', sorted(e.path(k) for k in keys))
            (set_aside if not inside and el.key in left_out else res).append(a)
    return sorted(res, key=lambda a: norm(a.item.title)), set_aside


# --- Preparation ------------------------------------------------------------------

def _author(el: Item) -> str:
    """First author, surname and initial of the first name: « Zhang » alone would gather too many people."""
    for (name, first_name), role in zip(el.creators, el.roles):
        if role == 'author':
            return norm(f'{name} {first_name[:1]}')
    return norm(f'{el.creators[0][0]} {el.creators[0][1][:1]}') if el.creators else ''


def _neighbors(b: Library, cfg: Config, keys: set[str]):
    """Themes of the subjects of the other items, by first author and by journal or book."""
    e = r._State(b)
    subjects = e.root(cfg.method.subjects) if cfg.method.subjects else None
    by_author: dict[str, Counter] = {}
    by_container: dict[str, Counter] = {}
    if subjects is None:
        return by_author, by_container
    prefix = cfg.method.subjects + '/'
    for el in b.items:
        if el.key in keys:
            continue
        themes = [e.path(e.key[c]).removeprefix(prefix) for c in el.collections
                  if e.key[c] != subjects and e.under(e.key[c], subjects)]
        if not themes:
            continue
        if a := _author(el):
            by_author.setdefault(a, Counter()).update(themes)
        if c := norm(next((el.fields[k] for k in CONTAINERS if el.fields.get(k)), '')):
            by_container.setdefault(c, Counter()).update(themes)
    return by_author, by_container


def prepare(b: Library, cfg: Config, services: Services, client: Client, schema: ItemTypes,
             show=None, day: date | None = None) -> tuple[str, list[ToSort]]:
    listing, left_out = to_sort_and_left_out(b, cfg)
    keys = {a.item.key for a in listing}
    hidden = privacy.hidden_keys(b, cfg)
    groups = [g for g in duplicates.find(b, cfg) if g.decision != duplicates.DISTINCT and set(g.keys) & keys]
    p_ty, _ = md.types(b, cfg, services, client, schema, show, keys=keys)
    p_id, _ = md.identifiers(b, cfg, services, client, show, keys=keys)
    p_co, _ = md.fill_in(b, cfg, services, client, show, keys=keys)
    cases = [c for c in md.load_tracking(cfg) if c.key in keys and not c.decision]
    entries = {x.key: x for x in r.load(cfg)}
    by_author, by_container = _neighbors(b, cfg, keys)
    subjects_refusal = no_filing(cfg)
    rules = _tag_rules(b, cfg)
    no_key = citation_keys.notify_no_key(b, cfg)

    day = day or date.today()
    if not subjects_refusal:
        r.create_if_missing(cfg)
    situations = Counter(_situation(a, cfg) for a in listing)
    outside = [L(en=f'{situations["aucune"]} outside any collection', fr=f'{situations["aucune"]} hors de toute collection'),
               L(en=f'{situations["projet"]} in a project', fr=f'{situations["projet"]} dans un projet')]
    if situations['ailleurs']:
        outside.append(L(en=f'{situations["ailleurs"]} in another collection outside the subjects (archives, '
                            f'collection outside the outline)',
                         fr=f'{situations["ailleurs"]} dans une autre collection hors du fonds (archives, collection '
                            f'hors plan)'))
    n_listing = plural(len(listing), en='item', fr='référence')
    n_inbox, n_other = situations['inbox'], len(listing) - situations['inbox']
    where = ', '.join(outside)
    n_left = plural(len(left_out), en='other item left', fr='autre référence laissée', en_plural='other items left')
    not_shown = (L(en='not shown', fr='non présentées') if len(left_out) > 1 else L(en='not shown', fr='non présentée'))
    out = [L(en=f"# Inbox sorting, {day:%d/%m/%Y}", fr=f"# Tri de l'Inbox, {day:%d/%m/%Y}"), '',
           L(en=f'{n_listing} to sort, {n_inbox} in the Inbox and {n_other} without a place in the subjects, of '
                f'which {where}.',
             fr=f"{n_listing} à trier, {n_inbox} dans l'Inbox et {n_other} sans place dans le fonds, dont "
                f"{where}.")
           + (L(en=f' {n_left} outside the subjects by decision (`zc subjects pending --leave-out`), '
                   f'{not_shown}.',
                fr=f' {n_left} hors du fonds par décision (`zc subjects pending --leave-out`), {not_shown}.')
              if left_out else ''),
           '']
    if groups:
        listed = ', '.join(' / '.join(g.keys) for g in groups)
        n_groups = plural(len(groups), en='group', fr='groupe')
        out += [L(en=f'**Duplicates.** {n_groups} to judge in `suivi/doublons.toml`: {listed}.',
                  fr=f'**Doublons.** {n_groups} à juger dans `suivi/doublons.toml` : {listed}.'), '']
    obvious = sum(c.grade == 'évident' for c in cases)
    corrected = {g.id for p in (p_ty, p_id, p_co) for g in p.groups}
    n_corrected = plural(len(corrected), en='item', fr='fiche')
    n_cases = len(cases)
    names = ', '.join(f'{c.key} ({c.problem})' for c in cases)
    listed = L(en=f': {names}', fr=f' : {names}') if cases else ''
    out += [L(en=f'**Metadata.** Safe corrections for {n_corrected}. {n_cases} case(s) to judge in '
                 f'`suivi/metadonnees.toml` ({obvious} obvious){listed}.',
              fr=f'**Métadonnées.** Corrections sûres pour {n_corrected}. {n_cases} cas à juger dans '
                 f'`suivi/metadonnees.toml` (dont {obvious} évident(s)){listed}.'), '']
    if subjects_refusal:
        out += [L(en=f'**Filing.** Impossible for now: {subjects_refusal}',
                  fr=f"**Rangement.** Impossible pour l'instant : {subjects_refusal}"), '']
    else:
        out += [L(en='**Filing.** For each item, write a `[[fiche]]` table in `suivi/rangement.toml`, like the '
                     'example of its header, with `cible` = path of the theme in `plan.md` (without the subjects '
                     'root). For an item of the Inbox, `action = "déplacer"` and `depuis` = the key given below. '
                     'For an item outside any collection, `action = "ajouter"` without `depuis` ("déplacer" would '
                     'come to the same). For an item of a project, `action = "ajouter"` without `depuis`, and it '
                     'stays in its project. The themes and their definitions are in `plan.md`. Have it approved '
                     'before writing `decision = "accepter"`. With no suitable theme, propose the closest one or a '
                     'new theme (added to `plan.md` with its definition, then `zc subjects validate`), the item '
                     'staying where it is meanwhile.',
                  fr="**Rangement.** Pour chaque référence, écrire une table `[[fiche]]` dans `suivi/rangement.toml`, "
                     "comme l'exemple de son en-tête, avec `cible` = chemin du thème dans `plan.md` (sans la racine "
                     "du fonds). Pour une référence de l'Inbox, `action = \"déplacer\"` et `depuis` = la clé donnée "
                     "ci-dessous. Pour une référence hors de toute collection, `action = \"ajouter\"` sans `depuis` "
                     "(« déplacer » reviendrait au même). Pour une référence d'un projet, `action = \"ajouter\"` sans "
                     "`depuis`, et elle reste dans son projet. Les thèmes et leurs définitions sont dans `plan.md`. "
                     "Faire approuver avant d'écrire `decision = \"accepter\"`. Sans thème qui convienne, proposer le "
                     "plus proche ou un nouveau thème (ajouté à `plan.md` avec sa définition, puis `zc subjects "
                     "validate`), la référence restant où elle est en attendant."),
                  '',
                  L(en='The neighbouring themes of an item are those where other items of the same first author or '
                       'of the same journal or the same book are filed. “No neighbouring theme found” means that '
                       'no item filed in the subjects shares this author or this journal or book title.',
                    fr="Les thèmes voisins d'une référence sont ceux où sont rangées d'autres fiches du même premier "
                       "auteur ou de la même revue ou du même ouvrage. « Aucun thème voisin trouvé » veut dire "
                       "qu'aucune fiche rangée dans le fonds ne partage cet auteur ni ce titre de revue ou "
                       "d'ouvrage."), '']
    if rules:
        out += [L(en='**Tags.** The accepted rules of `suivi/tags.toml` will apply to the plan. A tag flagged '
                     '“outside the families, no rule” is to be submitted to the user, who keeps it, converts it into '
                     'a concept or deletes it (`[[tag]]` entry of `suivi/tags.toml`).',
                  fr="**Tags.** Les règles acceptées de `suivi/tags.toml` s'appliqueront au plan. Un tag signalé « hors "
                     "familles, sans règle » est à soumettre à l'utilisateur, qui le garde, le convertit en concept ou "
                     "le supprime (entrée `[[tag]]` de `suivi/tags.toml`)."), '']
    if no_key and any(not a.item.fields.get('citationKey', '').strip() for a in listing):
        out += [L(en='**Citation keys.** An item “without a citation key” has not received its own from Better '
                     'BibTeX. Offer the user to fill it in Zotero by right click, Better BibTeX › Fill.',
                  fr="**Clés de citation.** Une référence « sans clé de citation » n'a pas reçu la sienne de Better "
                     "BibTeX. Proposer à l'utilisateur de la remplir dans Zotero par clic droit, Better BibTeX › "
                     "Fill."), '']
    out += [L(en='## Items', fr='## Références'), '']
    for a in listing:
        el = a.item
        no_key_note = L(en=' · without a citation key', fr=' · sans clé de citation')
        from_text = f' · depuis = "{a.origin}"' if a.origin else ''
        if el.key in hidden:
            out.append(f'- {el.key} · {privacy.mask()}' + from_text
                       + (no_key_note if no_key and not el.fields.get('citationKey', '').strip() else ''))
            continue
        container = next((el.fields[k] for k in CONTAINERS if el.fields.get(k)), '')
        tags = ', '.join(n for n, _ in el.tags)
        author = el.author or '?'
        when = year(el) or L(en='n.d.', fr='s. d.')
        title = el.title[:100] or L(en='(untitled)', fr='(sans titre)')
        kind = type_name(el.type)
        in_container = L(en=f' · in “{container[:60]}”', fr=f' · dans « {container[:60]} »') if container else ''
        in_collections = ', '.join(a.where) or L(en='no collection', fr='aucune collection')
        if a.origin:
            action = from_text
        else:
            action = L(en=' · action “ajouter”, without depuis', fr=' · action « ajouter », sans depuis')
            if _situation(a, cfg) == 'projet':
                action += L(en=', stays in its project', fr=', reste dans son projet')
        line = (f'- {el.key} · {author}, {when}, {title} · {kind}' + in_container
                + L(en=f' · in {in_collections}', fr=f' · dans {in_collections}') + action
                + (L(en=f' · tags {tags}', fr=f' · tags {tags}') if tags else ''))
        if x := entries.get(el.key):
            state = x.decision or L(en='to approve', fr='à approuver')
            line += L(en=f' · already in rangement.toml: {x.action} → {x.target} ({state})',
                      fr=f' · déjà dans rangement.toml : {x.action} → {x.target} ({state})')
        if rules and (new_ones := tg.to_flag(el, rules, cfg)):
            flagged = ', '.join(new_ones)
            line += L(en=f' · tags outside the families, no rule: {flagged}',
                      fr=f' · tags hors familles, sans règle : {flagged}')
        # Citation key missing while Better BibTeX, active, usually fills it on arrival (D146).
        if no_key and not el.fields.get('citationKey', '').strip():
            line += no_key_note
        out.append(line)
        neighbors = []
        for name, index, key in ((L(en='same author', fr='même auteur'), by_author, _author(el)),
                                 (L(en='same journal or book', fr='même revue ou ouvrage'), by_container,
                                  norm(container))):
            if key and key in index:
                listed = ', '.join(f'{t} ({n})' for t, n in index[key].most_common(3))
                neighbors.append(L(en=f'{name}: {listed}', fr=f'{name} : {listed}'))
        if subjects_refusal:
            continue
        out.append(L(en='  - neighbouring themes, ', fr='  - thèmes voisins, ') + ' ; '.join(neighbors) if neighbors
                   else L(en='  - no neighbouring theme found', fr='  - aucun thème voisin trouvé'))
    return '\n'.join(out) + '\n', listing


# --- Plan -------------------------------------------------------------------------

def _tag_rules(b: Library, cfg: Config) -> 'tg.Regles | None':
    """Accepted rules of step 6, None as long as `suivi/tags.toml` does not exist (D155)."""
    if not (cfg.tracking / tg.FILE).is_file():
        return None
    return tg.rules(tg.load(cfg), cfg, b)


def _merge_fields(ops: list[Operation]) -> Operation | None:
    """Identifiers and completions of a same item in a single operation, the identifiers prevailing."""
    if not ops:
        return None
    before, after = {}, {}
    for op in reversed(ops):
        before |= op.before
        after |= op.after
    return Operation(ops[0].key, before, after, 1, ' ; '.join(op.nature for op in ops if op.nature))


def make_plan(b: Library, cfg: Config, services: Services, client: Client, schema: ItemTypes,
              show=None) -> tuple[Plan, str]:
    listing = to_sort(b, cfg)
    keys = {a.item.key for a in listing}
    hidden = privacy.hidden_keys(b, cfg)
    e = r._State(b)
    inbox = e.root(cfg.method.inbox) if cfg.method.inbox else None
    from_inbox = {k for k in e.name if inbox and e.under(k, inbox)}

    # 1. Merges of the judged duplicates that touch a reference to sort. The kept item leaves the Inbox if it
    #    keeps another collection.
    p_d, _ = duplicates.make_plan(cfg, client, b)
    merges = [g for g in p_d.groups if any(op.key in keys for op in g.operations)]
    for g in merges:
        for op in g.operations:
            if 'collections' in op.after:
                outside = [k for k in op.after['collections'] if k not in from_inbox]
                if outside:
                    op.after['collections'] = outside
                if sorted(op.after['collections']) == sorted(op.before.get('collections') or []):
                    del op.after['collections'], op.before['collections']
    merged = {op.key for g in merges for op in g.operations}
    rest = keys - merged

    # 2. Type, identifiers and completions.
    p_ty, _ = md.types(b, cfg, services, client, schema, show, keys=rest)
    p_id, _ = md.identifiers(b, cfg, services, client, show, keys=rest)
    p_co, _ = md.fill_in(b, cfg, services, client, show, keys=rest)
    ops: dict[str, list[Operation]] = {}
    for g in p_ty.groups:
        ops.setdefault(g.id, []).append(g.operations[0])
    fields = {}
    for p in (p_id, p_co):
        for g in p.groups:
            fields.setdefault(g.id, []).append(g.operations[0])
    for key, op_list in fields.items():
        ops.setdefault(key, []).append(_merge_fields(op_list))

    # 2 bis. Duplicate citation keys that touch a sorted reference, separated according to D144 in the group of
    #        the reference (D146). The key of the reference itself joins its fields, at rank 1.
    disambiguation, keys_concealed = citation_keys.disambiguate_inbox(b, cfg, client, rest, merged)
    for key, op in disambiguation:
        rank1 = [o for o in ops.get(key, []) if o.rank == 1 and o.key == key]
        if op.key == key and rank1:
            ops[key].remove(rank1[0])
            op = _merge_fields([rank1[0], op])
        ops.setdefault(key, []).append(op)

    # 3. Collections, from the accepted decisions of rangement.toml (D116), and new themes to create.
    creations: list[Operation] = []
    problem = no_filing(cfg)
    if not problem:
        p_r, _ = r.make_plan(b, cfg, client)
        to_create = {op.key: op for g in p_r.groups for op in g.operations if op.kind == 'collections' and op.create}
        wanted = set()
        for g in p_r.groups:
            for op in g.operations:
                if op.kind == 'items' and op.key in rest:
                    ops.setdefault(op.key, []).append(Operation(op.key, op.before, op.after, 2, 'rangement'))
                    wanted |= set(op.after['collections']) - set(op.before['collections'])
        while wanted:  # a collection to create, and its parents to create
            k = wanted.pop()
            if k in to_create and to_create[k] not in creations:
                creations.append(to_create[k])
                if parent := to_create[k].after.get('parentCollection'):
                    wanted.add(parent)
        creations.reverse()

    # 4. Tags of the sorted items and their children, from the accepted rules (D155).
    #    The « before » is reread via the API.
    if (rules := _tag_rules(b, cfg)):
        item_ids = {by.id for by in b.items if by.key in rest}
        targeted = {el.key: v for el in b.all_items.values() if tg.item_of(b, el) in item_ids
                  and tg.normalize('tags', (v := tg.targeted_tags(el, rules)))
                  != tg.normalize('tags', [{'tag': n, 'type': t} for n, t in el.tags])}
        items_by_key = b.by_key()
        for key, d in client.items(list(targeted)).items():
            el = items_by_key[key]
            before = list(d.get('tags') or [])
            after = tg._compute_target(tg._tags_api(d), el.type == 'annotation', rules, el.id).tags
            if tg.normalize('tags', after) == tg.normalize('tags', before):
                continue
            item = b.all_items[tg.item_of(b, el)].key
            ops.setdefault(item, []).append(Operation(key, {'tags': before}, {'tags': after}, 3, 'tags'))

    # 5. Name of the main file of the items whose plan changes the creators, the date, the title or the type, or
    #    that it merges (D149), computed on the metadata according to the plan.
    masters = {next(op.key for op in g.operations if op.rank == 1): g for g in merges}
    renamings, filename_remarks = filenames.for_sorting(
        b, cfg, client, [(c, o, False) for c, o in ops.items()] + [(c, g.operations, True) for c, g in masters.items()],
        NAME_RANK)
    for key, op in renamings.items():
        (masters[key].operations if key in masters else ops[key]).append(op)

    groups = []
    if creations:
        # The group is recognized by its id, its title is only shown: it follows the language of the library.
        groups.append(Group('collections', L(en='new themes', fr='thèmes nouveaux'), creations))
    for i, g in enumerate(merges, 1):
        groups.append(Group(f'fusion-{i}', g.title, g.operations))
    titles = {g.id: g.title for p in (p_ty, p_id, p_co) for g in p.groups}
    by_key = b.by_key()
    for key in sorted(ops, key=lambda k: norm(by_key[k].title) if k in by_key else k):
        title = (privacy.mask() if key in hidden | keys_concealed
                 else titles.get(key) or (by_key[key].title[:80] if key in by_key else ''))
        groups.append(Group(key, title, sorted(ops[key], key=lambda op: op.rank)))
    # The description is only shown (`zc apply`), never read back: it follows the language of the library.
    n_groups = plural(len(groups), en='group', fr='groupe')
    plan = Plan(STEP, client.user, groups,
                description=L(en=f'Inbox sorting, {n_groups}.', fr=f"Tri de l'Inbox, {n_groups}."))
    # A group whose citation key is shared with a confidential item is shown without values (D126).
    report = _report(plan, listing, hidden | keys_concealed, e, problem)
    if filename_remarks:
        report += (L(en='\n## File names left as they are\n\n', fr='\n## Noms des fichiers laissés\n\n')
                   + '\n'.join(f'- {x}' for x in filename_remarks) + '\n')
    return plan, report


def _report(plan: Plan, listing: list[ToSort], hidden: set[str], e, problem: str) -> str:
    items = {op.key for g in plan.groups for op in g.operations if op.kind == 'items'}
    newly_created = {op.key: op for g in plan.groups for op in g.operations if op.create}

    def name(k: str) -> str:
        if k in e.name:
            return e.path(k)
        op = newly_created.get(k)
        return f"{name(op.after['parentCollection'])}/{op.after['name']} (nouveau)" if op else k

    n_items = plural(len(items), en='item', fr='élément')
    n_groups = plural(len(plan.groups), en='group', fr='groupe')
    out = [L(en='# Inbox sorting', fr="# Tri de l'Inbox"), '',
           L(en=f'{n_items} to modify in {n_groups}. Nothing is replaced in the fields already filled. The tags '
                f'follow the accepted rules of suivi/tags.toml.',
             fr=f"{n_items} à modifier en {n_groups}. Rien n'est remplacé dans les champs déjà remplis. "
                f"Les tags suivent les règles acceptées de suivi/tags.toml."), '']
    if problem:
        out += [L(en=f'Filing left aside: {problem}', fr=f'Rangement laissé de côté : {problem}'), '']
    for g in plan.groups:
        if g.id == 'collections':
            out += [L(en='## Themes created', fr='## Thèmes créés'), ''] + [f'- {name(op.key)}' for op in g.operations] + [
                '', L(en='## Items', fr='## Références'), '']
            continue
        if g.id.startswith('fusion-'):
            natures = ', '.join(op.nature for op in g.operations if op.nature)
            out.append(L(en=f'- merge “{g.title}”: {natures}', fr=f'- fusion « {g.title} » : {natures}'))
            continue
        chunks = []
        for op in g.operations:
            if op.rank == 0:
                new_type = type_name(op.after.get('itemType', ''))
                chunks.append(L(en=f'type → {new_type}', fr=f'type → {new_type}'))
            elif op.rank == 3:
                av = {t['tag'] for t in op.before['tags']}
                ap = {t['tag'] for t in op.after['tags']}
                what = '' if op.key == g.id else f' ({op.key})'
                if g.id in hidden:
                    n_removed, n_set = len(av - ap), len(ap - av)
                    chunks.append(L(en=f'tags{what}: {n_removed} removed, {n_set} set',
                                    fr=f'tags{what} : {n_removed} retiré(s), {n_set} posé(s)'))
                else:
                    changes = ', '.join([f'− {t}' for t in sorted(av - ap)] + [f'+ {t}' for t in sorted(ap - av)])
                    chunks.append(L(en=f'tags{what}: {changes}', fr=f'tags{what} : {changes}'))
            elif op.rank == NAME_RANK:
                described = filenames.describe(op, g.id in hidden)
                chunks.append(L(en=f'file {op.key}: {described}', fr=f'fichier {op.key} : {described}'))
            elif op.rank == 1:
                what = '' if op.key == g.id else f' ({op.key})'  # citation key of another item (D146)
                fields = (', '.join(op.after) if g.id in hidden else
                          ', '.join(f'{k} = {str(v)[:50]!r}' for k, v in op.after.items()))
                chunks.append(L(en=f'fields{what} {fields}', fr=f'champs{what} {fields}'))
            else:
                entries = [k for k in op.after['collections'] if k not in op.before['collections']]
                exited = [k for k in op.before['collections'] if k not in op.after['collections']]
                moves = ', '.join([L(en=f'leaves {name(k)}', fr=f'quitte {name(k)}') for k in exited]
                                  + [L(en=f'enters {name(k)}', fr=f'entre dans {name(k)}') for k in entries])
                chunks.append(L(en=f'filing {moves}', fr=f'rangement {moves}'))
        joined = ' ; '.join(chunks)
        out.append(L(en=f'- {g.id} “{g.title}”: {joined}', fr=f'- {g.id} « {g.title} » : {joined}'))
    filed = {op.key for g in plan.groups for op in g.operations if op.rank == 2}
    filed |= {op.key for g in plan.groups if g.id.startswith('fusion-') for op in g.operations}
    staying = [a for a in listing if a.origin and a.item.key not in filed]
    if staying:
        n_staying = plural(len(staying), en='item', fr='référence')
        keys = ', '.join(a.item.key for a in staying)
        remain = L(en='remains', fr='reste(nt)') if len(staying) == 1 else L(en='remain', fr='reste(nt)')
        out += ['', L(en=f'{n_staying} {remain} in the Inbox, with no accepted filing decision: {keys}.',
                      fr=f"{n_staying} {remain} dans l'Inbox, sans décision de rangement acceptée : {keys}.")]
    unplaced = [a for a in listing if not a.origin and a.item.key not in filed and not problem]
    if unplaced:
        n_unplaced = plural(len(unplaced), en='item', fr='référence')
        keys = ', '.join(a.item.key for a in unplaced)
        remain = L(en='remains', fr='reste(nt)') if len(unplaced) == 1 else L(en='remain', fr='reste(nt)')
        out += ['', L(en=f'{n_unplaced} {remain} without a place in the subjects, with no accepted filing '
                         f'decision: {keys}.',
                      fr=f"{n_unplaced} {remain} sans place dans le fonds, sans décision de rangement acceptée : "
                         f"{keys}.")]
    return '\n'.join(out) + '\n'
