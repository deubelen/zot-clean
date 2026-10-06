import pytest

from faux_serveur import FauxServeur
from faux_sources import FauxServices, crossref_work
from test_appliquer import ecrire
from test_doublons import Double
from zot_clean import metadonnees as m, plans, sources
from zot_clean.appliquer import ESSAI, appliquer
from zot_clean.config import Config

# Champs d'un article tels que l'API les renvoie, vides compris.
ARTICLE = dict(publicationTitle='', volume='', issue='', pages='', ISSN='', language='', publisher='', place='')


class DoubleMeta(Double):
    def article(self, titre, **champs):
        cle = self.fiche(titre, **champs)
        self.serveur.elements[cle].update({k: v for k, v in ARTICLE.items() if k not in self.serveur.elements[cle]})
        self.serveur.elements[cle].update({k: v for k, v in champs.items() if k in ARTICLE})
        return cle


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def double(zotero, serveur):
    return DoubleMeta(zotero, serveur)


@pytest.fixture
def faux():
    return FauxServices()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


def lancer(fonction, double, cfg, faux, serveur, afficher=None):
    services = sources.depuis_config(cfg, client_http=faux.client(), attendre=lambda s: None)
    return fonction(double.bibliotheque(), cfg, services, serveur.client(), afficher)


def cas_de(cfg):
    return {c.cle: c for c in m.charger_suivi(cfg)}


def test_normaliser_doi():
    assert m.normaliser_doi(' https://dx.doi.org/10.1037/0096-3445.131.4.477. ') == '10.1037/0096-3445.131.4.477'
    assert m.normaliser_doi('doi: 10.1111/x;') == '10.1111/x'
    assert m.normaliser_doi('http://dx.doi.org.ezproxy.exemple.org/10.1016/0010-0277(81)90002-0') == \
        '10.1016/0010-0277(81)90002-0'
    assert m.normaliser_doi('https://www.doi.org/10.1177/146349960505') == '10.1177/146349960505'


def test_forme_corrigee_et_doi_trouve(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/color', titre='Acquisition of categorical color perception')
    a = double.article('Acquisition of categorical color perception', DOI='https://doi.org/10.1111/color.',
                       auteurs=('Özgen',), date='2002')
    b = double.article('Radical embodied cognitive science of learning', auteurs=('Chemero',), date='2009')
    faux.crossref_recherche = [crossref_work('10.2222/rad', 'Radical Embodied Cognitive Science of Learning',
                                             auteurs=(('Chemero', 'Anthony'),), annee=2010)]
    plan, rapport = lancer(m.identifiants, double, cfg, faux, serveur)
    ops = {g.id: g.operations[0] for g in plan.groupes}
    assert ops[a].apres == {'DOI': '10.1111/color'} and ops[a].avant == {'DOI': 'https://doi.org/10.1111/color.'}
    assert ops[b].apres == {'DOI': '10.2222/rad'}
    appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert serveur.elements[a]['DOI'] == '10.1111/color' and serveur.elements[b]['DOI'] == '10.2222/rad'


def test_doi_inconnu_et_discordant_a_juger(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/livre', titre='Un tout autre ouvrage collectif', type_='book')
    inconnu = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                             auteurs=('Martin',), date='1991')
    discordant = double.article('Introduction au volume collectif', DOI='10.1111/livre')
    faux.crossref_recherche = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             auteurs=(('Martin', 'Claire'),), annee=2001)]
    plan, rapport = lancer(m.identifiants, double, cfg, faux, serveur)
    cas = cas_de(cfg)
    assert cas[inconnu].probleme == 'doi_inconnu'
    assert [p.champs for p in cas[inconnu].propositions] == [{'DOI': ''}, {'DOI': '10.1111/situe'}]
    assert cas[discordant].probleme == 'doi_discordant' and cas[discordant].propositions[1].champs == {}
    assert '2 cas à juger' in rapport and plan.groupes == []


def test_cas_tries_en_evidents_et_douteux(double, cfg, faux, serveur):
    # D134 : une seule proposition concorde en tout, le cas est évident et son numéro est retenu d'avance.
    evident = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                             auteurs=('Martin',), date='1991')
    faux.crossref_recherche = [
        crossref_work('10.1111/tard', 'Situated learning in communities of practice', auteurs=(('Martin', 'C'),),
                      annee=2005),
        crossref_work('10.1111/proche', 'Situated learnings in a community of practice', auteurs=(('Martin', 'C'),),
                      annee=1991)]
    _, rapport = lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[evident]
    assert c.probleme == 'doi_inconnu' and c.classe == 'évident' and c.decision == ''
    assert [p.avis for p in c.propositions] == ['', 'année', 'concorde'] and c.choix == 3
    assert 'Dont 1 évident(s)' in rapport
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    assert 'classe = "évident"' in texte and 'avis = "année"' in texte
    faux.crossref_recherche[1]['author'] = [{'family': 'Petit', 'given': 'A'}]
    for f in cfg.cache.glob('*.json'):
        f.unlink()
    lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[evident]
    assert c.classe == 'douteux' and c.propositions[2].avis == 'auteur'


