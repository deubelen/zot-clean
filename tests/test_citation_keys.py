"""Citation keys, step 7 (D144, D146): pure functions, then plan on the synthetic library and the fake
server (apply, conflict, undo, rerun, tracking, masking)."""

import itertools
import tomllib

import pytest

from fake_server import FakeServer
from test_apply import write as write_plan, fake_backup
from zot_clean import undo, bbt, citation_keys, reader, plans
from zot_clean.apply import TRIAL, ALL, apply_plan
from zot_clean.config import Config
from zot_clean.api import Refusal
from zot_clean.reader import Library, Item

_ids = itertools.count(1)


def item(citation_key: str = '', date_added: str = '2026-01-01 00:00:00', key: str | None = None, **fields) -> Item:
    n = next(_ids)
    if citation_key:
        fields['citationKey'] = citation_key
    return Item(n, key or f'FICHE{n:03d}', 'journalArticle', date_added, True, fields)


def biblio(*items: Item) -> Library:
    note = Item(next(_ids), 'NOTE0001', 'note', '2020-01-01', True, {'citationKey': 'durand2020'})
    return Library(129, {e.id: e for e in (*items, note)}, {}, {}, {}, [])


def test_case_insensitive_doubles():
    b = biblio(item('Durand2020'), item('durand2020'), item('martin2019'), item())
    assert list(citation_keys.doubles(b)) == ['durand2020']
    assert citation_keys.doubles(b, casing=True) == {}


def test_doubles_sorted_by_age():
    latest = item('k', '2025-05-01 10:00:00', 'RECENTE1')
    former = item('k', '2019-03-02 08:00:00', 'ANCIENNE')
    assert [e.key for e in citation_keys.doubles(biblio(latest, former))['k']] == ['ANCIENNE', 'RECENTE1']


def test_letters_like_bbt():
    assert [citation_keys.letters(n) for n in (1, 2, 26, 27, 28, 52, 53)] == ['a', 'b', 'z', 'aa', 'ab', 'az', 'ba']


def test_free_suffix():
    assert citation_keys.free_suffix('durand2020', {'durand2020'}) == 'a'
    assert citation_keys.free_suffix('durand2020', {'durand2020', 'durand2020a'}) == 'b'
    assert citation_keys.free_suffix('durand2020', {'Durand2020A'}) == 'b'
    assert citation_keys.free_suffix('durand2020', {'Durand2020A'}, casing=True) == 'a'
    taken = {'k'} | {f'k{citation_keys.letters(n)}' for n in range(1, 27)}
    assert citation_keys.free_suffix('k', taken) == 'aa'


def test_oldest_keeps_key_and_suffixes_skip_taken_keys():
    a = item('durand2020', '2020-01-01', 'AAAAAAAA')
    b_ = item('Durand2020', '2021-01-01', 'BBBBBBBB')
    c = item('durand2020', '2022-01-01', 'CCCCCCCC')
    holder = item('durand2020a', '2023-01-01')
    d = citation_keys.disambiguate(biblio(c, holder, b_, a))
    assert not d.deferred and len(d.doubles) == 1
    double = d.doubles[0]
    assert double.key == 'durand2020' and double.keeper is a
    assert [(ch.item.key, ch.before, ch.after) for ch in double.changes] == [
        ('BBBBBBBB', 'Durand2020', 'durand2020b'), ('CCCCCCCC', 'durand2020', 'durand2020c')]


def test_case_distinguished_by_bbt():
    b = biblio(item('Durand2020', '2020-01-01'), item('durand2020', '2021-01-01'))
    assert citation_keys.disambiguate(b, casing=True).doubles == []
    assert len(citation_keys.disambiguate(b).doubles) == 1


def test_imposed_item_keeps_key():
    a = item('k2020', '2020-01-01', 'AAAAAAAA')
    b_ = item('k2020', '2021-01-01', 'BBBBBBBB')
    d = citation_keys.disambiguate(biblio(a, b_), keepers={'K2020': 'BBBBBBBB'})
    assert d.doubles[0].keeper is b_ and d.doubles[0].changes[0].item is a
    # A required item missing from the group is ignored.
    d = citation_keys.disambiguate(biblio(a, b_), keepers={'k2020': 'ZZZZZZZZ'})
    assert d.doubles[0].keeper is a


