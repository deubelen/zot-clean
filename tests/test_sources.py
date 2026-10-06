from pathlib import Path

import httpx2
import pytest

from faux_sources import FauxServices
from zot_clean import sources
from zot_clean.config import Config


@pytest.fixture
def faux():
    return FauxServices()


@pytest.fixture
def cfg(tmp_path):
    c = Config(dossier_travail=tmp_path)
    c.sources.contact = 'moi@example.org'
    (tmp_path / '.env').write_text('OPENALEX_API_KEY=cle-openalex\n', encoding='utf-8')
    return c


def services(cfg, faux, **kw):
    return sources.depuis_config(cfg, client_http=faux.client(), attendre=lambda s: None, **kw)


def test_lecture_crossref(cfg, faux):
    faux.ajouter(doi='10.1/A', titre='Acquisition of color', subtitle=['A perceptual approach'],
                 **{'container-title': ['Journal of Tests'], 'volume': '131', 'page': '477-493',
                    'editor': [{'family': 'Durand', 'given': 'Anne'}], 'ISSN': ['0096-3445']})
    o = services(cfg, faux).oeuvre('10.1/a')
    assert o.source == 'crossref' and o.type == 'journalArticle'
    assert o.titre == 'Acquisition of color: A perceptual approach'
    assert o.date == '2002-08-01' and o.annee == '2002'
    assert o.auteurs == [['Özgen', 'Emre']] and o.editeurs_scientifiques == [['Durand', 'Anne']]
    assert (o.conteneur, o.volume, o.pages, o.issn) == ('Journal of Tests', '131', '477-493', ['0096-3445'])


def test_openalex_si_crossref_ne_connait_pas(cfg, faux):
    faux.openalex['10.5281/zenodo.1'] = {
        'doi': 'https://doi.org/10.5281/zenodo.1', 'title': 'Un jeu de données', 'type': 'dataset',
        'publication_date': '2020-05-04', 'authorships': [{'author': {'display_name': 'Marie Curie'}}],
        'primary_location': {'source': {'display_name': 'Zenodo'}}, 'biblio': {'first_page': '1', 'last_page': '9'}}
    o = services(cfg, faux).oeuvre('10.5281/zenodo.1')
    assert o.source == 'openalex' and o.auteurs == [['Curie', 'Marie']] and o.pages == '1-9'


def test_cache_et_absence(cfg, faux):
    faux.ajouter(doi='10.1/a', titre='A')
    s = services(cfg, faux)
    assert s.oeuvre('10.1/a').titre == 'A' and s.oeuvre('10.1/a').titre == 'A'
    assert s.oeuvre('10.1/inconnu') is None and s.oeuvre('10.1/inconnu') is None
    assert len(faux.requetes) == 3  # crossref A, crossref inconnu, openalex inconnu
    s.sauver()
    faux.requetes.clear()
    assert services(cfg, faux).oeuvre('10.1/a').titre == 'A' and faux.requetes == []
    services(cfg, faux, rafraichir=True).oeuvre('10.1/a')
    assert len(faux.requetes) == 1


def test_resolveur(cfg, faux):
    faux.handles.add('10.1/datacite')
    s = services(cfg, faux)
    assert s.resolveur.existe('10.1/datacite') and not s.resolveur.existe('10.1/rien')


def test_debit_limite(tmp_path, faux):
    temps, pauses = [0.0], []

    def attendre(s):
        pauses.append(s)
        temps[0] += s
    cr = sources.Crossref(tmp_path, debit=2, client_http=faux.client(), attendre=attendre, horloge=lambda: temps[0])
    for i in range(3):
        cr.oeuvre(f'10.1/{i}')
    assert pauses == [0.5, 0.5]


def test_contact_transmis(cfg, faux):
    s = services(cfg, faux)
    assert 'mailto:moi@example.org' in s.sources[0].entetes()['User-Agent']


def test_similarite():
    assert sources.similarite('Radical Embodied Cognitive Science', 'radical embodied cognitive science') == 1
    assert sources.similarite('Acquisition of categorical color perception',
                              'Acquisition of categorical color perception: a perceptual learning approach') == 0.97
    assert sources.similarite('La morale antique', 'Thought and language') < 0.5


