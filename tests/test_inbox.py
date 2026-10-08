"""Inbox sort (D135), on an already filed synthetic library, the fake server and the fake sources."""

import itertools

import pytest

from fake_server import FakeServer
from fake_sources import FakeServices, crossref_work
from test_apply import write
from zot_clean import duplicates, subjects as f, inbox as i, reader, filing as r, sources
from zot_clean.apply import TRIAL, apply_plan
from zot_clean.config import Config
from zot_clean.lang import language

OUTLINE = """\
# Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.

## Arts

Arts visuels.

# Concepts
"""

ARTICLE = dict(publicationTitle='', volume='', issue='', pages='', ISSN='', language='')


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def fake():
    return FakeServices()


@pytest.fixture
def cfg(tmp_path, zotero):
    c = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    c.workspace.mkdir()
    c.method.projects = ['Cours']
    return c


class World:
    def __init__(self, zotero, server):
        self.zotero, self.server = zotero, server
        server._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, name, parent=None):
        key = self.server.collection(name, parent)
        self.ids[key] = self.zotero.collection(name, self.ids[parent] if parent else None, key=key)
        return key

    def item(self, title, *collections, author='Durand', **fields):
        key = self.server._key()
        self.zotero.item(title, authors=(author,), collections=tuple(self.ids[c] for c in collections), key=key,
                          **fields)
        self.server.add(title=title, key=key, collections=list(collections),
                             creators=[{'creatorType': 'author', 'lastName': author}], date='2020',
                             **(ARTICLE | fields))
        return key

    def read(self):
        self.zotero.sync(self.server.version)
        return reader.read(self.zotero.save())


@pytest.fixture
def world(zotero, server, cfg):
    m = World(zotero, server)
    k = {'Inbox': m.collection('Inbox'), 'Fonds': m.collection('Fonds'), 'Cours': m.collection('Cours')}
    k['Psy'] = m.collection('Psychologie', k['Fonds'])
    k['Perception'] = m.collection('Perception', k['Psy'])
    k['Arts'] = m.collection('Arts', k['Fonds'])
    k['L1'] = m.collection('Psy L1', k['Cours'])
    items = {
        'gibson': m.item('The ecological approach to visual perception', k['Perception'], author='Gibson'),
        'ancienne': m.item('Museum displays and their publics', k['Arts'], DOI='10.1111/musee'),
        'nouvelle': m.item('Perceptual learning revisited', k['Inbox'], author='Gibson', DOI='10.1111/appr'),
        'double': m.item('Museum displays and their publics', k['Inbox'], DOI='10.1111/musee'),
        'projet': m.item('Teaching perception to first-year students', k['L1']),
    }
    b = m.read()
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    _, tracking, _, _ = f.inventory(b, cfg)
    actions = {'Fonds/Psychologie': (f.THEME, 'Psychologie'), 'Fonds/Psychologie/Perception':
             (f.THEME, 'Psychologie/Perception'), 'Fonds/Arts': (f.THEME, 'Arts')}
    for c in tracking.collections:
        if c.path in actions:
            c.action, c.target = actions[c.path]
    f.write_tracking(cfg, tracking)
    check = f.check(cfg)
    assert not check.errors, check.errors
    f.save(cfg, check)
    return m, k, items, b


def services(cfg, fake):
    return sources.from_config(cfg, client_http=fake.client(), wait=lambda s: None)


