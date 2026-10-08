import pytest

from fake_server import FakeServer
from fake_sources import FakeServices, crossref_work
from test_apply import write
from test_duplicates import Double
from zot_clean import metadata as m, plans, sources
from zot_clean.apply import TRIAL, apply_plan
from zot_clean.config import Config
from zot_clean.lang import language

# Fields of an article as the API returns them, empty ones included.
ARTICLE = dict(publicationTitle='', volume='', issue='', pages='', ISSN='', language='', publisher='', place='')


class DoubleMeta(Double):
    def article(self, title, **fields):
        key = self.item(title, **fields)
        self.server.all_items[key].update({k: v for k, v in ARTICLE.items() if k not in self.server.all_items[key]})
        self.server.all_items[key].update({k: v for k, v in fields.items() if k in ARTICLE})
        return key


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def double(zotero, server):
    return DoubleMeta(zotero, server)


@pytest.fixture
def fake():
    return FakeServices()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


def run(func, double, cfg, fake, server, show=None):
    services = sources.from_config(cfg, client_http=fake.client(), wait=lambda s: None)
    return func(double.library(), cfg, services, server.client(), show)


def cases_of(cfg):
    return {c.key: c for c in m.load_tracking(cfg)}


def test_normalize_doi():
    assert m.normalize_doi(' https://dx.doi.org/10.1037/0096-3445.131.4.477. ') == '10.1037/0096-3445.131.4.477'
    assert m.normalize_doi('doi: 10.1111/x;') == '10.1111/x'
    assert m.normalize_doi('http://dx.doi.org.ezproxy.exemple.org/10.1016/0010-0277(81)90002-0') == \
        '10.1016/0010-0277(81)90002-0'
    assert m.normalize_doi('https://www.doi.org/10.1177/146349960505') == '10.1177/146349960505'


def test_corrected_form_and_doi_found(double, cfg, fake, server):
    fake.add(doi='10.1111/color', title='Acquisition of categorical color perception')
    a = double.article('Acquisition of categorical color perception', DOI='https://doi.org/10.1111/color.',
                       authors=('Özgen',), date='2002')
    b = double.article('Radical embodied cognitive science of learning', authors=('Chemero',), date='2009')
    fake.crossref_search = [crossref_work('10.2222/rad', 'Radical Embodied Cognitive Science of Learning',
                                             authors=(('Chemero', 'Anthony'),), year=2010)]
    plan, report = run(m.identifiers, double, cfg, fake, server)
    ops = {g.id: g.operations[0] for g in plan.groups}
    assert ops[a].after == {'DOI': '10.1111/color'} and ops[a].before == {'DOI': 'https://doi.org/10.1111/color.'}
    assert ops[b].after == {'DOI': '10.2222/rad'}
    apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert server.all_items[a]['DOI'] == '10.1111/color' and server.all_items[b]['DOI'] == '10.2222/rad'


def test_unknown_and_mismatched_doi_to_judge(double, cfg, fake, server):
    fake.add(doi='10.1111/livre', title='Un tout autre ouvrage collectif', type_='book')
    unknown = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                             authors=('Martin',), date='1991')
    discordant = double.article('Introduction au volume collectif', DOI='10.1111/livre')
    fake.crossref_search = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             authors=(('Martin', 'Claire'),), year=2001)]
    plan, report = run(m.identifiers, double, cfg, fake, server)
    cases = cases_of(cfg)
    assert cases[unknown].problem == 'doi_inconnu'
    assert [p.fields for p in cases[unknown].proposals] == [{'DOI': ''}, {'DOI': '10.1111/situe'}]
    assert cases[discordant].problem == 'doi_discordant' and cases[discordant].proposals[1].fields == {}
    assert '2 cas à juger' in report and plan.groups == []


def test_cases_sorted_into_obvious_and_doubtful(double, cfg, fake, server):
    # D134: a single proposal matches on everything, the case is obvious and its number is chosen in advance.
    is_obvious = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                             authors=('Martin',), date='1991')
    fake.crossref_search = [
        crossref_work('10.1111/tard', 'Situated learning in communities of practice', authors=(('Martin', 'C'),),
                      year=2005),
        crossref_work('10.1111/proche', 'Situated learnings in a community of practice', authors=(('Martin', 'C'),),
                      year=1991)]
    _, report = run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[is_obvious]
    assert c.problem == 'doi_inconnu' and c.grade == 'évident' and c.decision == ''
    assert [p.verdict for p in c.proposals] == ['', 'année', 'concorde'] and c.selection == 3
    assert 'Dont 1 évident(s)' in report
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    assert 'classe = "évident"' in text and 'avis = "année"' in text
    fake.crossref_search[1]['author'] = [{'family': 'Petit', 'given': 'A'}]
    for f in cfg.cache.glob('*.json'):
        f.unlink()
    run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[is_obvious]
    assert c.grade == 'douteux' and c.proposals[2].verdict == 'auteur'


def test_translated_title_corroborated_by_author_year_and_journal(double, cfg, fake, server):
    # D131: Cairn gives the English title of a French article. Author, year and journal match.
    fake.add(doi='10.1111/rfs', title='The increased impact of social background on schooling',
                 authors=(('Martin', 'Claire'),), year=2001, **{'container-title': ['Revue française de sociologie']})
    translated = double.article("L'accroissement de l'effet de l'origine sociale", DOI='10.1111/rfs', authors=('Martin',),
                             date='2001', publicationTitle='Revue française de sociologie')
    fake.add(doi='10.1111/autre', title='Une histoire de la médecine', authors=(('Petit', 'Anne'),), year=2001,
                 **{'container-title': ['Revue française de sociologie']})
    other = double.article('Les inégalités scolaires', DOI='10.1111/autre', authors=('Martin',), date='2001',
                           publicationTitle='Revue française de sociologie')
    run(m.identifiers, double, cfg, fake, server)
    cases = cases_of(cfg)
    assert translated not in cases and cases[other].problem == 'doi_discordant'


