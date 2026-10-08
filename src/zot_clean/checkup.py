"""Regular check, ongoing management (D137, D139 to D142).

The check lives in `zc audit` (D139). Each audit keeps a snapshot of its
points, identified by keys without titles, in `suivi/audits/`, and its
report opens on what has appeared and what has been settled since the audit
of a previous day. A twelfth check compares `plan.md` and the subjects in Zotero.

The link between a theme and its collection goes through the path. To recognize
a theme renamed, moved or deleted in Zotero, `suivi/fonds-collections.json`
keeps the key of the collection of each theme where plan and Zotero agree
(D140). `suivre` then updates `plan.md` and the paths in the tracking files,
Zotero being authoritative after the cleanup (D23).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date

from zot_clean import privacy, subjects as f, filing as r
from zot_clean.audit import TO_REVIEW, INFO, OK, Section, line
from zot_clean.config import Config
from zot_clean.lang import L, plural
from zot_clean.reader import Library

SNAPSHOTS = 'audits'
MEMORY = 'fonds-collections.json'
NEW_MAX = 20


def outline_title() -> str:
    """Title of the twelfth check, in the language of the library (D225)."""
    return L(en='Subjects outline', fr='Plan du fonds')


# --- Comparison of two audits (D139) ------------------------------------------------

def snapshot(sections: list[Section], b: Library) -> dict:
    return {'chiffres': {'référence': len(b.items), 'pièce jointe': len(b.attachments), 'note': len(b.notes),
                         'collection': len(b.collections)},
            'points': {s.title: sorted(s.points) for s in sections}}


def save_snapshot(cfg: Config, snap: dict, day: date) -> None:
    folder = cfg.tracking / SNAPSHOTS
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'audit-{day:%Y-%m-%d}.json').write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                                                          encoding='utf-8')


def previous(cfg: Config, day: date) -> tuple[date, dict] | None:
    """Snapshot of the last audit of an earlier day, so that two audits of the same day compare to the same one."""
    folder = cfg.tracking / SNAPSHOTS
    found_list = []
    for p in folder.glob('audit-*.json') if folder.is_dir() else ():
        try:
            d = date.fromisoformat(p.stem.removeprefix('audit-'))
        except ValueError:
            continue
        if d < day:
            found_list.append((d, p))
    if not found_list:
        return None
    d, p = max(found_list)
    try:
        return d, json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def no_comparison() -> list[str]:
    """Report lines when no audit of a previous day exists (D170)."""
    return [L(en='## Comparison', fr='## Comparaison'), '',
            L(en='No audit from a previous day, nothing is compared. The next audits, made on another day, will '
                 'compare to the last audit of today.',
              fr="Aucun audit d'un jour précédent, rien n'est comparé. Les audits suivants, faits un autre jour, "
                 "compareront au dernier audit de ce jour-ci."), '']


def _gap(n: int) -> str:
    return f' ({"+" if n > 0 else "−"}{abs(n)})' if n else ''


def evolution(sections: list[Section], snap: dict, before: dict, day_before: date) -> list[str]:
    """Markdown lines of what has appeared and been settled since `before`. A check absent from the previous
    snapshot is not compared, so as not to present everything as new."""
    out = [L(en=f'## Since the audit of {day_before:%d/%m/%Y}', fr=f"## Depuis l'audit du {day_before:%d/%m/%Y}"), '',
           L(en=f'Comparison with the last audit of a previous day, that of {day_before:%d/%m/%Y}. Another audit '
                f'made today compares to the same one, so the corrections of the day appear as settled, and '
                f'replaces this report.',
             fr=f"Comparaison avec le dernier audit d'un jour précédent, celui du {day_before:%d/%m/%Y}. Un autre "
                f"audit fait aujourd'hui compare au même, si bien que les corrections de la journée apparaissent "
                f"comme réglées, et remplace ce rapport."), '']
    c0, c1 = before.get('chiffres', {}), snap['chiffres']
    # The names of the figures are stored words (D209, D225), their English noun is only for display.
    english = {'référence': 'item', 'pièce jointe': 'attachment', 'note': 'note', 'collection': 'collection'}
    out += [', '.join(f'{plural(n, en=english.get(word, word), fr=word)}{_gap(n - c0[word]) if word in c0 else ""}'
                      for word, n in c1.items()) + '.', '']
    p0 = before.get('points', {})
    nothing = True
    for i, s in enumerate(sections, 1):
        if s.title not in p0:
            continue
        new_ones = [k for k in s.points if k not in set(p0[s.title])]
        rules = len(set(p0[s.title]) - set(s.points))
        if not new_ones and not rules:
            continue
        nothing = False
        chunks = []
        if new_ones:
            n_new = len(new_ones)
            chunks.append(L(en=f'{n_new} new', fr=f'{n_new} nouveaux') if n_new > 1 else
                          L(en=f'{n_new} new', fr=f'{n_new} nouveau'))
        if rules:
            chunks.append(L(en=f'{rules} settled', fr=f'{rules} réglés') if rules > 1 else
                          L(en=f'{rules} settled', fr=f'{rules} réglé'))
        and_ = L(en=' and ', fr=' et ')
        out.append(f'- {i}. {s.title}, {and_.join(chunks)}.')
        out += [f'  - {s.points[k]}' for k in new_ones[:NEW_MAX]]
        if len(new_ones) > NEW_MAX:
            more = len(new_ones) - NEW_MAX
            out.append(L(en=f'  - … and {more} more, in the section of the check',
                         fr=f'  - … et {more} autres, dans la section du contrôle'))
    if nothing:
        out.append(L(en='No new or settled point.', fr='Aucun point nouveau ni réglé.'))
    return out + ['']


# --- Collections of the subjects and actions taken in Zotero (D140) -------------------------

def read_memory(cfg: Config) -> dict[str, str]:
    path = cfg.tracking / MEMORY
    if not path.is_file():
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(path.read_text(encoding='utf-8')).items()}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def write_memory(cfg: Config, memory: dict[str, str]) -> None:
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    (cfg.tracking / MEMORY).write_text(json.dumps(dict(sorted(memory.items(), key=lambda x: x[1])),
                                                ensure_ascii=False, indent=1), encoding='utf-8')


def subject_collections(b: Library, cfg: Config) -> dict[str, str] | None:
    """Key -> path relative to the subjects of each collection under the subjects root, None without a root."""
    e = r._State(b)
    root = e.root(cfg.method.subjects) if cfg.method.subjects else None
    if root is None:
        return None
    prefix = cfg.method.subjects + '/'
    return {k: e.path(k).removeprefix(prefix) for k in e.name if k != root and e.under(k, root)}


@dataclass
class ManualEdits:
    renamed: dict[str, tuple[str, str]] = field(default_factory=dict)  # key -> (plan path, current path)
    deleted: dict[str, str] = field(default_factory=dict)  # key -> plan path
    created_cols: dict[str, str] = field(default_factory=dict)  # key -> current path
    to_create: list[str] = field(default_factory=list)  # plan paths without a collection, never seen
    too_deep: dict[str, str] = field(default_factory=dict)
    memory: dict[str, str] = field(default_factory=dict)  # updated memory

    def __bool__(self) -> bool:
        return bool(self.renamed or self.deleted or self.created_cols)


def _subpath(path: str, parent: str) -> str | None:
    """Rest of `path` under `parent`, '' for the parent itself, None outside it."""
    if path == parent:
        return ''
    return path[len(parent) + 1:] if path.startswith(parent + '/') else None


def manual_edits(plan: f.Outline, current: dict[str, str], memory: dict[str, str], old_ones: set[str],
           max_depth: int) -> ManualEdits:
    """Gaps between the plan and the collections of the subjects, read through the key memory. A collection
    of the step 4 tracking (`old_ones`) is not a theme created by hand, the filing deals with it."""
    g = ManualEdits()
    taken = set(current.values())
    for k, seen in memory.items():
        if seen not in plan.nodes:
            continue
        if k not in current:
            if seen not in taken:
                g.deleted[k] = seen
        elif current[k] != seen and current[k] not in plan.nodes and seen not in taken:
            g.renamed[k] = (seen, current[k])
    for k, ch in current.items():
        if ch.count('/') + 1 > max_depth:
            g.too_deep[k] = ch
        elif ch not in plan.nodes and k not in g.renamed and k not in old_ones:
            g.created_cols[k] = ch
    known = set(memory.values()) | taken
    g.to_create = [ch for ch in plan.nodes if ch not in known]
    # A renamed or deleted parent takes its sub-collections along, only the parent is kept.
    g.renamed = {k: (a, n) for k, (a, n) in g.renamed.items()
                  if not any(k2 != k and (rest := _subpath(a, a2)) and n == f'{n2}/{rest}'
                             for k2, (a2, n2) in g.renamed.items())}
    g.deleted = {k: a for k, a in g.deleted.items()
                   if not any(k2 != k and _subpath(a, a2) for k2, a2 in g.deleted.items())}
    g.created_cols = {k: c for k, c in g.created_cols.items()
               if not any(k2 != k and _subpath(c, c2) for k2, c2 in g.created_cols.items())}
    # Memory: the themes where plan and Zotero agree, and the actions still to follow.
    g.memory = {k: ch for k, ch in current.items() if ch in plan.nodes}
    for k, seen in memory.items():
        if k not in g.memory and seen in plan.nodes and seen not in taken:
            g.memory[k] = seen
    return g


def _plan(cfg: Config) -> f.Outline:
    return f.read_outline((cfg.workspace / f.OUTLINE).read_text(encoding='utf-8'), cfg)


def _old_collections(cfg: Config) -> set[str]:
    return {c.key for c in f.load_tracking(cfg).collections}


def review(b: Library, cfg: Config) -> tuple[f.Outline, dict[str, str], ManualEdits] | None:
    current = subject_collections(b, cfg)
    if current is None or not (cfg.workspace / f.OUTLINE).is_file():
        return None
    plan = _plan(cfg)
    return plan, current, manual_edits(plan, current, read_memory(cfg), _old_collections(cfg), cfg.method.max_depth)


def outline_check(b: Library, cfg: Config, hidden: set[str] = frozenset()) -> tuple[Section, dict | None]:
    """Twelfth check (D139), and the key memory updated (None if there is nothing to keep)."""
    from zot_clean import inbox
    if cause := inbox.no_filing(cfg):
        why = cause[0].lower() + cause[1:]
        return Section(outline_title(), INFO, L(en=f'Check skipped, {why}', fr=f'Contrôle sauté, {why}')), None
    seen = review(b, cfg)
    if seen is None:
        name = cfg.method.subjects
        return Section(outline_title(), INFO,
                       L(en=f'Check skipped, no “{name}” root in Zotero.',
                         fr=f'Contrôle sauté, pas de racine « {name} » dans Zotero.')), None
    plan, current, g = seen
    m = cfg.method
    points: dict[str, str] = {}
    for k, (a, n) in g.renamed.items():
        what = 'renommé' if a.rpartition('/')[0] == n.rpartition('/')[0] else 'déplacé'  # stored in the key
        shown = L(en='renamed', fr='renommé') if what == 'renommé' else L(en='moved', fr='déplacé')
        points[f'{what} · {k}'] = L(en=f'{shown} in Zotero: {a} → {n}', fr=f'{shown} dans Zotero : {a} → {n}')
    points |= {f'supprimé · {k}': L(en=f'deleted in Zotero: {a}', fr=f'supprimé dans Zotero : {a}')
               for k, a in g.deleted.items()}
    points |= {f'créé · {k}': L(en=f'created in Zotero, missing from {f.OUTLINE}: {c}',
                                fr=f'créé dans Zotero, absent de {f.OUTLINE} : {c}')
               for k, c in g.created_cols.items()}
    points |= {f'trop profond · {k}': L(en=f'beyond {m.max_depth} levels: {c}', fr=f'au-delà de {m.max_depth} niveaux : {c}')
               for k, c in g.too_deep.items()}
    points |= {f'à créer · {c}': L(en=f'in {f.OUTLINE}, not in Zotero yet: {c}',
                                   fr=f'dans {f.OUTLINE}, pas encore dans Zotero : {c}') for c in g.to_create}
    points |= {f'sans définition · {nd.path}': L(en=f'no definition: {nd.path}', fr=f'sans définition : {nd.path}')
               for nd in plan.nodes.values() if not nd.definition and nd.path in current.values()}
    up_to_date, _ = f.validation_up_to_date(cfg)
    if not up_to_date:
        points['validation'] = L(en=f'{f.OUTLINE} or suivi/fonds.toml changed since the last validation',
                                 fr=f'{f.OUTLINE} ou suivi/fonds.toml ont changé depuis la dernière validation')
    to_sort, left_out = inbox.to_sort_and_left_out(b, cfg)
    outside = [a.item for a in to_sort if not a.origin]
    points |= {f'hors fonds · {e.key}': L(en=f'outside the subjects: {line(e, hidden)}',
                                           fr=f'hors du fonds : {line(e, hidden)}') for e in outside}
    counts: dict[str, int] = {}
    key_of = {c.id: c.key for c in b.collections.values()}
    for e in b.items:
        for c in e.collections:
            counts[key_of[c]] = counts.get(key_of[c], 0) + 1
    largest = sorted(((ch, counts.get(k, 0)) for k, ch in current.items()
                   if counts.get(k, 0) > m.subtheme_threshold and ch.count('/') + 1 < m.max_depth),
                  key=lambda x: -x[1])
    points |= {f'gros · {ch}': L(en=f'more than {m.subtheme_threshold} items: {ch} ({n})',
                                  fr=f'plus de {m.subtheme_threshold} références : {ch} ({n})') for ch, n in largest}
    serious = [p for p in points if not p.startswith('gros')]
    n_changed = len(g.renamed) + len(g.deleted) + len(g.created_cols)
    changed = plural(n_changed, en='theme', fr='thème')
    changed_word = L(en='changed', fr='changés') if n_changed > 1 else L(en='changed', fr='changé')
    n_outside = plural(len(outside), en='item', fr='référence')
    left = L(en=f', not counting {len(left_out)} left out of the subjects by decision)',
             fr=f', sans compter {len(left_out)} laissées hors du fonds par décision)') if len(left_out) > 1 else L(
        en=f', not counting {len(left_out)} left out of the subjects by decision)',
        fr=f', sans compter {len(left_out)} laissée hors du fonds par décision)')
    undefined = plural(sum(1 for p in points if p.startswith('sans définition')), en='theme', fr='thème')
    n_largest = plural(len(largest), en='theme', fr='thème')
    threshold = m.subtheme_threshold
    chunks = [L(en=f'{changed} {changed_word} in Zotero', fr=f'{changed} {changed_word} dans Zotero'),
              L(en=f'{n_outside} outside the subjects (outside Inbox', fr=f'{n_outside} hors du fonds (hors Inbox')
              + (left if left_out else ')'),
              L(en=f'{undefined} without a definition', fr=f'{undefined} sans définition'),
              L(en=f'{n_largest} of more than {threshold} items', fr=f'{n_largest} de plus de {threshold} références')]
    if g.to_create:
        to_create = plural(len(g.to_create), en='theme', fr='thème')
        chunks.append(L(en=f'{to_create} of the outline not in Zotero yet',
                        fr=f'{to_create} du plan pas encore dans Zotero'))
    text = ', '.join(chunks) + '.'
    if not up_to_date:
        text += L(en=f' {f.OUTLINE} changed since the last validation.', fr=f' {f.OUTLINE} a changé depuis la dernière validation.')
    remedy = L(en="A theme changed in Zotero is carried over into plan.md by `zc subjects track`, then the agent "
                  "writes the missing definitions. Items outside the subjects go through `zc inbox`, and those "
                  "that are decided to be left out of the subjects are noted with `zc subjects pending --leave-out`. "
                  "A theme that is too big is split into sub-themes from `zc subjects titles`, only if the split is "
                  "clean. A theme of the outline not in Zotero yet is created by `zc subjects plan`.",
               fr="Un thème changé dans Zotero se reporte dans plan.md par `zc subjects track`, puis l'agent écrit les "
                  "définitions manquantes. Les références hors du fonds passent par `zc inbox`, et celles qu'on "
                  "décide de laisser hors du fonds se notent par `zc subjects pending --leave-out`. Un thème trop "
                  "gros se découpe en sous-thèmes à partir de `zc subjects titles`, seulement si le découpage est "
                  "net. Un thème du plan pas encore dans Zotero est créé par `zc subjects plan`.")
    status = TO_REVIEW if serious else (INFO if points else OK)
    return Section(outline_title(), status, text, list(points.values()), remedy, points), g.memory


# --- Update of plan.md (D140) ---------------------------------------------------

def _titles(lines: list[str]) -> list[tuple[int, int, str]]:
    """(index, Markdown level, name) of the headings outside code blocks."""
    res, code = [], False
    for i, l in enumerate(lines):
        if l.lstrip().startswith(('```', '~~~')):
            code = not code
            continue
        if not code and (t := re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', l)):
            res.append((i, len(t.group(1)), t.group(2)))
    return res


def _sections(lines: list[str], subjects: str) -> tuple[dict[str, tuple[int, int, int]], int]:
    """Path -> (start, end, Markdown level) of each section of the subjects, and the end of the subjects section."""
    titles = _titles(lines)
    res, stack, inside, subjects_end = {}, [], False, len(lines)
    for j, (i, lvl, name) in enumerate(titles):
        if lvl == 1:
            if inside:
                subjects_end = i
                break
            inside = name == subjects
            continue
        if not inside:
            continue
        del stack[lvl - 2:]
        stack.append(name)
        end = next((i2 for i2, n2, _ in titles[j + 1:] if n2 <= lvl), len(lines))
        res['/'.join(stack)] = (i, end, lvl)
    if inside:
        for path, (i, end, lvl) in res.items():
            res[path] = (i, min(end, subjects_end), lvl)
    return res, subjects_end


def _insert(lines: list[str], subjects: str, parent: str, block: list[str]) -> list[str]:
    sections, subjects_end = _sections(lines, subjects)
    where = sections[parent][1] if parent else subjects_end
    while where > 0 and not lines[where - 1].strip():
        where -= 1
    # A blank line before the block, and after it if there is not one left before the next heading.
    block = [''] + block + ([''] if where < len(lines) and lines[where].strip() else [])
    return lines[:where] + block + lines[where:]


def _strip_trailing_blanks(block: list[str]) -> list[str]:
    while block and not block[-1].strip():
        block = block[:-1]
    return block


def rename(text: str, subjects: str, old: str, new: str) -> str:
    lines = text.splitlines()
    sections, _ = _sections(lines, subjects)
    start, end, lvl = sections[old]
    block = lines[start:end]
    new_level = new.count('/') + 2
    shift = new_level - lvl
    for i, n, _ in _titles(block):
        block[i] = '#' * (n + shift) + block[i].lstrip('#')
    block[0] = '#' * new_level + ' ' + new.rpartition('/')[2]
    if old.rpartition('/')[0] == new.rpartition('/')[0]:
        lines[start:end] = block
        return '\n'.join(lines) + '\n'
    rest = lines[:start] + lines[end:]
    return '\n'.join(_insert(rest, subjects, new.rpartition('/')[0], _strip_trailing_blanks(block))) + '\n'


def delete(text: str, subjects: str, path: str) -> str:
    lines = text.splitlines()
    start, end, _ = _sections(lines, subjects)[0][path]
    return '\n'.join(lines[:start] + lines[end:]) + '\n'


def add(text: str, subjects: str, path: str) -> str:
    block = ['#' * (path.count('/') + 2) + ' ' + path.rpartition('/')[2]]
    return '\n'.join(_insert(text.splitlines(), subjects, path.rpartition('/')[0], block)) + '\n'


@dataclass
class Tracking:
    text: str = ''
    renamings: dict[str, str] = field(default_factory=dict)  # old path -> new, sub-themes included
    deleted: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)  # what changes, readable


def track(b: Library, cfg: Config) -> Tracking | None:
    """New text of plan.md, from the actions taken in Zotero. None without a plan or without subjects.

    Renamings and additions are done in several passes, each as soon as its parent is in the text (a
    theme can be moved under a theme itself created by hand). Deletions come at the end."""
    seen = review(b, cfg)
    if seen is None:
        return None
    plan, current, g = seen
    subjects = cfg.method.subjects
    text = (cfg.workspace / f.OUTLINE).read_text(encoding='utf-8')
    s = Tracking()
    targets = {n + (f'/{rest}' if rest else '') for a, n in g.renamed.values()
              for ch in plan.nodes if (rest := _subpath(ch, a)) is not None}
    ops: list[tuple] = [('r', a, n) for a, n in sorted(g.renamed.values(), key=lambda x: x[0].count('/'))]
    ops += [('a', ch) for c in sorted(g.created_cols.values())
            for ch in sorted(x for x in current.values() if _subpath(x, c) is not None) if ch not in targets]
    while ops:
        todo = []
        for op in ops:
            sections, _ = _sections(text.splitlines(), subjects)
            path = op[-1]
            parent = path.rpartition('/')[0]
            if parent and parent not in sections:
                todo.append(op)
                continue
            if op[0] == 'a':
                if path.count('/') + 1 > cfg.method.max_depth:
                    s.ignored.append(path)
                    continue
                text = add(text, subjects, path)
                s.added.append(path)
                s.lines.append(L(en=f'added, definition to write: {path}', fr=f'ajouté, définition à écrire : {path}'))
                continue
            _, a, n = op
            cur = s.renamings.get(a, a)
            if cur not in sections:
                s.ignored.append(n)
                continue
            text = rename(text, subjects, cur, n)
            for ch in plan.nodes:
                if (rest := _subpath(ch, a)) is not None:
                    s.renamings[ch] = n + (f'/{rest}' if rest else '')
            what = (L(en='renamed', fr='renommé') if a.rpartition('/')[0] == n.rpartition('/')[0]
                    else L(en='moved', fr='déplacé'))
            s.lines.append(L(en=f'{what}: {a} → {n}', fr=f'{what} : {a} → {n}'))
        if len(todo) == len(ops):
            s.ignored += [op[-1] for op in todo]
            break
        ops = todo
    for a in sorted(g.deleted.values()):
        cur = s.renamings.get(a, a)
        if cur not in _sections(text.splitlines(), subjects)[0]:
            continue
        text = delete(text, subjects, cur)
        s.deleted += [ch for ch in plan.nodes if _subpath(ch, a) is not None]
        s.lines.append(L(en=f'removed, with its sub-themes: {cur}', fr=f'retiré, avec ses sous-thèmes : {cur}'))
    s.ignored += [ch for ch in g.too_deep.values() if ch not in s.ignored]
    s.text = text
    return s


def _rename_path(ch: str, renamings: dict[str, str]) -> str:
    return renamings.get(ch, ch)


def apply_changes(b: Library, cfg: Config, s: Tracking) -> list[str]:
    """Writes plan.md and carries the changed paths over to suivi/fonds.toml and suivi/rangement.toml. The
    references to a deleted theme are removed there. Returns what was removed, readable."""
    removals = []
    lost = set(s.deleted)
    (cfg.workspace / f.OUTLINE).write_text(s.text, encoding='utf-8')
    fs = f.load_tracking(cfg)
    existing_keys = {c.key for c in b.collections.values()}
    kept = []
    for c in fs.collections:
        if c.action in (f.THEME, f.DISTRIBUTE):
            if c.target in lost and c.key not in existing_keys:
                removals.append(L(en=f'suivi/fonds.toml: collection {c.key}, now “{c.target}”, deleted',
                                  fr=f'suivi/fonds.toml : collection {c.key}, devenue « {c.target} », supprimée'))
                continue
            c.target = _rename_path(c.target, s.renamings) if c.target not in lost else c.target
            c.candidates = [_rename_path(x, s.renamings) for x in c.candidates if x not in lost]
        kept.append(c)
    fs.collections = kept
    tags = {}
    for t, target in fs.tags.items():
        if target in lost:
            removals.append(L(en=f'suivi/fonds.toml: tag “{t}”, linked to “{target}”',
                              fr=f'suivi/fonds.toml : tag « {t} », relié à « {target} »'))
        else:
            tags[t] = _rename_path(target, s.renamings)
    fs.tags = tags
    if (cfg.tracking / f.FILE).is_file():
        f.write_tracking(cfg, fs)
    if (cfg.tracking / r.FILE).is_file():
        entries, n = [], 0
        for e in r.load(cfg):
            if e.target in lost:
                n += 1
                continue
            e.target = _rename_path(e.target, s.renamings)
            entries.append(e)
        if n:
            decisions = plural(n, en='decision', fr='décision')
            removals.append(L(en=f'suivi/rangement.toml: {decisions} to a deleted theme',
                              fr=f'suivi/rangement.toml : {decisions} vers un thème supprimé'))
        r.write(cfg, entries, b, privacy.excluded_items(b, cfg))
    return removals


# --- Titles of a theme (D141) ----------------------------------------------------------

def titles(b: Library, cfg: Config, path: str, day: date | None = None) -> tuple[str, int]:
    """All the titles of a theme and its sub-themes, with the plan's definition, so that the agent
    proposes sub-themes (D109). Confidential items stay hidden (D126)."""
    current = subject_collections(b, cfg) or {}
    keys = {k: ch for k, ch in current.items() if _subpath(ch, path) is not None}
    if path not in current.values():
        raise KeyError(L(en=f'No collection “{path}” under “{cfg.method.subjects}”.',
                         fr=f'Aucune collection « {path} » sous « {cfg.method.subjects} ».'))
    hidden = privacy.hidden_keys(b, cfg)
    plan = _plan(cfg) if (cfg.workspace / f.OUTLINE).is_file() else None
    key_of = {c.id: c.key for c in b.collections.values()}
    by: dict[str, list] = {}
    for e in b.items:
        for c in e.collections:
            if key_of[c] in keys:
                by.setdefault(keys[key_of[c]], []).append(e)
    n = len({e.key for v in by.values() for e in v})
    n_items = plural(n, en='item', fr='référence')
    day_text = f'{(day or date.today()):%d/%m/%Y}'
    out = [L(en=f'# Titles of “{path}”, {day_text}', fr=f'# Titres de « {path} », {day_text}'), '',
           L(en=f'{n_items}. Complete list, to propose clean sub-themes. A sub-theme is declared in {f.OUTLINE} '
                f'with its definition, then `zc subjects validate`, and the items go there through "déplacer" '
                f'entries of suivi/rangement.toml (`depuis` = key of the collection left), then '
                f'`zc subjects plan`.',
             fr=f"{n_items}. Liste complète, pour proposer des sous-thèmes nets. "
                f"Un sous-thème se déclare dans {f.OUTLINE} avec sa définition, puis `zc subjects validate`, et les "
                f"références y vont par des entrées « déplacer » de suivi/rangement.toml (`depuis` = clé de la "
                f"collection quittée), puis `zc subjects plan`.")]
    for ch in sorted(set(keys.values())):
        nd = plan.nodes.get(ch) if plan else None
        k = next(x for x, c in keys.items() if c == ch)
        items = sorted(by.get(ch, []), key=lambda e: e.title.lower())
        n_here = plural(len(items), en='item', fr='référence')
        out += ['', f'## {ch} ({k}), {n_here}', '']
        if nd and nd.definition:
            # The definition, then « Inclut. » and « Exclut. » as plan.md writes them, in either language (D228).
            out += [L(en=f'Definition. {nd.definition}', fr=f'Définition. {nd.definition}')] + (
                [L(en=f'Includes. {nd.includes}', fr=f'Inclut. {nd.includes}')] if nd.includes else []) + (
                [L(en=f'Excludes. {nd.excludes}', fr=f'Exclut. {nd.excludes}')] if nd.excludes else []) + ['']
        out += [f'- {line(e, hidden)}' for e in items]
    return '\n'.join(out) + '\n', n
