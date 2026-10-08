"""Identical PDFs (D125): detection, trash and reattachment, safeguard for annotated copies, undo."""

import pytest

from fake_server import FakeServer
from test_undo import undo_plan
from test_apply import write
from test_duplicates import Double
from zot_clean import attachments as p
from zot_clean.apply import TRIAL, apply_plan
from zot_clean.config import Config
from zot_clean.lang import language


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


@pytest.fixture
def world(zotero, server):
    """Grant's PDF also attached to Ardery's item, Vygotsky with the same PDF twice, a book and its
    chapter sharing the book's PDF, and an annotated PDF on the wrong item."""
    dd = Double(zotero, server)
    f = {n: dd.item(t) for n, t in (('grant', 'Paint and Be Happy'), ('ardery', 'Loser wins'),
                                     ('vygotsky', 'Mind in society'), ('livre', 'The practice turn'),
                                     ('chapitre', 'Throwing out the tacit rule book'), ('bon', 'Le bon article'),
                                     ('mauvais', 'Un autre article'))}
    c = {'grant': dd.pdf(f['grant'], 'grant.pdf', b'%PDF grant'),
         'ardery': dd.pdf(f['ardery'], 'grant.pdf', b'%PDF grant'),
         'v1': dd.pdf(f['vygotsky'], 'v.pdf', b'%PDF vygotsky'),
         'v2': dd.pdf(f['vygotsky'], 'v copie.pdf', b'%PDF vygotsky'),
         'livre': dd.pdf(f['livre'], 'livre.pdf', b'%PDF livre'),
         'chapitre': dd.pdf(f['chapitre'], 'livre.pdf', b'%PDF livre'),
         'bon': dd.pdf(f['bon'], 'a.pdf', b'%PDF annote'),
         'mauvais': dd.pdf(f['mauvais'], 'a.pdf', b'%PDF annote', annotated=True),
         'seul': dd.pdf(f['grant'], 'autre.pdf', b'%PDF unique')}
    return dd, f, c


def decide(cfg, b, decisions):
    entries = p.find(b, cfg)
    for e in entries:
        for copies, (decision, trash, move) in decisions.items():
            if set(e.copies) == set(copies):
                e.decision, e.trash, e.move = decision, trash, move
    p.write(cfg, entries, b)


def test_find(world, cfg):
    dd, f, c = world
    entries = p.find(dd.library(), cfg)
    assert sorted(sorted(e.copies) for e in entries) == sorted(sorted(g) for g in (
        (c['grant'], c['ardery']), (c['v1'], c['v2']), (c['livre'], c['chapitre']), (c['bon'], c['mauvais'])))
    text = (cfg.tracking / p.FILE).read_text(encoding='utf-8')
    assert 'Loser wins' in text and '1 annotation(s) ou note(s)' in text


