"""Filing, step 5 (D112 to D122), on a synthetic library and the fake server."""

import itertools

import pytest

from fake_server import FakeServer
from test_apply import write, fake_backup
from zot_clean import apply as a, subjects as f, reader, filing as r
from zot_clean.apply import TRIAL, ALL, apply_plan
from zot_clean.config import Config
from zot_clean.api import APIError

OUTLINE = """\
# 40 Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.

#### Apprentissage perceptif

Apprendre à percevoir.

### Émotion

Émotions.

## Arts

Arts visuels.

# Concepts
"""


class LibraryHelper:
    """Collections and items created both in the synthetic database and on the fake server, with the same keys."""

    def __init__(self, zotero, server):
        self.zotero, self.server = zotero, server
        server._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, name, parent=None):
        key = self.server.collection(name, parent)
        self.ids[key] = self.zotero.collection(name, self.ids[parent] if parent else None, key=key)
        return key

    def item(self, title, *collections, **fields):
        key = self.server._key()
        self.zotero.item(title, collections=tuple(self.ids[c] for c in collections), key=key, **fields)
        self.server.add(title=title, key=key, collections=list(collections))
        return key

    def read(self):
        self.zotero.sync(self.server.version)
        return reader.read(self.zotero.save())


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def cfg(tmp_path, zotero):
    c = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    c.workspace.mkdir()
    c.method.subjects, c.method.archives, c.method.projects = '40 Fonds', '80 Archives', ['20 Cours']
    return c


@pytest.fixture
def world(zotero, server, cfg):
    lib = LibraryHelper(zotero, server)
    k = {'Inbox': lib.collection('Inbox'), 'Fonds': lib.collection('40 Fonds'),
         'Archives': lib.collection('80 Archives'), 'Cours': lib.collection('20 Cours'), 'Vieux': lib.collection('Vieux')}
    k['Psy'] = lib.collection('Psychologie', k['Fonds'])
    k['Perception'] = lib.collection('Perception', k['Psy'])
    k['Emotions'] = lib.collection('Émotions', k['Psy'])
    k['Arts'] = lib.collection('Arts', k['Fonds'])
    k['Musees'] = lib.collection('Musées', k['Arts'])
    k['Ancien'] = lib.collection('Cours ancien', k['Vieux'])
    k['CoursPsy'] = lib.collection('Psy L1', k['Cours'])
    items = {
        'voir': lib.item('Learning to see', k['Perception'], k['CoursPsy']),
        'gibson': lib.item('Perceptual learning', k['Perception']),
        'peur': lib.item('Fear and faces', k['Emotions']),
        'musee': lib.item('Museum displays', k['Musees']),
        'vieux': lib.item('Une vieille chose', k['Vieux']),
        'manuel': lib.item('Introducing HTML5', k['Arts']),
        'ancien': lib.item('Syllabus 2019', k['Ancien']),
    }
    b = lib.read()
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    report, tracking, _, _ = f.inventory(b, cfg)
    actions = {'40 Fonds/Psychologie': (f.THEME, 'Psychologie', []),
             '40 Fonds/Psychologie/Perception': (f.DISTRIBUTE, '', ['Psychologie/Perception',
                                                                   'Psychologie/Perception/Apprentissage perceptif']),
             '40 Fonds/Psychologie/Émotions': (f.THEME, 'Psychologie/Émotion', []),
             '40 Fonds/Arts': (f.THEME, 'Arts', []), '40 Fonds/Arts/Musées': (f.THEME, 'Arts', []),
             'Vieux': (f.DISSOLVE, '', []), 'Vieux/Cours ancien': (f.ARCHIVES, '', [])}
    for c in tracking.collections:
        if c.path in actions:
            c.action, c.target, c.candidates = actions[c.path]
    f.write_tracking(cfg, tracking)
    k_ = f.check(cfg)
    assert not k_.errors, k_.errors
    f.save(cfg, k_)
    r.write(cfg, [
        r.Entry(items['voir'], r.MOVE, 'Psychologie/Perception/Apprentissage perceptif', decision=r.ACCEPT),
        r.Entry(items['manuel'], r.TRASH, source=r.INSTRUCTION, decision=r.ACCEPT),
        r.Entry(items['gibson'], r.MOVE, 'Psychologie/Perception/Apprentissage perceptif'),  # not yet judged
    ], b, set())
    return lib, k, items, b


def ops_by_key(plan):
    return {op.key: op for g in plan.groups for op in g.operations}


