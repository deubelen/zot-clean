from pathlib import Path

import httpx2
import pytest

from fake_sources import FakeServices
from zot_clean import sources
from zot_clean.config import Config
from zot_clean.lang import language


@pytest.fixture
def fake():
    return FakeServices()


@pytest.fixture
def cfg(tmp_path):
    c = Config(workspace=tmp_path)
    c.sources.contact = 'moi@example.org'
    (tmp_path / '.env').write_text('OPENALEX_API_KEY=cle-openalex\n', encoding='utf-8')
    return c


def services(cfg, fake, **kw):
    return sources.from_config(cfg, client_http=fake.client(), wait=lambda s: None, **kw)


def test_crossref_reading(cfg, fake):
    fake.add(doi='10.1/A', title='Acquisition of color', subtitle=['A perceptual approach'],
                 **{'container-title': ['Journal of Tests'], 'volume': '131', 'page': '477-493',
                    'editor': [{'family': 'Durand', 'given': 'Anne'}], 'ISSN': ['0096-3445']})
    o = services(cfg, fake).work('10.1/a')
    assert o.source == 'crossref' and o.type == 'journalArticle'
    assert o.title == 'Acquisition of color: A perceptual approach'
    assert o.date == '2002-08-01' and o.year == '2002'
    assert o.authors == [['Özgen', 'Emre']] and o.editors == [['Durand', 'Anne']]
    assert (o.container, o.volume, o.pages, o.issn) == ('Journal of Tests', '131', '477-493', ['0096-3445'])


def test_openalex_if_crossref_does_not_know(cfg, fake):
    fake.openalex['10.5281/zenodo.1'] = {
        'doi': 'https://doi.org/10.5281/zenodo.1', 'title': 'Un jeu de données', 'type': 'dataset',
        'publication_date': '2020-05-04', 'authorships': [{'author': {'display_name': 'Marie Curie'}}],
        'primary_location': {'source': {'display_name': 'Zenodo'}}, 'biblio': {'first_page': '1', 'last_page': '9'}}
    o = services(cfg, fake).work('10.5281/zenodo.1')
    assert o.source == 'openalex' and o.authors == [['Curie', 'Marie']] and o.pages == '1-9'


def test_cache_and_absence(cfg, fake):
    fake.add(doi='10.1/a', title='A')
    s = services(cfg, fake)
    assert s.work('10.1/a').title == 'A' and s.work('10.1/a').title == 'A'
    assert s.work('10.1/inconnu') is None and s.work('10.1/inconnu') is None
    assert len(fake.requests) == 3  # crossref A, crossref unknown, openalex unknown
    s.persist()
    fake.requests.clear()
    assert services(cfg, fake).work('10.1/a').title == 'A' and fake.requests == []
    services(cfg, fake, refresh=True).work('10.1/a')
    assert len(fake.requests) == 1


def test_refresh_keeps_openalex_cap(cfg, fake):
    budget = cfg.cache / sources.BUDGET_OPENALEX
    cfg.cache.mkdir(parents=True)
    budget.write_text('{"jour": "2026-10-06", "recherches": 899}', encoding='utf-8')
    (cfg.cache / 'crossref.json').write_text('{}', encoding='utf-8')
    services(cfg, fake, refresh=True)
    assert not (cfg.cache / 'crossref.json').exists()
    assert budget.read_text(encoding='utf-8') == '{"jour": "2026-10-06", "recherches": 899}'


def test_resolver(cfg, fake):
    fake.handles.add('10.1/datacite')
    s = services(cfg, fake)
    assert s.resolver.exists('10.1/datacite') and not s.resolver.exists('10.1/rien')


def test_rate_limited(tmp_path, fake):
    clock, pauses = [0.0], []

    def wait(s):
        pauses.append(s)
        clock[0] += s
    cr = sources.Crossref(tmp_path, rate=2, client_http=fake.client(), wait=wait, clock=lambda: clock[0])
    for i in range(3):
        cr.work(f'10.1/{i}')
    assert pauses == [0.5, 0.5]


def test_contact_passed_on(cfg, fake):
    s = services(cfg, fake)
    assert 'mailto:moi@example.org' in s.sources[0].headers()['User-Agent']


def test_similarity():
    assert sources.similarity('Radical Embodied Cognitive Science', 'radical embodied cognitive science') == 1
    assert sources.similarity('Acquisition of categorical color perception',
                              'Acquisition of categorical color perception: a perceptual learning approach') == 0.97
    assert sources.similarity('La morale antique', 'Thought and language') < 0.5