def test_titre_traduit_corrobore_par_auteur_annee_et_revue(double, cfg, faux, serveur):
    # D131 : Cairn donne le titre anglais d'un article français. Auteur, année et revue concordent.
    faux.ajouter(doi='10.1111/rfs', titre='The increased impact of social background on schooling',
                 auteurs=(('Martin', 'Claire'),), annee=2001, **{'container-title': ['Revue française de sociologie']})
    traduit = double.article("L'accroissement de l'effet de l'origine sociale", DOI='10.1111/rfs', auteurs=('Martin',),
                             date='2001', publicationTitle='Revue française de sociologie')
    faux.ajouter(doi='10.1111/autre', titre='Une histoire de la médecine', auteurs=(('Petit', 'Anne'),), annee=2001,
                 **{'container-title': ['Revue française de sociologie']})
    autre = double.article('Les inégalités scolaires', DOI='10.1111/autre', auteurs=('Martin',), date='2001',
                           publicationTitle='Revue française de sociologie')
    lancer(m.identifiants, double, cfg, faux, serveur)
    cas = cas_de(cfg)
    assert traduit not in cas and cas[autre].probleme == 'doi_discordant'


def test_doi_inexistant_remplace_par_un_candidat_certain(double, cfg, faux, serveur):
    # D128 : identifiant JSTOR pris pour un DOI, le vrai DOI de l'éditeur est trouvé avec certitude.
    a = double.article('Situated learning in communities of practice', DOI='10.2307/0000000',
                       auteurs=('Martin',), date='1991')
    faux.crossref_recherche = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             auteurs=(('Martin', 'Claire'),), annee=1991)]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    op = plan.groupes[0].operations[0]
    assert op.apres == {'DOI': '10.1111/situe'} and 'DOI inexistant (10.2307/0000000) remplacé' in op.nature
    assert cas_de(cfg) == {}


def test_decisions_reprises_au_plan_suivant(double, cfg, faux, serveur):
    a = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                       auteurs=('Martin',), date='1991')
    b = double.article('Un article au DOI fantôme', DOI='10.1111/fantome')
    faux.crossref_recherche = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             auteurs=(('Martin', 'Claire'),), annee=2001)]
    lancer(m.identifiants, double, cfg, faux, serveur)
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    blocs = texte.split('[[cas]]')
    blocs = [bl.replace('decision = ""\nchoix = 1', 'decision = "accepter"\nchoix = 2') if a in bl else
             bl.replace('decision = ""', 'decision = "refuser"') if b in bl else bl for bl in blocs]
    (cfg.suivi / m.FICHIER).write_text('[[cas]]'.join(blocs), encoding='utf-8')
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert [(g.id, g.operations[0].apres) for g in plan.groupes] == [(a, {'DOI': '10.1111/situe'})]
    assert cas_de(cfg)[b].decision == 'refuser'


def test_chapitre_jamais_rattache_au_livre(double, cfg, faux, serveur):
    double.fiche('Un volume collectif sur la cognition', type_='bookSection', auteurs=('Petit',), date='2015')
    faux.crossref_recherche = [crossref_work('10.1111/vol', 'Un volume collectif sur la cognition',
                                             auteurs=(('Petit', 'Anne'),), annee=2015, type_='book')]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert plan.groupes == [] and cas_de(cfg) == {}


def test_annee_trop_eloignee_a_juger(double, cfg, faux, serveur):
    a = double.article('Radical embodied cognitive science of learning', auteurs=('Chemero',), date='2001')
    faux.crossref_recherche = [crossref_work('10.2222/rad', 'Radical Embodied Cognitive Science of Learning',
                                             auteurs=(('Chemero', 'Anthony'),), annee=2010)]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert plan.groupes == [] and cas_de(cfg)[a].probleme == 'doi_manquant'


def test_fiche_filtree_jamais_cherchee_par_titre(double, cfg, faux, serveur):
    double.article('Un article très confidentiel', tags=('_privé',))
    lancer(m.identifiants, double, cfg, faux, serveur)
    assert not any('/works' == r.removeprefix('api.crossref.org') for r in faux.requetes)
    assert not any(r.startswith('api.openalex.org/works') for r in faux.requetes)