def test_trash_move_and_undo(world, cfg, server):
    dd, f, c = world
    b = dd.library()
    decide(cfg, b, {(c['grant'], c['ardery']): (p.APPLY, [c['ardery']], {}),
                     (c['v1'], c['v2']): (p.APPLY, [c['v2']], {}),
                     (c['livre'], c['chapitre']): (p.KEEP, [], {}),
                     # The annotated copy is on the wrong item: it is reattached, and the other goes to the trash.
                     (c['bon'], c['mauvais']): (p.APPLY, [c['bon']], {c['mauvais']: f['bon']})})
    plan, report = p.make_plan(cfg, server.client(), b)
    assert len(plan.groups) == 3 and 'Groupes écartés' not in report and plan.step == 'pieces'
    path = write(plan, cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert not outcome.conflicts and not outcome.errors
    el = server.all_items
    assert el[c['ardery']]['deleted'] and el[c['v2']]['deleted'] and el[c['bon']]['deleted']
    assert el[c['mauvais']]['parentItem'] == f['bon'] and not el[c['grant']].get('deleted')
    # A new search keeps the decisions of the groups still present.
    assert {e.decision for e in p.find(b, cfg)} == {p.APPLY, p.KEEP}
    plan_a, _, path_a = undo_plan(path, server, cfg)
    apply_plan(plan_a, path_a, server.client(), cfg, TRIAL)
    assert not el[c['ardery']].get('deleted') and el[c['mauvais']]['parentItem'] == f['mauvais']


def test_safeguards(world, cfg, server):
    dd, f, c = world
    b = dd.library()
    decide(cfg, b, {(c['bon'], c['mauvais']): (p.APPLY, [c['mauvais']], {}),
                     (c['v1'], c['v2']): (p.APPLY, [c['v1'], c['v2']], {}),
                     (c['grant'], c['ardery']): (p.APPLY, [c['seul']], {})})
    plan, report = p.make_plan(cfg, server.client(), b)
    assert not plan.groups
    assert 'porte des annotations ou des notes' in report
    assert 'toutes les copies iraient à la corbeille' in report
    assert 'ne fait pas partie des copies du groupe' in report


def test_confidential_group_hidden(zotero, server, cfg):
    dd = Double(zotero, server)
    secret_item = dd.item('Mon dossier médical', tags=('_privé',))
    other = dd.item('Une fiche publique')
    copy = dd.pdf(secret_item, 'a.pdf', b'%PDF secret')
    dd.pdf(other, 'a.pdf', b'%PDF secret')
    b = dd.library()
    p.find(b, cfg)
    text = (cfg.tracking / p.FILE).read_text(encoding='utf-8')
    assert 'médical' not in text and 'publique' not in text and '(fiche confidentielle)' in text
    decide(cfg, b, {tuple(e.copies): ('appliquer', [k for k in e.copies if k != copy], {})
                     for e in p.load(cfg)})
    plan, report = p.make_plan(cfg, server.client(), b)
    assert len(plan.groups) == 1 and 'médical' not in report and 'publique' not in report


def test_warning_duplicates_and_missing_files(world, cfg):
    """A PDF shared by two items points to `zc doublons chercher`, which proposes them (D125), and a PDF
    missing from the disk is reported (D168)."""
    from zot_clean import duplicates
    dd, f, c = world
    b = dd.library()
    entries = p.find(b, cfg)
    warn_msg = p.warning(b, cfg, entries)
    assert warn_msg.startswith('3 PDF partagés par des fiches différentes') and 'zc duplicates find' in warn_msg
    assert 'absent' not in warn_msg
    duplicates.find(b, cfg)
    assert p.warning(b, cfg, entries) == ''
    dd.pdf(f['bon'], 'absent.pdf', None)
    b = dd.library()
    assert p.warning(b, cfg, p.find(b, cfg)).startswith('1 PDF absent du disque')


def test_decisions_by_command(world, cfg, monkeypatch, capsys):
    """D177: each group is decided by command, designated by one of its copies, with the same safeguards as the
    plan (annotated copy never trashed, at least one copy kept)."""
    from zot_clean import api
    from zot_clean.cli import main
    dd, f, c = world
    b = dd.library()
    entries = p.find(b, cfg)
    with pytest.raises(SystemExit, match=f'ne contient la copie {f["grant"]}'):  # item key, not copy key
        p.decide(entries, b, [f['grant']])
    with pytest.raises(SystemExit, match='annotations ou des notes'):
        p.decide(entries, b, [c['mauvais']])
    with pytest.raises(SystemExit, match='il faut en garder une'):
        p.decide(entries, b, [c['v1'], c['v2']])
    entries = p.find(b, cfg)
    assert p.decide(entries, b, [c['bon']], {c['mauvais']: f['bon']}, reason='PDF annoté') == (1, 0)
    assert p.decide(entries, b, keep=[c['chapitre']], reason='chapitre et livre') == (0, 1)
    with pytest.raises(SystemExit, match='déjà décidé'):
        p.decide(entries, b, keep=[c['bon']])
    group = next(e for e in entries if c['bon'] in e.copies)
    assert (group.decision, group.trash, group.move, group.reason) == (
        p.APPLY, [c['bon']], {c['mauvais']: f['bon']}, 'PDF annoté')

    # Through the command line.
    cfg.workspace.mkdir(exist_ok=True)
    (cfg.workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n',
                                                     encoding='utf-8')

    def no_key(cfg):
        raise SystemExit('pas de clé')
    monkeypatch.setattr(api, 'from_config', no_key)
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['attachments', 'accept', '--trash', c['v2'], *folder]) == 0
    assert 'par cette commande dans ' in (out := capsys.readouterr().out) and 'pieces.toml : 1 groupe à appliquer. ' in out
    assert main(['attachments', 'reject', c['livre'], '--reason', 'chapitre et livre', *folder]) == 0
    assert main(['attachments', 'accept', '--move', c['mauvais'], *folder]) == 1
    assert 'COPIE=FICHE' in capsys.readouterr().err
    reloaded_entries = {frozenset(e.copies): e for e in p.load(cfg)}
    assert reloaded_entries[frozenset((c['v1'], c['v2']))].trash == [c['v2']]
    assert reloaded_entries[frozenset((c['livre'], c['chapitre']))].decision == p.KEEP
    assert reloaded_entries[frozenset((c['grant'], c['ardery']))].decision == ''
    assert 'Loser wins' in (cfg.tracking / p.FILE).read_text(encoding='utf-8')