def test_unjudged_duplicates_sent_back_to_step_2():
    a, b_, c = (item('k2020', f'202{i}-01-01', f'{x * 8}') for i, x in enumerate('ABC'))
    other_a, other_b = item('m2020', key='MMMMMMM1'), item('m2020', key='MMMMMMM2')
    d = citation_keys.disambiguate(biblio(a, b_, c, other_a, other_b),
                        unjudged_duplicates=[['AAAAAAAA', 'CCCCCCCC'], ['MMMMMMM1', 'XXXXXXXX']])
    assert list(d.deferred) == ['k2020'] and [e.key for e in d.deferred['k2020']] == ['AAAAAAAA', 'BBBBBBBB', 'CCCCCCCC']
    # Only one item of the duplicate group in the double: nothing to merge between them, the double is told apart.
    assert [x.key for x in d.doubles] == ['m2020']


def test_unique_suffixes_between_groups():
    """Two doubles whose suffixes could collide: each assigned key is reserved."""
    b = biblio(item('k', '2020-01-01'), item('k', '2021-01-01'), item('k', '2022-01-01'),
               item('ka', '2020-01-01'), item('KA', '2021-01-01'))
    new_ones = [ch.after.lower() for d in citation_keys.disambiguate(b).doubles for ch in d.changes]
    all_keys = new_ones + ['k', 'ka']
    assert len(set(all_keys)) == len(all_keys)


def test_leftovers_in_extra():
    a = item('', extra='tex.ids: vieux\nCitation Key: durand2020\noriginal-date: 1938')
    b_ = item('durand2020', extra='citation key:  martin2019  ')
    c = item('x', extra='Pas de clé ici. Citation Key: dans une phrase')
    leftovers = citation_keys.extra_leftovers(biblio(a, b_, c))
    assert [(e.key, k) for e, k in leftovers] == [(a.key, 'durand2020'), (b_.key, 'martin2019')]


def test_keys_extra_and_without_lines():
    text = 'tex.ids: vieux\r\ncitation key:  martin2019 \r\nCitation Key: autre\nnote libre'
    assert citation_keys.extra_keys(text) == ['martin2019', 'autre']
    assert citation_keys.without_lines(text) == 'tex.ids: vieux\r\nnote libre'


# --- Step 7 plan (D146) ---------------------------------------------------------

BBT = bbt.State(installed=True, active=True, version='9.1.0', source=bbt.PROFILE)


class World:
    """Items created both in the synthetic database and on the fake server, with the same key."""

    def __init__(self, zotero, server):
        self.zotero, self.server = zotero, server
        server._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def item(self, title, citation_key='', extra='', date_added='2026-01-01', tags=(), DOI=''):
        key = self.server._key()
        self.ids[key] = self.zotero.item(title, key=key, date_added=f'{date_added} 00:00:00', tags=tags, DOI=DOI,
                                          citationKey=citation_key, extra=extra)
        self.server.add(key=key, title=title, citationKey=citation_key, extra=extra, DOI=DOI,
                             dateAdded=f'{date_added}T00:00:00Z', tags=[{'tag': t} for t in tags])
        return key

    def sync(self):
        """Keys and Extra of the server carried over to the local database, as after a Zotero sync."""
        for key, iid in self.ids.items():
            d = self.server.all_items[key]
            self.zotero.db.execute("delete from itemData where itemID = ? and fieldID in (select fieldID from fields "
                                   "where fieldName in ('citationKey', 'extra'))", (iid,))
            self.zotero._fields(iid, {'citationKey': d.get('citationKey', ''), 'extra': d.get('extra', '')})

    def read(self):
        self.zotero.sync(self.server.version)
        return reader.read(self.zotero.save())


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


@pytest.fixture
def world(zotero, server):
    m = World(zotero, server)
    x = {
        # A key carried three times, case aside, and the first suffix already taken.
        'a': m.item('Article A', 'durand2020', date_added='2020-01-01'),
        'b': m.item('Article B', 'Durand2020', date_added='2021-01-01'),
        'c': m.item('Article C', 'durand2020', date_added='2022-01-01'),
        'd': m.item('Article D', 'durand2020a', date_added='2023-01-01'),
        # Extra lines: toward the empty native field, identical, different.
        'e': m.item('Article E', extra='tex.ids: vieux\nCitation Key: martin2019\noriginal-date: 1938'),
        'f': m.item('Article F', 'lee2018', extra='Citation Key: lee2018'),
        'g': m.item('Article G', 'kim2017', extra='Citation Key: park2017'),
        # A unique key, and a key leaving Extra to join it: the more recent item receives the suffix.
        'h': m.item('Article H', 'zhang2016', date_added='2016-01-01'),
        'k': m.item('Article K', extra='Citation Key: zhang2016', date_added='2025-01-01'),
        # Key shared with a confidential item: the whole group is masked.
        's1': m.item('Mon dossier médical', 'secret2020', date_added='2020-01-01', tags=('_privé',)),
        's2': m.item('Autre article', 'Secret2020', date_added='2021-01-01'),
        # Unjudged duplicates that share their key: sent back to step 2.
        'u1': m.item('Article U', 'dup2020', DOI='10.1/dup', date_added='2020-01-01'),
        'u2': m.item('Article U bis', 'dup2020', DOI='10.1/dup', date_added='2021-01-01'),
    }
    return m, x


