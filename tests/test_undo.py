import pytest

from fake_server import FakeServer
from test_apply import write, titles_plan, fake_backup
from zot_clean import undo, plans
from zot_clean.apply import TRIAL, ALL, apply_plan
from zot_clean.config import Config
from zot_clean.plans import Group, Operation, Plan


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def cfg(tmp_path, zotero):
    zotero.item('Une fiche')
    zotero.save()
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


def merge(server):
    """A manual merge: attachment moved, kept item completed, absorbed item sent to the trash."""
    m = server.add(title='Titre', DOI='', collections=['AAAA2222'], relations={})
    a = server.add(title='Titre', DOI='10.1/x', collections=['BBBB3333'])
    att = server.add('attachment', parentItem=a, title='PDF')
    uri = server.client().uri(a)
    g = Group('1', 'fusion', [
        Operation(att, {'parentItem': a}, {'parentItem': m}, rank=0),
        Operation(m, {'DOI': '', 'collections': ['AAAA2222'], 'relations': {}},
                  {'DOI': '10.1/x', 'collections': ['AAAA2222', 'BBBB3333'], 'relations': {'dc:replaces': [uri]}},
                  rank=1),
        Operation(a, {'deleted': False}, {'deleted': True}, rank=2)])
    return Plan('doublons', server.user, [g]), m, a, att


def undo_plan(path, server, cfg):
    plan, report = undo.make_plan(undo.targeted_journals(path, cfg), server.client())
    undo_path = plans.write(plan, cfg.plans, report)
    return plan, report, undo_path


def test_undo_of_a_merge(server, cfg):
    plan, m, a, att = merge(server)
    before = {k: dict(server.all_items[k]) for k in (m, a, att)}
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert server.all_items[a]['deleted'] and server.all_items[att]['parentItem'] == m
    plan_a, _, path_a = undo_plan(outcome.journal, server, cfg)
    assert [op.key for op in plan_a.groups[0].operations] == [a, m, att]
    outcome_a = apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    assert outcome_a.done == ['1']
    for k in (m, a, att):
        after = {c: v for c, v in server.all_items[k].items() if c != 'version'}
        assert after == {c: v for c, v in before[k].items() if c != 'version'}


def test_field_edited_since_left_as_is(server, cfg):
    plan, m, a, att = merge(server)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    server.modify(m, DOI='10.1/corrigé-à-la-main')
    plan_a, _, path_a = undo_plan(outcome.journal, server, cfg)
    outcome_a = apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    assert 'DOI' in outcome_a.partials['1']
    assert server.all_items[m]['DOI'] == '10.1/corrigé-à-la-main'
    assert server.all_items[m]['collections'] == ['AAAA2222'] and not server.all_items[a].get('deleted')


def test_vanished_item_makes_group_not_undoable(server, cfg):
    plan, m, a, att = merge(server)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    del server.all_items[a]  # trash emptied
    plan_a, report, _ = undo_plan(outcome.journal, server, cfg)
    assert plan_a.groups == [] and 'non annulables' in report and a in report


def test_undo_of_all_journals_of_a_plan(server, cfg):
    plan = titles_plan(server, 8)
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    apply_plan(plan, path, server.client(), cfg, ALL)
    plan_a, _, path_a = undo_plan(path, server, cfg)
    assert len(plan_a.groups) == 8 and len(plan_a.undoes) == 2
    apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    apply_plan(plan_a, path_a, server.client(), cfg, ALL)
    assert not any(d['title'].endswith('corrigé') for d in server.all_items.values())


def test_plan_recomputed_after_undo_reapplies(server, cfg):
    # A plan recomputed identically has the same fingerprint: its undone groups no longer count as done.
    plan = titles_plan(server, 8)
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    fake_backup(cfg)
    apply_plan(plan, path, server.client(), cfg, ALL)
    plan_a, _, path_a = undo_plan(path, server, cfg)
    apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    apply_plan(plan_a, path_a, server.client(), cfg, ALL)
    assert not any(d['title'].endswith('corrigé') for d in server.all_items.values())
    with pytest.raises(Exception, match='essai'):
        apply_plan(plan, path, server.client(), cfg, ALL)
    outcome = apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert outcome.done and not outcome.conflicts
    apply_plan(plan, path, server.client(), cfg, ALL)
    assert sum(d['title'].endswith('corrigé') for d in server.all_items.values()) == 8