def test_openalex_search_cleaned_and_refusal_without_failure(tmp_path, fake):
    oa = sources.OpenAlex(tmp_path, key='k', client_http=fake.client(), wait=lambda s: None)
    assert oa.find('What is art... and why should we care?') == []
    assert 'api.openalex.org/works' in fake.requests
    fake.handle = lambda req: httpx2.Response(400)
    assert sources.Crossref(tmp_path, client_http=fake.client(), wait=lambda s: None).work('10.1111/<x>') is None


def test_unavailable_source_set_aside(cfg, fake):
    fake.add(doi='10.1111/a', title='A')
    real = fake.handle
    fake.handle = lambda req: (httpx2.Response(429, headers={'Retry-After': '1'},
                                                json={'message': 'limite atteinte'})
                                if req.url.host == 'api.crossref.org' else real(req))
    s = services(cfg, fake)
    assert s.work('10.1111/a') is None  # OpenAlex does not know it
    assert 'crossref' in s.unavailable and 'limite atteinte' in s.warnings()[0]
    assert list(s.searches('A')) == [[]]  # only OpenAlex is still consulted
    fake.handle = real
    assert services(cfg, fake).work('10.1111/a').title == 'A'  # nothing was cached


def test_openalex_without_key_does_not_search_but_reads_by_doi(cfg, fake):
    (cfg.workspace / '.env').unlink()
    fake.openalex['10.5281/z'] = {'doi': 'https://doi.org/10.5281/z', 'title': 'Z'}
    s = services(cfg, fake)
    assert s.work('10.5281/z').title == 'Z'
    assert list(s.searches('Un titre')) == [[]]  # Crossref only
    assert 'OPENALEX_API_KEY' in s.warnings()[0]
    assert not any(r == 'api.openalex.org/works' for r in fake.requests)


def test_daily_search_cap(tmp_path, fake):
    day = ['2026-09-28']
    oa = sources.OpenAlex(tmp_path, key='k', cap=2, today=lambda: day[0], client_http=fake.client(),
                          wait=lambda s: None)
    oa.find('un'), oa.find('deux'), oa.find('un')  # the third comes from the cache
    with pytest.raises(sources.SearchImpossible, match='plafond'):
        oa.find('trois')
    oa.persist()
    oa2 = sources.OpenAlex(tmp_path, key='k', cap=2, today=lambda: day[0], client_http=fake.client())
    with pytest.raises(sources.SearchImpossible):
        oa2.find('quatre')
    day[0] = '2026-09-29'
    assert oa2.find('quatre') == []


def test_unimarc_record():
    from fake_sources import unimarc_record
    o = sources.read_unimarc(unimarc_record('La distinction', translator=('Nice', 'Richard')), 'bnf')
    assert (o.title, o.date, o.publisher, o.place, o.n_pages, o.collection, o.language) == (
        'La distinction', '1979', 'Éditions de Minuit', 'Paris', '670', 'Le Sens commun', 'fr')
    assert o.authors == [['Bourdieu', 'Pierre']] and o.translators == [['Nice', 'Richard']]
    former = sources.read_unimarc(unimarc_record('La Morale antique , par Léon Robin... 2e',
                                                   place='Paris, Presses universitaires de France', publisher=''), 'bnf')
    assert (former.title, former.place, former.publisher) == ('La Morale antique', 'Paris',
                                                                 'Presses universitaires de France')


def test_isbn_checksum():
    assert sources.isbns('2-7073-0275-9, 978-0-262-01322-2') == [('2707302759', True), ('9780262013222', True)]
    assert sources.isbns('2-7073-0275-8') == [('2707302758', False)]
    assert sources.isbns('2-7193-0001-2 2-7193-0002-0 (br.)') == [('2719300012', True), ('2719300020', True)]
    assert sources.isbns('ISBN 978-2-07-036822-8') == [('9782070368228', True)]
    assert sources.isbns('978 90 272 5202 9, 978 90 272 9343 5') == [('9789027252029', True), ('9789027293435', True)]
    assert sources.francophone('2707302759') and sources.francophone('9791012345678')
    assert not sources.francophone('9780262013222')


def test_book_by_isbn_by_language(cfg, fake):
    from fake_sources import unimarc_record
    fake.bnf['2707302759'] = unimarc_record('La distinction')
    fake.sudoc['9780262013222'] = unimarc_record('Radical embodied cognitive science', ('Chemero', 'Anthony'), '2009',
                                                 'The MIT Press', 'Cambridge', '978-0-262-01322-2', xml_prefix='')
    fake.openlibrary['9780262013222'] = {'title': 'Radical embodied cognitive science', 'publishers': ['MIT Press'],
                                         'authors': [{'key': '/authors/Anthony Chemero'}], 'publish_date': '2009'}
    s = services(cfg, fake)
    assert s.book('2707302759').source == 'bnf'
    o = s.book('9780262013222')
    assert o.source == 'openlibrary' and o.authors == [['Chemero', 'Anthony']]  # Open Library first outside the French-speaking world
    fake.openlibrary.clear()
    assert services(cfg, fake, refresh=True).book('9780262013222').source == 'sudoc'