def plan_ops(plan) -> dict:
    return {op.key: op for g in plan.groups for op in g.operations}


def test_plan_and_tracking(world, cfg, server):
    m, x = world
    cfg.writing.trial = 2
    plan, report = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    ops = plan_ops(plan)
    assert ops[x['b']].after == {'citationKey': 'durand2020b'} and ops[x['c']].after == {'citationKey': 'durand2020c'}
    assert ops[x['b']].before == {'citationKey': 'Durand2020'}
    assert ops[x['e']].after == {'citationKey': 'martin2019', 'extra': 'tex.ids: vieux\noriginal-date: 1938'}
    assert ops[x['f']].after == {'extra': ''} and ops[x['f']].before == {'extra': 'Citation Key: lee2018'}
    # The key leaving Extra joins a double: suffix and Extra in a single operation, in the double's group.
    assert ops[x['k']].after == {'citationKey': 'zhang2016a', 'extra': ''}
    assert ops[x['s2']].after == {'citationKey': 'secret2020a'}
    # Nothing for a unique key, the item that keeps the key, a different line (« à juger ») or unjudged duplicates.
    for k in ('a', 'd', 'g', 'h', 's1', 'u1', 'u2'):
        assert x[k] not in ops
    assert sorted(g.id for g in plan.groups) == sorted(
        [f"double-{x['a']}", f"double-{x['h']}", f"double-{x['s1']}", x['e'], x['f']])
    # The first two groups (the trial) cover the three kinds of change.
    kinds = {s for g in plan.groups[:2] for op in g.operations for s in op.nature.split(', ')}
    assert kinds == {citation_keys.SUFFIX, citation_keys.TO_NATIVE, citation_keys.REMOVED}

    assert '## Essai' in report and "## Renvoyés à l'étape 2" in report and 'dup2020' in report
    assert 'park2017' in report and '## À juger' in report
    tracking = (cfg.tracking / citation_keys.FILE).read_text(encoding='utf-8')
    raw = tomllib.loads(tracking)
    assert {tuple(d['fiches']) for d in raw['double']} == {
        (x['a'], x['b'], x['c']), (x['h'], x['k']), (x['s1'], x['s2']), (x['u1'], x['u2'])}
    assert [e['fiche'] for e in raw['extra']] == [x['g']]
    assert '→ durand2020c' in tracking and 'renvoyé' in tracking
    assert 'Article A, ajoutée le 2020-01-01, garde la clé' in tracking and 'Article A garde la clé' in report
    # Confidential item (D126): neither its title nor the citation key in the report and the tracking file, group
    # title masked in the plan, which keeps the values needed for writing.
    for text in (report, tracking):
        assert 'médical' not in text and 'ecret2020' not in text.lower()
    assert next(g.title for g in plan.groups if g.id == f"double-{x['s1']}") == '(fiche confidentielle)'
    assert f"{x['s2']} reçoit un suffixe" in report
    # The suffixed key reuses the title of another item: the report suggests regenerating it in Better BibTeX.
    assert "→ durand2020b (clé tirée du titre d'une autre fiche)" in report and 'Better BibTeX › Refresh' in report


