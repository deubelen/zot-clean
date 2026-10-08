"""Tags, step 6 (D151 to D156), on a synthetic library and the fake server."""

import itertools

import pytest

from fake_server import FakeServer
from test_apply import write as write_plan, fake_backup
from zot_clean import undo, reader, plans, filing as r, tags as t, show
from zot_clean.apply import TRIAL, ALL, apply_plan
from zot_clean.config import Config
from zot_clean.reader import Item

OUTLINE = """\
# Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.

### Émotion

Émotions.

## Arts

Arts visuels.

# Concepts
"""


def api(tags) -> list[dict]:
    return [{'tag': x} if isinstance(x, str) else ({'tag': x[0], 'type': 1} if x[1] == 1 else {'tag': x[0]})
            for x in tags]


class World:
    """Items created both in the synthetic database and on the fake server, with the same keys and tags."""

    def __init__(self, zotero, server):
        self.zotero, self.server = zotero, server
        server._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, name, parent=None):
        key = self.server.collection(name, parent)
        self.ids[key] = self.zotero.collection(name, self.ids[parent] if parent else None, key=key)
        return key

    def item(self, title, *collections, tags=(), **fields):
        key = self.server._key()
        self.ids[key] = self.zotero.item(title, collections=tuple(self.ids[c] for c in collections), key=key,
                                          tags=tags, **fields)
        self.server.add(title=title, key=key, collections=list(collections), tags=api(tags))
        return key

    def pdf(self, parent, tags=()):
        key = self.server._key()
        self.ids[key] = self.zotero.pdf(self.ids[parent], f'{key}.pdf', key=key, tags=tags)
        self.server.add('attachment', key=key, parentItem=parent, tags=api(tags))
        return key

    def annotation(self, attachment, tags=()):
        key = self.server._key()
        self.ids[key] = self.zotero.annotation(self.ids[attachment], tags=tags, key=key)
        self.server.add('annotation', key=key, parentItem=attachment, tags=api(tags))
        return key

    def sync(self):
        """Server tags copied into the local database, as after a Zotero sync."""
        for key, iid in self.ids.items():
            if key in self.server.all_items:
                self.zotero.db.execute('delete from itemTags where itemID = ?', (iid,))
                self.zotero.tags(iid, [(x['tag'], x.get('type', 0)) for x in self.server.all_items[key]['tags']])

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
    c.method.subjects = 'Fonds'
    (c.workspace / 'plan.md').write_text(OUTLINE, encoding='utf-8')
    return c


@pytest.fixture
def world(zotero, server):
    m = World(zotero, server)
    k = {'Inbox': m.collection('Inbox'), 'Fonds': m.collection('Fonds')}
    k['Psy'] = m.collection('Psychologie', k['Fonds'])
    k['Perception'] = m.collection('Perception', k['Psy'])
    k['Emotion'] = m.collection('Émotion', k['Psy'])
    k['Arts'] = m.collection('Arts', k['Fonds'])
    P, E = k['Perception'], k['Emotion']
    x = {
        'f1': m.item('Learning to see', P, tags=(('Humans', 1), ('Attention', 1), 'to read', 'perception visuelle',
                                                   'mémoire', ('Vision', 1))),
        'f2': m.item('Perceptual learning', P, tags=(('Humans', 1), ('Attention', 1), 'perception visuelle', '3 lu',
                                                       'to read')),
        'f3': m.item('Fear and faces', E, tags=(('Attention', 1), 'émotion', 'mémoire')),
        'f4': m.item('Emotional memory', E, tags=(('Attention', 1), ('Emotion', 1))),
        'f5': m.item('Moods', E, tags=(('Attention', 1), 'emotions', 'Machine-Learning')),
        'f6': m.item('Une chose', k['Arts'], tags=('truc divers', 'machine learning')),
        'f7': m.item('Rouge et noir', k['Arts'], tags=('rouge', '_zotfile')),
        'f8': m.item('Sans collection', tags=('perception visuelle',)),
        'f9': m.item('Importée', k['Arts'], tags=tuple(f'mot-clé {i}' for i in range(10))),
        'secret': m.item('Dossier médical', tags=('_privé', 'patient Dupont', ('Secretauto', 1))),
    }
    x['pdf'] = m.pdf(x['f1'], tags=(('PDF-auto', 1),))
    x['annotation'] = m.annotation(x['pdf'], tags=('à revoir',))
    m.zotero.color('rouge')
    m.zotero.search('Vision', 'Vision')
    return m, k, x