def test_nonexistent_doi_replaced_by_certain_candidate(double, cfg, fake, server):
    # D128: JSTOR identifier mistaken for a DOI, the publisher's real DOI is found with certainty.
    a = double.article('Situated learning in communities of practice', DOI='10.2307/0000000',
                       authors=('Martin',), date='1991')
    fake.crossref_search = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             authors=(('Martin', 'Claire'),), year=1991)]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    op = plan.groups[0].operations[0]
    assert op.after == {'DOI': '10.1111/situe'} and 'DOI inexistant (10.2307/0000000) remplacé' in op.nature
    assert cases_of(cfg) == {}


def test_decisions_carried_to_next_plan(double, cfg, fake, server):
    a = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                       authors=('Martin',), date='1991')
    b = double.article('Un article au DOI fantôme', DOI='10.1111/fantome')
    fake.crossref_search = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             authors=(('Martin', 'Claire'),), year=2001)]
    run(m.identifiers, double, cfg, fake, server)
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    blocks = text.split('[[cas]]')
    blocks = [bl.replace('decision = ""\nchoix = 1', 'decision = "accepter"\nchoix = 2') if a in bl else
             bl.replace('decision = ""', 'decision = "refuser"') if b in bl else bl for bl in blocks]
    (cfg.tracking / m.FILE).write_text('[[cas]]'.join(blocks), encoding='utf-8')
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert [(g.id, g.operations[0].after) for g in plan.groups] == [(a, {'DOI': '10.1111/situe'})]
    assert cases_of(cfg)[b].decision == 'refuser'


def test_chapter_never_reattached_to_book(double, cfg, fake, server):
    double.item('Un volume collectif sur la cognition', type_='bookSection', authors=('Petit',), date='2015')
    fake.crossref_search = [crossref_work('10.1111/vol', 'Un volume collectif sur la cognition',
                                             authors=(('Petit', 'Anne'),), year=2015, type_='book')]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups == [] and cases_of(cfg) == {}


def test_year_too_far_to_judge(double, cfg, fake, server):
    a = double.article('Radical embodied cognitive science of learning', authors=('Chemero',), date='2001')
    fake.crossref_search = [crossref_work('10.2222/rad', 'Radical Embodied Cognitive Science of Learning',
                                             authors=(('Chemero', 'Anthony'),), year=2010)]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups == [] and cases_of(cfg)[a].problem == 'doi_manquant'


def test_filtered_item_never_searched_by_title(double, cfg, fake, server):
    double.article('Un article très confidentiel', tags=('_privé',))
    run(m.identifiers, double, cfg, fake, server)
    assert not any('/works' == r.removeprefix('api.crossref.org') for r in fake.requests)
    assert not any(r.startswith('api.openalex.org/works') for r in fake.requests)


def test_complete_empty_fields(double, cfg, fake, server):
    fake.add(doi='10.1111/color', title='Acquisition of categorical color perception',
                 **{'container-title': ['Journal of Tests'], 'volume': '131', 'page': '477-493', 'issue': '4'})
    a = double.article('Acquisition of categorical color perception', DOI='10.1111/color', authors=('Özgen',),
                       date='2002', volume='13')
    no_author = double.article('Acquisition of categorical color perception, bis', DOI='10.1111/bis', authors=())
    fake.add(doi='10.1111/bis', title='Acquisition of categorical color perception, bis',
                 authors=(('Özgen', 'Emre'), ('Davies', 'Ian')))
    plan, report = run(m.fill_in, double, cfg, fake, server)
    ops = {g.id: g.operations[0] for g in plan.groups}
    assert ops[a].after == {'publicationTitle': 'Journal of Tests', 'pages': '477-493', 'issue': '4'}
    assert ops[no_author].after['creators'] == [
        {'creatorType': 'author', 'lastName': 'Özgen', 'firstName': 'Emre'},
        {'creatorType': 'author', 'lastName': 'Davies', 'firstName': 'Ian'}]
    assert "volume : '13' dans Zotero, '131' chez crossref" in report
    apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert server.all_items[a]['volume'] == '13' and server.all_items[a]['pages'] == '477-493'


def test_complete_skips_unjudged_mismatched_doi(double, cfg, fake, server):
    fake.add(doi='10.1111/livre', title='Un tout autre ouvrage collectif', volume='3')
    a = double.article('Introduction au volume collectif', DOI='10.1111/livre')
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert plan.groups == [] and '1 fiche(s) sautée(s)' in report


def test_force_a_value(double, cfg, fake, server):
    a = double.article('Un article quelconque', date='2020')
    cfg.tracking.mkdir(parents=True)
    (cfg.tracking / m.FILE).write_text(
        f'[[cas]]\ncle = "{a}"\nsous_etape = "completer"\nprobleme = "forcer"\ndecision = "accepter"\n'
        'forcer = { "date" = "1998" }\n', encoding='utf-8')
    plan, _ = run(m.fill_in, double, cfg, fake, server)
    assert plan.groups[0].operations[0].after == {'date': '1998'}


def test_force_removes_item_from_skipped_and_differences(double, cfg, fake, server):
    """After a `forcer`, the report no longer mentions the skipped item or its value left as is."""
    from fake_sources import unimarc_record
    fake.bnf['2707302759'] = unimarc_record('La distinction : critique sociale du jugement')
    a = book(double, 'La morale antique', ISBN='2-7073-0275-9', authors=('Robin',), date='1938')
    fake.add(doi='10.1111/col', title='Acquisition of categorical color perception',
                 **{'container-title': ['Journal of Experimental Psychology: General']})
    b = double.article('Acquisition of categorical color perception', DOI='10.1111/col', authors=('Özgen',),
                       date='2002', publicationTitle='Journal of Test Psychology')
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert '1 livre(s) ou chapitre(s) sauté(s)' in report and f'- {b} publicationTitle' in report
    cfg.tracking.mkdir(parents=True, exist_ok=True)
    (cfg.tracking / m.FILE).write_text(
        f'[[cas]]\ncle = "{a}"\nsous_etape = "completer"\nprobleme = "forcer"\ndecision = "accepter"\n'
        'forcer = { "ISBN" = "" }\n'
        f'[[cas]]\ncle = "{b}"\nsous_etape = "completer"\nprobleme = "forcer"\ndecision = "accepter"\n'
        'forcer = { "publicationTitle" = "Journal of Experimental Psychology: General" }\n', encoding='utf-8')
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert 'sauté' not in report and f'- {b} publicationTitle' not in report
    assert 'Valeurs imposées par un cas `forcer` : ISBN vidé (1), publicationTitle (1).' in report
    assert 'Champs remplis : ISBN' not in report