def test_trial_apply_conflict_undo_rerun(world, cfg, server):
    m, x = world
    cfg.writing.trial = 2
    plan, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    path = write_plan(plan, cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert len(outcome.done) == 2 and outcome.remaining == 3
    with pytest.raises(Refusal, match='sauvegarde'):
        apply_plan(plan, path, server.client(), cfg, ALL)
    fake_backup(cfg)
    # A key changed in Zotero in the meantime puts its group in conflict, this item stays intact.
    group = f"double-{x['a']}"
    assert group not in outcome.done
    server.modify(x['c'], citationKey='durandArticle2022')
    outcome = apply_plan(plan, path, server.client(), cfg, ALL)
    el = server.all_items
    assert list(outcome.conflicts) == [group]
    assert el[x['c']]['citationKey'] == 'durandArticle2022'
    assert el[x['e']]['citationKey'] == 'martin2019' and el[x['e']]['extra'] == 'tex.ids: vieux\noriginal-date: 1938'
    assert el[x['f']]['extra'] == '' and el[x['f']]['citationKey'] == 'lee2018'
    assert el[x['k']]['citationKey'] == 'zhang2016a' and el[x['h']]['citationKey'] == 'zhang2016'
    assert el[x['s2']]['citationKey'] == 'secret2020a' and el[x['g']]['extra'] == 'Citation Key: park2017'
    # With the key put back in Zotero, rerunning the same plan finishes the group.
    server.modify(x['c'], citationKey='durand2020')
    assert not apply_plan(plan, path, server.client(), cfg, ALL).conflicts
    assert el[x['b']]['citationKey'] == 'durand2020b' and el[x['c']]['citationKey'] == 'durand2020c'

    # Rerun after sync: nothing left to do, the case to judge stays reported (D119).
    m.sync()
    rest, report = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    assert rest.groups == [] and 'park2017' in report

    # Undo: the earlier keys and Extra come back.
    for journal in undo.targeted_journals(path, cfg):
        p_undo, _ = undo.make_plan([journal], server.client(), set())
        c_undo = plans.write(p_undo, cfg.plans, '# annulation')
        apply_plan(p_undo, c_undo, server.client(), cfg, TRIAL)
        apply_plan(p_undo, c_undo, server.client(), cfg, ALL)
    assert el[x['e']]['citationKey'] == '' and el[x['e']]['extra'].startswith('tex.ids: vieux\nCitation Key: martin')
    assert el[x['k']]['citationKey'] == '' and el[x['k']]['extra'] == 'Citation Key: zhang2016'
    assert el[x['b']]['citationKey'] == 'Durand2020' and el[x['f']]['extra'] == 'Citation Key: lee2018'


def test_rerun_after_trial_plans_only_difference(world, cfg, server):
    m, x = world
    cfg.writing.trial = 2
    plan, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    apply_plan(plan, write_plan(plan, cfg), server.client(), cfg, TRIAL)
    m.sync()
    rest, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    assert {g.id for g in rest.groups} == {g.id for g in plan.groups[2:]}


def test_tracking_decisions(world, cfg, server):
    m, x = world
    citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    path = cfg.tracking / citation_keys.FILE
    text = path.read_text(encoding='utf-8')
    # Item C keeps the key, the double of zhang2016 is set aside, the Extra key of G replaces the native key.
    replacements = {
        f'fiches = ["{x["a"]}", "{x["b"]}", "{x["c"]}"]\ngarde = ""':
            f'fiches = ["{x["a"]}", "{x["b"]}", "{x["c"]}"]\ngarde = "{x["c"]}"',
        f'fiches = ["{x["h"]}", "{x["k"]}"]\ngarde = ""\ndecision = ""':
            f'fiches = ["{x["h"]}", "{x["k"]}"]\ngarde = ""\ndecision = "écarter"',
        f'fiche = "{x["g"]}"\ndecision = ""': f'fiche = "{x["g"]}"\ndecision = "extra"'}
    for before, after in replacements.items():
        assert before in text
        text = text.replace(before, after)
    path.write_text(text, encoding='utf-8')
    plan, report = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    ops = plan_ops(plan)
    assert x['c'] not in ops and ops[x['a']].after == {'citationKey': 'durand2020b'}
    assert ops[x['b']].after == {'citationKey': 'durand2020c'}
    # The set-aside double stays as it is, but the Extra line of K still moves into the native field.
    assert x['h'] not in ops and ops[x['k']].after == {'citationKey': 'zhang2016', 'extra': ''}
    assert ops[x['g']].after == {'citationKey': 'park2017', 'extra': ''} and citation_keys.REPLACED in ops[x['g']].nature
    assert '1 cas écarté' in report
    # Decisions are kept when the tracking file is rewritten, G's too, until its case is settled in
    # Zotero (D177).
    raw = tomllib.loads(path.read_text(encoding='utf-8'))
    assert [d['decision'] for d in raw['double'] if x['h'] in d['fiches']] == ['écarter']
    assert [d['garde'] for d in raw['double'] if x['a'] in d['fiches']] == [x['c']]
    assert [(d['fiche'], d['decision']) for d in raw['extra']] == [(x['g'], 'extra')]
    plan, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    assert plan_ops(plan)[x['g']].after == {'citationKey': 'park2017', 'extra': ''}

    # « natif » keeps the native key and removes the line.
    path.write_text(citation_keys.header() + f'\n[[extra]]\nfiche = "{x["g"]}"\ndecision = "natif"\n', encoding='utf-8')
    plan, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    assert plan_ops(plan)[x['g']].after == {'extra': ''}
    # An unknown decision is refused.
    path.write_text(citation_keys.header() + f'\n[[extra]]\nfiche = "{x["g"]}"\ndecision = "peut-être"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='décision inconnue'):
        citation_keys.make_plan(m.read(), cfg, server.client(), BBT)


def test_decisions_by_command(world, cfg, server, monkeypatch, capsys):
    """D177: the same decisions as above, by command, on the only cases that are waiting."""
    from zot_clean import api
    from zot_clean.cli import main
    m, x = world
    citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    s = citation_keys.load(cfg)
    with pytest.raises(SystemExit, match='ne figure dans aucun cas'):
        citation_keys.decide(s, {'ZZZZZZZZ': 'garder'})
    with pytest.raises(SystemExit, match="pas de ligne d'Extra à juger"):
        citation_keys.decide(s, {x['a']: 'natif'})
    with pytest.raises(SystemExit, match='décision inconnue « peut-être »'):
        citation_keys.decide(s, {x['g']: 'peut-être'})
    with pytest.raises(SystemExit, match='Une seule décision par clé en double'):
        citation_keys.decide(s, {x['a']: 'garder', x['c']: 'garder'})

    cfg.workspace.mkdir(exist_ok=True)
    (cfg.workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n',
                                                     encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    monkeypatch.setattr(bbt, 'detect', lambda folder: BBT)
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['citation-keys', 'decide', f'{x["c"].lower()}=keep', f'{x["h"]}=skip', f'{x["g"]}=extra',
                 '--reason', 'cité ainsi', *folder]) == 0
    assert 'cles.toml : 3 cas décidés. ' in capsys.readouterr().out
    assert main(['citation-keys', 'decide', f'{x["h"]}=skip', *folder]) == 1
    assert 'déjà prise' in capsys.readouterr().err
    assert main(['citation-keys', 'decide', x['g'], *folder]) == 1
    assert 'FICHE=décision' in capsys.readouterr().err
    text = (cfg.tracking / citation_keys.FILE).read_text(encoding='utf-8')
    assert text.startswith(citation_keys.header()) and 'Article A, ajoutée le 2020-01-01' in text
    raw = tomllib.loads(text)
    assert [(d['decision'], d['raison']) for d in raw['double'] if x['h'] in d['fiches']] == [('écarter', 'cité ainsi')]
    assert [d['garde'] for d in raw['double'] if x['a'] in d['fiches']] == [x['c']]
    assert [(d['fiche'], d['decision']) for d in raw['extra']] == [(x['g'], 'extra')]
    plan, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    ops = plan_ops(plan)
    assert x['c'] not in ops and x['h'] not in ops
    assert ops[x['g']].after == {'citationKey': 'park2017', 'extra': ''}


def test_without_bbt_only_doubles(world, cfg, server):
    m, x = world
    plan, report = citation_keys.make_plan(m.read(), cfg, server.client(), bbt.State())
    ops = plan_ops(plan)
    assert x['b'] in ops and x['e'] not in ops and x['f'] not in ops and x['k'] not in ops
    assert "Better BibTeX n'est pas actif" in report and '4 fiches dont Extra garde une ligne « Citation Key: » attendent Better BibTeX' in report


def test_refusals_and_warnings(world, cfg, server, zotero):
    m, x = world
    b = m.read()
    with pytest.raises(Refusal, match='propre base'):
        citation_keys.make_plan(b, cfg, server.client(), bbt.State(installed=True, active=True, version='7.0.5'))
    cfg.method.use_citation_keys = False
    with pytest.raises(Refusal, match='cles_citation = false'):
        citation_keys.make_plan(b, cfg, server.client(), BBT)
    cfg.method.use_citation_keys = True
    zotero.db.execute("delete from fields where fieldName = 'citationKey'")
    with pytest.raises(Refusal, match='Zotero 7'):
        citation_keys.make_plan(reader.read(zotero.save()), cfg, server.client(), BBT)
    server.modify(x['a'], title='Changé ailleurs')
    with pytest.raises(Refusal, match='pas encore reçu'):
        citation_keys.make_plan(b, cfg, server.client(), BBT)


def test_bbt_settings_reported(zotero, server, cfg):
    m = World(zotero, server)
    m.item('Article A', 'durand2020')
    m.item('Sans clé')
    state = bbt.State(installed=True, active=True, version='9.1.0', source=bbt.PROFILE, regenerates=True, fill_after=0)
    _, report = citation_keys.make_plan(m.read(), cfg, server.client(), state)
    assert 'Regenerate citation key' in report and 'Automatically fill citation key after' in report
    assert 'clic droit, Better BibTeX › Fill' in report


def test_item_modified_since_local_copy(world, cfg, server):
    m, x = world
    b = m.read()
    server.all_items[x['e']]['extra'] = 'Citation Key: autre2019'  # without a new library version
    plan, report = citation_keys.make_plan(b, cfg, server.client(), BBT)
    assert x['e'] not in plan_ops(plan)
    assert f"La fiche {x['e']} a changé depuis la copie locale" in report


def test_tracking_not_written_without_cases(zotero, server, cfg):
    m = World(zotero, server)
    m.item('Article F', 'lee2018', extra='Citation Key: lee2018')
    plan, _ = citation_keys.make_plan(m.read(), cfg, server.client(), BBT)
    assert len(plan.groups) == 1 and not (cfg.tracking / citation_keys.FILE).exists()


def test_points_to_tracking_only_if_cases(zotero, server, tmp_path, monkeypatch, capsys):
    from zot_clean import api
    from zot_clean.cli import main
    m = World(zotero, server)
    m.item('Article A', 'durand2020')
    m.read()
    workspace = tmp_path / 'travail'
    (workspace / 'suivi').mkdir(parents=True)
    (workspace / 'suivi' / citation_keys.FILE).write_text(citation_keys.header(), encoding='utf-8')  # header only
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    monkeypatch.setattr(bbt, 'detect', lambda folder: BBT)
    main(['citation-keys', 'plan', '--workspace', str(workspace)])
    output = capsys.readouterr().out
    assert 'Rien à faire' in output and 'Cas qui demandent' not in output


def test_suffix_continues_bbt_series():
    from zot_clean import citation_keys as c
    assert c.base_of('durand2020a') == 'durand2020' and c.base_of('DURAND2020A') == 'DURAND2020'
    assert c.base_of('sacksLhommeQuiPrenait1988') == 'sacksLhommeQuiPrenait1988'
    database = c.base_of('auteurTitre2000a')
    assert database + c.free_suffix(database, ['auteurTitre2000a', 'AUTEURTITRE2000A']) == 'auteurTitre2000b'


def test_report_tracking_and_refusals_in_english(world, cfg, server):
    from zot_clean.lang import language
    m, x = world
    cfg.writing.trial = 2
    b = m.read()
    with language('en'):
        plan, report = citation_keys.make_plan(b, cfg, server.client(), BBT)
        tracking = (cfg.tracking / citation_keys.FILE).read_text(encoding='utf-8')
        with pytest.raises(Refusal, match='stores keys in its own database'):
            citation_keys.make_plan(b, cfg, server.client(), bbt.State(installed=True, active=True, version='7.0.5'))
    assert report.startswith('# Citation keys, plan of ') and '## Trial' in report and '## Duplicate keys' in report
    assert '## Sent back to step 2' in report and '`zc apply <plan> --trial`' in report
    assert 'Article A keeps the key' in report and '(key taken from the title of another item)' in report
    assert tracking.startswith('# Citation keys, cases that need an opinion') and 'added on 2020-01-01, keeps the key' in tracking
    assert plan.description.startswith('Citation keys, ')
    assert citation_keys.header().startswith('# Clés de citation')  # French outside the block


def test_kinds_of_change_shown_in_the_library_language():
    """The kinds of change are internal codes (trial selection); the nature and the report show them translated."""
    from zot_clean.lang import language
    kinds = {citation_keys.SUFFIX, citation_keys.REMOVED}
    assert citation_keys.kinds_shown(kinds) == "ligne d'Extra retirée, suffixe"
    with language('en'):
        assert citation_keys.kinds_shown(kinds) == 'Extra line removed, suffix'
        assert citation_keys.kind_label(citation_keys.TO_NATIVE) == 'Extra to the native field'