def test_plan_of_first_pass(world, cfg, server):
    lib, k, items, b = world
    plan, report = r.make_plan(b, cfg, server.client())
    assert plan.step == 'fonds'
    ops = ops_by_key(plan)
    # Émotions renamed in place, key kept (D113).
    assert ops[k['Emotions']].after == {'name': 'Émotion'} and ops[k['Emotions']].kind == 'collections'
    # Sub-theme created under Perception, the judged item moves into it and leaves Perception (D115).
    created_op = next(op for op in ops.values() if op.create and op.after['name'] == 'Apprentissage perceptif')
    assert created_op.after == {'name': 'Apprentissage perceptif', 'parentCollection': k['Perception']}
    assert ops[items['voir']].after['collections'] == [k['CoursPsy'], created_op.key]
    assert items['gibson'] not in ops  # proposal not accepted
    # Musées merged into Arts then trashed, Vieux dissolved, Cours ancien archived (D117, D113).
    assert ops[items['musee']].after['collections'] == [k['Arts']]
    assert ops[k['Musees']].after == {'deleted': True} and ops[k['Vieux']].after == {'deleted': True}
    # Archived at its current path (default target), under a « Vieux » collection created in the archives.
    old_archive = next(op for op in ops.values() if op.create and op.after['name'] == 'Vieux')
    assert old_archive.after['parentCollection'] == k['Archives']
    assert ops[k['Ancien']].after == {'parentCollection': old_archive.key}
    assert ops[items['manuel']].after == {'deleted': True}
    # Groups in tree order (D120): Psychologie/Perception/… before Émotion before Arts, trash at the end.
    titles = [g.title for g in plan.groups]
    assert titles.index('40 Fonds/Psychologie/Perception/Apprentissage perceptif') < titles.index(
        '40 Fonds/Psychologie/Émotion') < titles.index('40 Fonds/Arts')
    assert plan.groups[-1].title == 'fiches à la corbeille'
    # The items of Vieux (dissolved) and Cours ancien (archived) no longer have a place in the fonds (D20).
    assert 'Fiches sans place dans le fonds' in report and '2 fiches ne seront dans aucun thème du fonds' in report
    assert 'Musées dans 40 Fonds/Arts' in report


def test_apply_then_undo(world, cfg, server):
    lib, k, items, b = world
    plan, report = r.make_plan(b, cfg, server.client())
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, ALL)
    assert not outcome.conflicts and not outcome.errors
    assert server.collections[k['Emotions']]['name'] == 'Émotion'
    assert server.collections[k['Musees']]['deleted'] is True
    assert server.all_items[items['manuel']]['deleted'] is True
    new = next(c for c, d in server.collections.items() if d['name'] == 'Apprentissage perceptif')
    assert new in server.all_items[items['voir']]['collections']


def test_subtheme_already_created_recognized(world, cfg, server, zotero):
    """A following pass finds the sub-theme created by the previous one, by its path (D119)."""
    lib, k, items, _ = world
    under = lib.collection('Apprentissage perceptif', k['Perception'])
    b = lib.read()
    plan, _ = r.make_plan(b, cfg, server.client())
    ops = ops_by_key(plan)
    assert not any(op.create and op.after['name'] == 'Apprentissage perceptif' for op in ops.values())
    assert ops[items['voir']].after['collections'] == [k['CoursPsy'], under]


def test_roots_on_demand(world, cfg, server):
    lib, k, items, b = world
    plan, _ = r.make_plan(b, cfg, server.client())
    assert not any(op.nature == 'racine' for g in plan.groups for op in g.operations)
    plan, _ = r.make_plan(b, cfg, server.client(), with_roots=True)
    last = [op for g in plan.groups[-3:] for op in g.operations if op.nature == 'racine']
    assert {op.after['name'] for op in last} == {'Fonds', 'Archives', 'Cours'}


def test_match_after_renaming_roots(world, cfg, server, zotero):
    lib, k, items, _ = world
    zotero.db.execute("update collections set collectionName = 'Fonds' where key = ?", (k['Fonds'],))
    with pytest.raises(SystemExit, match='à reporter dans config.toml'):
        r.make_plan(lib.read(), cfg, server.client())


def test_structure_modified_since_validation(world, cfg, server):
    lib, k, items, b = world
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE.replace('# Concepts', '## Sociologie\n\nSociétés.\n\n# Concepts'),
                                               encoding='utf-8')
    with pytest.raises(SystemExit, match='pas validé'):
        r.make_plan(b, cfg, server.client())


def test_nothing_to_do_when_all_in_place(zotero, server, cfg):
    lib = LibraryHelper(zotero, server)
    subjects = lib.collection('40 Fonds')
    psy = lib.collection('Psychologie', subjects)
    lib.item('Titre', psy)
    b = lib.read()
    (cfg.workspace / f.OUTLINE).write_text('# 40 Fonds\n\n## Psychologie\n\nDéfinition.\n', encoding='utf-8')
    _, tracking, _, _ = f.inventory(b, cfg)
    assert tracking.collections[0].action == f.THEME  # prefilled: already in its place in the plan
    f.write_tracking(cfg, tracking)
    f.save(cfg, f.check(cfg))
    plan, _ = r.make_plan(b, cfg, server.client())
    assert plan.groups == []


