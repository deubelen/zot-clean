import json
from datetime import datetime, timedelta

import pytest

from fake_server import FakeServer
from zot_clean import journal, plans
from zot_clean.apply import TRIAL, ALL, apply_plan
from zot_clean.config import Config
from zot_clean.api import APIError, Refusal
from zot_clean.plans import Group, Operation, Plan


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def cfg(tmp_path, zotero):
    zotero.item('Une fiche')
    zotero.save()
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


def titles_plan(server, n, prefix='Titre'):
    """One group per item, changing its title."""
    groups = []
    for i in range(n):
        key = server.add(title=f'{prefix} {i}')
        groups.append(Group(str(i), f'fiche {i}', [Operation(key, {'title': f'{prefix} {i}'},
                                                               {'title': f'{prefix} {i} corrigé'})]))
    return Plan('test', server.user, groups)


def write(plan, cfg):
    return plans.write(plan, cfg.plans, '# rapport')


def fake_backup(cfg, age_hours=1):
    d = cfg.backups / 'factice'
    d.mkdir(parents=True)
    date = datetime.now().astimezone() - timedelta(hours=age_hours)
    (d / 'sauvegarde.json').write_text(json.dumps({'date': date.isoformat(), 'methode': 'base',
                                                   'version_bibliotheque': 1, 'taille': 1}), encoding='utf-8')


def test_small_plan_fully_applied_by_trial(server, cfg):
    plan = titles_plan(server, 3)
    path = write(plan, cfg)
    outcome = apply_plan(plans.load(path), path, server.client(), cfg, TRIAL)
    assert outcome.done == ['0', '1', '2'] and outcome.remaining == 0
    assert all(d['title'].endswith('corrigé') for d in server.all_items.values())
    lines = journal.read(outcome.journal)
    assert [l['type'] for l in lines] == (['en-tete'] + ['intention'] * 3 + ['element'] * 3 + ['groupe'] * 3
                                           + ['fin'])
    assert lines[4]['avant']['title'] == 'Titre 0' and lines[4]['ecrit'] == {'title': 'Titre 0 corrigé'}
    assert lines[0]['empreinte'] == plan.fingerprint
    # Rerunning redoes nothing.
    assert apply_plan(plan, path, server.client(), cfg, ALL).journal is None


def test_trial_then_backup_required_beyond(server, cfg):
    plan = titles_plan(server, 8)
    path = write(plan, cfg)
    client = server.client()
    with pytest.raises(Refusal, match='essai'):
        apply_plan(plan, path, client, cfg, ALL)
    outcome = apply_plan(plan, path, client, cfg, TRIAL)
    assert len(outcome.done) == 5 and outcome.remaining == 3
    with pytest.raises(Refusal, match='sauvegarde'):
        apply_plan(plan, path, client, cfg, ALL)
    fake_backup(cfg, age_hours=30)
    with pytest.raises(Refusal, match='sauvegarde'):
        apply_plan(plan, path, client, cfg, ALL)
    (cfg.backups / 'factice' / 'sauvegarde.json').unlink()
    (cfg.backups / 'factice').rmdir()
    fake_backup(cfg)
    outcome = apply_plan(plan, path, client, cfg, ALL)
    assert outcome.done == ['5', '6', '7'] and outcome.remaining == 0


def test_small_management_plan_without_trial_or_backup(server, cfg):
    # D136, D138: an Inbox sort of fewer than 50 items applies at once, without a trial or a backup.
    plan = titles_plan(server, 8)
    plan.step = 'inbox'
    client = server.client()
    outcome = apply_plan(plan, write(plan, cfg), client, cfg, ALL)
    assert len(outcome.done) == 8 and outcome.remaining == 0
    large = titles_plan(server, 8, 'Autre')
    large.step = 'inbox'
    cfg.writing.small_management_plan = 8
    path = write(large, cfg)
    with pytest.raises(Refusal, match='essai'):
        apply_plan(large, path, client, cfg, ALL)
    apply_plan(large, path, client, cfg, TRIAL)
    with pytest.raises(Refusal, match='sauvegarde'):
        apply_plan(large, path, client, cfg, ALL)


def test_conflict_when_field_has_changed(server, cfg):
    plan = titles_plan(server, 2)
    server.modify(plan.groups[0].operations[0].key, title='Corrigé à la main')
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert list(outcome.conflicts) == ['0'] and outcome.done == ['1']
    assert server.all_items[plan.groups[0].operations[0].key]['title'] == 'Corrigé à la main'
    assert outcome.remaining == 1