def test_completer_les_champs_vides(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/color', titre='Acquisition of categorical color perception',
                 **{'container-title': ['Journal of Tests'], 'volume': '131', 'page': '477-493', 'issue': '4'})
    a = double.article('Acquisition of categorical color perception', DOI='10.1111/color', auteurs=('Özgen',),
                       date='2002', volume='13')
    sans_auteur = double.article('Acquisition of categorical color perception, bis', DOI='10.1111/bis', auteurs=())
    faux.ajouter(doi='10.1111/bis', titre='Acquisition of categorical color perception, bis',
                 auteurs=(('Özgen', 'Emre'), ('Davies', 'Ian')))
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    ops = {g.id: g.operations[0] for g in plan.groupes}
    assert ops[a].apres == {'publicationTitle': 'Journal of Tests', 'pages': '477-493', 'issue': '4'}
    assert ops[sans_auteur].apres['creators'] == [
        {'creatorType': 'author', 'lastName': 'Özgen', 'firstName': 'Emre'},
        {'creatorType': 'author', 'lastName': 'Davies', 'firstName': 'Ian'}]
    assert "volume : '13' dans Zotero, '131' chez crossref" in rapport
    appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert serveur.elements[a]['volume'] == '13' and serveur.elements[a]['pages'] == '477-493'