def test_report_hides_confidential_items(server, cfg):
    plan, m, a, att = merge(server)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    _, report = undo.make_plan([outcome.journal], server.client(), {m, a})
    assert "'Titre'" not in report and '10.1/x' not in report and f'{att} ' in report
    _, report = undo.make_plan([outcome.journal], server.client())
    assert "'PDF'" not in report


def test_plain_report(server, cfg):
    plan, m, a, att = merge(server)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    _, report = undo.make_plan([outcome.journal], server.client(), set())
    assert f'{a} « Titre » : sort de la corbeille' in report
    assert f'{att} « PDF » : revient sur la fiche {a}' in report
    assert "le DOI redevient vide, retrouve ses collections d'avant, retrouve ses liens d'avant" in report
    assert '←' not in report


def test_second_undo_of_reapplied_plan(server, cfg):
    # D180 : apply, undo, reapply the same plan, then undo again. The second undo plan has
    # the same groups as the first, but not the same journals, hence not the same fingerprint.
    plan = titles_plan(server, 2)
    path = write(plan, cfg)
    client = server.client()
    for _ in range(2):
        outcome = apply_plan(plan, path, client, cfg, TRIAL)
        assert outcome.done == ['0', '1']
        plan_a, _, path_a = undo_plan(outcome.journal, server, cfg)
        assert apply_plan(plan_a, path_a, client, cfg, TRIAL).done == ['1', '0']
        assert sorted(d['title'] for d in server.all_items.values()) == ['Titre 0', 'Titre 1']


def test_undone_journals_in_fingerprint(server, cfg):
    plan = titles_plan(server, 1)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    _, _, path_a = undo_plan(outcome.journal, server, cfg)
    text = path_a.read_text(encoding='utf-8')
    path_a.write_text(text.replace(outcome.journal.name, 'autre.jsonl'), encoding='utf-8')
    with pytest.raises(SystemExit, match='modifié'):
        plans.load(path_a)


def test_undo_plan_of_format_1_still_read(server, cfg):
    import json
    plan = titles_plan(server, 1)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    plan_a, _, path_a = undo_plan(outcome.journal, server, cfg)
    old = Plan(plan_a.step, plan_a.library, plan_a.groups, partial=True, format=1)
    d = json.loads(path_a.read_text(encoding='utf-8'))
    d.update(format=1, empreinte=old.fingerprint)
    path_a.write_text(json.dumps(d), encoding='utf-8')
    loaded = plans.load(path_a)
    assert loaded.undoes == [outcome.journal.name] and loaded.fingerprint == old.fingerprint != plan_a.fingerprint


def test_undo_report_in_english(server, cfg):
    from zot_clean.lang import language
    plan, m, a, att = merge(server)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    with language('en'):
        plan_a, report, _ = undo_plan(outcome.journal, server, cfg)
    assert '# Undo plan' in report and 'group(s) to undo' in report and '## Details' in report
    assert plan_a.description.startswith('Undo of ')
    assert 'goes to the trash' in report or 'comes out of the trash' in report


def test_undo_report_names_the_tags_that_come_back(server, cfg):
    """D242, verification pilots: the report said « retrouve ses tags d'avant » for each item, without naming them."""
    from zot_clean.lang import language
    key = server.add(title='Une fiche', tags=[{'tag': 'à lire'}, {'tag': 'Humans', 'type': 1}])
    g = Group('1', 'fiche', [Operation(key, {'tags': [{'tag': 'à lire'}, {'tag': 'Humans', 'type': 1}]},
                                       {'tags': [{'tag': '1 à lire'}]})])
    plan = Plan('tags', server.user, [g])
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    journals = undo.targeted_journals(outcome.journal, cfg)
    _, report = undo.make_plan(journals, server.client(), set())
    assert "retrouve ses tags d'avant : « à lire », « Humans »" in report
    with language('en'):
        _, report = undo.make_plan(journals, server.client(), set())
    assert 'gets its earlier tags back: “à lire”, “Humans”' in report
    _, report = undo.make_plan(journals, server.client(), {key})
    assert 'Humans' not in report  # confidential item: no value (D126)