def test_doi_not_found_without_other_lead_obvious(double, cfg, fake, server):
    # D169: the only proposal is to remove a DOI that doi.org does not know.
    a = double.article('Article propre numéro 1', DOI='10.9999/zc.test.001')
    run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[a]
    assert c.problem == 'doi_inconnu' and c.grade == 'évident' and c.selection == 1
    assert c.proposals[0].fields == {'DOI': ''} and 'ni doi.org' in c.proposals[0].note


def test_mismatched_journal_never_certain(double, cfg, fake, server):
    """Title, author and year match, but not the journal: the candidate is « à juger », and doubtful."""
    a = double.article('Acquisition of categorical color perception', DOI='10.9999/fictif', authors=('Özgen',),
                       date='2002', publicationTitle='Journal of Test Psychology')
    fake.crossref_search = [crossref_work('10.1037/vrai', 'Acquisition of categorical color perception',
                                             **{'container-title': ['Journal of Experimental Psychology: General']})]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[a]
    assert plan.groups == [] and c.grade == 'douteux' and c.proposals[1].verdict == 'revue ou ouvrage'
    assert m.containers_match('J. Exp. Psychol.', 'Journal of Experimental Psychology')
    assert m.containers_match('The Journal of experimental biology', 'Journal of Experimental Biology')
    assert not m.containers_match('Psychological Review', 'Psychological Bulletin')
    assert not m.containers_match('Mind', 'Mind & Language')


def test_generic_titles_and_language():
    assert m.generic_title('Introduction') and m.generic_title('Self-Styling')
    assert m.generic_title('Avant-propos') and not m.generic_title('Radical embodied cognitive science of learning')
    assert m.title_language('The origin of language in the brain') == 'en'
    assert m.title_language('La notion de culture dans les sciences sociales') == 'fr'
    assert m.title_language('Gestalttheorie') == ''


def test_introduction_never_certain(double, cfg, fake, server):
    a = double.item('Introduction', type_='bookSection', authors=('Petit',), date='2015')
    fake.crossref_search = [crossref_work('10.1111/intro', 'Introduction', authors=(('Petit', 'Anne'),),
                                             year=2015, type_='book-chapter')]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups == [] and cases_of(cfg)[a].problem == 'doi_manquant'


def test_chapter_of_another_book_not_certain(double, cfg, fake, server):
    a = double.item('Perception and action in the embodied mind', type_='bookSection', authors=('Petit',),
                     date='2015', bookTitle='Handbook of embodied cognition')
    fake.crossref_search = [crossref_work('10.1111/ch', 'Perception and action in the embodied mind',
                                             authors=(('Petit', 'Anne'),), year=2015, type_='book-chapter',
                                             **{'container-title': ['Philosophy of perception today']})]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups == [] and cases_of(cfg)[a].problem == 'doi_manquant'


def test_publisher_of_articles_and_checked_language(double, cfg, fake, server):
    fake.add(doi='10.1111/en', title='The origin of language in the brain', publisher='Elsevier BV',
                 language='en', volume='4')
    fake.add(doi='10.1111/fr', title='La notion de culture dans les sciences sociales', language='en')
    a = double.article('The origin of language in the brain', DOI='10.1111/en')
    b = double.article('La notion de culture dans les sciences sociales', DOI='10.1111/fr')
    plan, _ = run(m.fill_in, double, cfg, fake, server)
    ops = {g.id: g.operations[0].after for g in plan.groups}
    assert ops[a] == {'volume': '4', 'language': 'en'} and b not in ops


def test_tracking_enriched_for_judging(double, cfg, fake, server):
    double.article('Radical embodied cognitive science of learning', authors=('Chemero',), date='2001',
                   publicationTitle='Revue de test')
    fake.crossref_search = [crossref_work('10.2222/rad', 'Radical Embodied Cognitive Science of Learning',
                                             authors=(('Chemero', 'Anthony'),), year=2010, volume='12',
                                             page='1-20', **{'container-title': ['Journal of Mind']})]
    run(m.identifiers, double, cfg, fake, server)
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    assert 'dans « Revue de test »' in text
    assert 'dans « Journal of Mind », vol. 12, p. 1-20' in text


def run_types(double, cfg, fake, server):
    from zot_clean import reader
    services = sources.from_config(cfg, client_http=fake.client(), wait=lambda s: None)
    b = double.library()
    return m.types(b, cfg, services, server.client(), reader.read_types(double.zotero.database))


def test_article_turned_chapter_then_undo(double, cfg, fake, server):
    from zot_clean import undo
    fake.add(doi='10.1111/ch', title='Perception and action in the embodied mind', type_='book-chapter',
                 authors=(('Petit', 'Anne'),), year=2015)
    a = double.article('Perception and action in the embodied mind', DOI='10.1111/ch', authors=('Petit',),
                       date='2015', publicationTitle='Handbook of embodied cognition', issue='4')
    before = dict(server.all_items[a])
    plan, report = run_types(double, cfg, fake, server)
    op = plan.groups[0].operations[0]
    assert op.after == {'itemType': 'bookSection', 'publicationTitle': '', 'bookTitle': 'Handbook of embodied cognition',
                        'issue': '', 'extra': 'issue : 4'}
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert server.all_items[a]['itemType'] == 'bookSection' and server.all_items[a]['bookTitle'].startswith('Handbook')
    plan_a, _ = undo.make_plan([outcome.journal], server.client())
    apply_plan(plan_a, plans.write(plan_a, cfg.plans, ''), server.client(), cfg, TRIAL)
    after = server.all_items[a]
    assert all(after.get(k) == v for k, v in before.items() if k != 'version')
    assert not after.get('bookTitle')


