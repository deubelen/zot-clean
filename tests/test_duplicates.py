import copy
import itertools
import tomllib

import pytest

from fake_server import FakeServer
from test_apply import write
from zot_clean import undo, audit, duplicates as d, privacy, reader, plans
from zot_clean.apply import TRIAL, apply_plan
from zot_clean.config import Config


class Double:
    """Items created both in the synthetic database and on the fake server, with the same key."""

    def __init__(self, zotero, server):
        self.zotero, self.server = zotero, server
        server._n = itertools.count(10 ** 6)
        self.ids = {}

    def item(self, title, type_='journalArticle', authors=('Durand',), date='2020', date_added='2020-01-01', **fields):
        key = self.server._key()
        self.ids[key] = self.zotero.item(title, type_, authors, date, key=key, **fields)
        self.server.add(type_, key=key, title=title, date=date, dateAdded=f'{date_added}T00:00:00Z',
                             creators=[{'creatorType': 'author', 'lastName': a, 'firstName': 'A.'} for a in authors],
                             **{k: v for k, v in fields.items() if k in ('DOI', 'ISBN', 'publicationTitle')})
        return key

    def pdf(self, parent, name, content=b'%PDF identique', annotated=False, note=''):
        """`note`: note of the attachment itself (`note` field of the `attachment` item)."""
        key = self.server._key()
        iid = self.zotero.pdf(self.ids[parent], name, content, key=key, note=note)
        if annotated:
            self.zotero.annotation(iid)
        self.server.add('attachment', key=key, parentItem=parent, title=name, linkMode='imported_file',
                             note=note)
        return key

    def note(self, parent):
        key = self.server._key()
        self.server.add('note', key=key, parentItem=parent, note='<p>Ma note</p>')
        return key

    def library(self):
        return reader.read(self.zotero.save())


def accept_certain(cfg, b):
    """The « sûr » groups accepted in bulk, as `zc doublons accepter --surs` does (D49)."""
    entries = d.load_tracking(cfg)
    d.decide(entries, True)
    d.write_tracking(cfg, entries, b)


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def double(zotero, server):
    return Double(zotero, server)


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


def test_find_grades_and_keeps_decisions(double, cfg):
    a = double.item('Radical embodied cognitive science', DOI='10.1/rad')
    b = double.item('Radical Embodied Cognitive Science', DOI='10.1/RAD')
    c = double.item('La morale antique', type_='book', authors=('Robin',), date='1938', ISBN='2-07-036822-X')
    e = double.item('La morale antique, nouvelle édition', type_='book', authors=('Robin',), date='1963',
                     ISBN='978-2-07-036822-8')
    entries = d.find(double.library(), cfg)
    grades = {frozenset(x.keys): x.grade for x in entries}
    assert grades == {frozenset({a, b}): d.CERTAIN, frozenset({c, e}): d.TO_JUDGE}
    raw = tomllib.loads((cfg.tracking / d.FILE).read_text(encoding='utf-8'))
    assert len(raw['groupe']) == 2

    # The user judges the group of distinct editions and decides to merge the other one.
    text = (cfg.tracking / d.FILE).read_text(encoding='utf-8')
    text = text.replace('classe = "à juger"\ndecision = ""', 'classe = "à juger"\ndecision = "distinct"')
    text = text.replace('classe = "sûr"\ndecision = ""', 'classe = "sûr"\ndecision = "fusionner"')
    (cfg.tracking / d.FILE).write_text(text, encoding='utf-8')
    entries = d.find(double.library(), cfg)
    decisions = {frozenset(x.keys): x.decision for x in entries}
    assert decisions == {frozenset({a, b}): d.MERGE, frozenset({c, e}): d.DISTINCT}

    b_ = double.library()
    section = audit.duplicates(b_, cfg)
    assert section.summary.startswith('1 groupe')