def test_recherche_openalex_nettoyee_et_refus_sans_panne(tmp_path, faux):
    oa = sources.OpenAlex(tmp_path, cle='k', client_http=faux.client(), attendre=lambda s: None)
    assert oa.chercher('What is art... and why should we care?') == []
    assert 'api.openalex.org/works' in faux.requetes
    faux.traiter = lambda req: httpx2.Response(400)
    assert sources.Crossref(tmp_path, client_http=faux.client(), attendre=lambda s: None).oeuvre('10.1111/<x>') is None


def test_source_indisponible_mise_de_cote(cfg, faux):
    faux.ajouter(doi='10.1111/a', titre='A')
    reel = faux.traiter
    faux.traiter = lambda req: (httpx2.Response(429, headers={'Retry-After': '1'},
                                                json={'message': 'limite atteinte'})
                                if req.url.host == 'api.crossref.org' else reel(req))
    s = services(cfg, faux)
    assert s.oeuvre('10.1111/a') is None  # OpenAlex ne le connaît pas
    assert 'crossref' in s.indisponibles and 'limite atteinte' in s.avertissements()[0]
    assert list(s.recherches('A')) == [[]]  # seule OpenAlex est encore consultée
    faux.traiter = reel
    assert services(cfg, faux).oeuvre('10.1111/a').titre == 'A'  # rien n'a été mis en cache


def test_openalex_sans_cle_ne_cherche_pas_mais_lit_par_doi(cfg, faux):
    (cfg.dossier_travail / '.env').unlink()
    faux.openalex['10.5281/z'] = {'doi': 'https://doi.org/10.5281/z', 'title': 'Z'}
    s = services(cfg, faux)
    assert s.oeuvre('10.5281/z').titre == 'Z'
    assert list(s.recherches('Un titre')) == [[]]  # Crossref seule
    assert 'OPENALEX_API_KEY' in s.avertissements()[0]
    assert not any(r == 'api.openalex.org/works' for r in faux.requetes)


def test_plafond_quotidien_des_recherches(tmp_path, faux):
    jour = ['2026-09-28']
    oa = sources.OpenAlex(tmp_path, cle='k', plafond=2, aujourdhui=lambda: jour[0], client_http=faux.client(),
                          attendre=lambda s: None)
    oa.chercher('un'), oa.chercher('deux'), oa.chercher('un')  # la troisième vient du cache
    with pytest.raises(sources.RechercheImpossible, match='plafond'):
        oa.chercher('trois')
    oa.sauver()
    oa2 = sources.OpenAlex(tmp_path, cle='k', plafond=2, aujourdhui=lambda: jour[0], client_http=faux.client())
    with pytest.raises(sources.RechercheImpossible):
        oa2.chercher('quatre')
    jour[0] = '2026-09-29'
    assert oa2.chercher('quatre') == []


def test_notice_unimarc():
    from faux_sources import notice_unimarc
    o = sources.lire_unimarc(notice_unimarc('La distinction', traducteur=('Nice', 'Richard')), 'bnf')
    assert (o.titre, o.date, o.editeur, o.lieu, o.nb_pages, o.collection, o.langue) == (
        'La distinction', '1979', 'Éditions de Minuit', 'Paris', '670', 'Le Sens commun', 'fr')
    assert o.auteurs == [['Bourdieu', 'Pierre']] and o.traducteurs == [['Nice', 'Richard']]
    ancienne = sources.lire_unimarc(notice_unimarc('La Morale antique , par Léon Robin... 2e',
                                                   lieu='Paris, Presses universitaires de France', editeur=''), 'bnf')
    assert (ancienne.titre, ancienne.lieu, ancienne.editeur) == ('La Morale antique', 'Paris',
                                                                 'Presses universitaires de France')


def test_isbn_somme_de_controle():
    assert sources.isbns('2-7073-0275-9, 978-0-262-01322-2') == [('2707302759', True), ('9780262013222', True)]
    assert sources.isbns('2-7073-0275-8') == [('2707302758', False)]
    assert sources.isbns('2-7193-0001-2 2-7193-0002-0 (br.)') == [('2719300012', True), ('2719300020', True)]
    assert sources.isbns('ISBN 978-2-07-036822-8') == [('9782070368228', True)]
    assert sources.isbns('978 90 272 5202 9, 978 90 272 9343 5') == [('9789027252029', True), ('9789027293435', True)]
    assert sources.francophone('2707302759') and sources.francophone('9791012345678')
    assert not sources.francophone('9780262013222')