def entries(tracking):
    return {e.name: e for e in tracking.tags}


def test_inventory(world, cfg):
    m, k, x = world
    report, tracking = t.inventory(m.read(), cfg)
    e = entries(tracking)
    # Exception to the global rule by item count, spread over two themes: concept (D152, D154).
    assert (e['Attention'].action, e['Attention'].target, e['Attention'].dispersion) == (t.CONCEPT, '#attention', 2)
    assert (e['mémoire'].action, e['mémoire'].target) == (t.CONCEPT, '#mémoire')
    # The target of a variant group is judged on all the group's items: it duplicates the Émotion theme.
    assert (e['émotion'].count, e['émotion'].action, e['émotion'].theme) == (3, t.DELETE, 'Psychologie/Émotion')
    # Rare automatic tag: removed by the rule, no entry. Cited by a saved search: entry required (D156).
    assert 'Humans' not in e and 'PDF-auto' not in e
    assert e['Vision'].searches == ['Vision'] and e['Vision'].grade == t.DOUBTFUL
    # State left over from another habit.
    assert (e['to read'].action, e['to read'].target) == (t.STATUS, '1 à lire')
    # Carried by a single item: obvious to delete.
    assert (e['truc divers'].action, e['truc divers'].grade) == (t.DELETE, t.OBVIOUS)
    # Concentrated in one theme: duplicates it, and the item outside the theme is proposed for filing (D154).
    pv = e['perception visuelle']
    assert (pv.action, pv.theme) == (t.DELETE, 'Psychologie/Perception')
    assert [(a.key, a.action, a.target, a.source) for a in tracking.pending] == [
        (x['f8'], r.ADD, 'Psychologie/Perception', r.TAG)]
    # Variants: doubtful plural, obvious hyphens and case.
    # The group whose target is proposed for deletion is merged into that target's entry, so as not to propose both
    # bringing names back to a tag and deleting that tag.
    assert 'émotion' not in {g.target for g in tracking.variants}
    assert set(e['émotion'].variants) == {'Emotion', 'emotions'}
    assert 'avec ses variantes' in report and "réuni(s) à l'entrée" in report
    ml = next(g for g in tracking.variants if 'machine learning' in g.names)
    assert ml.grade == t.OBVIOUS and set(ml.names) == {'machine learning', 'Machine-Learning'}
    assert 'Emotion' not in e and 'emotions' not in e
    # Protected and technical tags: no proposal (D151).
    assert not {'rouge', '_zotfile', '_privé', '3 lu'} & set(e)
    assert 'rouge (tag coloré' in report and '_zotfile (tag technique' in report
    # Imported keywords (D153).
    assert tracking.imported_summary.startswith('1 fiche') and not any(n.startswith('mot-clé') for n in e)
    # Tag of a confidential item, hidden everywhere (D156).
    assert 'patient Dupont' not in report and t.identifier('patient Dupont') in report
    assert 'Dossier médical' not in report
    # Tags of child items.
    assert 'à revoir (1 élément(s), dont 1 annotation(s))' in report


def test_tracking_written_and_decisions_kept(world, cfg):
    m, k, x = world
    b = m.read()
    _, tracking = t.inventory(b, cfg)
    t.write(cfg, tracking, b)
    text = (cfg.tracking / t.FILE).read_text(encoding='utf-8')
    assert '[automatiques]' in text and '[importes]' in text and '[[variantes]]' in text
    assert '# Durand 2020, « Learning to see »' in text and 'patient Dupont' not in text
    assert [a.key for a in r.load(cfg)] == [x['f8']]
    # The agent changes one proposal, the user accepts another: a rerun keeps everything.
    s = t.load(cfg)
    s.automatic = t.ACCEPT
    for e in s.tags:
        if e.name == 'Attention':
            e.target, e.source = '#attention visuelle', t.AGENT
        if e.name == 'truc divers':
            e.decision = t.ACCEPT
    s.variants[0].decision = t.REJECT
    t.write(cfg, s, b)
    _, tracking2 = t.inventory(m.read(), cfg)
    e = entries(tracking2)
    assert tracking2.automatic == t.ACCEPT
    assert (e['Attention'].target, e['Attention'].source) == ('#attention visuelle', t.AGENT)
    assert e['truc divers'].decision == t.ACCEPT
    assert tracking2.variants[0].decision == t.REJECT
    # The pending filing proposal protects the tag, its entry stays and is not applied yet.
    assert tracking2.pending == [] and 'perception visuelle' in e