def test_other_field_changed_elsewhere_without_conflict(server, cfg):
    plan = titles_plan(server, 1)
    key = plan.groups[0].operations[0].key
    server.modify(key, date='1999')
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['0'] and server.all_items[key]['date'] == '1999'


def test_retry_after_412(server, cfg):
    plan = titles_plan(server, 1)
    key = plan.groups[0].operations[0].key
    times = []

    def sync_check():
        if not times:
            times.append(1)
            server.modify(key, extra='modifié pendant l’écriture')
    server.before_write = sync_check
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['0'] and server.all_items[key]['title'] == 'Titre 0 corrigé'
    assert len([r for r in server.requests if r[0] == 'POST']) == 2


def test_failed_rank_stops_group(server, cfg):
    a = server.add(title='A')
    b = server.add(title='B')
    g = Group('1', 'fusion', [Operation('DISPARU2', {'deleted': False}, {'deleted': True}, rank=0),
                               Operation(a, {'title': 'A'}, {'title': 'A2'}, rank=1)])
    g2 = Group('2', 'autre', [Operation(b, {'title': 'B'}, {'title': 'B2'})])
    plan = Plan('test', server.user, [g, g2])
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert "n'existe plus" in outcome.conflicts['1'] and outcome.done == ['2']
    assert server.all_items[a]['title'] == 'A'


def test_trash_and_reattachment(server, cfg):
    p = server.add(title='Parent')
    x = server.add(title='Autre')
    att = server.add('attachment', parentItem=x, title='PDF')
    g = Group('1', 'fusion', [Operation(att, {'parentItem': x}, {'parentItem': p}, rank=0),
                               Operation(x, {'deleted': False}, {'deleted': True}, rank=1)])
    plan = Plan('test', server.user, [g])
    apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert server.all_items[att]['parentItem'] == p and server.all_items[x]['deleted'] is True


def test_partial_plan_leaves_only_conflicting_field(server, cfg):
    a = server.add(title='A2', date='2001')
    g = Group('1', 'annulation', [Operation(a, {'title': 'A2', 'date': '2001'}, {'title': 'A', 'date': '2000'})])
    plan = Plan('annulation', server.user, [g], partial=True)
    server.modify(a, title='Retouché')
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert '1' in outcome.partials
    assert server.all_items[a]['title'] == 'Retouché' and server.all_items[a]['date'] == '2000'


def test_resume_after_interruption(server, cfg):
    plan = titles_plan(server, 60)
    path = write(plan, cfg)
    client = server.client()
    cfg.writing.trial = 100
    posts = []

    def outage():
        posts.append(1)
        if len(posts) == 1:
            server.outages = [503] * 10
    server.before_write = outage
    with pytest.raises(APIError):
        apply_plan(plan, path, client, cfg, TRIAL)
    first = journal.all_entries(cfg.journal)[0]
    assert not first.finished and len(first.groups) == 50
    server.before_write, server.outages = None, []
    outcome = apply_plan(plan, path, client, cfg, TRIAL)
    assert len(outcome.done) == 10 and journal.summarize(outcome.journal).header['reprise']
    assert all(d['title'].endswith('corrigé') for d in server.all_items.values())


def test_other_account_rejected(server, cfg):
    plan = titles_plan(server, 1)
    plan.library = 1
    with pytest.raises(Refusal, match='compte'):
        apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)


def test_invalid_key_rejected(server, cfg, zotero):
    zotero.item('Clé cassée', key='ABC0DEF1')
    zotero.save()
    plan = titles_plan(server, 1)
    with pytest.raises(Refusal, match='clé invalide'):
        apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)


def test_edited_plan_rejected(server, cfg):
    path = write(titles_plan(server, 1), cfg)
    path.write_text(path.read_text(encoding='utf-8').replace('corrigé', 'autre'), encoding='utf-8')
    with pytest.raises(SystemExit, match='modifié'):
        plans.load(path)


def test_unsynced_annotations_reported_separately(tmp_path, zotero):
    from zot_clean.apply import check_sync
    item = zotero.item('Fiche')
    zotero.annotation(zotero.pdf(item, 'a.pdf'))
    zotero.db.execute("update items set synced = 0 where itemTypeID = (select itemTypeID from itemTypes "
                      "where typeName = 'annotation')")
    zotero.save()
    cfg = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    assert 'annotation(s) de PDF' in check_sync(cfg)