def test_completer_saute_les_doi_discordants_non_juges(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/livre', titre='Un tout autre ouvrage collectif', volume='3')
    a = double.article('Introduction au volume collectif', DOI='10.1111/livre')
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert plan.groupes == [] and '1 fiche(s) sautée(s)' in rapport


def test_forcer_une_valeur(double, cfg, faux, serveur):
    a = double.article('Un article quelconque', date='2020')
    cfg.suivi.mkdir(parents=True)
    (cfg.suivi / m.FICHIER).write_text(
        f'[[cas]]\ncle = "{a}"\nsous_etape = "completer"\nprobleme = "forcer"\ndecision = "accepter"\n'
        'forcer = { "date" = "1998" }\n', encoding='utf-8')
    plan, _ = lancer(m.completer, double, cfg, faux, serveur)
    assert plan.groupes[0].operations[0].apres == {'date': '1998'}


def test_forcer_retire_la_fiche_des_sautees_et_des_differences(double, cfg, faux, serveur):
    """Après un `forcer`, le rapport ne dit plus la fiche sautée ni sa valeur laissée telle quelle."""
    from faux_sources import notice_unimarc
    faux.bnf['2707302759'] = notice_unimarc('La distinction : critique sociale du jugement')
    a = livre(double, 'La morale antique', ISBN='2-7073-0275-9', auteurs=('Robin',), date='1938')
    faux.ajouter(doi='10.1111/col', titre='Acquisition of categorical color perception',
                 **{'container-title': ['Journal of Experimental Psychology: General']})
    b = double.article('Acquisition of categorical color perception', DOI='10.1111/col', auteurs=('Özgen',),
                       date='2002', publicationTitle='Journal of Test Psychology')
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert '1 livre(s) ou chapitre(s) sauté(s)' in rapport and f'- {b} publicationTitle' in rapport
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    (cfg.suivi / m.FICHIER).write_text(
        f'[[cas]]\ncle = "{a}"\nsous_etape = "completer"\nprobleme = "forcer"\ndecision = "accepter"\n'
        'forcer = { "ISBN" = "" }\n'
        f'[[cas]]\ncle = "{b}"\nsous_etape = "completer"\nprobleme = "forcer"\ndecision = "accepter"\n'
        'forcer = { "publicationTitle" = "Journal of Experimental Psychology: General" }\n', encoding='utf-8')
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert 'sauté' not in rapport and f'- {b} publicationTitle' not in rapport
    assert 'Valeurs imposées par un cas `forcer` : ISBN vidé (1), publicationTitle (1).' in rapport
    assert 'Champs remplis : ISBN' not in rapport


def test_doi_introuvable_sans_autre_piste_evident(double, cfg, faux, serveur):
    # D169 : la seule proposition est de retirer un DOI que doi.org ne connaît pas.
    a = double.article('Article propre numéro 1', DOI='10.9999/zc.test.001')
    lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[a]
    assert c.probleme == 'doi_inconnu' and c.classe == 'évident' and c.choix == 1
    assert c.propositions[0].champs == {'DOI': ''} and 'ni doi.org' in c.propositions[0].note


def test_revue_discordante_jamais_certaine(double, cfg, faux, serveur):
    """Titre, auteur et année concordent, mais pas la revue : le candidat est à juger, et douteux."""
    a = double.article('Acquisition of categorical color perception', DOI='10.9999/fictif', auteurs=('Özgen',),
                       date='2002', publicationTitle='Journal of Test Psychology')
    faux.crossref_recherche = [crossref_work('10.1037/vrai', 'Acquisition of categorical color perception',
                                             **{'container-title': ['Journal of Experimental Psychology: General']})]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[a]
    assert plan.groupes == [] and c.classe == 'douteux' and c.propositions[1].avis == 'revue ou ouvrage'
    assert m.conteneurs_concordants('J. Exp. Psychol.', 'Journal of Experimental Psychology')
    assert m.conteneurs_concordants('The Journal of experimental biology', 'Journal of Experimental Biology')
    assert not m.conteneurs_concordants('Psychological Review', 'Psychological Bulletin')
    assert not m.conteneurs_concordants('Mind', 'Mind & Language')


def test_titres_generiques_et_langue():
    assert m.titre_generique('Introduction') and m.titre_generique('Self-Styling')
    assert m.titre_generique('Avant-propos') and not m.titre_generique('Radical embodied cognitive science of learning')
    assert m.langue_du_titre('The origin of language in the brain') == 'en'
    assert m.langue_du_titre('La notion de culture dans les sciences sociales') == 'fr'
    assert m.langue_du_titre('Gestalttheorie') == ''


def test_introduction_jamais_sure(double, cfg, faux, serveur):
    a = double.fiche('Introduction', type_='bookSection', auteurs=('Petit',), date='2015')
    faux.crossref_recherche = [crossref_work('10.1111/intro', 'Introduction', auteurs=(('Petit', 'Anne'),),
                                             annee=2015, type_='book-chapter')]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert plan.groupes == [] and cas_de(cfg)[a].probleme == 'doi_manquant'


def test_chapitre_d_un_autre_ouvrage_pas_sur(double, cfg, faux, serveur):
    a = double.fiche('Perception and action in the embodied mind', type_='bookSection', auteurs=('Petit',),
                     date='2015', bookTitle='Handbook of embodied cognition')
    faux.crossref_recherche = [crossref_work('10.1111/ch', 'Perception and action in the embodied mind',
                                             auteurs=(('Petit', 'Anne'),), annee=2015, type_='book-chapter',
                                             **{'container-title': ['Philosophy of perception today']})]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert plan.groupes == [] and cas_de(cfg)[a].probleme == 'doi_manquant'


def test_editeur_des_articles_et_langue_verifiee(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/en', titre='The origin of language in the brain', publisher='Elsevier BV',
                 language='en', volume='4')
    faux.ajouter(doi='10.1111/fr', titre='La notion de culture dans les sciences sociales', language='en')
    a = double.article('The origin of language in the brain', DOI='10.1111/en')
    b = double.article('La notion de culture dans les sciences sociales', DOI='10.1111/fr')
    plan, _ = lancer(m.completer, double, cfg, faux, serveur)
    ops = {g.id: g.operations[0].apres for g in plan.groupes}
    assert ops[a] == {'volume': '4', 'language': 'en'} and b not in ops


def test_suivi_enrichi_pour_juger(double, cfg, faux, serveur):
    double.article('Radical embodied cognitive science of learning', auteurs=('Chemero',), date='2001',
                   publicationTitle='Revue de test')
    faux.crossref_recherche = [crossref_work('10.2222/rad', 'Radical Embodied Cognitive Science of Learning',
                                             auteurs=(('Chemero', 'Anthony'),), annee=2010, volume='12',
                                             page='1-20', **{'container-title': ['Journal of Mind']})]
    lancer(m.identifiants, double, cfg, faux, serveur)
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    assert 'dans « Revue de test »' in texte
    assert 'dans « Journal of Mind », vol. 12, p. 1-20' in texte


def lancer_types(double, cfg, faux, serveur):
    from zot_clean import lecture
    services = sources.depuis_config(cfg, client_http=faux.client(), attendre=lambda s: None)
    b = double.bibliotheque()
    return m.types(b, cfg, services, serveur.client(), lecture.lire_types(double.zotero.base))


def test_article_devenu_chapitre_puis_annulation(double, cfg, faux, serveur):
    from zot_clean import annulation
    faux.ajouter(doi='10.1111/ch', titre='Perception and action in the embodied mind', type_='book-chapter',
                 auteurs=(('Petit', 'Anne'),), annee=2015)
    a = double.article('Perception and action in the embodied mind', DOI='10.1111/ch', auteurs=('Petit',),
                       date='2015', publicationTitle='Handbook of embodied cognition', issue='4')
    avant = dict(serveur.elements[a])
    plan, rapport = lancer_types(double, cfg, faux, serveur)
    op = plan.groupes[0].operations[0]
    assert op.apres == {'itemType': 'bookSection', 'publicationTitle': '', 'bookTitle': 'Handbook of embodied cognition',
                        'issue': '', 'extra': 'issue : 4'}
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert serveur.elements[a]['itemType'] == 'bookSection' and serveur.elements[a]['bookTitle'].startswith('Handbook')
    plan_a, _ = annulation.planifier([bilan.journal], serveur.client())
    appliquer(plan_a, plans.ecrire(plan_a, cfg.plans, ''), serveur.client(), cfg, ESSAI)
    apres = serveur.elements[a]
    assert all(apres.get(k) == v for k, v in avant.items() if k != 'version')
    assert not apres.get('bookTitle')


def test_passage_au_livre_a_juger_et_completer_attend(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/livre', titre='Radical embodied cognitive science of learning', type_='book',
                 auteurs=(('Chemero', 'Anthony'),), annee=2009, volume='2')
    a = double.article('Radical embodied cognitive science of learning', DOI='10.1111/livre', auteurs=('Chemero',),
                       date='2009')
    plan, _ = lancer_types(double, cfg, faux, serveur)
    assert plan.groupes == [] and cas_de(cfg)[a].probleme == 'type_different'
    assert cas_de(cfg)[a].propositions[0].champs == {'itemType': 'book'}
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert plan.groupes == [] and "leur type diffère" in rapport


def test_roles_non_admis_deviennent_contributeurs(zotero):
    from zot_clean import lecture
    t = lecture.lire_types(zotero.enregistrer())
    d = {'itemType': 'book', 'title': 'T', 'creators': [{'creatorType': 'author', 'lastName': 'A'},
                                                          {'creatorType': 'editor', 'lastName': 'B'}]}
    apres, _, _ = m.conversion(d, 'thesis', t)
    assert [c['creatorType'] for c in apres['creators']] == ['author', 'contributor']


# --- Livres (D90 à D94) ---

LIVRE = dict(ISBN='', publisher='', place='', numPages='', edition='', series='', seriesNumber='', language='')


def livre(double, titre, **champs):
    cle = double.fiche(titre, type_='book', **champs)
    double.serveur.elements[cle].update({k: v for k, v in LIVRE.items() if k not in double.serveur.elements[cle]})
    double.serveur.elements[cle].update({k: v for k, v in champs.items() if k in LIVRE})
    return cle


def test_isbn_manquant_sur_ou_a_juger(double, cfg, faux, serveur):
    from faux_sources import notice_unimarc
    a = livre(double, 'La distinction critique sociale du jugement', auteurs=('Bourdieu',), date='1979',
              publisher='Éditions de Minuit')
    b = livre(double, 'Le métier de sociologue et ses préalables', auteurs=('Bourdieu',), date='1968')
    faux.bnf_recherche = [notice_unimarc('La distinction critique sociale du jugement'),
                          notice_unimarc('La distinction critique sociale du jugement', annee='1992', isbn='')]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert [(g.id, g.operations[0].apres) for g in plan.groupes] == [(a, {'ISBN': '2-7073-0275-9'})]
    # Deux éditions de la même année : à juger.
    faux.bnf_recherche = [notice_unimarc('Le métier de sociologue et ses préalables', annee='1968', isbn='2-7193-0001-2'),
                          notice_unimarc('Le métier de sociologue et ses préalables', annee='1968', isbn='2-7193-0002-0',
                                         editeur='Mouton')]
    for f in cfg.cache.glob('*.json'):
        f.unlink()
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[b]
    assert c.probleme == 'isbn_manquant' and len(c.propositions) == 2


def test_isbn_invalide_a_juger(double, cfg, faux, serveur):
    a = livre(double, 'Un livre au numéro faux', ISBN='2-7073-0275-8, 978-0-262-01322-2')
    lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[a]
    assert c.probleme == 'isbn_invalide' and c.propositions[0].champs == {'ISBN': '9780262013222'}


def test_document_qui_est_un_livre(double, cfg, faux, serveur):
    from faux_sources import notice_unimarc
    from zot_clean import lecture
    a = double.fiche('La distinction critique sociale du jugement', type_='document', auteurs=('Bourdieu',),
                     date='1979')
    faux.bnf_recherche = [notice_unimarc('La distinction critique sociale du jugement')]
    plan, _ = lancer_types(double, cfg, faux, serveur)
    c = cas_de(cfg)[a]
    assert plan.groupes == [] and c.probleme == 'livre_possible'
    assert c.propositions[0].champs == {'itemType': 'book', 'ISBN': '2-7073-0275-9'}
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8').replace('decision = ""', 'decision = "accepter"')
    (cfg.suivi / m.FICHIER).write_text(texte, encoding='utf-8')
    serveur.elements[a]['ISBN'] = ''  # champ absent du type document, présent après conversion
    plan, _ = lancer_types(double, cfg, faux, serveur)
    assert plan.groupes[0].operations[0].apres['itemType'] == 'book'
    assert plan.groupes[0].operations[0].apres['ISBN'] == '2-7073-0275-9'


def test_completer_livre_et_chapitre_par_isbn(double, cfg, faux, serveur):
    from faux_sources import notice_unimarc
    faux.bnf['2707302759'] = notice_unimarc('La distinction : critique sociale du jugement')
    a = livre(double, 'La distinction : critique sociale du jugement', ISBN='2-7073-0275-9', auteurs=('Bourdieu',),
              date='1979')
    ch = double.fiche('Le goût de nécessité', type_='bookSection', ISBN='2-7073-0275-9', auteurs=('Bourdieu',),
                      date='1979')
    serveur.elements[ch].update(bookTitle='', publisher='', place='', series='', ISBN='2-7073-0275-9', language='')
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    ops = {g.id: g.operations[0].apres for g in plan.groupes}
    assert ops[a] == {'publisher': 'Éditions de Minuit', 'place': 'Paris', 'numPages': '670',
                      'series': 'Le Sens commun', 'language': 'fr'}
    assert ops[ch] == {'bookTitle': 'La distinction : critique sociale du jugement', 'publisher': 'Éditions de Minuit',
                       'place': 'Paris', 'series': 'Le Sens commun', 'language': 'fr'}


def test_isbn_d_un_autre_livre_liste_dans_le_rapport(double, cfg, faux, serveur):
    from faux_sources import notice_unimarc
    faux.bnf['2707302759'] = notice_unimarc('La distinction : critique sociale du jugement')
    a = livre(double, 'Le sens pratique', ISBN='2-7073-0275-9', auteurs=('Bourdieu',), date='1980')
    b = livre(double, 'Mes carnets de santé', ISBN='2-7073-0275-9', auteurs=('Bourdieu',), date='1980',
              tags=('_privé',))
    afficher = []
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur, afficher.append)
    assert plan.groupes == [] and '2 livre(s) ou chapitre(s) sauté(s)' in rapport
    assert f"- {a} (ISBN) : 'Le sens pratique' dans Zotero, 'La distinction : critique sociale du jugement' chez bnf" \
           in rapport
    assert f'- {b} (ISBN) : (fiche confidentielle)' in rapport and 'santé' not in rapport
    assert '2/2 livres et chapitres examinés par leur ISBN' in afficher