def test_livre_par_isbn_selon_la_langue(cfg, faux):
    from faux_sources import notice_unimarc
    faux.bnf['2707302759'] = notice_unimarc('La distinction')
    faux.sudoc['9780262013222'] = notice_unimarc('Radical embodied cognitive science', ('Chemero', 'Anthony'), '2009',
                                                 'The MIT Press', 'Cambridge', '978-0-262-01322-2', balise='')
    faux.openlibrary['9780262013222'] = {'title': 'Radical embodied cognitive science', 'publishers': ['MIT Press'],
                                         'authors': [{'key': '/authors/Anthony Chemero'}], 'publish_date': '2009'}
    s = services(cfg, faux)
    assert s.livre('2707302759').source == 'bnf'
    o = s.livre('9780262013222')
    assert o.source == 'openlibrary' and o.auteurs == [['Chemero', 'Anthony']]  # Open Library d'abord hors francophonie
    faux.openlibrary.clear()
    assert services(cfg, faux, rafraichir=True).livre('9780262013222').source == 'sudoc'


def test_source_trop_lente_mise_de_cote(tmp_path, faux):
    temps = [0.0]
    reel = faux.traiter

    def lent(req):
        temps[0] += 25  # chaque réponse met 25 secondes
        return reel(req)
    faux.traiter = lent
    cr = sources.Crossref(tmp_path, client_http=faux.client(), attendre=lambda s: None, horloge=lambda: temps[0])
    cr.oeuvre('10.1111/a'), cr.oeuvre('10.1111/b')
    with pytest.raises(sources.SourceIndisponible, match='trop lent'):
        cr.oeuvre('10.1111/c')


def test_cache_sauve_regulierement(tmp_path, faux):
    temps = [0.0]
    cr = sources.Crossref(tmp_path, client_http=faux.client(), attendre=lambda s: None, horloge=lambda: temps[0])
    cr.oeuvre('10.1111/a')
    assert not cr.fichier.exists()
    temps[0] = 31
    cr.oeuvre('10.1111/b')
    assert cr.fichier.exists()


def test_lenteurs_espacees_toleres(tmp_path, faux):
    temps, n = [0.0], [0]
    reel = faux.traiter

    def parfois_lent(req):
        n[0] += 1
        temps[0] += 25 if n[0] % 2 else 1  # une réponse lente sur deux
        return reel(req)
    faux.traiter = parfois_lent
    cr = sources.Crossref(tmp_path, client_http=faux.client(), attendre=lambda s: None, horloge=lambda: temps[0])
    for i in range(10):
        cr.oeuvre(f'10.1111/{i}')


def test_titres_concordants_a_un_sous_titre_pres():
    # D131 : sous-titre, collection entre parenthèses, article initial, apostrophes, entités HTML.
    ok = sources.titres_concordants
    assert ok('Implicit Meanings', 'Implicit Meanings : Selected Essays in Anthropology', 0.8)
    assert ok('Darwin', 'Darwin (Grands auteurs)', 0.8)
    assert ok('The minds new science', "The Mind's New Science : A History of the Cognitive Revolution", 0.8)
    assert ok('Esquisse d’une théorie de la pratique', "Esquisse d'une théorie de la pratique : Précédé de", 0.8)
    assert ok("Kant's Metaphysics of Morals", 'Kant&amp;apos;s Metaphysics of Morals', 0.8)
    assert not ok('Perception', 'Perceptual Consciousness', 0.8)
    assert not ok('Cognitive dissonance theory', 'Handbook of theories of social psychology', 0.8)


def test_contact_reserve_a_crossref_et_openalex(cfg, faux):
    # D189 : l'adresse ne part qu'aux deux services que `zc init` annonce.
    s = services(cfg, faux)
    assert all('moi@example.org' in x.entetes()['User-Agent'] for x in s.sources) and len(s.sources) == 2
    assert all('moi@example.org' not in x.entetes()['User-Agent'] for x in [*s.livres, s.resolveur])