def test_response_lost_write_journaled(server, cfg):
    # D178: zotero.org performs the write but its response is lost. The new attempt receives a 412, re-reading finds
    # the written values, and the intent recorded before sending makes it a journaled write, hence undoable.
    from zot_clean import undo
    plan = titles_plan(server, 3)
    server.lost_responses = 1
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['0', '1', '2'] and outcome.items_written == 3
    lines = journal.read(outcome.journal)
    assert [l['avant']['title'] for l in lines if l['type'] == 'element'] == ['Titre 0', 'Titre 1', 'Titre 2']
    assert not journal.pending([outcome.journal])
    plan_a, _ = undo.make_plan([outcome.journal], server.client())
    assert len(plan_a.groups) == 3


def test_collection_created_response_lost(server, cfg):
    key = 'ARCH2345'
    plan = Plan('test', server.user, [Group('1', 'archives', [
        Operation(key, {}, {'name': 'Archives', 'parentCollection': False}, kind='collections', create=True)])])
    server.lost_responses = 1
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['1'] and outcome.items_written == 1
    item = [l for l in journal.read(outcome.journal) if l['type'] == 'element']
    assert item[0]['cle'] == key and item[0]['cree']


def test_interruption_after_send_resume_then_undo(server, cfg):
    from zot_clean import undo
    plan = titles_plan(server, 2)
    path = write(plan, cfg)
    client = server.client()
    server.lost_responses = 10  # written at the first send, then no response: the command stops
    with pytest.raises(APIError):
        apply_plan(plan, path, client, cfg, TRIAL)
    first = journal.all_entries(cfg.journal)[0].path
    assert len(journal.pending([first])) == 2
    assert all(d['title'].endswith('corrigé') for d in server.all_items.values())
    server.lost_responses = 0
    outcome = apply_plan(plan, path, client, cfg, TRIAL)  # the resume recognizes its own writes
    assert outcome.done == ['0', '1'] and outcome.items_written == 2
    assert not journal.pending([first, outcome.journal])
    plan_a, _ = undo.make_plan(undo.targeted_journals(path, cfg), client)
    outcome_a = apply_plan(plan_a, plans.write(plan_a, cfg.plans, '#'), client, cfg, TRIAL)
    assert outcome_a.done == ['1', '0'] and sorted(d['title'] for d in server.all_items.values()) == ['Titre 0',
                                                                                                    'Titre 1']


@pytest.mark.parametrize('happened', [True, False])
def test_undo_of_an_uncertain_write(server, cfg, happened):
    # Command interrupted without resume: undo reverses the write if it happened, and touches nothing otherwise.
    from zot_clean import undo
    plan = titles_plan(server, 1)
    client = server.client()
    cut_client = server.client()
    if happened:
        server.lost_responses = 10
    else:
        def cut_write(*a, **k):
            raise APIError('zotero.org injoignable')
        cut_client.write = cut_write
    with pytest.raises(APIError):
        apply_plan(plan, write(plan, cfg), cut_client, cfg, TRIAL)
    server.lost_responses = 0
    j = journal.all_entries(cfg.journal)[0].path
    plan_a, report = undo.make_plan([j], client)
    assert 'sans que Zotero en confirme le résultat' in report
    outcome_a = apply_plan(plan_a, plans.write(plan_a, cfg.plans, report), client, cfg, TRIAL)
    assert outcome_a.done == ['0'] and outcome_a.items_written == (1 if happened else 0)
    assert [d['title'] for d in server.all_items.values()] == ['Titre 0']


def test_rerun_trial_does_not_advance_in_plan(server, cfg):
    # D179: a rerun `--essai` only resumes the groups of the trial, never the following ones, and nothing goes
    # beyond without a backup.
    plan = titles_plan(server, 12)
    path = write(plan, cfg)
    client = server.client()
    key = plan.groups[1].operations[0].key
    server.modify(key, title='Corrigé à la main')
    outcome = apply_plan(plan, path, client, cfg, TRIAL)
    assert outcome.done == ['0', '2', '3', '4'] and list(outcome.conflicts) == ['1']
    server.modify(key, title='Titre 1')
    outcome = apply_plan(plan, path, client, cfg, TRIAL)
    assert outcome.done == ['1'] and outcome.remaining == 7
    outcome = apply_plan(plan, path, client, cfg, TRIAL)
    assert outcome.journal is None and outcome.remaining == 7
    assert sum(d['title'].endswith('corrigé') for d in server.all_items.values()) == 5
    with pytest.raises(Refusal, match='sauvegarde'):
        apply_plan(plan, path, client, cfg, ALL)