def test_switch_to_book_to_judge_and_complete_waits(double, cfg, fake, server):
    fake.add(doi='10.1111/livre', title='Radical embodied cognitive science of learning', type_='book',
                 authors=(('Chemero', 'Anthony'),), year=2009, volume='2')
    a = double.article('Radical embodied cognitive science of learning', DOI='10.1111/livre', authors=('Chemero',),
                       date='2009')
    plan, _ = run_types(double, cfg, fake, server)
    assert plan.groups == [] and cases_of(cfg)[a].problem == 'type_different'
    assert cases_of(cfg)[a].proposals[0].fields == {'itemType': 'book'}
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert plan.groups == [] and "leur type diffère" in report


def test_unallowed_roles_become_contributors(zotero):
    from zot_clean import reader
    t = reader.read_types(zotero.save())
    d = {'itemType': 'book', 'title': 'T', 'creators': [{'creatorType': 'author', 'lastName': 'A'},
                                                          {'creatorType': 'editor', 'lastName': 'B'}]}
    after, _, _ = m.conversion(d, 'thesis', t)
    assert [c['creatorType'] for c in after['creators']] == ['author', 'contributor']


# --- Books (D90 to D94) ---

BOOK = dict(ISBN='', publisher='', place='', numPages='', edition='', series='', seriesNumber='', language='')


def book(double, title, **fields):
    key = double.item(title, type_='book', **fields)
    double.server.all_items[key].update({k: v for k, v in BOOK.items() if k not in double.server.all_items[key]})
    double.server.all_items[key].update({k: v for k, v in fields.items() if k in BOOK})
    return key


def test_missing_isbn_certain_or_to_judge(double, cfg, fake, server):
    from fake_sources import unimarc_record
    a = book(double, 'La distinction critique sociale du jugement', authors=('Bourdieu',), date='1979',
              publisher='Éditions de Minuit')
    b = book(double, 'Le métier de sociologue et ses préalables', authors=('Bourdieu',), date='1968')
    fake.bnf_search = [unimarc_record('La distinction critique sociale du jugement'),
                          unimarc_record('La distinction critique sociale du jugement', year='1992', isbn='')]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert [(g.id, g.operations[0].after) for g in plan.groups] == [(a, {'ISBN': '2-7073-0275-9'})]
    # Two editions from the same year: « à juger ».
    fake.bnf_search = [unimarc_record('Le métier de sociologue et ses préalables', year='1968', isbn='2-7193-0001-2'),
                          unimarc_record('Le métier de sociologue et ses préalables', year='1968', isbn='2-7193-0002-0',
                                         publisher='Mouton')]
    for f in cfg.cache.glob('*.json'):
        f.unlink()
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[b]
    assert c.problem == 'isbn_manquant' and len(c.proposals) == 2


def test_invalid_isbn_to_judge(double, cfg, fake, server):
    a = book(double, 'Un livre au numéro faux', ISBN='2-7073-0275-8, 978-0-262-01322-2')
    run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[a]
    assert c.problem == 'isbn_invalide' and c.proposals[0].fields == {'ISBN': '9780262013222'}


def test_invalid_isbn_replaced_by_certain_book(double, cfg, fake, server):
    """An invalid ISBN gives way to the book found with certainty by title, as D128 for a DOI (pilot bench)."""
    from fake_sources import unimarc_record
    a = book(double, 'La distinction critique sociale du jugement', ISBN='2-7073-0275-8', authors=('Bourdieu',),
             date='1979', publisher='Éditions de Minuit')
    fake.bnf_search = [unimarc_record('La distinction critique sociale du jugement')]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    op = plan.groups[0].operations[0]
    assert op.after == {'ISBN': '2-7073-0275-9'} and "ISBN invalide ('2-7073-0275-8') remplacé, bnf" in op.nature
    assert cases_of(cfg) == {}
    with language('en'):
        plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert "invalid ISBN ('2-7073-0275-8') replaced, bnf" in plan.groups[0].operations[0].nature


def test_invalid_isbn_candidates_closest_first(double, cfg, fake, server):
    """Without a certain book, the candidates found by title follow the removal, the closest to the current ISBN
    first (typing mistake)."""
    from fake_sources import unimarc_record
    a = book(double, 'Le métier de sociologue et ses préalables', ISBN='2-7193-0002-7', authors=('Bourdieu',),
             date='1968')
    fake.bnf_search = [unimarc_record('Le métier de sociologue et ses préalables', year='1968', isbn='2-7073-0275-9'),
                       unimarc_record('Le métier de sociologue et ses préalables', year='1968', isbn='2-7193-0002-0',
                                      publisher='Mouton')]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[a]
    assert plan.groups == [] and c.problem == 'isbn_invalide'
    assert [p.fields['ISBN'] for p in c.proposals] == ['', '2-7193-0002-0', '2-7073-0275-9']
    assert c.proposals[0].note == "retirer l'ISBN"
    assert c.proposals[1].note.endswith("à 1 caractère(s) de l'ISBN actuel")
    assert 'caractère' not in c.proposals[2].note
    assert m.isbn_gap('2719300027', '978-2-7193-0002-2') == 1  # same ISBN written in 13 digits


def test_invalid_isbn_of_confidential_item_never_searched(double, cfg, fake, server):
    from fake_sources import unimarc_record
    a = book(double, 'La distinction critique sociale du jugement', ISBN='2-7073-0275-8', authors=('Bourdieu',),
             date='1979', tags=('_privé',))
    fake.bnf_search = [unimarc_record('La distinction critique sociale du jugement')]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups == [] and len(cases_of(cfg)[a].proposals) == 1
    assert not any(r.startswith('catalogue.bnf.fr') for r in fake.requests)