def test_unknown_action(cfg):
    cfg.tracking.mkdir(parents=True)
    (cfg.tracking / r.FILE).write_text('[[fiche]]\ncle = "AAAA2222"\naction = "jeter"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='action inconnue'):
        r.load(cfg)


def test_pending_and_tag_proposals(world, cfg, server, zotero):
    """D121: batches of items to distribute and without a place, proposals drawn from tags, filter respected."""
    lib, k, items, _ = world
    tagged = lib.item('Perceptual expertise', k['Perception'], tags=('apprentissage visuel',))
    lib.item('Carnet privé', k['Perception'], tags=('_privé',))
    b = lib.read()
    s = f.load_tracking(cfg)
    s.tags['apprentissage visuel'] = 'Psychologie/Perception/Apprentissage perceptif'
    f.write_tracking(cfg, s)
    report, bundles, additions = r.pending(b, cfg)
    perception = next(p for p in bundles if p.origin == k['Perception'])
    # « voir » and « gibson » are already in rangement.toml, the private item is omitted.
    assert [el.key for el in perception.items] == [tagged]
    assert 'Carnet privé' not in report and 'Apprendre à percevoir.' in report
    assert additions == 1
    entry = next(x for x in r.load(cfg) if x.key == tagged)
    assert (entry.action, entry.source, entry.decision, entry.origin) == (r.MOVE, r.TAG, '', k['Perception'])
    assert entry.note == 'tag « apprentissage visuel »'  # reread by step 6 (test_mots_lus)
    without = next(p for p in bundles if p.source == 'sans place dans le fonds')
    assert {el.key for el in without.items} == {items['vieux'], items['ancien']}
    # The paths an item is filed in, as in the other bundles: themes and sub-themes, and a discipline without theme.
    assert without.candidates == ['Psychologie/Perception', 'Psychologie/Perception/Apprentissage perceptif',
                                  'Psychologie/Émotion', 'Arts']
    assert '- **Psychologie/Émotion**. Émotions.' in report and '- **Psychologie**.' not in report
    # Rerun, nothing is proposed twice.
    assert r.pending(b, cfg)[2] == 0


def test_pending_creates_the_decisions_file(world, cfg):
    """Without rangement.toml, `a-ranger` writes it with its header and a commented example, which reads as no entry
    and whose example, uncommented, is a valid entry (pilot rehearsal)."""
    lib, k, items, _ = world
    lib.item('Sans collection')
    (cfg.tracking / r.FILE).unlink()
    report, _, _ = r.pending(lib.read(), cfg)
    text = (cfg.tracking / r.FILE).read_text(encoding='utf-8')
    assert text == r.header() and r.load(cfg) == []
    example = text.split('# [[fiche]]', 1)[1]
    (cfg.tracking / r.FILE).write_text('[[fiche]]' + example.replace('\n# ', '\n'), encoding='utf-8')
    assert [(x.key, x.action, x.target) for x in r.load(cfg)] == [('ABCD2345', r.MOVE, 'Psychologie/Perception')]
    assert '## Paquet 2 · sans place dans le fonds\n' in report and 'zc subjects accept CLÉ=CHEMIN' in report
    assert 'Une vieille chose · Article de revue · aussi dans Vieux\n' in report
    assert 'Sans collection · Article de revue · hors de toute collection' in report


def test_abstract_refused_for_excluded_item(world, cfg):
    lib, k, items, _ = world
    private_item = lib.item('Carnet privé', k['Perception'], tags=('_privé',), abstractNote='secret')
    public_item = lib.item('Public', k['Perception'], abstractNote='Un résumé.')
    b = lib.read()
    assert 'Un résumé.' in r.abstract(b, cfg, public_item)
    with pytest.raises(SystemExit, match='exclue'):
        r.abstract(b, cfg, private_item)


def test_pending_and_make_plan_commands(world, cfg, server, monkeypatch, capsys):
    from zot_clean import api
    lib, k, items, b = world
    from zot_clean.cli import main
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n[methode]\nfonds = "40 Fonds"\n'
        'archives = "80 Archives"\nprojets = ["20 Cours"]\n', encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['subjects', 'pending', *folder]) == 0
    assert 'paquet(s)' in capsys.readouterr().out
    assert list((cfg.workspace / 'rapports').glob('fonds-a-ranger-*.md'))
    assert main(['subjects', 'plan', *folder]) == 0
    output = capsys.readouterr()
    assert '--trial' in output.out and 'État visé calculé' in output.err
    # A refusal exits with a non-zero code and its message on the error output (pilot rehearsal).
    assert main(['subjects', 'pending', '--reviewed', k['Arts'], *folder]) == 1
    assert "n'est pas une collection à répartir" in capsys.readouterr().err


def test_readable_report(world, cfg, server):
    lib, k, items, b = world
    _, report = r.make_plan(b, cfg, server.client())
    assert 'création de « Apprentissage perceptif » sous 40 Fonds/Psychologie/Perception' in report
    assert '« Émotions » renommée « Émotion »' in report
    assert 'Vieux à la corbeille' in report


def test_local_copy_behind_server(world, cfg, server):
    """After a pass, as long as Zotero has not received the changes, planning refuses: otherwise the collections
    created by the pass, absent from the local copy, would be recreated (found on the real library)."""
    lib, k, items, b = world
    server.collection('Apprentissage perceptif', k['Perception'])  # created by a pass, not yet received
    with pytest.raises(SystemExit, match='pas encore reçu'):
        r.make_plan(b, cfg, server.client())