def test_isbn_d_un_autre_livre_vu_des_identifiants(double, cfg, faux, serveur):
    """Un ISBN valide qui désigne un autre livre est un cas `isbn_discordant`. Jugé juste, `completer` complète
    depuis lui. Retiré, la fiche reste sautée jusqu'à l'application."""
    from faux_sources import notice_unimarc
    faux.bnf['2707302759'] = notice_unimarc('La distinction : critique sociale du jugement')
    a = livre(double, 'La morale antique', ISBN='2-7073-0275-9', auteurs=('Robin',), date='1938')
    lancer(m.identifiants, double, cfg, faux, serveur)
    c = cas_de(cfg)[a]
    assert c.probleme == 'isbn_discordant' and [p.champs for p in c.propositions[:2]] == [{'ISBN': ''}, {}]
    assert c.classe == 'douteux' and 'garder' in c.propositions[1].note
    requetes = len(faux.requetes)
    lancer(m.completer, double, cfg, faux, serveur)
    assert len(faux.requetes) == requetes  # notice déjà en cache
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    (cfg.suivi / m.FICHIER).write_text(texte.replace('decision = ""', 'decision = "accepter"'), encoding='utf-8')
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert plan.groupes[0].operations[0].apres == {'ISBN': ''}
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert plan.groupes == [] and '1 livre(s) ou chapitre(s) sauté(s)' in rapport
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    (cfg.suivi / m.FICHIER).write_text(texte.replace('choix = 1', 'choix = 2'), encoding='utf-8')
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert 'sauté' not in rapport and plan.groupes[0].operations[0].apres['publisher'] == 'Éditions de Minuit'