def _remove_isbn_locally(double, server, key):
    """The removal applied, in Zotero and in the database copy."""
    double.zotero.db.execute("delete from itemData where itemID = ? and fieldID = "
                             "(select fieldID from fields where fieldName = 'ISBN')", (double.ids[key],))
    server.all_items[key]['ISBN'] = ''


def test_isbn_removed_by_judged_case_not_added_back_silently(double, cfg, fake, server):
    """The user removed an invalid ISBN. A book found later by title is a case to judge, never certain, with a note
    saying so, and the removal stays in memory (pilot bench)."""
    from fake_sources import unimarc_record
    a = book(double, 'La distinction critique sociale du jugement', ISBN='2-7073-0275-8', authors=('Bourdieu',),
             date='1979', publisher='Éditions de Minuit')
    run(m.identifiers, double, cfg, fake, server)
    cases = m.load_tracking(cfg)
    assert [len(c.proposals) for c in cases] == [1]
    m.decide(cases, accept={a: 1})
    m.write_tracking(cfg, cases, double.library())
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups[0].operations[0].after == {'ISBN': ''}
    _remove_isbn_locally(double, server, a)
    fake.bnf_search = [unimarc_record('La distinction critique sociale du jugement')]
    for f in cfg.cache.glob('*.json'):
        f.unlink()
    for _ in range(2):
        plan, _ = run(m.identifiers, double, cfg, fake, server)
        assert plan.groups == []
        by_problem = {c.problem: c for c in m.load_tracking(cfg)}
        assert by_problem[m.REMOVED_ISBN].decision == m.REJECT
        c = by_problem['isbn_manquant']
        assert (c.decision, c.grade, c.proposals[0].fields) == ('', 'douteux', {'ISBN': '2-7073-0275-9'})
        assert c.proposals[0].note.startswith("l'ISBN de cette fiche a été retiré plus tôt par un cas jugé ; bnf")


def test_isbns_ruled_out_by_removal_never_proposed_again():
    """Removing the ISBN rather than retaining a listed candidate rules the candidates out, whatever their form."""
    removal = m.Proposal({'ISBN': ''}, '', "retirer l'ISBN")
    candidate = m.Proposal({'ISBN': '2-7073-0275-9'}, 'bnf', 'La distinction', 'concorde')
    accepted = m.Case('ABCD1234', m.IDENTIFIERS, 'isbn_invalide', [removal, candidate], m.ACCEPT, 1)
    res = m.merge_tracking([accepted], [], m.IDENTIFIERS)
    assert [(c.problem, c.decision, [p.fields['ISBN'] for p in c.proposals]) for c in res] == [
        (m.REMOVED_ISBN, m.REJECT, ['2-7073-0275-9'])]
    removed, forced = m.isbn_removals(res)
    assert forced == set() and '9782707302755' in removed['ABCD1234']
    assert m.after_removal('ABCD1234', m.Proposal({'ISBN': '978-2-7073-0275-5'}, 'bnf'), removed['ABCD1234']) is None
    other = m.after_removal('ABCD1234', m.Proposal({'ISBN': '2-7193-0001-2'}, 'bnf', 'autre', 'concorde'),
                            removed['ABCD1234'])
    assert (other.problem, other.grade) == ('isbn_manquant', 'douteux')
    # The memory is not lost on the next pass.
    assert [c.problem for c in m.merge_tracking(res, [other], m.IDENTIFIERS)] == ['isbn_manquant', m.REMOVED_ISBN]
    # An ISBN emptied by a `forcer` case is never proposed again.
    forcing = m.Case('ABCD1234', m.FILL_IN, 'forcer', [], m.ACCEPT, force={'ISBN': ''})
    assert m.isbn_removals([forcing]) == ({}, {'ABCD1234'})


def test_document_that_is_a_book(double, cfg, fake, server):
    from fake_sources import unimarc_record
    from zot_clean import reader
    a = double.item('La distinction critique sociale du jugement', type_='document', authors=('Bourdieu',),
                     date='1979')
    fake.bnf_search = [unimarc_record('La distinction critique sociale du jugement')]
    plan, _ = run_types(double, cfg, fake, server)
    c = cases_of(cfg)[a]
    assert plan.groups == [] and c.problem == 'livre_possible'
    assert c.proposals[0].fields == {'itemType': 'book', 'ISBN': '2-7073-0275-9'}
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8').replace('decision = ""', 'decision = "accepter"')
    (cfg.tracking / m.FILE).write_text(text, encoding='utf-8')
    server.all_items[a]['ISBN'] = ''  # field absent from the document type, present after conversion
    plan, _ = run_types(double, cfg, fake, server)
    assert plan.groups[0].operations[0].after['itemType'] == 'book'
    assert plan.groups[0].operations[0].after['ISBN'] == '2-7073-0275-9'


def test_complete_book_and_chapter_by_isbn(double, cfg, fake, server):
    from fake_sources import unimarc_record
    fake.bnf['2707302759'] = unimarc_record('La distinction : critique sociale du jugement')
    a = book(double, 'La distinction : critique sociale du jugement', ISBN='2-7073-0275-9', authors=('Bourdieu',),
              date='1979')
    ch = double.item('Le goût de nécessité', type_='bookSection', ISBN='2-7073-0275-9', authors=('Bourdieu',),
                      date='1979')
    server.all_items[ch].update(bookTitle='', publisher='', place='', series='', ISBN='2-7073-0275-9', language='')
    plan, report = run(m.fill_in, double, cfg, fake, server)
    ops = {g.id: g.operations[0].after for g in plan.groups}
    assert ops[a] == {'publisher': 'Éditions de Minuit', 'place': 'Paris', 'numPages': '670',
                      'series': 'Le Sens commun', 'language': 'fr'}
    assert ops[ch] == {'bookTitle': 'La distinction : critique sociale du jugement', 'publisher': 'Éditions de Minuit',
                       'place': 'Paris', 'series': 'Le Sens commun', 'language': 'fr'}