def test_annotation_added_after_the_plan(world, cfg, server):
    # D182: the copy had no annotation at plan time, it received one before the application. It stays in place.
    dd, f, c = world
    b = dd.library()
    decide(cfg, b, {(c['v1'], c['v2']): (p.APPLY, [c['v2']], {})})
    plan, _ = p.make_plan(cfg, server.client(), b)
    assert [op.children for op in plan.groups[0].operations] == [[]]
    annotation = server.add('annotation', parentItem=c['v2'])
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert annotation in outcome.conflicts['1'] and 'hors de la corbeille' in outcome.conflicts['1']
    assert not server.all_items[c['v2']].get('deleted')


def test_copy_with_own_note_never_to_trash(zotero, server, cfg):
    # D206: an attachment's own note protects the copy like an annotation (D125).
    dd = Double(zotero, server)
    f = dd.item('Mind in society')
    v1 = dd.pdf(f, 'v.pdf', b'%PDF vygotsky')
    v2 = dd.pdf(f, 'v copie.pdf', b'%PDF vygotsky', note='<p>Mes remarques</p>')
    b = dd.library()
    decide(cfg, b, {(v1, v2): (p.APPLY, [v2], {})})
    plan, report = p.make_plan(cfg, server.client(), b)
    assert not plan.groups and 'porte des annotations ou des notes' in report


def test_texts_in_english(zotero, server, cfg):
    dd = Double(zotero, server)
    f = dd.item('Mind in society')
    v1 = dd.pdf(f, 'v.pdf', b'%PDF vygotsky')
    v2 = dd.pdf(f, 'v copie.pdf', b'%PDF vygotsky', note='<p>Mes remarques</p>')
    b = dd.library()
    with language('en'):
        decide(cfg, b, {(v1, v2): (p.APPLY, [v2], {})})
        header = (cfg.tracking / p.FILE).read_text(encoding='utf-8')
        assert 'Identical PDFs found by `zc attachments find`' in header and '# decision  : "appliquer"' in header
        plan, report = p.make_plan(cfg, server.client(), b)
        assert not plan.groups and 'carries annotations or notes and does not go to the trash' in report
        assert '## Groups set aside' in report
        with pytest.raises(SystemExit, match='No group of pieces.toml contains the copy ZZZZZZZZ'):
            p.decide(p.load(cfg), b, trash=['ZZZZZZZZ'])