def test_fiche_confidentielle_masquee(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/sante', titre='Mon dossier médical', type_='book',
                 **{'container-title': ['Revue de santé'], 'volume': '7'})
    discordante = double.article('Mon dossier médical, version longue', DOI='10.1111/autre', tags=('_privé',))
    faux.ajouter(doi='10.1111/autre', titre='Une histoire de la médecine')
    complete = double.article('Mon dossier médical', DOI='10.1111/sante', tags=('_privé',))
    _, rapport = lancer(m.identifiants, double, cfg, faux, serveur)
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    assert cas_de(cfg)[discordante].probleme == 'doi_discordant'
    assert 'médic' not in texte and 'médic' not in rapport
    _, rapport = lancer_types(double, cfg, faux, serveur)
    assert 'médic' not in rapport and 'médic' not in (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    plan, rapport = lancer(m.completer, double, cfg, faux, serveur)
    assert 'médic' not in rapport and 'santé' not in rapport


def test_chapitre_dont_le_directeur_est_saisi_en_premier(double, cfg, faux, serveur):
    # Le directeur de l'ouvrage précède l'auteur du chapitre : c'est l'auteur qui se compare à la source.
    a = double.fiche('World articulating animals in phenomenology', type_='bookSection', auteurs=('Rouse',),
                     editeurs=('Burch',), date='2019', bookTitle='Normativity, Meaning, and Phenomenology')
    faux.crossref_recherche = [crossref_work('10.4324/rouse', 'World Articulating Animals in Phenomenology',
                                             auteurs=(('Rouse', 'Joseph'),), annee=2019, type_='book-chapter',
                                             **{'container-title': ['Normativity, Meaning, and Phenomenology']})]
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert [(g.id, g.operations[0].apres) for g in plan.groupes] == [(a, {'DOI': '10.4324/rouse'})]


def test_valeur_deja_sur_le_serveur_ignoree(double, cfg, faux, serveur):
    # La copie locale a encore l'ancien DOI, le serveur a déjà le nouveau (Zotero pas encore synchronisé).
    faux.ajouter(doi='10.1111/color', titre='Acquisition of categorical color perception')
    a = double.article('Acquisition of categorical color perception', DOI='https://doi.org/10.1111/color',
                       auteurs=('Özgen',), date='2002')
    serveur.elements[a]['DOI'] = '10.1111/color'
    plan, _ = lancer(m.identifiants, double, cfg, faux, serveur)
    assert plan.groupes == []


def test_communication_jamais_retypee_en_chapitre_sans_jugement():
    # D130 : Crossref range en chapitres les communications publiées dans des actes en collection.
    assert not m.transition_sure('conferencePaper', 'bookSection')
    assert m.transition_sure('bookSection', 'conferencePaper')


def test_changement_de_type_sur_refuse(double, cfg, faux, serveur):
    faux.ajouter(doi='10.1111/ch', titre='Perception and action in the embodied mind', type_='book-chapter',
                 auteurs=(('Petit', 'Anne'),), annee=2015)
    a = double.article('Perception and action in the embodied mind', DOI='10.1111/ch', auteurs=('Petit',),
                       date='2015', publicationTitle='Handbook of embodied cognition')
    cfg.suivi.mkdir(parents=True)
    (cfg.suivi / m.FICHIER).write_text(
        f'[[cas]]\ncle = "{a}"\nsous_etape = "types"\nprobleme = "type_different"\ndecision = "refuser"\n'
        '[[cas.propositions]]\nchamps = { "itemType" = "bookSection" }\n', encoding='utf-8')
    plan, _ = lancer_types(double, cfg, faux, serveur)
    assert plan.groupes == [] and cas_de(cfg)[a].decision == 'refuser'


def test_differences_de_pure_forme():
    # D132 : ces écarts ne sont plus listés dans le rapport des compléments.
    f = m.meme_forme
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


def test_types_d_un_groupe_de_doublons(double, cfg, faux, serveur):
    """Doublons à fusionner de types différents, au DOI inconnu des sources : chaque fiche se voit proposer le type
    de l'autre, et une seule des deux propositions peut être acceptée."""
    from zot_clean import doublons
    a = double.article('Self-organization in communicating groups', auteurs=('Heylen',), date='2013',
                       DOI='10.9999/heylen')
    c = double.fiche('Self-organization in communicating groups', type_='conferencePaper', auteurs=('Heylen',),
                     date='2013', DOI='10.9999/heylen')
    serveur.elements[c].update(proceedingsTitle='Actes de test')
    doc = double.fiche('Un document au type par défaut', type_='document', auteurs=('Roux',), date='2011')
    doublons.chercher(double.bibliotheque(), cfg)
    texte = (cfg.suivi / doublons.FICHIER).read_text(encoding='utf-8')
    (cfg.suivi / doublons.FICHIER).write_text(texte.replace('decision = ""', 'decision = "fusionner"'),
                                              encoding='utf-8')
    plan, rapport = lancer_types(double, cfg, faux, serveur)
    cas = cas_de(cfg)
    assert plan.groupes == [] and cas[a].probleme == cas[c].probleme == 'type_doublon'
    assert cas[a].propositions[0].champs == {'itemType': 'conferencePaper'}
    assert cas[c].propositions[0].champs == {'itemType': 'journalArticle'}
    assert f'1 fiche(s) « Document » sans livre trouvé par leur titre ({doc})' in rapport
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    (cfg.suivi / m.FICHIER).write_text(texte.replace('decision = ""', 'decision = "accepter"'), encoding='utf-8')
    plan, rapport = lancer_types(double, cfg, faux, serveur)
    assert plan.groupes == [] and "n'accepter qu'un des deux cas" in rapport
    texte = (cfg.suivi / m.FICHIER).read_text(encoding='utf-8')
    debut, _, fin = texte.partition(f'cle = "{c}"')
    (cfg.suivi / m.FICHIER).write_text(debut + f'cle = "{c}"' + fin.replace('decision = "accepter"',
                                                                            'decision = "refuser"', 1),
                                       encoding='utf-8')
    plan, _ = lancer_types(double, cfg, faux, serveur)
    assert [(g.id, g.operations[0].apres['itemType']) for g in plan.groupes] == [(a, 'conferencePaper')]


def test_decisions_en_bloc(double, cfg, faux, serveur):
    """D172 : les évidents s'acceptent en une commande, sauf ceux que l'utilisateur écarte. Un douteux s'accepte
    avec son numéro de proposition, ou se refuse. Seuls les cas encore à juger changent."""
    evident = double.article('Situated learning in communities of practice', DOI='10.1111/inexistant',
                             auteurs=('Martin',), date='1991')
    ecarte = double.article('Un article au DOI fantôme', DOI='10.1111/fantome')
    douteux = double.article('Perceptual learning', DOI='10.1111/perdu', auteurs=('Gibson',), date='1963')
    refuse = double.article('Encore un fantôme', DOI='10.1111/fantome2')
    faux.crossref_recherche = [crossref_work('10.1111/proche', 'Situated learnings in a community of practice',
                                             auteurs=(('Martin', 'C'),), annee=1991)]
    lancer(m.identifiants, double, cfg, faux, serveur)
    cas = m.charger_suivi(cfg)
    classes = {c.cle: c.classe for c in cas}
    assert classes[evident] == classes[ecarte] == 'évident'
    with pytest.raises(SystemExit, match='Aucun cas à juger pour ZZZZZZZZ'):
        m.decider(cas, accepter={'ZZZZZZZZ': None})
    assert m.decider(cas, refuser=[refuse]) == (0, 1)
    assert m.decider(cas, True, {douteux: 1}, sauf={ecarte}) == (2, 0)
    m.ecrire_suivi(cfg, cas, double.bibliotheque())
    relus = cas_de(cfg)
    assert {k: c.decision for k, c in relus.items()} == {evident: 'accepter', ecarte: '', douteux: 'accepter',
                                                           refuse: 'refuser'}
    assert relus[evident].choix == cas[[c.cle for c in cas].index(evident)].choix
    assert m.decider(m.charger_suivi(cfg), True, sauf={ecarte}) == (0, 0)  # déjà décidés


def test_decision_sur_un_seul_cas_d_une_fiche():
    cas = [m.Cas('ABCD1234', 'identifiants', 'doi_manquant', [m.Proposition({'DOI': '10.1/a'})] * 2),
           m.Cas('ABCD1234', 'identifiants', 'isbn_manquant', [m.Proposition({'ISBN': '978'})])]
    with pytest.raises(SystemExit, match='ABCD1234:doi_manquant, ABCD1234:isbn_manquant'):
        m.decider(cas, accepter={'ABCD1234': 2})
    assert m.decider(cas, accepter={'ABCD1234:doi_manquant': 2}, refuser=['ABCD1234:isbn_manquant']) == (1, 1)
    assert [(c.decision, c.choix) for c in cas] == [('accepter', 2), ('refuser', 1)]


def test_doi_ecarte_jamais_repropose():
    """Un faux DOI retiré (cas accepté, proposition 1) : le candidat écarté ne revient pas en `doi_manquant` quand la
    fiche, désormais sans DOI, est examinée de nouveau (tri de l'Inbox, répétition du pilote)."""
    def abma():
        return m.Proposition({'DOI': '10.1/abma'}, 'crossref', 'Abma 2007')
    retrait = m.Proposition({'DOI': ''}, '', 'retirer le DOI')
    accepte = m.Cas('ABCD1234', m.IDENTIFIANTS, 'doi_inconnu', [retrait, abma()], m.ACCEPTER, 1)
    res = m.fusionner_suivi([accepte], [m.Cas('ABCD1234', m.IDENTIFIANTS, 'doi_manquant', [abma()])], m.IDENTIFIANTS)
    assert [(c.probleme, c.decision, [p.champs['DOI'] for p in c.propositions]) for c in res] == [
        ('doi_manquant', m.REFUSER, ['10.1/abma'])]
    # Passe suivante : le refus reste.
    res = m.fusionner_suivi(res, [m.Cas('ABCD1234', m.IDENTIFIANTS, 'doi_manquant', [abma()])], m.IDENTIFIANTS)
    assert [(c.probleme, c.decision) for c in res] == [('doi_manquant', m.REFUSER)]
    # Un candidat nouveau reste proposé, sans celui qui a été écarté.
    autre = m.Proposition({'DOI': '10.1/autre'}, 'crossref', 'autre')
    res = m.fusionner_suivi([accepte], [m.Cas('ABCD1234', m.IDENTIFIANTS, 'doi_manquant', [abma(), autre])],
                            m.IDENTIFIANTS)
    assert [(c.decision, [p.champs['DOI'] for p in c.propositions]) for c in res] == [('', ['10.1/autre'])]