def test_isbn_of_another_book_listed_in_report(double, cfg, fake, server):
    from fake_sources import unimarc_record
    fake.bnf['2707302759'] = unimarc_record('La distinction : critique sociale du jugement')
    a = book(double, 'Le sens pratique', ISBN='2-7073-0275-9', authors=('Bourdieu',), date='1980')
    b = book(double, 'Mes carnets de santé', ISBN='2-7073-0275-9', authors=('Bourdieu',), date='1980',
              tags=('_privé',))
    show = []
    plan, report = run(m.fill_in, double, cfg, fake, server, show.append)
    assert plan.groups == [] and '2 livre(s) ou chapitre(s) sauté(s)' in report
    assert f"- {a} (ISBN) : 'Le sens pratique' dans Zotero, 'La distinction : critique sociale du jugement' chez bnf" \
           in report
    assert f'- {b} (ISBN) : (fiche confidentielle)' in report and 'santé' not in report
    assert '2/2 livres et chapitres examinés par leur ISBN' in show


def test_isbn_of_another_book_seen_from_identifiers(double, cfg, fake, server):
    """A valid ISBN that designates another book is an `isbn_discordant` case. Judged right, `completer` completes
    from it. Removed, the item stays skipped until applied."""
    from fake_sources import unimarc_record
    fake.bnf['2707302759'] = unimarc_record('La distinction : critique sociale du jugement')
    a = book(double, 'La morale antique', ISBN='2-7073-0275-9', authors=('Robin',), date='1938')
    run(m.identifiers, double, cfg, fake, server)
    c = cases_of(cfg)[a]
    assert c.problem == 'isbn_discordant' and [p.fields for p in c.proposals[:2]] == [{'ISBN': ''}, {}]
    assert c.grade == 'douteux' and 'garder' in c.proposals[1].note
    requests = len(fake.requests)
    run(m.fill_in, double, cfg, fake, server)
    assert len(fake.requests) == requests  # record already cached
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    (cfg.tracking / m.FILE).write_text(text.replace('decision = ""', 'decision = "accepter"'), encoding='utf-8')
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups[0].operations[0].after == {'ISBN': ''}
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert plan.groups == [] and '1 livre(s) ou chapitre(s) sauté(s)' in report
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    (cfg.tracking / m.FILE).write_text(text.replace('choix = 1', 'choix = 2'), encoding='utf-8')
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert 'sauté' not in report and plan.groups[0].operations[0].after['publisher'] == 'Éditions de Minuit'