def test_zotero_style_merge_then_undo(double, server, cfg):
    keeper = double.item('Perceptual learning of categorical colour', publicationTitle='JEP', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    kept_pdf = double.pdf(keeper, 'a.pdf')
    for n in ('e', 'f'):
        double.pdf(keeper, f'{n}.pdf', content=f'%PDF {n}'.encode())
    identical_pdf = double.pdf(absorbed, 'b.pdf')
    annotated_pdf = double.pdf(absorbed, 'c.pdf', annotated=True)
    other_pdf = double.pdf(absorbed, 'd.pdf', content=b'%PDF autre')
    note = double.note(absorbed)
    server.all_items[keeper]['collections'] = ['COLLAAAA']
    server.all_items[absorbed].update(collections=['COLLBBBB'], tags=[{'tag': '#norme'}])
    before = {k: dict(v) for k, v in server.all_items.items()}

    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    assert len(plan.groups) == 1 and plan.step == 'doublons'
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[identical_pdf].after == {'deleted': True}
    assert ops[annotated_pdf].after == {'parentItem': keeper} and ops[other_pdf].after == {'parentItem': keeper}
    assert ops[note].after == {'parentItem': keeper}
    assert 'Ma note' not in ops[note].nature  # D191
    assert ops[keeper].after['DOI'] == '10.1/col' and 'publicationTitle' not in ops[keeper].after
    assert ops[keeper].after['collections'] == ['COLLAAAA', 'COLLBBBB']
    assert ops[keeper].after['relations'] == {'dc:replaces': [server.client().uri(absorbed)]}
    assert ops[absorbed].after == {'deleted': True} and ops[absorbed].rank == 2
    assert kept_pdf not in ops
    assert 'identique' in report and 'gardée pour ses annotations ou notes' in ops[annotated_pdf].nature
    assert 'Article de revue' in report and 'journalArticle' not in report

    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['1']
    assert server.all_items[absorbed]['deleted'] and server.all_items[note]['parentItem'] == keeper
    assert server.all_items[keeper]['tags'] == [{'tag': '#norme'}]

    plan_a, report_a = undo.make_plan([outcome.journal], server.client(), set())
    assert 'Ma note' not in report_a
    apply_plan(plan_a, plans.write(plan_a, cfg.plans, ''), server.client(), cfg, TRIAL)
    for k, v in before.items():
        assert {c: x for c, x in server.all_items[k].items() if c != 'version'} == \
               {c: x for c, x in v.items() if c != 'version'}


def test_same_doi_different_titles_to_judge(double, server, cfg):
    """The same DOI is not enough when the titles differ (erratum entered with the article's DOI, chapter
    imported with the book's): the group is « à juger », and nothing merges without a decision (D49)."""
    a = double.item('Perceptual learning of categorical colour', DOI='10.1/col')
    b_ = double.item('Erratum to: Perceptual learning of categorical colour', DOI='10.1/col')
    c = double.item('Language and thought', DOI='10.1/livre', authors=('Vygotski',))
    e = double.item('Thought and word', DOI='10.1/livre', authors=('Vygotski',))
    f = double.item('Radical embodied cognitive science', DOI='10.1/rad', authors=('Chemero',))
    g = double.item('Radical Embodied Cognitive Science.', DOI='10.1/RAD', authors=('Chemero',), date='2009')
    b = double.library()
    grades = {frozenset(x.keys): x.grade for x in d.find(b, cfg)}
    assert grades == {frozenset({a, b_}): d.TO_JUDGE, frozenset({c, e}): d.TO_JUDGE, frozenset({f, g}): d.CERTAIN}
    # Without a decision, even a « sûr » group does not merge.
    plan, report = d.make_plan(cfg, server.client(), b)
    assert plan.groups == [] and '3 groupe(s) restent à juger' in report
    accept_certain(cfg, b)
    plan, _ = d.make_plan(cfg, server.client(), b)
    assert [sorted(op.key for op in g.operations) for g in plan.groups] == [sorted([f, g])]


def test_make_plan_no_longer_has_certain_option(double, cfg, capsys):
    """`zc doublons planifier --surs` used to merge « sûr » groups without a decision: the option no longer exists,
    the decision goes through `zc doublons accepter --surs`."""
    import inspect
    from zot_clean.cli import main
    assert list(inspect.signature(d.make_plan).parameters) == ['cfg', 'client', 'b']
    with pytest.raises(SystemExit) as output:
        main(['doublons', 'planifier', '--surs'])
    assert output.value.code == 2 and '--surs' in capsys.readouterr().err


def test_identical_copy_with_attachment_note_reattached(double, server, cfg):
    """D51: an identical copy that carries a note (that of the attachment itself) is not trashed, it is attached as
    an annotated copy, without the note text leaking out (D191)."""
    keeper = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    double.pdf(keeper, 'a.pdf')
    double.pdf(keeper, 'e.pdf', content=b'%PDF e')
    with_note = double.pdf(absorbed, 'b.pdf', note='<p>Chapitre trois à relire</p>')
    no_note = double.pdf(absorbed, 'c.pdf', note='')
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[with_note].after == {'parentItem': keeper} and 'gardée pour sa note' in ops[with_note].nature
    assert ops[no_note].after == {'deleted': True}
    assert 'Chapitre trois' not in report and 'Chapitre trois' not in plans.write(plan, cfg.plans, report).read_text(
        encoding='utf-8')


def test_natures_and_description_in_english(double, server, cfg):
    """The natures and the description of a merge plan are only shown (reports, `zc apply`), never read back: in an
    English library they are English (pilot bench). The group title is the title of the kept item."""
    from zot_clean.lang import language
    keeper = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    double.pdf(keeper, 'a.pdf')
    double.pdf(keeper, 'e.pdf', content=b'%PDF e')
    with_note = double.pdf(absorbed, 'b.pdf', note='<p>To read again</p>')
    identical = double.pdf(absorbed, 'c.pdf', note='')
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    with language('en'):
        plan, report = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert plan.description == 'Merge of 1 group(s) of duplicates.'
    assert plan.groups[0].title == 'Perceptual learning of categorical colour'
    assert ops[keeper].nature == 'complete the kept item' and ops[absorbed].nature == 'absorbed item to the trash'
    assert ops[with_note].nature.startswith('move the attachment') and \
        ops[with_note].nature.endswith('(identical to a copy already there, kept for its attachment note)')
    assert ops[identical].nature.startswith('identical attachment to the trash')
    for french in ('fiche', 'pièce jointe', 'rattacher', 'compléter', 'corbeille', 'Fusion'):
        assert french not in report and not any(french in op.nature for op in ops.values())
    # The missing-PDF warning recognizes the completed item in either language.
    assert d.fill_in() == 'compléter la fiche conservée'


def test_links_of_absorbed_items_carried_over_like_zotero(double, server, cfg):
    """Like Zotero's `moveRelations`: the relations of an absorbed item move to the kept item, except a link to
    itself, the absorbed item loses its `dc:replaces`, and a linked item that pointed to the absorbed one now
    points to the kept item. Undo puts everything back."""
    keeper = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    related_item = double.item('Colour categories in infancy', authors=('Franklin',), tags=('_privé',))
    other = double.item('Une fiche sans rapport', authors=('Autre',))
    u = server.client().uri
    group, old_uri = 'http://zotero.org/groups/77/items/ABCD2345', u('VIEILLE2')
    server.all_items[absorbed]['relations'] = {'dc:relation': [u(related_item), u(keeper)], 'owl:sameAs': group,
                                               'dc:replaces': old_uri}
    server.all_items[keeper]['relations'] = {'dc:relation': u(absorbed)}
    server.all_items[related_item]['relations'] = {'dc:relation': [u(absorbed), u(other)]}
    server.all_items[other]['relations'] = {'dc:relation': u(related_item)}
    before = copy.deepcopy(server.all_items)

    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    rel = lambda v: plans.normalize('relations', v)
    # The link from the kept item to the absorbed one stays, as in Zotero, and no link to itself.
    assert rel(ops[keeper].after['relations']) == rel({'dc:relation': [u(absorbed), u(related_item)], 'owl:sameAs': [group],
                                                      'dc:replaces': [old_uri, u(absorbed)]})
    assert ops[related_item].rank == 1 and rel(ops[related_item].before['relations']) == rel(before[related_item]['relations'])
    assert rel(ops[related_item].after['relations']) == rel({'dc:relation': [u(keeper), u(other)]})
    assert other not in ops
    assert ops[absorbed].rank == 2 and ops[absorbed].after == {
        'deleted': True, 'relations': {'dc:relation': [u(related_item), u(keeper)], 'owl:sameAs': [group]}}
    # The linked item is confidential: its key only.
    assert f'fiche liée {related_item} {privacy.mask()}' in report and 'infancy' not in report

    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['1']
    assert rel(server.all_items[related_item]['relations']) == rel({'dc:relation': [u(keeper), u(other)]})
    assert server.all_items[absorbed]['deleted'] and 'dc:replaces' not in server.all_items[absorbed]['relations']

    plan_a, _ = undo.make_plan([outcome.journal], server.client(), set())
    apply_plan(plan_a, plans.write(plan_a, cfg.plans, ''), server.client(), cfg, TRIAL)
    for k, v in before.items():
        current = server.all_items[k]
        assert {c: x for c, x in current.items() if c not in ('version', 'relations')} == \
               {c: x for c, x in v.items() if c not in ('version', 'relations')}
        assert rel(current['relations']) == rel(v['relations'])


def test_links_between_two_groups_of_same_plan(double, server, cfg):
    """Two duplicates linked to each other, each in its own group: like two successive merges in Zotero, the two
    kept items end up linked to each other. The second group starts from the state left by the first."""
    a2 = double.item('Alpha, a study of colour', DOI='10.1/alpha', date_added='2014-01-01')
    a1 = double.item('Alpha, a study of colour', DOI='10.1/alpha', date_added='2020-01-01')
    b2 = double.item('Beta, a study of form', DOI='10.1/beta', date_added='2014-01-01')
    b1 = double.item('Beta, a study of form', DOI='10.1/beta', date_added='2020-01-01')
    u = server.client().uri
    server.all_items[a1]['relations'] = {'dc:relation': [u(b1)]}
    server.all_items[b1]['relations'] = {'dc:relation': [u(a1)]}
    before = copy.deepcopy(server.all_items)
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, _ = d.make_plan(cfg, server.client(), b)
    assert [g.title for g in plan.groups] == ['Alpha, a study of colour', 'Beta, a study of form']
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert outcome.done == ['1', '2'] and not outcome.conflicts
    rel = lambda k: plans.normalize('relations', server.all_items[k]['relations'])
    assert rel(a2) == {'dc:relation': [u(b2)], 'dc:replaces': [u(a1)]}
    assert rel(b2) == {'dc:relation': [u(a2)], 'dc:replaces': [u(b1)]}

    plan_a, _ = undo.make_plan([outcome.journal], server.client(), set())
    outcome_a = apply_plan(plan_a, plans.write(plan_a, cfg.plans, ''), server.client(), cfg, TRIAL)
    assert not outcome_a.conflicts and not outcome_a.partials
    for k, v in before.items():
        assert rel(k) == plans.normalize('relations', v['relations'])
        assert bool(server.all_items[k].get('deleted')) == bool(v.get('deleted'))


def test_different_types_skipped(double, server, cfg):
    double.item('Self-organization in communicating groups', DOI='10.1/so')
    double.item('Self-organization in communicating groups', type_='conferencePaper', DOI='10.1/so')
    b = double.library()
    entries = d.find(b, cfg)
    assert entries[0].grade == d.TO_JUDGE
    text = (cfg.tracking / d.FILE).read_text(encoding='utf-8').replace('decision = ""', 'decision = "fusionner"')
    (cfg.tracking / d.FILE).write_text(text, encoding='utf-8')
    plan, report = d.make_plan(cfg, server.client(), b)
    assert plan.groups == [] and 'types différents' in report


def test_keep_and_force(double, server, cfg):
    a = double.item('La morale antique de Robin', date='1938', date_added='2010-01-01')
    b = double.item('La morale antique de Robin', date='1938', date_added='2020-01-01')
    server.all_items[b]['extra'] = 'OCLC: 1'
    lib = double.library()
    d.find(lib, cfg)
    text = (cfg.tracking / d.FILE).read_text(encoding='utf-8')
    text = text.replace('decision = ""', 'decision = "fusionner"').replace('conserver = ""', f'conserver = "{b}"')
    text = text.replace('forcer = {  }', 'forcer = { "date" = "1938, rééd. 1963" }')
    (cfg.tracking / d.FILE).write_text(text, encoding='utf-8')
    plan, report = d.make_plan(cfg, server.client(), lib)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[b].rank == 1 and ops[b].after['date'] == '1938, rééd. 1963'
    assert ops[a].after == {'deleted': True}


def test_items_sharing_a_pdf(double, cfg):
    """Two items with nothing in common but their PDF are proposed, « à juger » (D125)."""
    a = double.item('Paint and Be Happy', authors=('Grant',), date='2011')
    b_ = double.item('Loser wins', authors=('Ardery',), date='1997')
    c = double.item('Sans rapport', authors=('Autre',), date='2000')
    double.pdf(a, 'grant.pdf', b'%PDF grant')
    double.pdf(b_, 'grant.pdf', b'%PDF grant')
    double.pdf(c, 'autre.pdf', b'%PDF autre')
    entries = d.find(double.library(), cfg)
    assert [(sorted(e.keys), e.grade) for e in entries] == [(sorted([a, b_]), d.TO_JUDGE)]


def test_confidential_items_hidden(double, server, cfg):
    keeper = double.item('Mon dossier médical', DOI='10.1/med', publicationTitle='JEP', tags=('_privé',))
    absorbed = double.item('Mon dossier médical', DOI='10.1/med', publicationTitle='Autre revue')
    double.pdf(absorbed, 'Mon dossier médical.pdf', content=b'%PDF autre')
    b = double.library()
    d.find(b, cfg)
    assert 'médical' not in (cfg.tracking / d.FILE).read_text(encoding='utf-8')
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    assert len(plan.groups) == 1 and plan.groups[0].title == '(fiche confidentielle)'
    path = plans.write(plan, cfg.plans, report)
    for text in (report, path.read_text(encoding='utf-8')):
        assert 'médical' not in text and 'Autre revue' not in report


def test_citation_key_of_absorbed_item_reported(double, server, cfg):
    """Two merged items that each have a key: the report says which one disappears (D146)."""
    keeper = double.item('Embodied cognition', DOI='10.1/emb', date_added='2014-01-01')
    absorbed = double.item('Embodied cognition', DOI='10.1/emb', date_added='2020-01-01')
    server.all_items[keeper]['citationKey'] = 'durandEmbodied2020'
    server.all_items[absorbed]['citationKey'] = 'durandEmbodied2020a'
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    assert f'clé de citation « durandEmbodied2020a » de {absorbed} qui disparaît' in report
    assert 'gardant « durandEmbodied2020 »' in report
    # Flagged separately, and not among the other differing values.
    assert '  - citationKey' not in report

    # Kept item without a key: it receives the absorbed item's key, nothing disappears.
    server.all_items[keeper]['citationKey'] = ''  # the API returns the field empty
    plan, report = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[keeper].after['citationKey'] == 'durandEmbodied2020a' and 'qui disparaît' not in report



def test_kept_item_takes_key_without_suffix(double, server, cfg):
    """The kept item carries the key suffixed by BBT, the absorbed one the base key: the kept item takes the base
    key, the most cited, and the report says which one disappears (pilot rehearsal, Özgen 2002)."""
    keeper = double.item('Embodied cognition', DOI='10.1/emb', date_added='2014-01-01')
    absorbed = double.item('Embodied cognition', DOI='10.1/emb', date_added='2020-01-01')
    server.all_items[keeper]['citationKey'] = 'durandEmbodied2020a'
    server.all_items[absorbed]['citationKey'] = 'durandEmbodied2020'
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[keeper].after['citationKey'] == 'durandEmbodied2020'
    assert f'clé de citation « durandEmbodied2020a » de {keeper} remplacée par « durandEmbodied2020 »' in report
    assert 'qui disparaît' not in report

def test_citation_key_hidden_for_confidential_item(double, server, cfg):
    keeper = double.item('Mon dossier', DOI='10.1/sec', date_added='2014-01-01', tags=('_privé',))
    absorbed = double.item('Mon dossier', DOI='10.1/sec', date_added='2020-01-01')
    server.all_items[keeper]['citationKey'] = 'moiDossier2020'
    server.all_items[absorbed]['citationKey'] = 'moiDossier2020a'
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    _, report = d.make_plan(cfg, server.client(), b)
    assert f'clé de citation de {absorbed} qui disparaît' in report and 'Dossier2020' not in report


def test_missing_pdfs_reported_in_plan(double, server, cfg):
    """D168: without the file, an identical copy is attached, and the report says so."""
    keeper = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    double.pdf(keeper, 'a.pdf', None)
    copy = double.pdf(absorbed, 'a.pdf', None)
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, report = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[copy].after == {'parentItem': keeper}
    assert '**Attention.** 2 PDF absents du disque' in report and 'rattachée à la fiche conservée' in report
    assert d.warning(b, cfg, plan).startswith('2 PDF absents')


def test_group_added_by_hand_kept(double, cfg):
    """A group to merge that zc does not detect stays in the file as long as its items exist."""
    a = double.item('Un article sous deux titres', authors=('Leroy',), date='2004')
    b_ = double.item('Article dont le titre diffère', authors=('Leroy',), date='2004')
    cfg.tracking.mkdir(parents=True)
    (cfg.tracking / d.FILE).write_text(f'[[groupe]]\ncles = ["{a}", "{b_}"]\ndecision = "fusionner"\n'
                                       f'conserver = "{a}"\n', encoding='utf-8')
    entries = d.find(double.library(), cfg)
    assert [(e.keys, e.decision, e.keep) for e in entries] == [([a, b_], d.MERGE, a)]
    double.zotero.trash(double.ids[b_])
    assert d.find(double.library(), cfg) == []


def test_decisions_by_command(double, cfg, monkeypatch, capsys):
    """D177: groups are decided by command, each designated by the key of one of its items. Only the groups still
    « à juger » change, and the file keeps its comments."""
    from zot_clean import api
    from zot_clean.cli import main
    a = double.item('Radical embodied cognitive science', DOI='10.1/rad')
    b = double.item('Radical Embodied Cognitive Science', DOI='10.1/RAD')
    f = double.item('Sensorimotor theory', DOI='10.1/sens', authors=('Noë',))
    g = double.item('Sensorimotor Theory', DOI='10.1/SENS', authors=('Noë',))
    c = double.item('La morale antique', type_='book', authors=('Robin',), date='1938', ISBN='2-07-036822-X')
    e = double.item('La morale antique, nouvelle édition', type_='book', authors=('Robin',), date='1963',
                     ISBN='978-2-07-036822-8')
    entries = d.find(double.library(), cfg)
    with pytest.raises(SystemExit, match='Aucun groupe de doublons.toml ne contient ZZZZZZZZ'):
        d.decide(entries, to_merge=['ZZZZZZZZ'])
    with pytest.raises(SystemExit, match='Une seule fiche conservée'):
        d.decide(entries, keep=[a, b])
    assert d.decide(entries, distinct=[c], reason='éditions différentes') == (0, 1, 0)
    assert d.decide(entries, True, keep=[b], except_=[f]) == (1, 0, 0)
    by_group = {frozenset(x.keys): x for x in entries}
    assert (by_group[frozenset({a, b})].decision, by_group[frozenset({a, b})].keep) == (d.MERGE, b)
    assert by_group[frozenset({f, g})].decision == ''
    assert (by_group[frozenset({c, e})].decision, by_group[frozenset({c, e})].reason) == (
        d.DISTINCT, 'éditions différentes')
    with pytest.raises(SystemExit, match='déjà décidé'):
        d.decide(entries, to_merge=[e])

    # Through the command line.
    cfg.workspace.mkdir(exist_ok=True)
    (cfg.workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n',
                                                     encoding='utf-8')

    def no_key(cfg):
        raise SystemExit('pas de clé')
    monkeypatch.setattr(api, 'from_config', no_key)
    folder = ['--workspace', str(cfg.workspace)]
    assert main(['duplicates', 'reject', c.lower(), *folder]) == 0
    assert 'doublons.toml : 1 groupe jugé distinct. Lancer' in capsys.readouterr().out
    assert main(['duplicates', 'accept', '--certain', '--except', f, *folder]) == 0
    capsys.readouterr()
    # The counts are those of the command, not the totals of the file (pilot bench), in the library's language.
    (cfg.workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n'
                                               '[methode]\nlangue = "en"\n', encoding='utf-8')
    assert main(['duplicates', 'accept', g, *folder]) == 0
    out = capsys.readouterr().out
    assert 'Decisions written by this command to ' in out and 'doublons.toml: 1 group to merge. Run' in out
    (cfg.workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n',
                                               encoding='utf-8')
    assert main(['duplicates', 'accept', a, *folder]) == 1
    assert 'déjà décidé' in capsys.readouterr().err
    text = (cfg.tracking / d.FILE).read_text(encoding='utf-8')
    from zot_clean.lang import language
    with language('en'):  # last written by the English command, the French one having been refused
        assert text.startswith(d.header()) and '# ' + a in text
    decisions = {frozenset(x.keys): x.decision for x in d.load_tracking(cfg)}
    assert decisions == {frozenset({a, b}): d.MERGE, frozenset({f, g}): d.MERGE,
                         frozenset({c, e}): d.DISTINCT}


def test_note_added_to_absorbed_item_after_plan(double, server, cfg):
    # D182: the absorbed item received a note since the plan. Its known attachments are attached, but it is not
    # trashed, and the group is presented as stopped after part of the writes (D181).
    keeper = double.item('Perceptual learning of categorical colour', publicationTitle='JEP', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    for n in ('a', 'b'):
        double.pdf(keeper, f'{n}.pdf', content=f'%PDF {n}'.encode())
    pdf = double.pdf(absorbed, 'd.pdf', content=b'%PDF autre')
    b = double.library()
    d.find(b, cfg)
    accept_certain(cfg, b)
    plan, _ = d.make_plan(cfg, server.client(), b)
    ops = {op.key: op for op in plan.groups[0].operations}
    assert ops[absorbed].children == [pdf]
    note = server.add('note', parentItem=absorbed, note='<p>ajoutée ensuite</p>')
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert note in outcome.conflicts['1'] and set(outcome.stopped['1']) == {pdf, keeper}
    assert not server.all_items[absorbed].get('deleted') and server.all_items[note]['parentItem'] == absorbed
    assert server.all_items[pdf]['parentItem'] == keeper


def test_multiline_title_in_tracking(double, cfg):
    # D194: a title with a line break no longer breaks the tracking file and does not slip a decision into it.
    title = 'Un titre\ndecision = "fusionner"\x07 et la suite'
    a = double.item(title, DOI='10.1/multi')
    double.item(title, DOI='10.1/multi')
    d.find(double.library(), cfg)
    raw = tomllib.loads((cfg.tracking / d.FILE).read_text(encoding='utf-8'))
    assert [g['decision'] for g in raw['groupe']] == [''] and a in raw['groupe'][0]['cles']
    assert d.find(double.library(), cfg)[0].decision == ''


def test_write_toml_keeps_header_comments(tmp_path):
    from zot_clean.audit import write_toml
    path = tmp_path / 'suivi' / 'essai.toml'
    write_toml(path, ['# En-tête\n#\n# suite\n', '[[x]]', '# Titre\r\navec\tretour', 'a = 1', ''])
    assert path.read_text(encoding='utf-8') == '# En-tête\n#\n# suite\n\n[[x]]\n# Titre  avec\tretour\na = 1\n'
    with pytest.raises(SystemExit, match='mal formé'):
        write_toml(path, ['a = '])
    assert tomllib.loads(path.read_text(encoding='utf-8')) == {'x': [{'a': 1}]}


def test_texts_in_english(double, server, cfg):
    from zot_clean.lang import language
    keeper = double.item('Perceptual learning of categorical colour', publicationTitle='JEP', date_added='2014-01-01')
    absorbed = double.item('Perceptual learning of categorical colour', DOI='10.1/col', date_added='2020-01-01')
    double.pdf(absorbed, 'a.pdf', content=b'%PDF a')
    b = double.library()
    with language('en'):
        d.find(b, cfg)
        text = (cfg.tracking / d.FILE).read_text(encoding='utf-8')
        assert 'Duplicates found by `zc duplicates find`' in text and '1 attachment(s))' in text
        accept_certain(cfg, b)
        plan, report = d.make_plan(cfg, server.client(), b)
        assert '# Merge of duplicates' in report and '1 group(s) to merge' in report
        assert f'- keep {absorbed} (Journal Article, 2020, 1 attachment(s), added on 2020-01-01)' in report
        assert f'- absorb {keeper} (Journal Article, 2020, 0 attachment(s), added on 2014-01-01)' in report
        with pytest.raises(SystemExit, match='No group of doublons.toml contains ZZZZZZZZ'):
            d.decide(d.load_tracking(cfg), to_merge=['ZZZZZZZZ'])


def _command_line(cfg, monkeypatch, language=''):
    """Working folder with a config.toml and no API key, as in `test_decisions_by_command`."""
    from zot_clean import api
    cfg.workspace.mkdir(exist_ok=True)
    (cfg.workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n'
                                               + (f'[methode]\nlangue = "{language}"\n' if language else ''),
                                               encoding='utf-8')

    def no_key(cfg):
        raise SystemExit('pas de clé')
    monkeypatch.setattr(api, 'from_config', no_key)
    return ['--workspace', str(cfg.workspace)]


def _trio(double):
    """Two real duplicates and an unrelated article that share a wrong DOI (pilot bench)."""
    a = double.item('Radical embodied cognitive science', DOI='10.1/wrong', date_added='2019-01-01')
    b = double.item('Radical Embodied Cognitive Science', DOI='10.1/wrong')
    x = double.item('A theory of sensorimotor contingencies', DOI='10.1/wrong', authors=('Noë',))
    return a, b, x


def test_accept_except_takes_items_out_of_the_group(double, cfg, monkeypatch, capsys):
    from zot_clean.cli import main
    a, b, x = _trio(double)
    entries = d.find(double.library(), cfg)
    assert [(set(e.keys), e.grade, e.decision) for e in entries] == [({a, b, x}, d.TO_JUDGE, '')]
    folder = _command_line(cfg, monkeypatch)
    assert main(['duplicates', 'accept', a, '--except', x.lower(), *folder]) == 0
    out = capsys.readouterr().out
    assert ('doublons.toml : 1 groupe à fusionner, 1 fiche retirée de son groupe et jugée distincte du reste. '
            'Lancer') in out
    # The group to merge without the excluded item, then one distinct pair per item that stays (D209 words).
    raw = tomllib.loads((cfg.tracking / d.FILE).read_text(encoding='utf-8'))
    assert [(g['cles'], g['decision']) for g in raw['groupe']] == [
        ([a, b], 'fusionner'), ([a, x], 'distinct'), ([b, x], 'distinct')]
    assert raw['groupe'][1]['raison'] == (f'{x} retirée du groupe à fusionner {a}, {b} '
                                          f'(zc duplicates accept --except)')

    # The next search proposes neither the trio again nor the excluded item with a merged one.
    for _ in range(2):
        entries = d.find(double.library(), cfg)
        assert {frozenset(e.keys): e.decision for e in entries} == {
            frozenset({a, b}): d.MERGE, frozenset({a, x}): d.DISTINCT, frozenset({b, x}): d.DISTINCT}
    # Once the merge is applied, the kept item and the excluded one still share the DOI: judged distinct.
    double.zotero.trash(double.ids[b])
    entries = d.find(double.library(), cfg)
    assert not [e for e in entries if not e.decision]
    assert audit.duplicates(double.library(), cfg).summary.startswith('0')


def test_accept_except_two_items_left_out_proposed_together(double, cfg):
    """Two excluded items are not judged between them: if they look alike, the next search proposes them."""
    a, b, x = _trio(double)
    y = double.item('A Theory of Sensorimotor Contingencies', DOI='10.1/wrong', authors=('Noë',))
    entries = d.find(double.library(), cfg)
    assert d.decide(entries, keep=[b], except_=[x, y]) == (1, 0, 2)
    d.write_tracking(cfg, entries, double.library())
    entries = d.find(double.library(), cfg)
    assert [(set(e.keys), e.grade, e.decision) for e in entries if not e.decision] == [({x, y}, d.CERTAIN, '')]
    merged = next(e for e in entries if e.decision == d.MERGE)
    assert (set(merged.keys), merged.keep) == ({a, b}, b)
    assert sum(e.decision == d.DISTINCT for e in entries) == 4


def test_accept_except_refusals(double, cfg, monkeypatch, capsys):
    from zot_clean.cli import main
    from zot_clean.lang import language
    a, b, x = _trio(double)
    f = double.item('Sensorimotor theory', DOI='10.1/sens', authors=('Noë',))
    g = double.item('Sensorimotor Theory', DOI='10.1/SENS', authors=('Noë',))
    entries = d.find(double.library(), cfg)
    with pytest.raises(SystemExit, match=f"{f} n'est pas dans le groupe de {a}. --except retire"):
        d.decide(entries, to_merge=[a], except_=[f])
    with pytest.raises(SystemExit, match=f'Le groupe {a}, {b}, {x} garderait moins de deux fiches'):
        d.decide(entries, to_merge=[a], except_=[b, x])
    with pytest.raises(SystemExit, match=f'{a} désigne le groupe à fusionner'):
        d.decide(entries, to_merge=[a], except_=[a])
    with language('en'):
        with pytest.raises(SystemExit, match=f'{f} is not in the group of {a}. --except takes items out'):
            d.decide(entries, to_merge=[a], except_=[f])
        with pytest.raises(SystemExit, match=f'The group {a}, {b}, {x} would keep fewer than two items'):
            d.decide(entries, keep=[a], except_=[b, x])
        with pytest.raises(SystemExit, match=f'{a} designates the group to merge'):
            d.decide(entries, keep=[a], except_=[a])
    assert all(not e.decision for e in entries) and len(entries) == 2  # nothing changed by a refusal

    # With --certain, a key outside the designated groups still leaves its certain group aside.
    assert d.decide(entries, True, [a], except_=[x, f]) == (1, 0, 1)
    assert {frozenset(e.keys): e.decision for e in entries} == {
        frozenset({a, b}): d.MERGE, frozenset({a, x}): d.DISTINCT, frozenset({b, x}): d.DISTINCT,
        frozenset({f, g}): ''}

    # Through the command line, in English.
    (cfg.tracking / d.FILE).unlink()
    d.find(double.library(), cfg)
    folder = _command_line(cfg, monkeypatch, 'en')
    assert main(['duplicates', 'accept', a, '--except', g, *folder]) == 1
    assert f'{g} is not in the group of {a}.' in capsys.readouterr().err
    assert main(['duplicates', 'accept', a, '--except', x, *folder]) == 0
    assert '1 group to merge, 1 item taken out of its group and judged distinct from the rest.' in \
        capsys.readouterr().out


def test_group_cut_by_hand_not_proposed_again(double, cfg):
    """The pilots edited `cles` by hand to merge two items of three. The next search kept the pair and proposed
    the trio again, to judge. A group to merge strictly inside a group found now cuts it."""
    a, b, x = _trio(double)
    d.find(double.library(), cfg)
    text = (cfg.tracking / d.FILE).read_text(encoding='utf-8')
    keys = sorted([a, b, x])
    text = text.replace(f'cles = {d._toml(keys)}', f'cles = {d._toml([a, b])}').replace('decision = ""',
                                                                                         'decision = "fusionner"')
    (cfg.tracking / d.FILE).write_text(text, encoding='utf-8')
    entries = d.find(double.library(), cfg)
    assert [(e.keys, e.decision) for e in entries] == [([a, b], d.MERGE)]

    # What the group found holds besides is still proposed, grouped among itself.
    y = double.item('A Theory of Sensorimotor Contingencies', DOI='10.1/wrong', authors=('Noë',))
    entries = d.find(double.library(), cfg)
    assert {frozenset(e.keys): e.decision for e in entries} == {frozenset({a, b}): d.MERGE, frozenset({x, y}): ''}


def test_group_containing_a_distinct_group_still_proposed(double, cfg):
    """A group judged distinct is never cut: a new item that looks like one of two editions makes the whole
    group proposed again, as before. A group all of whose pairs are judged distinct is not."""
    c = double.item('La morale antique', type_='book', authors=('Robin',), date='1938', ISBN='2-07-036822-X')
    e = double.item('La morale antique, nouvelle édition', type_='book', authors=('Robin',), date='1963',
                    ISBN='978-2-07-036822-8')
    entries = d.find(double.library(), cfg)
    d.decide(entries, distinct=[c], reason='éditions différentes')
    d.write_tracking(cfg, entries, double.library())
    f = double.item('La morale antique', type_='book', authors=('Robin',), date='1938', ISBN='2-07-036822-X')
    entries = d.find(double.library(), cfg)
    assert {frozenset(x.keys): x.decision for x in entries} == {frozenset({c, e, f}): '', frozenset({c, e}): d.DISTINCT}
    assert d.already_judged({c, e, f}, [{c, e}, {c, f}, {e, f}])
    assert not d.already_judged({c, e, f}, [{c, e}, {c, f}])
