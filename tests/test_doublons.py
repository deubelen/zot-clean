import itertools
import tomllib

import pytest

from faux_serveur import FauxServeur
from test_appliquer import ecrire
from zot_clean import annulation, audit, doublons as d, lecture, plans
from zot_clean.appliquer import ESSAI, appliquer
from zot_clean.config import Config


class Double:
    """Fiches créées à la fois dans la base synthétique et sur le faux serveur, avec la même clé."""

    def __init__(self, zotero, serveur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids = {}

    def fiche(self, titre, type_='journalArticle', auteurs=('Durand',), date='2020', ajout='2020-01-01', **champs):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.fiche(titre, type_, auteurs, date, cle=cle, **champs)
        self.serveur.ajouter(type_, key=cle, title=titre, date=date, dateAdded=f'{ajout}T00:00:00Z',
                             creators=[{'creatorType': 'author', 'lastName': a, 'firstName': 'A.'} for a in auteurs],
                             **{k: v for k, v in champs.items() if k in ('DOI', 'ISBN', 'publicationTitle')})
        return cle

    def pdf(self, parent, nom, contenu=b'%PDF identique', annotee=False):
        cle = self.serveur._cle()
        iid = self.zotero.pdf(self.ids[parent], nom, contenu, cle=cle)
        if annotee:
            self.zotero.annotation(iid)
        self.serveur.ajouter('attachment', key=cle, parentItem=parent, title=nom, linkMode='imported_file')
        return cle

    def note(self, parent):
        cle = self.serveur._cle()
        self.serveur.ajouter('note', key=cle, parentItem=parent, note='<p>Ma note</p>')
        return cle

    def bibliotheque(self):
        return lecture.lire(self.zotero.enregistrer())


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def double(zotero, serveur):
    return Double(zotero, serveur)


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


def test_chercher_classe_et_garde_les_decisions(double, cfg):
    a = double.fiche('Radical embodied cognitive science', DOI='10.1/rad')
    b = double.fiche('Radical Embodied Cognitive Science', DOI='10.1/RAD')
    c = double.fiche('La morale antique', type_='book', auteurs=('Robin',), date='1938', ISBN='2-07-036822-X')
    e = double.fiche('La morale antique, nouvelle édition', type_='book', auteurs=('Robin',), date='1963',
                     ISBN='978-2-07-036822-8')
    entrees = d.chercher(double.bibliotheque(), cfg)
    classes = {frozenset(x.cles): x.classe for x in entrees}
    assert classes == {frozenset({a, b}): d.SUR, frozenset({c, e}): d.A_JUGER}
    brut = tomllib.loads((cfg.suivi / d.FICHIER).read_text(encoding='utf-8'))
    assert len(brut['groupe']) == 2

    # L'utilisateur juge le groupe des éditions distinctes et décide de fusionner l'autre.
    texte = (cfg.suivi / d.FICHIER).read_text(encoding='utf-8')
    texte = texte.replace('classe = "à juger"\ndecision = ""', 'classe = "à juger"\ndecision = "distinct"')
    texte = texte.replace('classe = "sûr"\ndecision = ""', 'classe = "sûr"\ndecision = "fusionner"')
    (cfg.suivi / d.FICHIER).write_text(texte, encoding='utf-8')
    entrees = d.chercher(double.bibliotheque(), cfg)
    decisions = {frozenset(x.cles): x.decision for x in entrees}
    assert decisions == {frozenset({a, b}): d.FUSIONNER, frozenset({c, e}): d.DISTINCT}

    b_ = double.bibliotheque()
    section = audit.doublons(b_, cfg)
    assert section.resume.startswith('1 groupe')


def test_fusion_a_la_maniere_de_zotero_puis_annulation(double, serveur, cfg):
    garde = double.fiche('Perceptual learning of categorical colour', publicationTitle='JEP', ajout='2014-01-01')
    absorbee = double.fiche('Perceptual learning of categorical colour', DOI='10.1/col', ajout='2020-01-01')
    pdf_garde = double.pdf(garde, 'a.pdf')
    for n in ('e', 'f'):
        double.pdf(garde, f'{n}.pdf', contenu=f'%PDF {n}'.encode())
    pdf_identique = double.pdf(absorbee, 'b.pdf')
    pdf_annote = double.pdf(absorbee, 'c.pdf', annotee=True)
    pdf_autre = double.pdf(absorbee, 'd.pdf', contenu=b'%PDF autre')
    note = double.note(absorbee)
    serveur.elements[garde]['collections'] = ['COLLAAAA']
    serveur.elements[absorbee].update(collections=['COLLBBBB'], tags=[{'tag': '#norme'}])
    avant = {k: dict(v) for k, v in serveur.elements.items()}

    b = double.bibliotheque()
    d.chercher(b, cfg)
    plan, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    assert len(plan.groupes) == 1
    ops = {op.cle: op for op in plan.groupes[0].operations}
    assert ops[pdf_identique].apres == {'deleted': True}
    assert ops[pdf_annote].apres == {'parentItem': garde} and ops[pdf_autre].apres == {'parentItem': garde}
    assert ops[note].apres == {'parentItem': garde}
    assert 'Ma note' not in ops[note].nature  # D191
    assert ops[garde].apres['DOI'] == '10.1/col' and 'publicationTitle' not in ops[garde].apres
    assert ops[garde].apres['collections'] == ['COLLAAAA', 'COLLBBBB']
    assert ops[garde].apres['relations'] == {'dc:replaces': [serveur.client().uri(absorbee)]}
    assert ops[absorbee].apres == {'deleted': True} and ops[absorbee].rang == 2
    assert pdf_garde not in ops
    assert 'identique' in rapport and 'gardée pour ses annotations ou notes' in ops[pdf_annote].nature
    assert 'Article de revue' in rapport and 'journalArticle' not in rapport

    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['1']
    assert serveur.elements[absorbee]['deleted'] and serveur.elements[note]['parentItem'] == garde
    assert serveur.elements[garde]['tags'] == [{'tag': '#norme'}]

    plan_a, rapport_a = annulation.planifier([bilan.journal], serveur.client(), set())
    assert 'Ma note' not in rapport_a
    appliquer(plan_a, plans.ecrire(plan_a, cfg.plans, ''), serveur.client(), cfg, ESSAI)
    for k, v in avant.items():
        assert {c: x for c, x in serveur.elements[k].items() if c != 'version'} == \
               {c: x for c, x in v.items() if c != 'version'}


def test_types_differents_ecartes(double, serveur, cfg):
    double.fiche('Self-organization in communicating groups', DOI='10.1/so')
    double.fiche('Self-organization in communicating groups', type_='conferencePaper', DOI='10.1/so')
    b = double.bibliotheque()
    entrees = d.chercher(b, cfg)
    assert entrees[0].classe == d.A_JUGER
    texte = (cfg.suivi / d.FICHIER).read_text(encoding='utf-8').replace('decision = ""', 'decision = "fusionner"')
    (cfg.suivi / d.FICHIER).write_text(texte, encoding='utf-8')
    plan, rapport = d.planifier(cfg, serveur.client(), b)
    assert plan.groupes == [] and 'types différents' in rapport


def test_conserver_et_forcer(double, serveur, cfg):
    a = double.fiche('La morale antique de Robin', date='1938', ajout='2010-01-01')
    b = double.fiche('La morale antique de Robin', date='1938', ajout='2020-01-01')
    serveur.elements[b]['extra'] = 'OCLC: 1'
    bib = double.bibliotheque()
    d.chercher(bib, cfg)
    texte = (cfg.suivi / d.FICHIER).read_text(encoding='utf-8')
    texte = texte.replace('decision = ""', 'decision = "fusionner"').replace('conserver = ""', f'conserver = "{b}"')
    texte = texte.replace('forcer = {  }', 'forcer = { "date" = "1938, rééd. 1963" }')
    (cfg.suivi / d.FICHIER).write_text(texte, encoding='utf-8')
    plan, rapport = d.planifier(cfg, serveur.client(), bib)
    ops = {op.cle: op for op in plan.groupes[0].operations}
    assert ops[b].rang == 1 and ops[b].apres['date'] == '1938, rééd. 1963'
    assert ops[a].apres == {'deleted': True}


def test_fiches_qui_partagent_un_pdf(double, cfg):
    """Deux fiches sans rien de commun que leur PDF sont proposées, à juger (D125)."""
    a = double.fiche('Paint and Be Happy', auteurs=('Grant',), date='2011')
    b_ = double.fiche('Loser wins', auteurs=('Ardery',), date='1997')
    c = double.fiche('Sans rapport', auteurs=('Autre',), date='2000')
    double.pdf(a, 'grant.pdf', b'%PDF grant')
    double.pdf(b_, 'grant.pdf', b'%PDF grant')
    double.pdf(c, 'autre.pdf', b'%PDF autre')
    entrees = d.chercher(double.bibliotheque(), cfg)
    assert [(sorted(e.cles), e.classe) for e in entrees] == [(sorted([a, b_]), d.A_JUGER)]


def test_fiches_confidentielles_masquees(double, serveur, cfg):
    garde = double.fiche('Mon dossier médical', DOI='10.1/med', publicationTitle='JEP', tags=('_privé',))
    absorbee = double.fiche('Mon dossier médical', DOI='10.1/med', publicationTitle='Autre revue')
    double.pdf(absorbee, 'Mon dossier médical.pdf', contenu=b'%PDF autre')
    b = double.bibliotheque()
    d.chercher(b, cfg)
    assert 'médical' not in (cfg.suivi / d.FICHIER).read_text(encoding='utf-8')
    plan, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    assert len(plan.groupes) == 1 and plan.groupes[0].titre == '(fiche confidentielle)'
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    for texte in (rapport, chemin.read_text(encoding='utf-8')):
        assert 'médical' not in texte and 'Autre revue' not in rapport


def test_cle_de_citation_de_la_fiche_absorbee_signalee(double, serveur, cfg):
    """Deux fiches fusionnées qui ont chacune une clé : le rapport dit laquelle disparaît (D146)."""
    garde = double.fiche('Embodied cognition', DOI='10.1/emb', ajout='2014-01-01')
    absorbee = double.fiche('Embodied cognition', DOI='10.1/emb', ajout='2020-01-01')
    serveur.elements[garde]['citationKey'] = 'durandEmbodied2020'
    serveur.elements[absorbee]['citationKey'] = 'durandEmbodied2020a'
    b = double.bibliotheque()
    d.chercher(b, cfg)
    plan, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    assert f'clé de citation « durandEmbodied2020a » de {absorbee} qui disparaît' in rapport
    assert 'gardant « durandEmbodied2020 »' in rapport
    # Signalée à part, et non parmi les autres valeurs différentes.
    assert '  - citationKey' not in rapport

    # Fiche conservée sans clé : elle reçoit celle de la fiche absorbée, rien ne disparaît.
    serveur.elements[garde]['citationKey'] = ''  # l'API rend le champ vide
    plan, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    ops = {op.cle: op for op in plan.groupes[0].operations}
    assert ops[garde].apres['citationKey'] == 'durandEmbodied2020a' and 'qui disparaît' not in rapport



def test_fiche_conservee_reprend_la_cle_sans_suffixe(double, serveur, cfg):
    """La fiche conservée porte la clé suffixée par BBT, l'absorbée la clé de base : la conservée prend la clé de base,
    la plus citée, et le rapport dit laquelle disparaît (répétition du pilote, Özgen 2002)."""
    garde = double.fiche('Embodied cognition', DOI='10.1/emb', ajout='2014-01-01')
    absorbee = double.fiche('Embodied cognition', DOI='10.1/emb', ajout='2020-01-01')
    serveur.elements[garde]['citationKey'] = 'durandEmbodied2020a'
    serveur.elements[absorbee]['citationKey'] = 'durandEmbodied2020'
    b = double.bibliotheque()
    d.chercher(b, cfg)
    plan, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    ops = {op.cle: op for op in plan.groupes[0].operations}
    assert ops[garde].apres['citationKey'] == 'durandEmbodied2020'
    assert f'clé de citation « durandEmbodied2020a » de {garde} remplacée par « durandEmbodied2020 »' in rapport
    assert 'qui disparaît' not in rapport

def test_cle_de_citation_masquee_pour_une_fiche_confidentielle(double, serveur, cfg):
    garde = double.fiche('Mon dossier', DOI='10.1/sec', ajout='2014-01-01', tags=('_privé',))
    absorbee = double.fiche('Mon dossier', DOI='10.1/sec', ajout='2020-01-01')
    serveur.elements[garde]['citationKey'] = 'moiDossier2020'
    serveur.elements[absorbee]['citationKey'] = 'moiDossier2020a'
    b = double.bibliotheque()
    d.chercher(b, cfg)
    _, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    assert f'clé de citation de {absorbee} qui disparaît' in rapport and 'Dossier2020' not in rapport


def test_pdf_absents_signales_dans_le_plan(double, serveur, cfg):
    """D168 : sans le fichier, une copie identique est rattachée, et le rapport le dit."""
    garde = double.fiche('Perceptual learning of categorical colour', DOI='10.1/col', ajout='2014-01-01')
    absorbee = double.fiche('Perceptual learning of categorical colour', DOI='10.1/col', ajout='2020-01-01')
    double.pdf(garde, 'a.pdf', None)
    copie = double.pdf(absorbee, 'a.pdf', None)
    b = double.bibliotheque()
    d.chercher(b, cfg)
    plan, rapport = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    ops = {op.cle: op for op in plan.groupes[0].operations}
    assert ops[copie].apres == {'parentItem': garde}
    assert '**Attention.** 2 PDF absents du disque' in rapport and 'rattachée à la fiche conservée' in rapport
    assert d.avertissement(b, cfg, plan).startswith('2 PDF absents')


def test_groupe_ajoute_a_la_main_garde(double, cfg):
    """Un groupe à fusionner que zc ne repère pas reste dans le fichier tant que ses fiches existent."""
    a = double.fiche('Un article sous deux titres', auteurs=('Leroy',), date='2004')
    b_ = double.fiche('Article dont le titre diffère', auteurs=('Leroy',), date='2004')
    cfg.suivi.mkdir(parents=True)
    (cfg.suivi / d.FICHIER).write_text(f'[[groupe]]\ncles = ["{a}", "{b_}"]\ndecision = "fusionner"\n'
                                       f'conserver = "{a}"\n', encoding='utf-8')
    entrees = d.chercher(double.bibliotheque(), cfg)
    assert [(e.cles, e.decision, e.conserver) for e in entrees] == [([a, b_], d.FUSIONNER, a)]
    double.zotero.corbeille(double.ids[b_])
    assert d.chercher(double.bibliotheque(), cfg) == []


def test_decisions_par_commande(double, cfg, monkeypatch, capsys):
    """D177 : les groupes se décident par commande, chacun désigné par la clé de l'une de ses fiches. Seuls les
    groupes encore à juger changent, et le fichier garde ses commentaires."""
    from zot_clean import ecriture
    from zot_clean.cli import main
    a = double.fiche('Radical embodied cognitive science', DOI='10.1/rad')
    b = double.fiche('Radical Embodied Cognitive Science', DOI='10.1/RAD')
    f = double.fiche('Sensorimotor theory', DOI='10.1/sens', auteurs=('Noë',))
    g = double.fiche('Sensorimotor Theory', DOI='10.1/SENS', auteurs=('Noë',))
    c = double.fiche('La morale antique', type_='book', auteurs=('Robin',), date='1938', ISBN='2-07-036822-X')
    e = double.fiche('La morale antique, nouvelle édition', type_='book', auteurs=('Robin',), date='1963',
                     ISBN='978-2-07-036822-8')
    entrees = d.chercher(double.bibliotheque(), cfg)
    with pytest.raises(SystemExit, match='Aucun groupe de doublons.toml ne contient ZZZZZZZZ'):
        d.decider(entrees, fusionner=['ZZZZZZZZ'])
    with pytest.raises(SystemExit, match='Une seule fiche conservée'):
        d.decider(entrees, conserver=[a, b])
    assert d.decider(entrees, distinct=[c], raison='éditions différentes') == (0, 1)
    assert d.decider(entrees, True, conserver=[b], sauf=[f]) == (1, 0)
    par_groupe = {frozenset(x.cles): x for x in entrees}
    assert (par_groupe[frozenset({a, b})].decision, par_groupe[frozenset({a, b})].conserver) == (d.FUSIONNER, b)
    assert par_groupe[frozenset({f, g})].decision == ''
    assert (par_groupe[frozenset({c, e})].decision, par_groupe[frozenset({c, e})].raison) == (
        d.DISTINCT, 'éditions différentes')
    with pytest.raises(SystemExit, match='déjà décidé'):
        d.decider(entrees, fusionner=[e])

    # Par la ligne de commande.
    cfg.dossier_travail.mkdir(exist_ok=True)
    (cfg.dossier_travail / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n',
                                                     encoding='utf-8')

    def sans_cle(cfg):
        raise SystemExit('pas de clé')
    monkeypatch.setattr(ecriture, 'depuis_config', sans_cle)
    dossier = ['--dossier', str(cfg.dossier_travail)]
    assert main(['doublons', 'refuser', c.lower(), *dossier]) == 0
    assert '0 groupe(s) à fusionner, 1 jugé(s) distinct(s)' in capsys.readouterr().out
    assert main(['doublons', 'accepter', '--surs', '--sauf', f, *dossier]) == 0
    assert main(['doublons', 'accepter', g, *dossier]) == 0
    assert main(['doublons', 'accepter', a, *dossier]) == 1
    assert 'déjà décidé' in capsys.readouterr().err
    texte = (cfg.suivi / d.FICHIER).read_text(encoding='utf-8')
    assert texte.startswith(d.EN_TETE) and '# ' + a in texte
    decisions = {frozenset(x.cles): x.decision for x in d.charger_suivi(cfg)}
    assert decisions == {frozenset({a, b}): d.FUSIONNER, frozenset({f, g}): d.FUSIONNER,
                         frozenset({c, e}): d.DISTINCT}


def test_note_ajoutee_a_la_fiche_absorbee_apres_le_plan(double, serveur, cfg):
    # D182 : la fiche absorbée a reçu une note depuis le plan. Ses pièces jointes connues sont rattachées, mais elle
    # ne va pas à la corbeille, et le groupe est présenté comme arrêté après une partie des écritures (D181).
    garde = double.fiche('Perceptual learning of categorical colour', publicationTitle='JEP', ajout='2014-01-01')
    absorbee = double.fiche('Perceptual learning of categorical colour', DOI='10.1/col', ajout='2020-01-01')
    for n in ('a', 'b'):
        double.pdf(garde, f'{n}.pdf', contenu=f'%PDF {n}'.encode())
    pdf = double.pdf(absorbee, 'd.pdf', contenu=b'%PDF autre')
    b = double.bibliotheque()
    d.chercher(b, cfg)
    plan, _ = d.planifier(cfg, serveur.client(), b, avec_surs=True)
    ops = {op.cle: op for op in plan.groupes[0].operations}
    assert ops[absorbee].enfants == [pdf]
    note = serveur.ajouter('note', parentItem=absorbee, note='<p>ajoutée ensuite</p>')
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert note in bilan.conflits['1'] and set(bilan.arretes['1']) == {pdf, garde}
    assert not serveur.elements[absorbee].get('deleted') and serveur.elements[note]['parentItem'] == absorbee
    assert serveur.elements[pdf]['parentItem'] == garde


def test_titre_sur_plusieurs_lignes_dans_le_suivi(double, cfg):
    # D194 : un titre avec un saut de ligne ne casse plus le fichier de suivi et n'y glisse pas de décision.
    titre = 'Un titre\ndecision = "fusionner"\x07 et la suite'
    a = double.fiche(titre, DOI='10.1/multi')
    double.fiche(titre, DOI='10.1/multi')
    d.chercher(double.bibliotheque(), cfg)
    brut = tomllib.loads((cfg.suivi / d.FICHIER).read_text(encoding='utf-8'))
    assert [g['decision'] for g in brut['groupe']] == [''] and a in brut['groupe'][0]['cles']
    assert d.chercher(double.bibliotheque(), cfg)[0].decision == ''


def test_ecrire_toml_garde_les_commentaires_d_en_tete(tmp_path):
    from zot_clean.audit import ecrire_toml
    chemin = tmp_path / 'suivi' / 'essai.toml'
    ecrire_toml(chemin, ['# En-tête\n#\n# suite\n', '[[x]]', '# Titre\r\navec\tretour', 'a = 1', ''])
    assert chemin.read_text(encoding='utf-8') == '# En-tête\n#\n# suite\n\n[[x]]\n# Titre  avec\tretour\na = 1\n'
    with pytest.raises(SystemExit, match='mal formé'):
        ecrire_toml(chemin, ['a = '])
    assert tomllib.loads(chemin.read_text(encoding='utf-8')) == {'x': [{'a': 1}]}