def test_sorting_end_to_end(world, cfg, server, fake, zotero):
    m, k, items, b = world
    fake.add(doi='10.1111/appr', title='Perceptual learning revisited', authors=(('Gibson', 'Eleanor'),),
                 year=2020, volume='12', **{'container-title': ['Cognition']})
    fake.add(doi='10.1111/musee', title='Museum displays and their publics', authors=(('Durand', 'A'),),
                 year=2020)
    schema = reader.read_types(zotero.database)
    report, listing = i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
    assert {a.item.key for a in listing} == {items['nouvelle'], items['double'], items['projet']}
    assert "2 dans l'Inbox et 1 sans place dans le fonds" in report
    assert f"{items['ancienne']} / {items['double']}" in report or f"{items['double']} / {items['ancienne']}" in report
    assert 'thèmes voisins, même auteur : Psychologie/Perception (1)' in report
    assert 'zc subjects accept CLÉ=CHEMIN' in report and 'depuis' not in report
    # Pilot rehearsal: situation of the references outside the Inbox, absence of a neighboring theme stated.
    assert 'dont 0 hors de toute collection, 1 dans un projet.' in report
    assert ' · reste dans son projet' in report
    assert (cfg.tracking / r.FILE).read_text(encoding='utf-8').startswith(r.header())

    # Judgment: merge of the duplicate, filing of the new one and of the project one.
    entries = duplicates.load_tracking(cfg)
    for e in entries:
        e.decision, e.keep = duplicates.MERGE, items['ancienne']
    duplicates.write_tracking(cfg, entries, b)
    r.write(cfg, [r.Entry(items['nouvelle'], r.MOVE, 'Psychologie/Perception', k['Inbox'], decision=r.ACCEPT),
                   r.Entry(items['projet'], r.ADD, 'Arts', decision=r.ACCEPT)], b, set())

    plan, report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
    assert plan.step == 'inbox' and [g.id for g in plan.groups][0] == 'fusion-1'
    by_id = {g.id: g for g in plan.groups}
    new = by_id[items['nouvelle']].operations
    assert [op.rank for op in new] == [1, 2]
    assert new[0].after['volume'] == '12' and new[1].after['collections'] == [k['Perception']]
    # The item kept by the merge does not receive the Inbox of the absorbed item.
    kept_item = next(op for op in by_id['fusion-1'].operations if op.key == items['ancienne'])
    assert 'collections' not in kept_item.after
    assert 'entre dans Fonds/Psychologie/Perception' in report and 'quitte Inbox' in report

    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert not outcome.conflicts and not outcome.errors and outcome.remaining == 0
    assert server.all_items[items['nouvelle']]['collections'] == [k['Perception']]
    assert server.all_items[items['nouvelle']]['volume'] == '12'
    assert server.all_items[items['projet']]['collections'] == [k['L1'], k['Arts']]
    assert server.all_items[items['double']]['deleted'] is True
    assert server.all_items[items['ancienne']]['collections'] == [k['Arts']]


def test_reference_outside_any_collection(world, cfg, server, fake, zotero):
    """A reference without a collection is described as « hors de toute collection », not « dans un projet », and the
    absence of a neighboring theme is stated (pilot rehearsal). Without a decision, the plan lists it among those
    that remain."""
    m, k, items, _ = world
    free = m.item('Un texte isolé', author='Personne')
    b = m.read()
    schema = reader.read_types(zotero.database)
    report, _ = i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
    assert 'dont 1 hors de toute collection, 1 dans un projet.' in report
    line = report.split(f'- {free} · ', 1)[1]
    assert 'dans aucune collection\n  - aucun thème voisin trouvé' in line
    _, report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
    assert 'sans place dans le fonds, sans décision de rangement acceptée' in report and free in report
    # Seen and left outside the subject collections by decision (D176), it is no longer presented, only counted.
    r.leave_out(b, cfg, [free])
    report, listing = i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
    assert free not in {x.item.key for x in listing} and f'- {free} · ' not in report
    assert '1 autre référence laissée hors du fonds par décision' in report
    _, report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
    assert free not in report


def _pdf(zotero, server, parent_id, parent, name, title):
    key = server._key()
    zotero.pdf(parent_id, name, name.encode(), key=key, title=title)
    server.add('attachment', key=key, parentItem=parent, linkMode='imported_file', filename=name, title=title,
                    contentType='application/pdf')
    return key