def test_load_rejects_inconsistent_file(cfg):
    cfg.tracking.mkdir(parents=True)
    path = cfg.tracking / t.FILE
    path.write_text('[[tag]]\nnom = "x"\nsort = "jeter"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='sort inconnu'):
        t.load(cfg)
    path.write_text('[[tag]]\nnom = "x"\nsort = "concept"\ncible = "x"\ndecision = "accepter"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='doit commencer par « # »'):
        t.load(cfg)
    path.write_text('[[tag]]\nnom = "x"\nsort = "état"\ncible = "lu"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match="ni un état ni une marque"):
        t.load(cfg)
    path.write_text('[[variantes]]\nnoms = ["a"]\ncible = "_privé"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='filtre de confidentialité'):
        t.load(cfg)


def test_forms():
    cfg = Config(workspace=None)
    assert t.form('#Émotions', cfg) == t.form('émotion', cfg) == t.form('EMOTION', cfg)
    assert t.form('chevaux', cfg) == t.form('cheval', cfg) and t.form('réseaux', cfg) == t.form('réseau', cfg)
    assert t.weak_form('Machine-Learning', cfg) == t.weak_form('machine learning', cfg)
    assert t.weak_form('émotions', cfg) != t.weak_form('émotion', cfg)
    assert t.form('_lu', cfg) != t.form('lu', cfg)
    assert t.form('記憶', cfg) == '記憶' and t.form('★', cfg) == '★'


def accept_all(cfg, b, except_=(), keep=('émotion',)):
    """All proposals accepted, except `except_` (left pending). « émotion », which duplicates the Émotion
    theme, is kept."""
    _, tracking = t.inventory(b, cfg)
    tracking.automatic = tracking.imported = t.ACCEPT
    for e in tracking.tags:
        if e.name in keep:
            e.action = t.KEEP
        if e.name not in except_:
            e.decision = t.ACCEPT
    for g in tracking.variants:
        g.decision = t.ACCEPT
    tracking.pending = []
    t.write(cfg, tracking, b)


def item(*tags, type_='journalArticle'):
    return Item(1, 'AAAAAAAA', type_, '', True, tags=list(tags))


def test_targeted_tags(world, cfg):
    m, k, x = world
    b = m.read()
    accept_all(cfg, b)
    s = t.load(cfg)
    for e in s.tags:
        if e.name == 'Vision':
            e.action = t.KEEP
    t.write(cfg, s, b)
    R = t.rules(t.load(cfg), cfg, b)
    # Two variants on one item: a single form, set as manual.
    assert t.targeted_tags(item(('Emotion', 1), ('emotions', 0)), R) == [{'tag': 'émotion'}]
    # Two states: the most advanced wins.
    assert t.targeted_tags(item(('to read', 0), ('3 lu', 0)), R) == [{'tag': '3 lu'}]
    assert t.targeted_tags(item(('to read', 0)), R) == [{'tag': '1 à lire'}]
    # Automatic tag kept: its type stays. Converted to concept: manual.
    assert t.targeted_tags(item(('Vision', 1), ('Attention', 1), ('Humans', 1)), R) == [
        {'tag': 'Vision', 'type': 1}, {'tag': '#attention'}]
    # Protected tags, filter and confidential-item tag untouched, except for the global rule.
    assert t.targeted_tags(item(('_privé', 0), ('rouge', 0), ('_zotfile', 1), ('patient Dupont', 0),
                                ('Secretauto', 1)), R) == [
        {'tag': '_privé'}, {'tag': 'rouge'}, {'tag': '_zotfile', 'type': 1}, {'tag': 'patient Dupont'}]
    # Imported keywords removed, except on an annotation.
    assert t.targeted_tags(item(('mot-clé 1', 0)), R) == []
    assert t.targeted_tags(item(('mot-clé 1', 0), type_='annotation'), R) == [{'tag': 'mot-clé 1'}]
    # New manual tag, to flag at triage (D155).
    assert t.to_flag(item(('inédit', 0), ('#concept', 0), ('3 lu', 0)), R, cfg) == ['inédit']


def test_saved_search_blocks_deletion(world, cfg):
    m, k, x = world
    b = m.read()
    accept_all(cfg, b, except_=('Vision',))
    R = t.rules(t.load(cfg), cfg, b)
    assert {'tag': 'Vision', 'type': 1} in t.targeted_tags(b.by_key()[x['f1']], R)
    accept_all(cfg, b)
    R = t.rules(t.load(cfg), cfg, b)
    assert all(v['tag'] != 'Vision' for v in t.targeted_tags(b.by_key()[x['f1']], R))


def test_protected_changes_only_by_user(world, cfg):
    m, k, x = world
    b = m.read()
    accept_all(cfg, b)
    s = t.load(cfg)
    s.tags.append(t.Entry('rouge', action=t.DELETE, source=t.AGENT, decision=t.ACCEPT))
    s.tags.append(t.Entry(t.identifier('patient Dupont'), action=t.DELETE, source=t.USER,
                           decision=t.ACCEPT))
    s.tags.append(t.Entry('_privé', action=t.DELETE, source=t.USER, decision=t.ACCEPT))
    t.write(cfg, s, b)
    R = t.rules(t.load(cfg), cfg, b)
    assert any('« rouge » est protégé' in p for p in R.problems)
    assert any('filtre de confidentialité' in p for p in R.problems)
    assert t.targeted_tags(item(('rouge', 0), ('patient Dupont', 0), ('_privé', 0)), R) == [
        {'tag': 'rouge'}, {'tag': '_privé'}]


def test_plan_trial_apply_undo_rerun(world, cfg, server):
    m, k, x = world
    b = m.read()
    accept_all(cfg, b)
    plan, report = t.make_plan(b, cfg, server.client())
    ops = {op.key: op for g in plan.groups for op in g.operations}
    # One operation per item, full list, children included, nothing for an unchanged item.
    assert x['f7'] not in ops and x['annotation'] not in ops
    assert ops[x['pdf']].after == {'tags': []}
    assert {d['tag'] for d in ops[x['f1']].after['tags']} == {'#attention', '1 à lire', '#mémoire'}
    assert ops[x['f4']].after['tags'] == [{'tag': '#attention'}, {'tag': 'émotion'}]
    assert ops[x['secret']].after['tags'] == [{'tag': '_privé'}, {'tag': 'patient Dupont'}]
    # The first five groups cover every kind of change.
    kinds = {s for op in ops.values() for s in op.nature.split(', ')}
    first_groups = {s for g in plan.groups[:5] for op in g.operations for s in op.nature.split(', ')}
    assert first_groups == kinds and {'automatique', 'importé', 'variante', 'état', 'concept', 'suppression'} <= kinds
    assert '## Essai' in report and 'patient Dupont' not in report and 'Dossier médical' not in report
    assert '« Vision » cite « Vision »' in report

    path = write_plan(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    # A tag set in Zotero in the meantime puts the item in conflict.
    server.modify(x['f6'], tags=[{'tag': 'truc divers'}, {'tag': 'machine learning'}, {'tag': 'ajouté'}])
    outcome = apply_plan(plan, path, server.client(), cfg, ALL)
    assert list(outcome.conflicts) == [x['f6']] and not outcome.errors
    assert server.all_items[x['f4']]['tags'] == [{'tag': '#attention'}, {'tag': 'émotion'}]
    assert server.all_items[x['f9']]['tags'] == []

    # Undo: the earlier tags come back, types included.
    journals = undo.targeted_journals(path, cfg)
    p_undo, _ = undo.make_plan(journals, server.client(), set())
    c_undo = plans.write(p_undo, cfg.plans, '# annulation')
    apply_plan(p_undo, c_undo, server.client(), cfg, TRIAL)
    apply_plan(p_undo, c_undo, server.client(), cfg, ALL)
    assert server.all_items[x['f4']]['tags'] == [{'tag': 'Attention', 'type': 1}, {'tag': 'Emotion', 'type': 1}]
    assert server.all_items[x['pdf']]['tags'] == [{'tag': 'PDF-auto', 'type': 1}]



def test_rerun_after_apply(world, cfg, server):
    """A pass applied then received by Zotero: nothing left to do (D119). An interrupted pass only replans the
    remaining items."""
    m, k, x = world
    accept_all(cfg, m.read())
    plan, _ = t.make_plan(m.read(), cfg, server.client())
    path = write_plan(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    m.sync()
    rest, _ = t.make_plan(m.read(), cfg, server.client())
    assert {g.id for g in rest.groups} == {g.id for g in plan.groups[cfg.writing.trial:]}
    fake_backup(cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, ALL)
    assert not outcome.conflicts and not outcome.errors
    m.sync()
    end, _ = t.make_plan(m.read(), cfg, server.client())
    assert end.groups == []


def test_late_local_copy(world, cfg, server):
    m, k, x = world
    b = m.read()
    server.modify(x['f1'], title='Changé ailleurs')
    with pytest.raises(SystemExit, match='pas encore reçu'):
        t.make_plan(b, cfg, server.client())


def test_show_tag(world, cfg):
    m, k, x = world
    b = m.read()
    text = show.describe_tag(b, cfg, 'Attention')
    assert 'automatique, porté par 5 élément(s)' in text and 'Learning to see' in text
    assert 'Fonds/Psychologie/Perception' in text and '(automatique)' in text
    assert 'Noms de même forme : Emotion, emotions, émotion.' in show.describe_tag(b, cfg, 'Émotion')
    secret = show.describe_tag(b, cfg, t.identifier('patient Dupont'))
    assert 'patient Dupont' not in secret and 'Dossier médical' not in secret and '(fiche confidentielle)' in secret
    assert 'annotation de Durand' in show.describe_tag(b, cfg, 'à revoir')


def test_commands(world, cfg, server, monkeypatch, capsys):
    from zot_clean import api
    from zot_clean.cli import main
    m, k, x = world
    m.read()
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n[methode]\nfonds = "Fonds"\ncouleurs = []\n',
        encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['tags', 'inventory', *folder]) == 0
    output = capsys.readouterr().out
    assert 'Règle à approuver' in output and 'tag(s) à juger' in output
    assert list((cfg.workspace / 'rapports').glob('tags-inventaire-*.md'))
    assert main(['tags', 'plan', *folder]) == 0
    assert 'Rien à faire' in capsys.readouterr().out  # no rule accepted
    assert main(['tags', 'reject', 'Inconnu', *folder]) == 1
    assert '« Inconnu » ne figure pas' in capsys.readouterr().err
    assert main(['tags', 'accept', 'truc divers', '--automatic-rule', *folder]) == 0
    assert 'tags.toml : 2 règles acceptées. ' in capsys.readouterr().out
    assert main(['tags', 'add', 'rouge', '--action', 'delete', '--user', *folder]) == 0
    assert main(['tags', 'plan', *folder]) == 0
    assert 'Plan :' in capsys.readouterr().out
    assert main(['show', '--tag', 'mémoire', *folder]) == 0
    assert 'Fear and faces' in capsys.readouterr().out
    assert main(['show', *folder]) == 1


def test_decisions_by_command(world, cfg):
    """D177: rules are decided by command, by tag name, and only those still waiting change. The rewrite keeps
    the header, the summary of the global rule and the titles of each entry."""
    m, k, x = world
    b = m.read()
    _, tracking = t.inventory(b, cfg)
    t.write(cfg, tracking, b)
    s = t.load(cfg)
    assert s.automatic_summary == tracking.automatic_summary and s.imported_summary == tracking.imported_summary
    with pytest.raises(SystemExit, match='« inconnu » ne figure pas'):
        t.decide(s, cfg, t.ACCEPT, ['inconnu'])
    with pytest.raises(SystemExit, match='--variants'):  # a group is not a [[tag]] entry
        t.decide(s, cfg, t.ACCEPT, ['Machine-Learning'])
    with pytest.raises(SystemExit, match='sans cible'):
        t.decide(s, cfg, t.ACCEPT, ['truc divers'], action='concept')
    s = t.load(cfg)
    obvious = {e.name for e in s.tags if e.grade == t.OBVIOUS and e.action}
    assert 'truc divers' in obvious
    n = t.decide(s, cfg, t.ACCEPT, ['Attention'], obvious=True, except_=['truc divers', 'machine learning'],
                  rules=['automatiques'], target='#attention visuelle')
    assert n == 1 + 1 + len(obvious) - 1 + sum(g.grade == t.OBVIOUS for g in s.variants) - 1
    assert t.decide(s, cfg, t.REJECT, ['truc divers'], ['machine learning'], rules=['importes']) == 3
    assert t.decide(s, cfg, t.ACCEPT, ['mémoire'], action='garder') == 1
    t.write(cfg, s, b)
    text = (cfg.tracking / t.FILE).read_text(encoding='utf-8')
    assert text.startswith(t.header()) and f'[automatiques]\n# {tracking.automatic_summary}\n' in text
    assert '# Durand 2020, « Learning to see »' in text
    reloaded = t.load(cfg)
    e = entries(reloaded)
    assert (reloaded.automatic, reloaded.imported) == (t.ACCEPT, t.REJECT)
    assert (e['Attention'].decision, e['Attention'].target, e['Attention'].source) == (
        t.ACCEPT, '#attention visuelle', t.AGENT)
    assert (e['mémoire'].action, e['mémoire'].target, e['mémoire'].source) == (t.KEEP, '', t.AGENT)
    assert e['truc divers'].decision == t.REJECT and e['to read'].decision == ''
    assert next(g for g in reloaded.variants if 'machine learning' in g.names).decision == t.REJECT
    # What is decided no longer changes by command.
    with pytest.raises(SystemExit, match='rien à juger sous ce nom'):
        t.decide(reloaded, cfg, t.ACCEPT, ['truc divers'])
    with pytest.raises(SystemExit, match='déjà décidée'):
        t.decide(reloaded, cfg, t.REJECT, rules=['automatiques'])
    # New entry for a tag without one, here a protected one, at the user's request.
    assert t.add(reloaded, cfg, b, ['rouge'], 'supprimer', user=True) == 1
    with pytest.raises(SystemExit, match='déjà une entrée'):
        t.add(reloaded, cfg, b, ['Attention'], 'garder')
    with pytest.raises(SystemExit, match='Aucun tag « absent »'):
        t.add(reloaded, cfg, b, ['absent'], 'garder')
    t.write(cfg, reloaded, b)
    red = entries(t.load(cfg))['rouge']
    assert (red.action, red.source, red.decision, red.count) == (t.DELETE, t.USER, t.ACCEPT, 1)


NFC, NFD, MIXED = 'été', 'été', 'été'  # same displayed name, three Unicode forms


def test_decisions_by_command_in_several_unicode_forms(cfg):
    """Two entries whose names differ only by Unicode form display the same. The exact name designates its own entry
    alone. Another form is refused when it designates several, with their code points."""
    s = t.Tracking(tags=[t.Entry(NFC, action=t.KEEP), t.Entry(NFD, action=t.KEEP), t.Entry('ok', action=t.KEEP)],
                variants=[t.Variants([NFC, 'ete'], 'été (a)'), t.Variants([NFD, 'Ete'], 'été (b)'),
                           t.Variants(['hiver', 'Hiver'], 'hiver')])
    assert t.decide(s, cfg, t.ACCEPT, [NFC]) == 1
    assert [e.decision for e in s.tags] == [t.ACCEPT, '', '']
    with pytest.raises(SystemExit, match=r"forme Unicode.*'\\xe9t\\xe9'.*'e\\u0301te\\u0301'"):
        t.decide(s, cfg, t.ACCEPT, ['ok', MIXED])
    assert s.tags[2].decision == ''  # nothing changed before the refusal
    assert t.decide(s, cfg, t.REJECT, [NFD]) == 1 and s.tags[1].decision == t.REJECT
    # Same logic for groups, designated by one of their names.
    with pytest.raises(SystemExit, match='forme Unicode'):
        t.decide(s, cfg, t.ACCEPT, variants=[MIXED])
    assert t.decide(s, cfg, t.ACCEPT, variants=[NFD]) == 1
    assert [g.decision for g in s.variants] == ['', t.ACCEPT, '']
    # A group that itself carries several forms of the name stays designated by each, without refusal.
    s = t.Tracking(variants=[t.Variants([NFC, NFD], 'été')])
    assert t.decide(s, cfg, t.ACCEPT, variants=[MIXED]) == 1 and s.variants[0].decision == t.ACCEPT


def test_add_saves_the_real_tag_name(zotero, tmp_path):
    """`zc tags ajouter` keeps the name as it is carried in the library, so that the rule applies to it, and
    refuses a name that designates several tags differing only by Unicode form."""
    cfg = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    cfg.workspace.mkdir()
    a = zotero.item('A', tags=(NFD, 'café', 'reste'))  # « été » decomposed, « café » composed
    b = reader.read(zotero.save())
    s = t.Tracking()
    assert t.add(s, cfg, b, [NFC, 'cafe\u0301'], 'supprimer') == 2
    assert [e.name for e in s.tags] == ['café', NFD] and [e.count for e in s.tags] == [1, 1]
    with pytest.raises(SystemExit, match='déjà une entrée'):
        t.add(s, cfg, b, [MIXED], 'garder')
    t.write(cfg, s, b)
    reloaded = t.load(cfg)
    assert [e.name for e in reloaded.tags] == ['café', NFD]
    R = t.rules(reloaded, cfg, b)
    assert t.targeted_tags(b.all_items[a], R) == [{'tag': 'reste'}]
    # Two real tags under two forms, and a name typed under a third, which designates neither exactly.
    zotero.item('B', tags=(NFC,))
    b = reader.read(zotero.save())
    with pytest.raises(SystemExit, match=r"plusieurs tags.*'\\xe9t\\xe9'.*'e\\u0301te\\u0301'"):
        t.add(t.Tracking(), cfg, b, [MIXED], 'supprimer')
    s = t.Tracking()
    assert t.add(s, cfg, b, [NFC], 'supprimer') == 1 and [e.name for e in s.tags] == [NFC]


def test_technical_mark_never_proposed_as_concept(zotero, tmp_path):
    from zot_clean import tags as tg
    from zot_clean.config import Config
    cfg = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    for i in range(6):
        zotero.item(f'Fiche {i}', tags=(('/unread', 1),))
    from zot_clean import reader
    b = reader.read(zotero.save())
    a = tg._Analysis(b, cfg)
    e = a.propose(tg.Entry('/unread'))
    assert e.action == tg.DELETE and e.grade == tg.OBVIOUS and 'marque technique' in e.note


def test_tag_doubling_theme_stays_on_items_not_yet_filed(world, cfg):
    # D154: « perception visuelle » duplicates Psychologie/Perception. It leaves f1, already filed, but stays on f8,
    # which is not yet in the theme, even when the decision to file it has already been taken elsewhere.
    m, k, x = world
    b = m.read()
    accept_all(cfg, b)
    R = t.rules(t.load(cfg), cfg, b)
    by_key = b.by_key()
    assert 'perception visuelle' not in {d['tag'] for d in t.targeted_tags(by_key[x['f1']], R)}
    assert 'perception visuelle' in {d['tag'] for d in t.targeted_tags(by_key[x['f8']], R)}
    assert any('perception visuelle' in p and 'rangement' in p for p in R.problems)


def test_variants_merged_into_deletion_of_their_target(world, cfg):
    m, k, x = world
    b = m.read()
    accept_all(cfg, b, keep=())
    text = (cfg.tracking / t.FILE).read_text(encoding='utf-8')
    assert 'variantes = [' in text
    R = t.rules(t.load(cfg), cfg, b)
    # Once accepted, the entry deletes the tag and its variants on the items already in the theme.
    by_key = b.by_key()
    assert t.targeted_tags(by_key[x['f4']], R) == [{'tag': '#attention'}]
    assert t.targeted_tags(by_key[x['f5']], R) == [{'tag': '#attention'}, {'tag': '#machine learning'}]
    # A rerun does not recreate the variant group.
    _, tracking = t.inventory(m.read(), cfg)
    assert 'émotion' not in {g.target for g in tracking.variants}
    assert set(entries(tracking)['émotion'].variants) == {'Emotion', 'emotions'}


def test_case_of_targets_and_concept_name(zotero, tmp_path):
    cfg = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    for title, tag in (('A', '#Mémoire'), ('B', '#memoire'), ('C', '#Apprentissage'), ('D', '#apprentissage'),
                       ('E', '#Kant'), ('F', '#Kants')):
        zotero.item(title, tags=(tag,))
    b = reader.read(zotero.save())
    groups, _ = t._Analysis(b, cfg).groups()
    targets = {g.target for g in groups}
    # Capitals are kept only if all the names carry them (proper noun).
    assert {'#mémoire', '#apprentissage'} < targets and len(targets) == 3
    assert all(c.startswith('#K') for c in targets - {'#mémoire', '#apprentissage'})
    assert t.concept_name('Embodied_Cognition', cfg) == '#embodied cognition'
    assert t.concept_name("TDAH chez l'Adulte", cfg) == "#TDAH chez l'adulte"


def test_colors_of_method_tags(world, cfg, server):
    """D175: the method's tags get their color and the first ranks (keys 1, 2, 3…), even when still unused. A
    method tag that already has a color keeps it, the other colored tags follow. First group of the plan, hence in
    the trial, and undoable."""
    m, k, x = world
    server.set_setting('tagColors', [{'name': 'perso', 'color': '#000000'}, {'name': '3 lu', 'color': '#123456'}])
    b = m.read()
    plan, report = t.make_plan(b, cfg, server.client())
    g = plan.groups[0]
    assert g.id == 'tagColors' and g.operations[0].kind == 'settings'
    wanted = [('1 à lire', '#FF6666'), ('2 en cours', '#FF8C19'), ('3 lu', '#123456'), ('★ essentiel', '#FFD400'),
               ('papier', '#A28AE5'), ('perso', '#000000')]
    assert [(c['name'], c['color']) for c in g.operations[0].after['value']] == wanted
    assert '## Couleurs' in report and '- 6. perso (#000000), gardait le rang 1, touche changée' in report
    assert '- 3. 3 lu' in report  # rank changed (2 → 3)
    assert not any(gr.id == 'tagColors' for gr in plan.groups[1:])

    path = write_plan(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert [(c['name'], c['color']) for c in server.settings['tagColors']['value']] == wanted
    # Nothing to redo afterwards.
    assert t._colors(cfg, server.settings['tagColors']['value']) is None

    journals = undo.targeted_journals(path, cfg)
    p_undo, _ = undo.make_plan(journals, server.client(), set())
    c_undo = plans.write(p_undo, cfg.plans, '# annulation')
    apply_plan(p_undo, c_undo, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    apply_plan(p_undo, c_undo, server.client(), cfg, ALL)
    assert server.settings['tagColors']['value'] == [{'name': 'perso', 'color': '#000000'},
                                                      {'name': '3 lu', 'color': '#123456'}]


def test_colors_created_then_removed_by_undo(world, cfg, server):
    m, k, x = world
    b = m.read()
    plan, _ = t.make_plan(b, cfg, server.client())
    assert plan.groups[0].operations[0].before == {'value': None}
    path = write_plan(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert len(server.settings['tagColors']['value']) == 5
    p_undo, _ = undo.make_plan(undo.targeted_journals(path, cfg), server.client(), set())
    c_undo = plans.write(p_undo, cfg.plans, '# annulation')
    apply_plan(p_undo, c_undo, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    apply_plan(p_undo, c_undo, server.client(), cfg, ALL)
    assert 'tagColors' not in server.settings


def test_inventory_plan_and_header_in_english(world, cfg, server):
    from zot_clean.lang import language
    m, k, x = world
    b = m.read()
    with language('en'):
        report, tracking = t.inventory(b, cfg)
        header = t.header()
        accept_all(cfg, b)
        plan, plan_report = t.make_plan(b, cfg, server.client())
    assert report.startswith('# Tag inventory, ') and '## Global rule on automatic tags' in report
    assert '## Variants' in report and '## Protected tags' in report and 'Current decision: "to be taken"' in report
    assert 'automatic name' in tracking.automatic_summary and 'The rule removes' in tracking.automatic_summary
    assert header.startswith('# Tag rules, prepared by `zc tags inventory`') and '`zc tags accept`' in header
    assert plan_report.startswith('# Tag plan of ') and '## By kind of change' in plan_report
    assert '## Trial' in plan_report and '`zc apply <plan> --trial`' in plan_report
    assert '"Vision" cites "Vision"' in plan_report and plan.description.startswith('Tags, ')
    assert t.header().startswith('# Règles des tags')  # French outside the block


def test_one_filed_item_does_not_make_a_theme(world, cfg):
    """D241, pilot bench: a tag carried by three items of which one only is filed is not « concentrated in the
    theme », nor are the two others proposed for filing there."""
    m, k, x = world
    lonely = [m.item('Grève générale', k['Arts'], tags=('exemplaire',)), m.item('Sans place 1', tags=('exemplaire',)),
              m.item('Sans place 2', tags=('exemplaire',))]
    _, tracking = t.inventory(m.read(), cfg)
    e = entries(tracking)['exemplaire']
    assert (e.action, e.theme) != (t.DELETE, 'Arts')
    assert not any(a.key in lonely[1:] for a in tracking.pending)


def test_stored_kinds_and_grades_shown_in_english():
    """Natures of the plan and grades of the variants stay the stored French words (D209), shown translated."""
    from zot_clean.lang import language
    assert t.nature_shown('automatique, importé') == 'automatique, importé'
    assert t.grade_shown(t.OBVIOUS) == 'évident'
    with language('en'):
        assert t.nature_shown('automatique, importé, état') == 'automatic, imported, status'
        assert (t.grade_shown(t.OBVIOUS), t.grade_shown(t.DOUBTFUL)) == ('obvious', 'doubtful')


def test_inventory_report_in_english_shows_types_and_fates_in_english(world, cfg):
    """Verification pilot: an English report read « domination (manuel, 3 item(s) …) : concept » and « supprimer »."""
    from zot_clean.lang import language
    m, k, x = world
    with language('en'):
        report, tracking = t.inventory(m.read(), cfg)
    assert '(manual, ' in report and '(manuel' not in report and '(automatique' not in report
    assert ': delete' in report and ': supprimer' not in report and ' : ' not in report.split('\n## ')[1]
    assert {e.action for e in tracking.tags} <= {t.DELETE, t.KEEP, t.CONCEPT, t.STATUS, t.MERGE, ''}  # stored words