def test_late_copy_caught_up_by_api(world, cfg, server):
    """D171: a pass that Zotero has not yet received is read from zotero.org, without waiting for the sync.
    The collection created by the pass is therefore not recreated."""
    lib, k, items, b = world
    new = server.collection('Apprentissage perceptif', k['Perception'])  # created by a pass
    server.modify(items['voir'], collections=[k['CoursPsy'], new])
    server.collections[k['Vieux']].update(deleted=True, version=server.version + 1)
    server.version += 1
    server.delete(items['ancien'])
    messages = []
    b2 = a.read_up_to_date(cfg, server.client(), messages.append, read=lambda: b)
    assert b2.version == server.version and len(messages) == 1 and '4 changement(s)' in messages[0]
    by_key = b2.by_key()
    assert items['ancien'] not in by_key
    assert {b2.path(c) for c in by_key[items['voir']].collections} == {
        '20 Cours/Psy L1', '40 Fonds/Psychologie/Perception/Apprentissage perceptif'}
    assert 'Vieux' not in {c.name for c in b2.collections.values()}
    plan, _ = r.make_plan(b2, cfg, server.client())  # no longer refuses
    assert not any(op.create and op.after.get('name') == 'Apprentissage perceptif'
                   for g in plan.groups for op in g.operations)


def test_up_to_date_copy_without_catch_up(world, cfg, server):
    lib, k, items, b = world
    messages, client = [], server.client()
    assert a.read_up_to_date(cfg, client, messages.append, read=lambda: b) is b
    assert not messages and not any('since' in c for _, c in server.requests)


def test_chained_decisions(world, cfg, server):
    """Émotions to Perception, then Perception to Apprentissage perceptif: the item goes directly into the
    sub-theme, without keeping Perception, which it never had (found on the real library)."""
    lib, k, items, b = world
    entries = r.load(cfg) + [
        r.Entry(items['peur'], r.MOVE, 'Psychologie/Perception', k['Emotions'], decision=r.ACCEPT),
        r.Entry(items['peur'], r.MOVE, 'Psychologie/Perception/Apprentissage perceptif', k['Perception'],
                 decision=r.ACCEPT)]
    r.write(cfg, entries, b, set())
    plan, _ = r.make_plan(b, cfg, server.client())
    ops = ops_by_key(plan)
    created_op = next(op for op in ops.values() if op.create and op.after['name'] == 'Apprentissage perceptif')
    assert ops[items['peur']].after['collections'] == [created_op.key]


def test_reviewed_collection(world, cfg, server, zotero):
    """A collection to distribute, fully judged: its items left in place are no longer presented, those that arrive
    in it afterwards are (D124)."""
    lib, k, items, b = world
    entries = r.load(cfg)
    with pytest.raises(SystemExit, match='attente'):  # the proposal on « gibson » is not judged
        r.mark_reviewed(b, cfg, [k['Perception']])
    for x in entries:
        x.decision = x.decision or r.REJECT
    r.write(cfg, entries, b, set())
    stayed = lib.item('Laissée en place, sans entrée', k['Perception'])
    _, bundles, _ = r.pending(lib.read(), cfg)
    assert [el.key for p in bundles if p.origin == k['Perception'] for el in p.items] == [stayed]
    assert r.mark_reviewed(lib.read(), cfg, [k['Perception']]) == {'40 Fonds/Psychologie/Perception': 3}
    new = lib.item('Arrivée ensuite', k['Perception'])
    _, bundles, _ = r.pending(lib.read(), cfg)
    assert [el.key for p in bundles if p.origin == k['Perception'] for el in p.items] == [new]
    with pytest.raises(SystemExit, match="n'est pas une collection à répartir"):
        r.mark_reviewed(b, cfg, [k['Arts']])


def _misc(lib, cfg, b, candidates):
    """Gives the « répartir » fate to the « Divers » collection and revalidates the plan."""
    misc = next(c.key for c in b.collections.values() if c.name == 'Divers')
    _, tracking, _, _ = f.inventory(b, cfg)
    for c in tracking.collections:
        if c.key == misc:
            c.action, c.candidates = f.DISTRIBUTE, candidates
    f.write_tracking(cfg, tracking)
    f.save(cfg, f.check(cfg))
    return misc


def test_split_collection_reviewed_to_trash(world, cfg, server):
    """A collection to distribute that is outside the plan, once examined, goes to the trash even if items were left
    in it, since they have their place elsewhere or are presented as without a place (D167). An item arriving
    afterwards holds it back until it is judged."""
    lib, k, items, _ = world
    misc = lib.collection('Divers')
    is_left_out = lib.item('Déjà en psychologie', misc, k['Psy'])
    part = lib.item('Des musées', misc)
    b = lib.read()
    _misc(lib, cfg, b, ['Psychologie', 'Arts'])
    r.write(cfg, r.load(cfg) + [r.Entry(part, r.MOVE, 'Arts', misc, decision=r.ACCEPT)], b, set())
    plan, _ = r.make_plan(b, cfg, server.client())
    assert misc not in ops_by_key(plan)  # « Déjà en psychologie » stays there, collection not yet examined
    r.mark_reviewed(b, cfg, [misc])
    plan, report = r.make_plan(b, cfg, server.client())
    ops = ops_by_key(plan)
    assert ops[misc].after == {'deleted': True} and is_left_out not in ops
    assert 'corbeille : Divers (répartie et examinée)' in [g.title for g in plan.groups]
    assert '## Collections réparties' in report and '- Divers, 1 fiche laissée' in report
    lib.item('Arrivée après examen', misc)
    plan, _ = r.make_plan(lib.read(), cfg, server.client())
    assert misc not in ops_by_key(plan)