def test_filename_follows_sorting_plan(world, cfg, server, fake, zotero):
    # D149: the completed date and the merge change the name of the main file, computed from the plan.
    m, k, items, b = world
    no_date = server._key()
    iid = zotero.item('Seeing affordances', authors=('Gibson',), date='', collections=(m.ids[k['Inbox']],),
                       key=no_date, DOI='10.1111/aff')
    server.add(title='Seeing affordances', key=no_date, collections=[k['Inbox']], date='', DOI='10.1111/aff',
                    creators=[{'creatorType': 'author', 'lastName': 'Gibson'}], **ARTICLE)
    ids = b.by_key()
    pdf = _pdf(zotero, server, iid, no_date, 'Gibson - Seeing affordances.pdf', 'Gibson - Seeing affordances.pdf')
    scan = _pdf(zotero, server, ids[items['double']].id, items['double'], 'scan.pdf', 'PDF')
    # A name lagging behind on an item whose plan only changes the volume stays as it is.
    stale = _pdf(zotero, server, ids[items['nouvelle']].id, items['nouvelle'], 'vieux.pdf', 'PDF')
    b = m.read()
    fake.add(doi='10.1111/aff', title='Seeing affordances', authors=(('Gibson', 'James'),), year=2021)
    fake.add(doi='10.1111/appr', title='Perceptual learning revisited', authors=(('Gibson', 'Eleanor'),),
                 year=2020, volume='12')
    fake.add(doi='10.1111/musee', title='Museum displays and their publics', authors=(('Durand', 'A'),),
                 year=2020)
    schema = reader.read_types(zotero.database)
    i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
    entries = duplicates.load_tracking(cfg)
    for e in entries:
        e.decision, e.keep = duplicates.MERGE, items['ancienne']
    duplicates.write_tracking(cfg, entries, b)

    plan, report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
    by_id = {g.id: g for g in plan.groups}
    op = next(op for op in by_id[no_date].operations if op.key == pdf)
    assert op.rank == i.NAME_RANK > 1
    assert op.after == {'filename': 'Gibson - 2021 - Seeing affordances.pdf', 'title': 'PDF'}
    # The PDF of the absorbed item becomes the main file of the kept item, which had none.
    op = next(op for op in by_id['fusion-1'].operations if op.key == scan and op.rank == i.NAME_RANK)
    assert op.after == {'filename': 'Durand - 2020 - Museum displays and their publics.pdf'}
    assert stale not in {op.key for g in plan.groups for op in g.operations}
    assert '« Gibson - Seeing affordances.pdf » → « Gibson - 2021 - Seeing affordances.pdf »' in report

    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert not outcome.conflicts and not outcome.errors and outcome.remaining == 0
    assert server.all_items[pdf]['filename'] == 'Gibson - 2021 - Seeing affordances.pdf'
    assert server.all_items[scan]['parentItem'] == items['ancienne']
    assert server.all_items[scan]['filename'] == 'Durand - 2020 - Museum displays and their publics.pdf'


def test_cases_of_other_items_kept(world, cfg, server, fake, zotero):
    # Limiting the review to the references to sort must not erase the pending cases of the other items.
    from zot_clean import metadata as md
    m, k, items, b = world
    other = md.Case(items['gibson'], md.IDENTIFIERS, 'doi_manquant', [md.Proposal({'DOI': '10.1/x'}, 'crossref')])
    md.write_tracking(cfg, [other], b)
    i.prepare(b, cfg, services(cfg, fake), server.client(), reader.read_types(zotero.database))
    assert items['gibson'] in {c.key for c in md.load_tracking(cfg)}


def test_without_outline(zotero, server, cfg, fake):
    m = World(zotero, server)
    inbox = m.collection('Inbox')
    m.item('Une nouveauté', inbox)
    b = m.read()
    report, listing = i.prepare(b, cfg, services(cfg, fake), server.client(), reader.read_types(zotero.database))
    assert len(listing) == 1 and "plan.md n'existe pas encore" in report


def test_sorting_tags_follow_rules(zotero, server, cfg, fake):
    # D155: automatic tags removed according to the accepted rule, new manual tag only reported.
    from zot_clean import tags as tg
    m = World(zotero, server)
    inbox = m.collection('Inbox')
    key = m.server._key()
    zotero.item('Une nouveauté', collections=(m.ids[inbox],), key=key, tags=(('Neurosciences', 1), 'mon idée'))
    server.add(title='Une nouveauté', key=key, collections=[inbox], date='2020',
                    creators=[{'creatorType': 'author', 'lastName': 'Durand'}],
                    tags=[{'tag': 'Neurosciences', 'type': 1}, {'tag': 'mon idée'}], **ARTICLE)
    b = m.read()
    s = tg.Tracking(automatic=tg.ACCEPT)
    tg.write(cfg, s, b)
    schema = reader.read_types(zotero.database)
    report, _ = i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
    assert 'tags hors familles, sans règle : mon idée' in report
    plan, report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
    op = next(op for g in plan.groups for op in g.operations if op.rank == 3)
    assert op.key == key and op.after['tags'] == [{'tag': 'mon idée'}]
    assert '− Neurosciences' in report


# --- Citation keys (D146) ------------------------------------------------------

def set_key(zotero, server, key, citation_key, date_added=None):
    """Citation key set in the local database and on the server, local date added changed if needed."""
    iid = zotero.db.execute('select itemID from items where key = ?', (key,)).fetchone()[0]
    zotero._fields(iid, {'citationKey': citation_key})
    if date_added:
        zotero.db.execute('update items set dateAdded = ? where itemID = ?', (date_added, iid))
    server.all_items[key]['citationKey'] = citation_key