def test_too_slow_source_set_aside(tmp_path, fake):
    clock = [0.0]
    real = fake.handle

    def slow(req):
        clock[0] += 25  # each response takes 25 seconds
        return real(req)
    fake.handle = slow
    cr = sources.Crossref(tmp_path, client_http=fake.client(), wait=lambda s: None, clock=lambda: clock[0])
    cr.work('10.1111/a'), cr.work('10.1111/b')
    with pytest.raises(sources.SourceUnavailable, match='trop lent'):
        cr.work('10.1111/c')


def test_cache_saved_regularly(tmp_path, fake):
    clock = [0.0]
    cr = sources.Crossref(tmp_path, client_http=fake.client(), wait=lambda s: None, clock=lambda: clock[0])
    cr.work('10.1111/a')
    assert not cr.file.exists()
    clock[0] = 31
    cr.work('10.1111/b')
    assert cr.file.exists()


def test_spaced_slowdowns_tolerated(tmp_path, fake):
    clock, n = [0.0], [0]
    real = fake.handle

    def sometimes_slow(req):
        n[0] += 1
        clock[0] += 25 if n[0] % 2 else 1  # every other response is slow
        return real(req)
    fake.handle = sometimes_slow
    cr = sources.Crossref(tmp_path, client_http=fake.client(), wait=lambda s: None, clock=lambda: clock[0])
    for i in range(10):
        cr.work(f'10.1111/{i}')


def test_titles_matching_up_to_subtitle():
    # D131: subtitle, collection in parentheses, initial article, apostrophes, HTML entities.
    ok = sources.titles_match
    assert ok('Implicit Meanings', 'Implicit Meanings : Selected Essays in Anthropology', 0.8)
    assert ok('Darwin', 'Darwin (Grands auteurs)', 0.8)
    assert ok('The minds new science', "The Mind's New Science : A History of the Cognitive Revolution", 0.8)
    assert ok('Esquisse d’une théorie de la pratique', "Esquisse d'une théorie de la pratique : Précédé de", 0.8)
    assert ok("Kant's Metaphysics of Morals", 'Kant&amp;apos;s Metaphysics of Morals', 0.8)
    assert not ok('Perception', 'Perceptual Consciousness', 0.8)
    assert not ok('Cognitive dissonance theory', 'Handbook of theories of social psychology', 0.8)


def test_contact_reserved_to_crossref_and_openalex(cfg, fake):
    # D189: the address goes only to the two services that `zc init` announces.
    s = services(cfg, fake)
    assert all('moi@example.org' in x.headers()['User-Agent'] for x in s.sources) and len(s.sources) == 2
    assert all('moi@example.org' not in x.headers()['User-Agent'] for x in [*s.books, s.resolver])


def test_messages_in_english(cfg, fake, tmp_path):
    fake.add(doi='10.1111/a', title='A')
    real = fake.handle
    fake.handle = lambda req: (httpx2.Response(429, headers={'Retry-After': '1'}, json={'message': 'limit reached'})
                               if req.url.host == 'api.crossref.org' else real(req))
    with language('en'):
        s = services(cfg, fake)
        s.work('10.1111/a')
        assert 'crossref: response 429, limit reached' in s.unavailable['crossref']
        assert s.warnings()[0].startswith('Source set aside during this run, crossref: response 429')
        (cfg.workspace / '.env').unlink()
        s2 = services(cfg, fake)
        list(s2.searches('Un titre'))
        assert 'no OPENALEX_API_KEY key in .env' in s2.warnings()[-1]


def test_contact_note_only_when_crossref_or_openalex_queried(cfg, fake):
    """No contact address: a short note, only when Crossref or OpenAlex were actually queried (pilot bench)."""
    cfg.sources.contact = ''
    fake.add(doi='10.1/a', title='Acquisition of color')
    s = services(cfg, fake)
    assert s.contact_note() == ''
    s.book('2707302759')  # book sources only
    assert s.contact_note() == ''
    s.work('10.1/a')
    assert s.contact_note().startswith("Pas d'adresse de contact dans config.toml")
    s.persist()
    s = services(cfg, fake)
    s.work('10.1/a')  # from the cache, nothing sent
    assert s.contact_note() == ''
    with language('en'):
        s = services(cfg, fake)
        s.work('10.1/b')
        assert s.contact_note().startswith('No contact address in config.toml')
    cfg.sources.contact = 'moi@example.org'
    s = services(cfg, fake)
    s.work('10.1/c')
    assert s.contact_note() == ''