def test_reviewed_collection_already_trashed(world, cfg, server):
    """A collection to distribute emptied and trashed by a pass: `--reviewed` says there is nothing left to mark,
    rather than that it is not a collection to distribute (skills audit, D246)."""
    lib, k, items, _ = world
    misc = lib.collection('Divers')
    b = lib.read()
    _misc(lib, cfg, b, ['Arts'])
    b.collections = {cid: c for cid, c in b.collections.items() if c.key != misc}
    with pytest.raises(SystemExit, match='corbeille'):
        r.mark_reviewed(b, cfg, [misc])



def test_split_collection_with_its_subcollection(world, cfg, server):
    """A collection to distribute and its sub-collection, both examined, go to the trash in the same pass
    (the second pass was only needed for the parent, pilot rehearsal)."""
    lib, k, items, _ = world
    misc = lib.collection('Divers')
    under = lib.collection('À trier', misc)
    lib.item('Déjà en psychologie', under, k['Psy'])
    b = lib.read()
    _, tracking, _, _ = f.inventory(b, cfg)
    for c in tracking.collections:
        if c.key in (misc, under):
            c.action, c.candidates = f.DISTRIBUTE, ['Psychologie']
    f.write_tracking(cfg, tracking)
    f.save(cfg, f.check(cfg))
    r.mark_reviewed(b, cfg, [misc, under])
    plan, report = r.make_plan(b, cfg, server.client())
    ops = ops_by_key(plan)
    assert ops[misc].after == ops[under].after == {'deleted': True}
    assert 'garde des sous-collections' not in report

def test_item_shown_in_single_batch(world, cfg, server):
    """An item of a collection to distribute that is outside the plan, with no other place in the fonds, is only
    presented in its collection's batch, not also among the items without a place (found at the pilot rehearsal)."""
    lib, k, items, _ = world
    lone_item = lib.item('Seule dans Divers', lib.collection('Divers'))
    b = lib.read()
    _misc(lib, cfg, b, ['Arts'])
    _, bundles, _ = r.pending(b, cfg)
    assert [p.source for p in bundles if lone_item in {el.key for el in p.items}] == ['Divers']


def test_item_of_two_collections_to_distribute(world, cfg, server):
    """An item of two collections to distribute appears only in the bundle of the first one in the order of
    suivi/fonds.toml, and its tags give a single proposal. No proposal sends an item to a theme it is already in, or
    whose sub-theme it is in (pilot bench)."""
    lib, k, items, _ = world
    misc = lib.collection('Divers')
    both = lib.item('In two catch-alls', misc, k['Perception'], tags=('beaux-arts',))
    in_place = lib.item('Already in Perception', misc, k['Perception'], tags=('apprentissage visuel',))
    in_subtheme = lib.item('Already under Psychologie', misc, k['Perception'], tags=('psycho',))
    alone = lib.item('Only in Divers', misc, tags=('apprentissage visuel',))
    b = lib.read()
    _misc(lib, cfg, b, ['Arts', 'Psychologie/Perception'])
    s = f.load_tracking(cfg)
    s.tags.update({'apprentissage visuel': 'Psychologie/Perception', 'psycho': 'Psychologie', 'beaux-arts': 'Arts'})
    f.write_tracking(cfg, s)
    order = [c.key for c in f.load_tracking(cfg).collections if c.key in (misc, k['Perception'])]
    report, bundles, additions = r.pending(b, cfg)
    for key in (both, in_place, in_subtheme):
        assert [p.origin for p in bundles if key in {el.key for el in p.items}] == order[:1]
    assert additions == 2
    proposals = {x.key: (x.target, x.origin) for x in r.load(cfg) if x.source == r.TAG}
    assert proposals == {both: ('Arts', order[0]), alone: ('Psychologie/Perception', misc)}
    assert "celui de sa première collection à répartir dans l'ordre de `suivi/fonds.toml`" in report


def test_pending_report_says_what_it_counts(world, cfg, server):
    """The report of `pending` splits its number between the collections to distribute and the items in no theme,
    the filing plan says that its own number covers only the latter (pilot bench)."""
    lib, k, items, _ = world
    lib.item('Not yet judged', k['Perception'])
    b = lib.read()
    report, bundles, _ = r.pending(b, cfg)
    assert sum(len(p.items) for p in bundles) == 3
    assert ('3 fiches en 2 paquets de 50 au plus, à savoir 1 fiche des collections à répartir, '
            "qu'elles aient déjà ou non une place dans le fonds, et 2 fiches dans aucun thème du fonds") in report
    _, plan_report = r.make_plan(b, cfg, server.client())
    assert ('2 fiches ne seront dans aucun thème du fonds après ce plan, hors Inbox, y compris celles qui ne '
            'restent que dans une collection à répartir.') in plan_report


def test_optional_reading_without_zotero_org(world, cfg, server):
    """A command that only reads (`zc voir`) makes do with the local copy if zotero.org does not answer."""
    lib, k, items, b = world
    server.outages = [503] * 5
    messages = []
    assert a.read_up_to_date(cfg, server.client(), messages.append, read=lambda: b, optional=True) is b
    assert 'injoignable' in messages[0]
    server.outages = [503] * 5
    with pytest.raises(APIError):
        a.read_up_to_date(cfg, server.client(), read=lambda: b)