def test_citation_keys_of_sorting(world, cfg, server, fake, zotero):
    m, k, items, _ = world
    (zotero.folder / 'better-bibtex').mkdir()  # Better BibTeX active, detected by its folder
    fake.add(doi='10.1111/appr', title='Perceptual learning revisited', authors=(('Gibson', 'Eleanor'),),
                 year=2020, volume='12', **{'container-title': ['Cognition']})
    # The new reference received the key of an older item. The project one, older than the subject-collection item
    # whose key it shares, keeps it: the other item receives the suffix.
    set_key(zotero, server, items['gibson'], 'gibson2020')
    set_key(zotero, server, items['nouvelle'], 'Gibson2020')
    set_key(zotero, server, items['projet'], 'durand2020', date_added='2010-01-01 00:00:00')
    set_key(zotero, server, items['ancienne'], 'durand2020')
    b = m.read()
    schema = reader.read_types(zotero.database)

    report, _ = i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
    lines = {line.split(' · ')[0][2:]: line for line in report.splitlines() if line.startswith('- ')}
    assert 'sans clé de citation' in lines[items['double']]
    assert 'sans clé de citation' not in lines[items['nouvelle']] and 'Better BibTeX › Fill' in report

    plan, report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
    by_id = {g.id: g for g in plan.groups}
    # The key of the sorted reference joins its fields, in a single operation at rank 1.
    rank1 = [op for op in by_id[items['nouvelle']].operations if op.rank == 1]
    assert len(rank1) == 1 and rank1[0].after['volume'] == '12' and rank1[0].after['citationKey'] == 'gibson2020a'
    # The other item of the double is told apart in the group of the sorted reference.
    op = next(op for op in by_id[items['projet']].operations if op.key == items['ancienne'])
    assert op.rank == 1 and op.after == {'citationKey': 'durand2020a'}
    assert f"champs ({items['ancienne']}) citationKey = 'durand2020a'" in report
    assert items['gibson'] not in by_id

    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert not outcome.conflicts and not outcome.errors
    assert server.all_items[items['nouvelle']]['citationKey'] == 'gibson2020a'
    assert server.all_items[items['ancienne']]['citationKey'] == 'durand2020a'
    assert server.all_items[items['gibson']]['citationKey'] == 'gibson2020'


def test_sorting_without_bbt_does_not_report_keys(world, cfg, server, fake, zotero):
    m, k, items, b = world
    report, _ = i.prepare(b, cfg, services(cfg, fake), server.client(), reader.read_types(zotero.database))
    assert 'sans clé de citation' not in report


def test_key_shared_with_confidential_item(world, cfg, server, fake, zotero):
    # D126, D188: the sorted reference receives the key of an older confidential item. The sort report does not
    # show the key, which can reveal the subject of the item.
    m, k, items, _ = world
    (zotero.folder / 'better-bibtex').mkdir()
    set_key(zotero, server, items['projet'], 'secret2020', date_added='2010-01-01 00:00:00')
    set_key(zotero, server, items['nouvelle'], 'secret2020')
    zotero.tags(zotero.db.execute('select itemID from items where key = ?', (items['projet'],)).fetchone()[0],
                ['_privé'])
    server.all_items[items['projet']]['tags'] = [{'tag': '_privé'}]
    plan, report = i.make_plan(m.read(), cfg, services(cfg, fake), server.client(), reader.read_types(zotero.database))
    ops = [op for g in plan.groups for op in g.operations if op.key == items['nouvelle']]
    assert any(op.after.get('citationKey') == 'secret2020a' for op in ops)
    assert 'secret2020' not in report


def test_texts_in_english(world, cfg, server, fake, zotero):
    m, k, items, b = world
    fake.add(doi='10.1111/appr', title='Perceptual learning revisited', authors=(('Gibson', 'Eleanor'),),
             year=2020, volume='12', **{'container-title': ['Cognition']})
    fake.add(doi='10.1111/musee', title='Museum displays and their publics', authors=(('Durand', 'A'),), year=2020)
    schema = reader.read_types(zotero.database)
    with language('en'):
        report, listing = i.prepare(b, cfg, services(cfg, fake), server.client(), schema)
        assert '# Inbox sorting' in report and '2 in the Inbox and 1 without a place in the subjects' in report
        assert 'neighbouring themes, same author: Psychologie/Perception (1)' in report
        assert 'zc subjects accept KEY=PATH' in report and '**Duplicates.**' in report
        plan, plan_report = i.make_plan(b, cfg, services(cfg, fake), server.client(), schema)
        assert '# Inbox sorting' in plan_report and 'item(s) to modify' not in plan_report
        assert 'to modify in' in plan_report
