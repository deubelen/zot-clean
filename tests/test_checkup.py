"""Regular checkup (D137, D139 to D141), on the synthetic library of test_inbox."""

from datetime import date

from test_inbox import cfg, fake, world, server  # noqa: F401 (fixtures)
from zot_clean import checkup as k, subjects as f, filing as r
from zot_clean.audit import TO_REVIEW, Section
from zot_clean.lang import language


def _zotero(m, sql: str, *args):
    m.zotero.db.execute(sql, args)
    m.server.version += 1


def test_evolution_between_two_audits():
    before = {'chiffres': {'référence': 10}, 'points': {'Doublons probables': ['A/B', 'C/D']}}
    sections = [Section('Doublons probables', TO_REVIEW, '', points={'C/D': 'C / D', 'E/F': 'E / F'}),
                Section('Plan du fonds', TO_REVIEW, '', points={'x': 'x'})]

    class B:
        items, attachments, notes, collections = [1] * 12, [], [], []
    snap = k.snapshot(sections, B)
    text = '\n'.join(k.evolution(sections, snap, before, date(2026, 10, 1)))
    assert "Depuis l'audit du 01/10/2026" in text and '12 références (+2)' in text
    assert '1. Doublons probables, 1 nouveau et 1 réglé.' in text and '  - E / F' in text
    assert 'Plan du fonds' not in text  # checkup absent from the previous audit, not compared
    # D170 : the report says which audit it compares with, and that an audit from the same day compares with
    # the same one.
    assert "dernier audit d'un jour précédent, celui du 01/10/2026" in text
    assert "Aucun audit d'un jour précédent" in '\n'.join(k.no_comparison())


def test_previous_snapshot(cfg):
    k.save_snapshot(cfg, {'points': {}}, date(2026, 9, 30))
    k.save_snapshot(cfg, {'points': {'a': []}}, date(2026, 10, 2))
    k.save_snapshot(cfg, {'points': {'b': []}}, date(2026, 10, 3))
    day, snap = k.previous(cfg, date(2026, 10, 3))
    assert day == date(2026, 10, 2) and 'a' in snap['points']


def test_renaming_and_create_tracked(world, cfg):
    m, keys, items, b = world
    section, memory = k.outline_check(b, cfg)
    assert memory == {keys['Psy']: 'Psychologie', keys['Perception']: 'Psychologie/Perception', keys['Arts']: 'Arts'}
    assert f'hors fonds · {items["projet"]}' in section.points and 'validation' not in section.points
    k.write_memory(cfg, memory)
    r.write(cfg, [r.Entry(items['nouvelle'], r.MOVE, 'Psychologie/Perception', keys['Inbox'],
                            decision=r.ACCEPT)], b, set())

    # In Zotero, Perception is renamed and a Musées theme is created under Arts.
    _zotero(m, 'update collections set collectionName = ? where key = ?', 'Perception visuelle', keys['Perception'])
    museums = m.collection('Musées', keys['Arts'])
    b = m.read()
    section, _ = k.outline_check(b, cfg)
    assert section.points[f'renommé · {keys["Perception"]}'].endswith('Psychologie/Perception → Psychologie/Perception visuelle')
    assert f'créé · {museums}' in section.points

    s = k.track(b, cfg)
    assert '### Perception visuelle\n\nPerception humaine.\n\n## Arts' in s.text
    assert 'Arts visuels.\n\n### Musées\n\n# Concepts' in s.text
    k.apply_changes(b, cfg, s)
    assert f.load_tracking(cfg).collections and not f.check(cfg).errors
    assert {c.target for c in f.load_tracking(cfg).collections if c.key == keys['Perception']} == {'Psychologie/Perception visuelle'}
    assert r.load(cfg)[0].target == 'Psychologie/Perception visuelle'
    # Once followed, nothing left to report on these themes, except the definition to write.
    f.save(cfg, f.check(cfg))
    section, memory = k.outline_check(b, cfg)
    assert memory[keys['Perception']] == 'Psychologie/Perception visuelle' and memory[museums] == 'Arts/Musées'
    assert set(p for p in section.points if not p.startswith('hors fonds')) == {'sans définition · Arts/Musées'}


def test_move_and_delete_tracked(world, cfg):
    m, keys, items, b = world
    k.write_memory(cfg, k.outline_check(b, cfg)[1])
    _zotero(m, 'update collections set parentCollectionID = ? where key = ?', m.ids[keys['Psy']], keys['Arts'])
    _zotero(m, 'insert into deletedCollections (collectionID) values (?)', m.ids[keys['Perception']])
    b = m.read()
    s = k.track(b, cfg)
    assert s.lines == ['déplacé : Arts → Psychologie/Arts', 'retiré, avec ses sous-thèmes : Psychologie/Perception']
    assert s.text.endswith('## Psychologie\n\nEsprit et comportement.\n\n### Arts\n\nArts visuels.\n\n# Concepts\n')
    k.apply_changes(b, cfg, s)
    assert not f.check(cfg).errors
    assert keys['Perception'] not in {c.key for c in f.load_tracking(cfg).collections}


def test_titles_of_theme(world, cfg):
    m, keys, items, b = world
    report, n = k.titles(b, cfg, 'Psychologie')
    assert n == 1 and '## Psychologie/Perception' in report and 'Définition. Perception humaine.' in report
    assert 'The ecological approach to visual perception' in report


def test_comparison_in_english():
    before = {'chiffres': {'référence': 10}, 'points': {'Probable duplicates': ['A/B', 'C/D']}}
    sections = [Section('Probable duplicates', TO_REVIEW, '', points={'C/D': 'C / D', 'E/F': 'E / F'})]

    class B:
        items, attachments, notes, collections = [1] * 12, [], [], []
    with language('en'):
        snap = k.snapshot(sections, B)
        text = '\n'.join(k.evolution(sections, snap, before, date(2026, 10, 1)))
        assert '## Since the audit of 01/10/2026' in text and '12 items (+2)' in text
        assert '1. Probable duplicates, 1 new and 1 settled.' in text
        assert 'No audit from a previous day' in '\n'.join(k.no_comparison())
        assert k.outline_title() == 'Subjects outline'


def test_point_key_stays_french_and_is_shown_in_english(zotero):
    """The keys of the points are stored in the snapshots and compared between audits (D225): they stay French in
    an English library, only what is shown of them is English. A snapshot written in French keeps matching."""
    from zot_clean import audit, reader
    zotero.item('An undated paper', date='')
    b = reader.read(zotero.save())
    with language('en'):
        section = audit.metadata(b)
    key = next(p for p in section.points if p.startswith('sans année · '))
    assert section.points[key].startswith('no year: ') and section.summary.startswith('No year 1')
    assert not any('sans année' in d for d in section.details)
    before = {'chiffres': {}, 'points': {section.title: sorted(section.points)}}
    with language('en'):
        snap = k.snapshot([section], b)
        text = '\n'.join(k.evolution([section], snap, before, date(2026, 10, 1)))
    assert key in snap['points'][section.title] and 'No new or settled point.' in text