def test_archive_without_target_no_longer_moves(world, cfg, server):
    """An archived collection without a target goes to its current path under the archives. At the next pass it is
    already there: nothing moves it again to « Archives/Archives/… » (pilot rehearsal)."""
    lib, k, items, b = world
    plan, _ = r.make_plan(b, cfg, server.client())
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    assert not apply_plan(plan, path, server.client(), cfg, ALL).conflicts
    b2 = a.read_up_to_date(cfg, server.client(), read=lambda: b)
    assert b2.path(next(c for c in b2.collections.values() if c.key == k['Ancien']).id) == \
        '80 Archives/Vieux/Cours ancien'
    plan2, _ = r.make_plan(b2, cfg, server.client())
    assert plan2.groups == [], [g.title for g in plan2.groups]


def test_items_left_out_of_subjects(world, cfg, server):
    """D176: an item without a place, seen and left outside the fonds by decision, no longer comes back in `a-ranger`,
    the Inbox triage or point 12 of the audit, which counts it separately. It comes back if its collections change."""
    from zot_clean import checkup, inbox
    lib, k, items, _ = world
    loose_item = lib.item('Notes diverses')  # outside any collection
    in_inbox = lib.item('À trier', k['Inbox'])
    b = lib.read()

    def unplaced(b):
        return {el.key for p in r.pending(b, cfg)[1] if not p.origin for el in p.items}

    assert loose_item in unplaced(b) and loose_item in {a.item.key for a in inbox.to_sort(b, cfg)}
    section, _ = checkup.outline_check(b, cfg)
    assert f'hors fonds · {loose_item}' in section.points
    # Refusal: an Inbox item, an item already in the fonds, an item with a pending decision.
    with pytest.raises(SystemExit, match="Inbox"):
        r.leave_out(b, cfg, [in_inbox])
    with pytest.raises(SystemExit, match='déjà sa place'):
        r.leave_out(b, cfg, [items['peur']])
    r.write(cfg, r.load(cfg) + [r.Entry(loose_item, r.MOVE, 'Arts')], b, set())
    with pytest.raises(SystemExit, match='en attente ou acceptée'):
        r.leave_out(b, cfg, [loose_item])
    r.write(cfg, [x for x in r.load(cfg) if x.key != loose_item] + [r.Entry(loose_item, r.MOVE, 'Arts',
                                                                         decision=r.REJECT)], b, set())
    assert r.leave_out(b, cfg, [loose_item, items['ancien']]) == sorted([loose_item, items['ancien']])

    assert loose_item not in unplaced(b)
    report, _, _ = r.pending(b, cfg)
    assert 'Fiches laissées hors du fonds par décision' in report
    listing, left_out = inbox.to_sort_and_left_out(b, cfg)
    assert loose_item not in {a.item.key for a in listing} and loose_item in {a.item.key for a in left_out}
    assert in_inbox in {a.item.key for a in listing}
    section, _ = checkup.outline_check(b, cfg)
    assert f'hors fonds · {loose_item}' not in section.points
    assert 'laissées hors du fonds par décision' in section.summary
    # The filing plan counts them separately. « Cours ancien » is archived without changing key, its item stays
    # left out. « Vieux » goes to the trash, its item is not left out and stays counted as without a place.
    _, report = r.make_plan(b, cfg, server.client())
    assert '1 fiche ne sera dans aucun thème du fonds' in report and '2 autres fiches laissées hors du fonds' in report

    # Filed in another collection, the item comes back (its refused decision removed, otherwise `a-ranger` omits it).
    r.write(cfg, [x for x in r.load(cfg) if x.key != loose_item], b, set())
    server.modify(loose_item, collections=[k['Vieux']])
    b2 = a.read_up_to_date(cfg, server.client(), read=lambda: b)
    assert loose_item in unplaced(b2) and loose_item in {x.item.key for x in inbox.to_sort(b2, cfg)}


def test_leave_out_command(world, cfg, server, monkeypatch, capsys):
    from zot_clean.cli import main
    lib, k, items, b = world
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n[methode]\nfonds = "40 Fonds"\n'
        'archives = "80 Archives"\nprojets = ["20 Cours"]\n', encoding='utf-8')
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['subjects', 'pending', '--leave-out', items['ancien'], *folder]) == 0
    assert '1 fiche(s) laissée(s) hors du fonds' in capsys.readouterr().out
    assert (cfg.tracking / r.LEFT_OUT).is_file()
    assert main(['subjects', 'pending', '--leave-out', items['peur'], *folder]) == 1
    assert 'déjà sa place' in capsys.readouterr().err


def test_item_filed_after_creation_of_all_its_collections(world, cfg, server):
    """An item that enters two collections created by the plan goes in the group of the last one created. In the
    first one's group, the trial (or a previous batch) would write it before the second exists, and the group would
    fail."""
    lib, k, items, b = world
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE.replace('# Concepts', '## Sociologie\n\nSociétés.\n\n# Concepts'),
                                               encoding='utf-8')
    f.save(cfg, f.check(cfg))
    r.write(cfg, r.load(cfg) + [
        r.Entry(items['peur'], r.ADD, 'Psychologie/Perception/Apprentissage perceptif', decision=r.ACCEPT),
        r.Entry(items['peur'], r.ADD, 'Sociologie', decision=r.ACCEPT)], b, set())
    plan, _ = r.make_plan(b, cfg, server.client())
    titles = [g.title for g in plan.groups]
    first = titles.index('40 Fonds/Psychologie/Perception/Apprentissage perceptif')
    socio = titles.index('40 Fonds/Sociologie')
    assert first < socio
    assert items['peur'] in {op.key for op in plan.groups[socio].operations}
    # The trial stops before Sociologie is created: none of its writes targets a missing collection.
    cfg.writing.trial = first + 1
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert not outcome.errors and not outcome.conflicts