def test_confidential_item_hidden(double, cfg, fake, server):
    fake.add(doi='10.1111/sante', title='Mon dossier médical', type_='book',
                 **{'container-title': ['Revue de santé'], 'volume': '7'})
    mismatched = double.article('Mon dossier médical, version longue', DOI='10.1111/autre', tags=('_privé',))
    fake.add(doi='10.1111/autre', title='Une histoire de la médecine')
    complete = double.article('Mon dossier médical', DOI='10.1111/sante', tags=('_privé',))
    _, report = run(m.identifiers, double, cfg, fake, server)
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    assert cases_of(cfg)[mismatched].problem == 'doi_discordant'
    assert 'médic' not in text and 'médic' not in report
    _, report = run_types(double, cfg, fake, server)
    assert 'médic' not in report and 'médic' not in (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    plan, report = run(m.fill_in, double, cfg, fake, server)
    assert 'médic' not in report and 'santé' not in report


def test_chapter_whose_editor_is_entered_first(double, cfg, fake, server):
    # The book's editor comes before the chapter's author: it is the author who is compared to the source.
    a = double.item('World articulating animals in phenomenology', type_='bookSection', authors=('Rouse',),
                     editors=('Burch',), date='2019', bookTitle='Normativity, Meaning, and Phenomenology')
    fake.crossref_search = [crossref_work('10.4324/rouse', 'World Articulating Animals in Phenomenology',
                                             authors=(('Rouse', 'Joseph'),), year=2019, type_='book-chapter',
                                             **{'container-title': ['Normativity, Meaning, and Phenomenology']})]
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert [(g.id, g.operations[0].after) for g in plan.groups] == [(a, {'DOI': '10.4324/rouse'})]


def test_value_already_on_server_ignored(double, cfg, fake, server):
    # The local copy still has the old DOI, the server already has the new one (Zotero not yet synced).
    fake.add(doi='10.1111/color', title='Acquisition of categorical color perception')
    a = double.article('Acquisition of categorical color perception', DOI='https://doi.org/10.1111/color',
                       authors=('Özgen',), date='2002')
    server.all_items[a]['DOI'] = '10.1111/color'
    plan, _ = run(m.identifiers, double, cfg, fake, server)
    assert plan.groups == []


def test_conference_paper_never_retyped_as_chapter_without_judgement():
    # D130: Crossref files as chapters the papers published in proceedings that belong to a series.
    assert not m.certain_transition('conferencePaper', 'bookSection')
    assert m.certain_transition('bookSection', 'conferencePaper')


def test_certain_type_change_rejected(double, cfg, fake, server):
    fake.add(doi='10.1111/ch', title='Perception and action in the embodied mind', type_='book-chapter',
                 authors=(('Petit', 'Anne'),), year=2015)
    a = double.article('Perception and action in the embodied mind', DOI='10.1111/ch', authors=('Petit',),
                       date='2015', publicationTitle='Handbook of embodied cognition')
    cfg.tracking.mkdir(parents=True)
    (cfg.tracking / m.FILE).write_text(
        f'[[cas]]\ncle = "{a}"\nsous_etape = "types"\nprobleme = "type_different"\ndecision = "refuser"\n'
        '[[cas.propositions]]\nchamps = { "itemType" = "bookSection" }\n', encoding='utf-8')
    plan, _ = run_types(double, cfg, fake, server)
    assert plan.groups == [] and cases_of(cfg)[a].decision == 'refuser'


def test_pure_form_differences():
    # D132: these differences are no longer listed in the report of completions.
    f = m.same_form
    assert f('date', '1991-00-00 1991', '1991-02') and f('date', '2004-08-00 08/2004', '2004-08-01')
    assert not f('date', '2009-11-25 2009/11/25', '2020') and not f('date', '2011-03-00 3/2011', '2011-06-28')
    assert f('ISSN', '00122017', '0012-2017') and f('ISSN', '1040-0419', '1040-0419, 1532-6934')
    assert not f('ISSN', '1540-7063', '0003-1569')
    assert f('ISBN', '978-3-642-31726-2 978-3-642-31727-9', '9783642317262, 9783642317279')
    assert f('pages', '422-31', '422-431') and f('pages', '55–60', '55') and not f('pages', '109-117', '108-117')
    assert f('publicationTitle', 'The Journal of experimental biology', 'Journal of Experimental Biology')
    assert f('publicationTitle', 'Social Philosophy & Policy', 'Social Philosophy and Policy')
    assert f('issue', '5–6', '5-6') and not f('issue', '101', '1')
    assert not f('publicationTitle', 'Evol. Comput.', 'Evolutionary Computation')


def test_types_of_duplicate_group(double, cfg, fake, server):
    """Duplicates to merge with different types, whose DOI is unknown to the sources: each item is offered the
    other's type, and only one of the two proposals can be accepted."""
    from zot_clean import duplicates
    a = double.article('Self-organization in communicating groups', authors=('Heylen',), date='2013',
                       DOI='10.9999/heylen')
    c = double.item('Self-organization in communicating groups', type_='conferencePaper', authors=('Heylen',),
                     date='2013', DOI='10.9999/heylen')
    server.all_items[c].update(proceedingsTitle='Actes de test')
    doc = double.item('Un document au type par défaut', type_='document', authors=('Roux',), date='2011')
    duplicates.find(double.library(), cfg)
    text = (cfg.tracking / duplicates.FILE).read_text(encoding='utf-8')
    (cfg.tracking / duplicates.FILE).write_text(text.replace('decision = ""', 'decision = "fusionner"'),
                                              encoding='utf-8')
    plan, report = run_types(double, cfg, fake, server)
    cases = cases_of(cfg)
    assert plan.groups == [] and cases[a].problem == cases[c].problem == 'type_doublon'
    assert cases[a].proposals[0].fields == {'itemType': 'conferencePaper'}
    assert cases[c].proposals[0].fields == {'itemType': 'journalArticle'}
    assert f'1 fiche(s) « Document » sans livre trouvé par leur titre ({doc})' in report
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    (cfg.tracking / m.FILE).write_text(text.replace('decision = ""', 'decision = "accepter"'), encoding='utf-8')
    plan, report = run_types(double, cfg, fake, server)
    assert plan.groups == [] and "n'accepter qu'un des deux cas" in report
    text = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    start, _, end = text.partition(f'cle = "{c}"')
    (cfg.tracking / m.FILE).write_text(start + f'cle = "{c}"' + end.replace('decision = "accepter"',
                                                                            'decision = "refuser"', 1),
                                       encoding='utf-8')
    plan, _ = run_types(double, cfg, fake, server)
    assert [(g.id, g.operations[0].after['itemType']) for g in plan.groups] == [(a, 'conferencePaper')]


def test_bulk_decisions(double, cfg, fake, server):
    """D172: the obvious ones are accepted in one command, except those the user sets aside. A doubtful one is
    accepted with its proposal number, or refused. Only the cases still « à juger » change."""
    is_obvious = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                             authors=('Martin',), date='1991')
    skipped = double.article('Un article au DOI fantôme', DOI='10.1111/fantome')
    doubtful = double.article('Perceptual learning', DOI='10.1111/perdu', authors=('Gibson',), date='1963')
    rejected_one = double.article('Encore un fantôme', DOI='10.1111/fantome2')
    fake.crossref_search = [crossref_work('10.1111/proche', 'Situated learnings in a community of practice',
                                             authors=(('Martin', 'C'),), year=1991)]
    run(m.identifiers, double, cfg, fake, server)
    cases = m.load_tracking(cfg)
    grades = {c.key: c.grade for c in cases}
    assert grades[is_obvious] == grades[skipped] == 'évident'
    with pytest.raises(SystemExit, match='Aucun cas à juger pour ZZZZZZZZ'):
        m.decide(cases, accept={'ZZZZZZZZ': None})
    assert m.decide(cases, reject=[rejected_one]) == (0, 1)
    assert m.decide(cases, True, {doubtful: 1}, except_={skipped}) == (2, 0)
    m.write_tracking(cfg, cases, double.library())
    reloaded_cases = cases_of(cfg)
    assert {k: c.decision for k, c in reloaded_cases.items()} == {is_obvious: 'accepter', skipped: '', doubtful: 'accepter',
                                                           rejected_one: 'refuser'}
    assert reloaded_cases[is_obvious].selection == cases[[c.key for c in cases].index(is_obvious)].selection
    assert m.decide(m.load_tracking(cfg), True, except_={skipped}) == (0, 0)  # already decided


def test_decision_on_single_case_of_item():
    cases = [m.Case('ABCD1234', 'identifiants', 'doi_manquant', [m.Proposal({'DOI': '10.1/a'})] * 2),
           m.Case('ABCD1234', 'identifiants', 'isbn_manquant', [m.Proposal({'ISBN': '978'})])]
    with pytest.raises(SystemExit, match='ABCD1234:doi_manquant, ABCD1234:isbn_manquant'):
        m.decide(cases, accept={'ABCD1234': 2})
    assert m.decide(cases, accept={'ABCD1234:doi_manquant': 2}, reject=['ABCD1234:isbn_manquant']) == (1, 1)
    assert [(c.decision, c.selection) for c in cases] == [('accepter', 2), ('refuser', 1)]


