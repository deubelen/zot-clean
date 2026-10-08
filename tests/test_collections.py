"""Plans on collections (D114): creation under a key drawn by the plan, filing, rerun, undo."""

import hashlib
import json

import pytest

from fake_server import FakeServer
from test_undo import undo_plan
from test_apply import write
from zot_clean import journal, plans
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


def create(key, name, parent=False):
    return Operation(key, {}, {'name': name, 'parentCollection': parent}, kind='collections', create=True)


def subtheme_plan(server):
    """An existing theme, renamed, a sub-theme created, an item moving from the theme to the sub-theme."""
    theme = server.collection('Ethologie')
    item = server.add(title='Cultures in chimpanzees', collections=[theme])
    under = 'PRIM2345'
    g = Group('1', 'Éthologie/Primates', [
        Operation(theme, {'name': 'Ethologie'}, {'name': 'Éthologie'}, kind='collections'),
        create(under, 'Primates', theme),
        Operation(item, {'collections': [theme]}, {'collections': [under]}, rank=1)])
    return Plan('fonds', server.user, [g]), theme, under, item


def test_create_and_filing(server, cfg):
    plan, theme, under, item = subtheme_plan(server)
    path = write(plan, cfg)
    outcome = apply_plan(plans.load(path), path, server.client(), cfg, TRIAL)
    assert outcome.done == ['1'] and not outcome.conflicts and not outcome.errors
    assert server.collections[theme]['name'] == 'Éthologie'
    assert (server.collections[under]['name'], server.collections[under]['parentCollection']) == ('Primates', theme)
    assert server.all_items[item]['collections'] == [under]
    lines = [l for l in journal.read(outcome.journal) if l['type'] == 'element']
    assert [(l.get('genre', 'items'), l.get('cree', False)) for l in lines] == [
        ('collections', False), ('collections', True), ('items', False)]
    # Rerunning does nothing, the group is done.
    assert apply_plan(plan, path, server.client(), cfg, ALL).journal is None


def test_collection_already_created_by_interrupted_run(server, cfg):
    plan, theme, under, item = subtheme_plan(server)
    server.collection('Primates', theme, key=under)
    path = write(plan, cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert outcome.done == ['1'] and server.all_items[item]['collections'] == [under]


def test_key_already_taken_by_another_collection(server, cfg):
    plan, theme, under, item = subtheme_plan(server)
    server.collection('Autre chose', key=under)
    path = write(plan, cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert '1' in outcome.conflicts and 'existe déjà' in outcome.conflicts['1']
    assert server.all_items[item]['collections'] == [theme]


def test_undo_restores_the_item_and_trashes_the_created_collection(server, cfg):
    plan, theme, under, item = subtheme_plan(server)
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    plan_a, report, path_a = undo_plan(path, server, cfg)
    assert [op.kind for op in plan_a.groups[0].operations] == ['items', 'collections', 'collections']
    assert 'Primates' in report
    outcome = apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    assert outcome.done == ['1']
    assert server.all_items[item]['collections'] == [theme]
    assert server.collections[under]['deleted'] is True
    assert server.collections[theme]['name'] == 'Ethologie'


def test_item_to_nonexistent_collection_rejected(server, cfg):
    theme = server.collection('Thème')
    item = server.add(title='Titre', collections=[theme])
    plan = Plan('fonds', server.user, [Group('1', 'x', [
        Operation(item, {'collections': [theme]}, {'collections': ['NULLE234']})])])
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert '1' in outcome.errors and server.all_items[item]['collections'] == [theme]


def test_fingerprint_of_old_plans_unchanged():
    """The fields added for collections, at their default value, do not enter the fingerprint."""
    plan = Plan('test', 1, [Group('1', 't', [Operation('ABCD2345', {'title': 'a'}, {'title': 'b'})])])
    old = [plans._stored_group(g) for g in plan.groups]  # keys of the file (D209)
    for g in old:
        g['operations'] = [{k: v for k, v in o.items() if k not in ('genre', 'creation', 'enfants', 'exige')} for o in g['operations']]
    content = {'etape': 'test', 'bibliotheque': 1, 'partiel': False, 'groupes': old}
    expected = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    assert plan.fingerprint == expected


def test_undo_replays_groups_from_last_to_first(server, cfg):
    """A collection created by one group and another moved into it by a later group: the undo takes out
    the second first, then sends the first to the trash (found by the trial on the test account)."""
    former = server.collection('Vieux classement')
    archives = 'ARCH2345'
    plan = Plan('fonds', server.user, [
        Group('1', 'Archives', [create(archives, 'Archives')]),
        Group('2', 'Archives/Vieux classement', [
            Operation(former, {'parentCollection': False}, {'parentCollection': archives}, kind='collections')])])
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    plan_a, _, _ = undo_plan(path, server, cfg)
    assert [g.id for g in plan_a.groups] == ['2', '1']


@pytest.mark.parametrize('tweak', ['renommee', 'fiche ajoutee', 'sous-collection'])
def test_undo_keeps_a_created_collection_changed_since(server, cfg, tweak):
    # D183 : a collection created by the pass, since renamed or filled by the user, stays in place. The
    # rest of the pass is undone.
    plan, theme, under, item = subtheme_plan(server)
    path = write(plan, cfg)
    apply_plan(plan, path, server.client(), cfg, TRIAL)
    if tweak == 'renommee':
        server.collections[under]['name'] = 'Projet ajouté à la main'
    elif tweak == 'fiche ajoutee':
        server.add(title='Ajoutée à la main', collections=[under])
    else:
        server.collection('Ajoutée à la main', under)
    plan_a, _, path_a = undo_plan(path, server, cfg)
    outcome = apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    assert under in outcome.conflicts['1'] and outcome.stopped['1']
    assert not server.collections[under].get('deleted')
    assert server.all_items[item]['collections'] == [theme]