def test_reports_and_header_in_english(world, cfg, server):
    from zot_clean.lang import language
    lib, k, items, b = world
    with language('en'):
        plan, report = r.make_plan(b, cfg, server.client())
        pending_report, bundles, _ = r.pending(b, cfg)
        header = r.header()
    assert report.startswith('# Filing plan of')
    assert 'creation of "Apprentissage perceptif" under 40 Fonds/Psychologie/Perception' in report
    assert '"Émotions" renamed "Émotion"' in report and 'Vieux to the trash' in report
    assert plan.description.startswith('Filing of the subjects')
    assert '# Items to file' in pending_report and '## Bundle 1' in pending_report and 'Candidates:' in pending_report
    assert any(p.source == 'no place in the subjects' for p in bundles)
    assert header.startswith('# Item-by-item filing decisions, read by `zc subjects plan`')
    assert r.header().startswith('# Décisions de rangement')  # French outside the block


def test_paths_of_the_report_after_the_plan(zotero, server, cfg):
    """A collection left in place under an old collection moved into the subjects is shown under the subjects root,
    like the collection created under it, and not at its current path (pilot bench, « Fonds/Sociologie/Méthodes »
    beside « Sociologie/Éducation »)."""
    lib = LibraryHelper(zotero, server)
    lib.collection('40 Fonds')
    psy = lib.collection('Psychologie')  # old tree, at the root of the library
    perception = lib.collection('Perception', psy)
    lib.collection('Émotions', psy)
    lib.collection('Arts', lib.collection('Beaux-arts'))
    item = lib.item('Learning to see', perception)
    b = lib.read()
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    _, tracking, _, _ = f.inventory(b, cfg)
    actions = {'Psychologie': (f.THEME, 'Psychologie'), 'Psychologie/Perception': (f.THEME, 'Psychologie/Perception'),
               'Psychologie/Émotions': (f.THEME, 'Psychologie/Émotion'), 'Beaux-arts/Arts': (f.THEME, 'Arts'),
               'Beaux-arts': (f.DISSOLVE, '')}
    for c in tracking.collections:
        if c.path in actions:
            c.action, c.target = actions[c.path]
    f.write_tracking(cfg, tracking)
    checked = f.check(cfg)
    assert not checked.errors, checked.errors
    f.save(cfg, checked)
    r.write(cfg, [r.Entry(item, r.MOVE, 'Psychologie/Perception/Apprentissage perceptif', decision=r.ACCEPT)], b,
            set())
    plan, report = r.make_plan(b, cfg, server.client())
    titles = [g.title for g in plan.groups]
    assert '40 Fonds/Psychologie/Perception/Apprentissage perceptif' in titles
    assert not any(t.startswith('Psychologie') for t in titles)
    assert ('entre dans 40 Fonds/Psychologie/Perception/Apprentissage perceptif, quitte 40 Fonds/Psychologie/'
            'Perception') in report
    assert 'sous 40 Fonds/Psychologie/Perception' in report
    # A moved collection leaves its current place: Arts goes from Beaux-arts, as it is now, to 40 Fonds.
    assert 'déplacée de Beaux-arts vers 40 Fonds' in report
    assert 'les thèmes étant sous « 40 Fonds »' in report


def _entries(cfg, key):
    return [(x.action, x.target, x.origin, x.source, x.decision) for x in r.load(cfg) if x.key == key]


def test_accept_deduces_action_and_collection_left(world, cfg, server):
    """D245: `zc subjects accept KEY=PATH` finds « déplacer » or « ajouter » and `depuis` by the rule of the
    reports: the Inbox, then the first collection to distribute, then the only theme, otherwise added."""
    lib, k, items, _ = world
    new = lib.item('Nouvelle fiche', k['Inbox'])
    twice = lib.item('Deux thèmes', k['Emotions'], k['Musees'])
    b = lib.read()
    w = r.accept(b, cfg, [f'{new}=Psychologie/Émotion', f'{items["peur"]}=40 Fonds/Arts', f'{items["vieux"]}=Arts',
                          f'{items["ancien"]}= Psychologie / Perception ', items['gibson']])
    assert w.accepted == 5 and not w.replaced
    assert _entries(cfg, new) == [(r.MOVE, 'Psychologie/Émotion', k['Inbox'], r.AGENT, r.ACCEPT)]
    assert _entries(cfg, items['peur']) == [(r.MOVE, 'Arts', k['Emotions'], r.AGENT, r.ACCEPT)]
    assert _entries(cfg, items['vieux']) == [(r.ADD, 'Arts', '', r.AGENT, r.ACCEPT)]
    assert _entries(cfg, items['ancien']) == [(r.ADD, 'Psychologie/Perception', '', r.AGENT, r.ACCEPT)]
    # KEY alone accepts the proposal already written, with its own target and collection left.
    assert _entries(cfg, items['gibson']) == [(r.MOVE, 'Psychologie/Perception/Apprentissage perceptif', '',
                                               r.AGENT, r.ACCEPT)]
    with pytest.raises(SystemExit, match='plusieurs thèmes'):
        r.accept(b, cfg, [f'{twice}=Psychologie/Perception'])
    r.accept(b, cfg, [f'{twice}=Psychologie/Perception'], origin=k['Musees'], user=True, note='Demandé.')
    assert _entries(cfg, twice) == [(r.MOVE, 'Psychologie/Perception', k['Musees'], r.INSTRUCTION, r.ACCEPT)]
    # Already in the collection that will embody the path (« Émotions » renamed « Émotion »): nothing written.
    w = r.accept(b, cfg, [f'{twice}=Psychologie/Émotion'], add=True)
    assert w.accepted == 0 and 'déjà dans' in w.notices[0]