def test_skipped_doi_never_proposed_again():
    """A false DOI removed (case accepted, proposal 1): the discarded candidate does not come back as `doi_manquant`
    when the item, now without a DOI, is examined again (Inbox triage, pilot rehearsal)."""
    def abma():
        return m.Proposal({'DOI': '10.1/abma'}, 'crossref', 'Abma 2007')
    removal = m.Proposal({'DOI': ''}, '', 'retirer le DOI')
    accepted = m.Case('ABCD1234', m.IDENTIFIERS, 'doi_inconnu', [removal, abma()], m.ACCEPT, 1)
    res = m.merge_tracking([accepted], [m.Case('ABCD1234', m.IDENTIFIERS, 'doi_manquant', [abma()])], m.IDENTIFIERS)
    assert [(c.problem, c.decision, [p.fields['DOI'] for p in c.proposals]) for c in res] == [
        ('doi_manquant', m.REJECT, ['10.1/abma'])]
    # Next pass: the refusal stays.
    res = m.merge_tracking(res, [m.Case('ABCD1234', m.IDENTIFIERS, 'doi_manquant', [abma()])], m.IDENTIFIERS)
    assert [(c.problem, c.decision) for c in res] == [('doi_manquant', m.REJECT)]
    # A new candidate is still proposed, without the one that was discarded.
    other = m.Proposal({'DOI': '10.1/autre'}, 'crossref', 'autre')
    res = m.merge_tracking([accepted], [m.Case('ABCD1234', m.IDENTIFIERS, 'doi_manquant', [abma(), other])],
                            m.IDENTIFIERS)
    assert [(c.decision, [p.fields['DOI'] for p in c.proposals]) for c in res] == [('', ['10.1/autre'])]


def test_texts_in_english(double, cfg, fake, server):
    fake.add(doi='10.1111/livre', title='Un tout autre ouvrage collectif', type_='book')
    double.article('Introduction au volume collectif', DOI='10.1111/livre')
    fake.add(doi='10.1111/color', title='Acquisition of categorical color perception',
             **{'container-title': ['Journal of Tests'], 'volume': '131'})
    double.article('Acquisition of categorical color perception', DOI='10.1111/color', authors=('Özgen',),
                   date='2002', volume='13')
    with language('en'):
        plan, report = run(m.identifiers, double, cfg, fake, server)
        assert '# Identifiers' in report and '1 case(s) to judge in suivi/metadonnees.toml' in report
        assert 'Metadata cases to judge, written by `zc metadata identifiers`' in (
            cfg.tracking / m.FILE).read_text(encoding='utf-8')
        plan, report = run(m.fill_in, double, cfg, fake, server)
        assert '# Complements' in report and "volume: '13' in Zotero, '131' at crossref" in report
        with pytest.raises(SystemExit, match='No case to judge for ZZZZZZZZ in metadonnees.toml'):
            m.decide(m.load_tracking(cfg), accept={'ZZZZZZZZ': None})


FRENCH_MARKS = ('dans «', 'similarité', 'remplacé', 'forme corrigée', 'garder', 'retirer', 'complété', 'cas jugé',
                'identifiant trouvé', 's. d.', 'type inconnu', 'éditions chez', 'Transférés', 'Recopiés', 'livre :',
                "d'après", 'corrigés', 'Champs vides')


def test_notes_natures_and_descriptions_in_english(double, cfg, fake, server):
    """Notes of the proposals, natures and descriptions of the plans are only shown, never read back: in an English
    library they are English (pilot bench). The verdicts (`avis`) stay French, stored and documented as such."""
    fake.add(doi='10.1111/color', title='Acquisition of categorical color perception',
             **{'container-title': ['Journal of Tests'], 'volume': '131'})
    double.article('Acquisition of categorical color perception', DOI='https://doi.org/10.1111/color.',
                   authors=('Özgen',), date='2002')
    double.article('Situated learning in communities of practice', DOI='10.2307/0000000', authors=('Martin',),
                   date='1991')
    fake.add(doi='10.1111/livre', title='Un tout autre ouvrage collectif', type_='book')
    double.article('Introduction au volume collectif', DOI='10.1111/livre')
    fake.crossref_search = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                          authors=(('Martin', 'Claire'),), year=1991)]
    with language('en'):
        plan, report = run(m.identifiers, double, cfg, fake, server)
        tracking = (cfg.tracking / m.FILE).read_text(encoding='utf-8')
    natures = [g.operations[0].nature for g in plan.groups]
    assert plan.description == 'Identifiers (DOI, ISBN) fixed or added.'
    assert any(n.startswith('form fixed (') for n in natures)
    assert any(n.startswith('nonexistent DOI (10.2307/0000000) replaced, crossref: “Situated learning') for n in natures)
    assert 'note = "remove the DOI"' in tracking and 'keep the DOI, it is right (' in tracking
    assert 'avis = ' in tracking  # stored verdict, still French
    for text in (report, tracking.split('[[cas]]', 1)[1], *natures):
        assert not [x for x in FRENCH_MARKS if x in text], text


def test_date_of_zotero_shown_as_entered(double, cfg, fake, server):
    """The database stores « 2015-00-00 2015 »: the report shows « 2015 », as Zotero does (pilot bench)."""
    fake.add(doi='10.1111/color', title='Acquisition of categorical color perception', year=2003)
    double.article('Acquisition of categorical color perception', DOI='10.1111/color', authors=('Özgen',),
                   date='2015')
    _, report = run(m.fill_in, double, cfg, fake, server)
    assert "date : '2015' dans Zotero, '2003-08-01' chez crossref" in report and '2015-00-00' not in report
    with language('en'):
        _, report = run(m.fill_in, double, cfg, fake, server)
    assert "date: '2015' in Zotero, '2003-08-01' at crossref" in report
    assert plan_description_in_english(m.fill_in, double, cfg, fake, server) == \
        'Empty fields completed from the metadata sources.'


def plan_description_in_english(func, double, cfg, fake, server) -> str:
    with language('en'):
        plan, _ = run(func, double, cfg, fake, server)
    return plan.description