def test_group_stopped_after_part_of_writes(server, cfg):
    # D181: the first rank is written, the second is in conflict. The group is not presented as intact.
    a = server.add(title='A')
    b = server.add(title='B')
    c = server.add(title='C')
    plan = Plan('test', server.user, [
        Group('1', 'fusion', [Operation(a, {'title': 'A'}, {'title': 'A2'}, rank=0),
                               Operation(b, {'title': 'B'}, {'title': 'B2'}, rank=1)]),
        Group('2', 'autre', [Operation(c, {'title': 'Autre'}, {'title': 'C2'})])])
    server.modify(b, title='Corrigé à la main')
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert set(outcome.conflicts) == {'1', '2'} and outcome.stopped == {'1': [a]}
    assert f"après l'écriture de {a}" in outcome.conflicts['1']


def test_key_of_another_account_rejected_at_apply(server, cfg, zotero):
    """The key must be that of the account Zotero syncs on this computer. A researcher with two accounts
    (personal and institutional) who creates the key on the other one would otherwise write to another library."""
    plan = titles_plan(server, 2)
    path = write(plan, cfg)
    zotero.account(9999, 'institution')
    zotero.save()
    with pytest.raises(Refusal, match=r'synchronise le compte « institution » \(n° 9999\)'):
        apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert not [r for r in server.requests if r[0] != 'GET'] and not cfg.journal.exists()
    zotero.account(server.user)
    zotero.save()
    assert apply_plan(plan, path, server.client(), cfg, TRIAL).done == ['0', '1']


def test_key_of_another_account_rejected_at_planning(server, cfg, zotero):
    """`read_up_to_date`, through which all the planning goes, refuses before any request. Without this check, the
    recent changes of the other library, further along than the local database, would be carried over to this one."""
    from zot_clean.apply import read_up_to_date
    server.add(title="Fiche de l'autre bibliothèque")
    zotero.account(9999)
    zotero.save()
    with pytest.raises(Refusal, match='il modifierait donc une autre bibliothèque'):
        read_up_to_date(cfg, server.client())
    with pytest.raises(Refusal, match='autre bibliothèque'):  # even for a command that only reads
        read_up_to_date(cfg, server.client(), optional=True)
    assert server.requests == []
    zotero.account(server.user)
    zotero.save()
    # Normal case: the changes of the server, further along than the local database, are carried over.
    assert "Fiche de l'autre bibliothèque" in {e.title for e in read_up_to_date(cfg, server.client()).items}


def test_database_never_synced_rejected(server, cfg, zotero):
    """Without an account recorded in the database, nothing says which library it is, and Zotero would not receive
    the writes made by zotero.org."""
    from zot_clean.apply import read_up_to_date
    plan = titles_plan(server, 1)
    path = write(plan, cfg)
    zotero.account(None)
    zotero.save()
    for trial in (lambda: read_up_to_date(cfg, server.client()),
                  lambda: apply_plan(plan, path, server.client(), cfg, TRIAL)):
        with pytest.raises(Refusal, match="jamais synchronisé.*Réglages › Synchronisation"):
            trial()
    assert server.requests == []


def test_refusals_and_messages_in_english(server, cfg):
    from zot_clean.lang import language
    plan = titles_plan(server, 8)
    path = write(plan, cfg)
    client = server.client()
    with language('en'):
        with pytest.raises(Refusal, match=r'No trial of this plan.*`zc apply <plan> --trial`'):
            apply_plan(plan, path, client, cfg, ALL)
        apply_plan(plan, path, client, cfg, TRIAL)
        with pytest.raises(Refusal, match=r'No backup less than .* hours old.*`zc backup`'):
            apply_plan(plan, path, client, cfg, ALL)
        path.write_text(path.read_text(encoding='utf-8').replace('corrigé', 'autre'), encoding='utf-8')
        with pytest.raises(SystemExit, match='plan was modified after it was created'):
            plans.load(path)