def test_accept_replaces_adds_and_trashes(world, cfg, server):
    """D245: a new place replaces the earlier decision of the item, --add writes a second one, --trash takes keys
    alone."""
    lib, k, items, b = world
    voir = items['voir']
    w = r.accept(b, cfg, [f'{voir}=Arts'])
    assert w.replaced == [f'{voir} : Psychologie/Perception/Apprentissage perceptif → Arts']
    assert [t for _, t, *_ in _entries(cfg, voir)] == ['Arts']
    r.accept(b, cfg, [f'{voir}=Psychologie/Émotion'], add=True)
    assert [(a_, t) for a_, t, *_ in _entries(cfg, voir)] == [(r.MOVE, 'Arts'), (r.ADD, 'Psychologie/Émotion')]
    w = r.accept(b, cfg, [f'{voir}=Arts'])
    assert w.accepted == 0 and 'inchangée' in w.notices[0]
    r.accept(b, cfg, [items['vieux']], trash=True)
    assert _entries(cfg, items['vieux']) == [(r.TRASH, '', '', r.AGENT, r.ACCEPT)]
    with pytest.raises(SystemExit, match='clé seule'):
        r.accept(b, cfg, [f'{items["vieux"]}=Arts'], trash=True)


def test_accept_and_reject_refusals(world, cfg, server):
    """D245: everything is checked before anything is written."""
    lib, k, items, b = world
    before = (cfg.tracking / r.FILE).read_text(encoding='utf-8')
    with pytest.raises(SystemExit, match='Psychologie/Émotion'):  # closest path cited
        r.accept(b, cfg, [f'{items["peur"]}=Arts', f'{items["vieux"]}=Psychologie/Emotions'])
    with pytest.raises(SystemExit, match='Aucune fiche de clé ZZZZ2222'):
        r.accept(b, cfg, ['ZZZZ2222=Arts'])
    with pytest.raises(SystemExit, match='Aucune proposition à accepter'):
        r.accept(b, cfg, [items['peur']])
    with pytest.raises(SystemExit, match="n'est pas une collection"):
        r.accept(b, cfg, [f'{items["peur"]}=Arts'], origin=k['Arts'])
    with pytest.raises(SystemExit, match='Aucune décision ni proposition à refuser'):
        r.reject(b, cfg, [items['gibson'], items['peur']])
    assert (cfg.tracking / r.FILE).read_text(encoding='utf-8') == before
    assert r.reject(b, cfg, [items['gibson']]).rejected == 1
    assert _entries(cfg, items['gibson'])[0][-1] == r.REJECT


def test_accept_and_reject_commands(world, cfg, server, monkeypatch, capsys):
    from zot_clean.cli import main
    lib, k, items, b = world
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n[methode]\nlangue = "en"\nfonds = "40 Fonds"\n'
        'archives = "80 Archives"\nprojets = ["20 Cours"]\n', encoding='utf-8')
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['subjects', 'accept', f'{items["peur"]}=Arts', f'{items["voir"]}=Arts', '--user',
                 '--note', 'Asked by the user.', *folder]) == 0
    out = capsys.readouterr().out
    assert f'{items["voir"]}: Psychologie/Perception/Apprentissage perceptif → Arts' in out
    assert '2 decisions accepted, of which 1 replacing an earlier place' in out and '`zc subjects plan`' in out
    assert _entries(cfg, items['peur'])[0][3] == r.INSTRUCTION
    assert main(['subjects', 'reject', items['gibson'], *folder]) == 0
    assert '1 decision rejected' in capsys.readouterr().out
    assert main(['subjects', 'accept', f'{items["peur"]}=Nowhere', *folder]) == 1
    assert 'is not a path of plan.md' in capsys.readouterr().err


def test_item_trashed_by_decision_not_reported(world, cfg, server):
    """D245, bench pilot: an item sent to the trash by its accepted decision is not reported as missing."""
    lib, k, items, b = world
    for name in ('manuel', 'peur'):
        del b.all_items[next(i for i, e in b.all_items.items() if e.key == items[name])]
    entries = r.load(cfg) + [r.Entry(items['peur'], r.MOVE, 'Arts', decision=r.ACCEPT)]
    outline = f.read_outline((cfg.workspace / f.OUTLINE).read_text(encoding='utf-8'), cfg)
    v = r.compute_target(b, cfg, outline, f.load_tracking(cfg), entries)
    assert not any(items['manuel'] in p for p in v.problems)
    assert any(items['peur'] in p for p in v.problems)
