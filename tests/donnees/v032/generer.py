"""Génère les fixtures dorées de la version 0.3.2 (D209). À ne lancer qu'avec le code de la 0.3.2.

    ZC_GENERER_V032=1 uv run pytest tests/donnees/v032/generer.py -q

Rejoue, sur la bibliothèque synthétique et le faux serveur, les scénarios des
tests de chaque étape, chacun dans son propre dossier de travail, puis réunit
dans `dossier/` les plans, les journaux et les fichiers de `suivi/`. Écrit aussi
les plans au format 1 (`format1/`, sans les champs apparus avec le format 2),
trois configurations, un descriptif de sauvegarde, et `attendu.json`, calculé par
`tests/test_v032.resultats`. Le code renommé ne sait plus exécuter ce fichier,
qui reste comme trace de la façon dont les fixtures ont été produites.
"""

import itertools
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from conftest import ZoteroFactice
from faux_serveur import FauxServeur
from faux_sources import FauxServices, crossref_work
from test_appliquer import sauvegarde_factice
from test_v032 import resultats
from zot_clean import (annulation, bbt, cles, doublons as d, fonds as f, inbox as i, init, lecture, metadonnees as m,
                       noms, pieces as p, plans, rangement as r, sauvegarde, sources, tags as t)
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.ecriture import ErreurAPI

ICI = Path(__file__).parent
ZOTERO = '/zotero-factice/Zotero'  # dossier Zotero écrit dans les fixtures, à la place du dossier temporaire

pytestmark = pytest.mark.skipif(not os.environ.get('ZC_GENERER_V032'), reason='génération explicite seulement')


class Monde:
    """Collections, fiches et pièces jointes créées à la fois dans la base synthétique et sur le faux serveur."""

    def __init__(self, zotero: ZoteroFactice, serveur: FauxServeur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, nom, parent=None):
        cle = self.serveur.collection(nom, parent)
        self.ids[cle] = self.zotero.collection(nom, self.ids[parent] if parent else None, cle=cle)
        return cle

    def fiche(self, titre, *collections, auteurs=('Durand',), date='2020', tags=(), ajout='2020-01-01', type_='journalArticle',
              **champs):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.fiche(titre, type_, auteurs, date, collections=tuple(self.ids[c] for c in collections),
                                          tags=tags, cle=cle, ajout=f'{ajout} 00:00:00', **champs)
        api = [{'tag': x} if isinstance(x, str) else ({'tag': x[0], 'type': 1} if x[1] == 1 else {'tag': x[0]})
               for x in tags]
        self.serveur.ajouter(type_, key=cle, title=titre, date=date, dateAdded=f'{ajout}T00:00:00Z',
                             collections=list(collections), tags=api,
                             creators=[{'creatorType': 'author', 'lastName': a, 'firstName': 'A.'} for a in auteurs],
                             **champs)
        return cle

    def pdf(self, parent, nom, contenu=b'%PDF identique', titre=None, annotee=False):
        cle = self.serveur._cle()
        iid = self.zotero.pdf(self.ids[parent], nom, contenu, cle=cle, titre=nom if titre is None else titre)
        self.ids[cle] = iid
        if annotee:
            self.zotero.annotation(iid)
        self.serveur.ajouter('attachment', key=cle, parentItem=parent, title=nom if titre is None else titre,
                             linkMode='imported_file', contentType='application/pdf', filename=nom, md5='abc')
        return cle

    def lire(self):
        self.zotero.synchroniser(self.serveur.version)
        return lecture.lire(self.zotero.enregistrer())


@pytest.fixture
def scenario(tmp_path, base_vide):
    """Fabrique d'un scénario : son Zotero factice, son faux serveur et son dossier de travail."""
    n = itertools.count(1)

    def creer(nom: str) -> tuple[Monde, Config]:
        k = next(n)
        zotero = ZoteroFactice(tmp_path / f'{k}-{nom}' / 'Zotero', base_vide)
        cfg = Config(dossier_travail=tmp_path / f'{k}-{nom}' / 'travail', dossier_zotero=zotero.dossier)
        cfg.dossier_travail.mkdir()
        return Monde(zotero, FauxServeur()), cfg
    return creer


def ecrire(plan, cfg):
    return plans.ecrire(plan, cfg.plans, '# rapport')


def annuler(chemin, monde, cfg, modes=(ESSAI,)):
    plan, _ = annulation.planifier(annulation.journaux_vises(chemin, cfg), monde.serveur.client(), set())
    c = ecrire(plan, cfg)
    for mode in modes:
        appliquer(plan, c, monde.serveur.client(), cfg, mode)
    return c


# --- Scénarios, repris des tests de chaque étape ------------------------------------

def doublons(monde, cfg):
    """Fusion à la manière de Zotero, puis annulation (test_doublons) ; deux éditions jugées distinctes."""
    garde = monde.fiche('Perceptual learning of categorical colour', publicationTitle='JEP', ajout='2014-01-01')
    absorbee = monde.fiche('Perceptual learning of categorical colour', DOI='10.1/col')
    monde.pdf(garde, 'a.pdf')
    monde.pdf(absorbee, 'b.pdf')
    monde.pdf(absorbee, 'c.pdf', annotee=True)
    monde.fiche('La morale antique', type_='book', auteurs=('Robin',), date='1938', ISBN='2-07-036822-X')
    monde.fiche('La morale antique, nouvelle édition', type_='book', auteurs=('Robin',), date='1963',
                ISBN='978-2-07-036822-8')
    b = monde.lire()
    entrees = d.chercher(b, cfg)
    for e in entrees:
        e.decision = d.FUSIONNER if e.classe == d.SUR else d.DISTINCT
        e.raison = '' if e.classe == d.SUR else 'éditions différentes'
    d.ecrire_suivi(cfg, entrees, b)
    plan, _ = d.planifier(cfg, monde.serveur.client(), b)
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plan, chemin, monde.serveur.client(), cfg, ESSAI)
    assert bilan.faits
    annuler(chemin, monde, cfg)


def pdf_identiques(monde, cfg):
    """Corbeille et rattachement (test_pieces), appliqués par l'essai."""
    fi = {n: monde.fiche(n) for n in ('Paint and Be Happy', 'Loser wins', 'Mind in society', 'The practice turn',
                                      'Throwing out the tacit rule book', 'Le bon article', 'Un autre article')}
    grant, ardery = monde.pdf(fi['Paint and Be Happy'], 'grant.pdf', b'%PDF grant'), \
        monde.pdf(fi['Loser wins'], 'grant.pdf', b'%PDF grant')
    v1, v2 = monde.pdf(fi['Mind in society'], 'v.pdf', b'%PDF v'), monde.pdf(fi['Mind in society'], 'v2.pdf', b'%PDF v')
    livre = monde.pdf(fi['The practice turn'], 'livre.pdf', b'%PDF livre')
    chapitre = monde.pdf(fi['Throwing out the tacit rule book'], 'livre.pdf', b'%PDF livre')
    bon = monde.pdf(fi['Le bon article'], 'a.pdf', b'%PDF annote')
    mauvais = monde.pdf(fi['Un autre article'], 'a.pdf', b'%PDF annote', annotee=True)
    b = monde.lire()
    decisions = {frozenset((grant, ardery)): (p.APPLIQUER, [ardery], {}, ''),
                 frozenset((v1, v2)): (p.APPLIQUER, [v2], {}, ''),
                 frozenset((livre, chapitre)): (p.GARDER, [], {}, 'chapitre et livre entier'),
                 frozenset((bon, mauvais)): (p.APPLIQUER, [bon], {mauvais: fi['Le bon article']}, '')}
    entrees = p.chercher(b, cfg)
    for e in entrees:
        e.decision, e.corbeille, e.rattacher, e.raison = decisions[frozenset(e.copies)]
    p.ecrire(cfg, entrees, b)
    plan, _ = p.planifier(cfg, monde.serveur.client(), b)
    appliquer(plan, ecrire(plan, cfg), monde.serveur.client(), cfg, ESSAI)


def metadonnees(monde, cfg):
    """DOI corrigé et cas à juger (identifiants), article devenu chapitre (types), champs complétés (completer)."""
    faux = FauxServices()
    services = sources.depuis_config(cfg, client_http=faux.client(), attendre=lambda s: None)
    vides = dict(publicationTitle='', volume='', issue='', pages='', ISSN='', language='', publisher='', place='')

    def article(titre, **champs):
        cle = monde.fiche(titre, **champs)
        monde.serveur.elements[cle].update({k: v for k, v in vides.items() if k not in champs})
        return cle

    faux.ajouter(doi='10.1111/color', titre='Acquisition of categorical color perception')
    article('Acquisition of categorical color perception', DOI='https://doi.org/10.1111/color.', auteurs=('Özgen',),
            date='2002')
    article('Situated learning in communities of practice', DOI='10.1111/inexistant', auteurs=('Martin',), date='1991')
    faux.crossref_recherche = [crossref_work('10.1111/situe', 'Situated learning in communities of practice',
                                             auteurs=(('Martin', 'Claire'),), annee=2001)]
    faux.ajouter(doi='10.1111/ch', titre='Perception and action in the embodied mind', type_='book-chapter',
                 auteurs=(('Petit', 'Anne'),), annee=2015)
    article('Perception and action in the embodied mind', DOI='10.1111/ch', auteurs=('Petit',), date='2015',
            publicationTitle='Handbook of embodied cognition', issue='4')
    faux.ajouter(doi='10.1111/vol', titre='Categorical perception of colour in the left and right visual field',
                 auteurs=(('Drivonikou', 'Gilda'),), annee=2007,
                 **{'container-title': ['PNAS'], 'volume': '104', 'page': '1097-1102', 'issue': '3'})
    article('Categorical perception of colour in the left and right visual field', DOI='10.1111/vol',
            auteurs=('Drivonikou',), date='2007')
    plan, _ = m.identifiants(monde.lire(), cfg, services, monde.serveur.client(), None)
    ecrire(plan, cfg)
    cas = m.charger_suivi(cfg)
    m.decider(cas, refuser=[c.cle for c in cas if c.classe != 'évident'][:1])
    m.ecrire_suivi(cfg, cas, monde.lire())
    b = monde.lire()
    plan, _ = m.types(b, cfg, services, monde.serveur.client(), lecture.lire_types(monde.zotero.base))
    ecrire(plan, cfg)
    plan, _ = m.completer(monde.lire(), cfg, services, monde.serveur.client(), None)
    ecrire(plan, cfg)
    services.sauver()


PLAN_40 = """\
# 40 Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.
Inclut. Psychophysique des couleurs.
Exclut. Neurologie clinique.

#### Apprentissage perceptif

Apprendre à percevoir.

### Émotion

Émotions.

## Arts

Arts visuels.

# Concepts
"""


def rangement(monde, cfg):
    """Plan du fonds validé, décisions de rangement, fiches examinées et laissées, plan appliqué (test_rangement),
    puis un audit, pour l'instantané et la mémoire des collections du fonds."""
    cfg.methode.fonds, cfg.methode.archives, cfg.methode.projets = '40 Fonds', '80 Archives', ['20 Cours']
    k = {'Inbox': monde.collection('Inbox'), 'Fonds': monde.collection('40 Fonds'),
         'Archives': monde.collection('80 Archives'), 'Cours': monde.collection('20 Cours'),
         'Vieux': monde.collection('Vieux')}
    k['Psy'] = monde.collection('Psychologie', k['Fonds'])
    k['Perception'] = monde.collection('Perception', k['Psy'])
    k['Emotions'] = monde.collection('Émotions', k['Psy'])
    k['Arts'] = monde.collection('Arts', k['Fonds'])
    k['Musees'] = monde.collection('Musées', k['Arts'])
    k['Ancien'] = monde.collection('Cours ancien', k['Vieux'])
    k['CoursPsy'] = monde.collection('Psy L1', k['Cours'])
    fi = {'voir': monde.fiche('Learning to see', k['Perception'], k['CoursPsy']),
          'gibson': monde.fiche('Perceptual learning', k['Perception']),
          'expertise': monde.fiche('Perceptual expertise', k['Perception'], tags=('apprentissage visuel',)),
          'peur': monde.fiche('Fear and faces', k['Emotions']),
          'musee': monde.fiche('Museum displays', k['Musees']),
          'vieux': monde.fiche('Une vieille chose', k['Vieux']),
          'manuel': monde.fiche('Introducing HTML5', k['Arts']),
          'ancien': monde.fiche('Syllabus 2019', k['Ancien']),
          'vague': monde.fiche('Notes diverses')}
    b = monde.lire()
    (cfg.dossier_travail / f.PLAN).write_text(PLAN_40, encoding='utf-8')
    _, suivi, _, _ = f.inventaire(b, cfg)
    sorts = {'40 Fonds/Psychologie': (f.THEME, 'Psychologie', []),
             '40 Fonds/Psychologie/Perception': (f.REPARTIR, '', ['Psychologie/Perception',
                                                                   'Psychologie/Perception/Apprentissage perceptif']),
             '40 Fonds/Psychologie/Émotions': (f.THEME, 'Psychologie/Émotion', []),
             '40 Fonds/Arts': (f.THEME, 'Arts', []), '40 Fonds/Arts/Musées': (f.THEME, 'Arts', []),
             'Vieux': (f.DISSOUDRE, '', []), 'Vieux/Cours ancien': (f.ARCHIVES, '', [])}
    for c in suivi.collections:
        if c.chemin in sorts:
            c.sort, c.cible, c.candidats = sorts[c.chemin]
        if c.chemin == 'Vieux':
            c.note = 'plus utilisée'
    suivi.tags['apprentissage visuel'] = 'Psychologie/Perception/Apprentissage perceptif'
    f.ecrire_suivi(cfg, suivi)
    controle = f.controler(cfg)
    assert not controle.erreurs, controle.erreurs
    f.enregistrer(cfg, controle)
    r.ecrire(cfg, [
        r.Entree(fi['voir'], r.DEPLACER, 'Psychologie/Perception/Apprentissage perceptif', decision=r.ACCEPTER),
        r.Entree(fi['manuel'], r.CORBEILLE, source=r.CONSIGNE, decision=r.ACCEPTER),
        r.Entree(fi['gibson'], r.AJOUTER, 'Psychologie/Perception', note='reste aussi dans Perception'),
    ], b, set())
    _, _, ajouts = r.a_ranger(b, cfg)  # la fiche taguée reçoit une proposition de source « tag »
    assert ajouts == 1
    entrees = r.charger(cfg)
    for x in entrees:
        x.decision = x.decision or (r.ACCEPTER if x.source == r.TAG else r.REFUSER)
    r.ecrire(cfg, entrees, b, set())
    r.marquer_examinees(b, cfg, [k['Perception']])
    r.laisser(b, cfg, [fi['vague']])
    plan, _ = r.planifier(b, cfg, monde.serveur.client())
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, monde.serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    bilan = appliquer(plan, chemin, monde.serveur.client(), cfg, TOUT)
    assert not bilan.conflits and not bilan.erreurs
    # Audit en ligne de commande, sur un config.toml qui désigne ce Zotero.
    from zot_clean.cli import main
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n\n[methode]\nfonds = "40 Fonds"\n'
        'archives = "80 Archives"\nprojets = ["20 Cours"]\n', encoding='utf-8')
    assert main(['audit', '--dossier', str(cfg.dossier_travail), '--hors-ligne']) == 0
    shutil.rmtree(cfg.rapports)
    # Sauvegarde réelle, dont seul le descriptif est gardé.
    info = sauvegarde.sauvegarder(cfg, ouvert=lambda: False)
    return info.dossier


PLAN_TAGS = PLAN_40.replace('# 40 Fonds', '# Fonds')


def tags_(monde, cfg):
    """Règles acceptées, plan avec les couleurs, essai, conflit, reste, puis annulation partielle (test_tags)."""
    cfg.methode.fonds = 'Fonds'
    (cfg.dossier_travail / 'plan.md').write_text(PLAN_TAGS, encoding='utf-8')
    k = {'Inbox': monde.collection('Inbox'), 'Fonds': monde.collection('Fonds')}
    k['Psy'] = monde.collection('Psychologie', k['Fonds'])
    P = k['Perception'] = monde.collection('Perception', k['Psy'])
    E = k['Emotion'] = monde.collection('Émotion', k['Psy'])
    k['Arts'] = monde.collection('Arts', k['Fonds'])
    x = {'f1': monde.fiche('Learning to see', P, tags=(('Humans', 1), ('Attention', 1), 'to read',
                                                       'perception visuelle', 'mémoire', ('Vision', 1))),
         'f2': monde.fiche('Perceptual learning', P, tags=(('Humans', 1), ('Attention', 1), 'perception visuelle',
                                                           '3 lu', 'to read')),
         'f3': monde.fiche('Fear and faces', E, tags=(('Attention', 1), 'émotion', 'mémoire')),
         'f4': monde.fiche('Emotional memory', E, tags=(('Attention', 1), ('Emotion', 1))),
         'f5': monde.fiche('Moods', E, tags=(('Attention', 1), 'emotions', 'Machine-Learning')),
         'f6': monde.fiche('Une chose', k['Arts'], tags=('truc divers', 'machine learning')),
         'f7': monde.fiche('Rouge et noir', k['Arts'], tags=('rouge', '_zotfile')),
         'f9': monde.fiche('Importée', k['Arts'], tags=tuple(f'mot-clé {n}' for n in range(10))),
         'secret': monde.fiche('Dossier médical', tags=('_privé', 'patient Dupont', ('Secretauto', 1)))}
    monde.zotero.couleur('rouge')
    monde.zotero.recherche('Vision', 'Vision')
    b = monde.lire()
    _, suivi = t.inventaire(b, cfg)
    suivi.automatiques = suivi.importes = t.ACCEPTER
    for e in suivi.tags:
        if e.nom == 'émotion':
            e.sort, e.note = t.GARDER, 'double le thème, gardé'
        e.decision = t.REFUSER if e.nom == 'mémoire' else t.ACCEPTER
    for g in suivi.variantes:
        g.decision = t.ACCEPTER
    suivi.a_ranger = []
    t.ecrire(cfg, suivi, b)
    plan, _ = t.planifier(b, cfg, monde.serveur.client())
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, monde.serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    monde.serveur.modifier(x['f6'], tags=[{'tag': 'truc divers'}, {'tag': 'machine learning'}, {'tag': 'ajouté'}])
    bilan = appliquer(plan, chemin, monde.serveur.client(), cfg, TOUT)
    assert bilan.conflits
    # Un tag ajouté depuis à une fiche : l'annulation laisse ce champ et marque son groupe « partiel ».
    monde.serveur.modifier(x['f4'], tags=[{'tag': '#attention'}, {'tag': 'émotion'}, {'tag': 'ajouté'}])
    annuler(chemin, monde, cfg, modes=(ESSAI, TOUT))


def cles_(monde, cfg):
    """Doubles et lignes d'Extra (test_cles), décisions prises, essai interrompu sans réponse de Zotero."""
    cfg.ecriture.essai = 2
    x = {nom: monde.fiche(f'Article {nom}', citationKey=cle, extra=extra, ajout=ajout)
         for nom, cle, extra, ajout in (('A', 'durand2020', '', '2020-01-01'), ('B', 'Durand2020', '', '2021-01-01'),
                                        ('C', 'durand2020', '', '2022-01-01'),
                                        ('E', '', 'tex.ids: vieux\nCitation Key: martin2019', '2020-01-01'),
                                        ('F', 'lee2018', 'Citation Key: lee2018', '2020-01-01'),
                                        ('G', 'kim2017', 'Citation Key: park2017', '2020-01-01'),
                                        ('H', 'zhang2016', '', '2016-01-01'), ('K', 'zhang2016', '', '2025-01-01'))}
    etat = bbt.Etat(installe=True, actif=True, version='9.1.0', source=bbt.PROFIL)
    cles.planifier(monde.lire(), cfg, monde.serveur.client(), etat)
    # Décisions comme `zc cles decider B=garder H=écarter G=natif`.
    s = cles.charger(cfg)
    assert cles.decider(s, {x['B']: 'garder', x['H']: 'écarter', x['G']: 'natif'}, 'décidé pour les fixtures') == 3
    b = monde.lire()
    cles.ecrire(cfg, b, cles.analyser(b, cfg, etat, s, avec_extra=True), set(), s)
    plan, _ = cles.planifier(monde.lire(), cfg, monde.serveur.client(), etat)
    monde.serveur.reponses_perdues = 10  # écrit au premier envoi, puis aucune réponse : la commande s'arrête
    with pytest.raises(ErreurAPI):
        appliquer(plan, ecrire(plan, cfg), monde.serveur.client(), cfg, ESSAI)


def noms_(monde, cfg):
    """Fichiers en retard sur le modèle de Zotero (test_noms), essai seul sur deux des quatre groupes."""
    cfg.ecriture.essai = 2
    for titre, nom, titre_pj in (('Titre court', 'scan.pdf', None), ('Deux PDF', 'article.pdf', 'ARTICLE'),
                                 ('casse', 'Durand - 2020 - Casse.pdf', 'Texte intégral'),
                                 ('Autre retard', 'x.pdf', 'PDF')):
        monde.pdf(monde.fiche(titre), nom, b'%PDF-1.4 factice', titre=titre_pj)
    plan, _ = noms.planifier(monde.lire(), cfg, monde.serveur.client(), {}, bbt.ZOTERO_ORG)
    bilan = appliquer(plan, ecrire(plan, cfg), monde.serveur.client(), cfg, ESSAI)
    assert bilan.restants


PLAN_INBOX = """\
# Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.

## Arts

Arts visuels.

# Concepts
"""


def inbox(monde, cfg):
    """Tri de bout en bout (test_inbox) : fusion, champs complétés, rangement."""
    cfg.methode.projets = ['Cours']
    faux = FauxServices()
    services = sources.depuis_config(cfg, client_http=faux.client(), attendre=lambda s: None)
    vides = dict(publicationTitle='', volume='', issue='', pages='', ISSN='', language='')
    k = {'Inbox': monde.collection('Inbox'), 'Fonds': monde.collection('Fonds'), 'Cours': monde.collection('Cours')}
    k['Psy'] = monde.collection('Psychologie', k['Fonds'])
    k['Perception'] = monde.collection('Perception', k['Psy'])
    k['Arts'] = monde.collection('Arts', k['Fonds'])
    k['L1'] = monde.collection('Psy L1', k['Cours'])

    def fiche(titre, *cols, auteur='Durand', **champs):
        cle = monde.fiche(titre, *cols, auteurs=(auteur,), **champs)
        monde.serveur.elements[cle].update({c: v for c, v in vides.items() if c not in champs})
        return cle

    fi = {'gibson': fiche('The ecological approach to visual perception', k['Perception'], auteur='Gibson'),
          'ancienne': fiche('Museum displays and their publics', k['Arts'], DOI='10.1111/musee'),
          'nouvelle': fiche('Perceptual learning revisited', k['Inbox'], auteur='Gibson', DOI='10.1111/appr'),
          'double': fiche('Museum displays and their publics', k['Inbox'], DOI='10.1111/musee'),
          'projet': fiche('Teaching perception to first-year students', k['L1'])}
    b = monde.lire()
    (cfg.dossier_travail / f.PLAN).write_text(PLAN_INBOX, encoding='utf-8')
    _, suivi, _, _ = f.inventaire(b, cfg)
    sorts = {'Fonds/Psychologie': (f.THEME, 'Psychologie'), 'Fonds/Psychologie/Perception':
             (f.THEME, 'Psychologie/Perception'), 'Fonds/Arts': (f.THEME, 'Arts')}
    for c in suivi.collections:
        if c.chemin in sorts:
            c.sort, c.cible = sorts[c.chemin]
    f.ecrire_suivi(cfg, suivi)
    f.enregistrer(cfg, f.controler(cfg))
    faux.ajouter(doi='10.1111/appr', titre='Perceptual learning revisited', auteurs=(('Gibson', 'Eleanor'),),
                 annee=2020, volume='12', **{'container-title': ['Cognition']})
    faux.ajouter(doi='10.1111/musee', titre='Museum displays and their publics', auteurs=(('Durand', 'A'),),
                 annee=2020)
    schema = lecture.lire_types(monde.zotero.base)
    i.preparer(b, cfg, services, monde.serveur.client(), schema)
    entrees = d.charger_suivi(cfg)
    for e in entrees:
        e.decision, e.conserver = d.FUSIONNER, fi['ancienne']
    d.ecrire_suivi(cfg, entrees, b)
    r.ecrire(cfg, [r.Entree(fi['nouvelle'], r.DEPLACER, 'Psychologie/Perception', k['Inbox'], decision=r.ACCEPTER),
                   r.Entree(fi['projet'], r.AJOUTER, 'Arts', decision=r.ACCEPTER)], b, set())
    plan, _ = i.planifier(b, cfg, services, monde.serveur.client(), schema)
    bilan = appliquer(plan, ecrire(plan, cfg), monde.serveur.client(), cfg, ESSAI)
    assert not bilan.conflits and not bilan.erreurs


# --- Assemblage ---------------------------------------------------------------------

def _reunir(sources_: list[Path], cible: Path, sous: str) -> None:
    (cible / sous).mkdir(parents=True, exist_ok=True)
    for travail in sources_:
        for x in sorted((travail / sous).glob('*')):
            if x.suffix == '.md':
                continue
            dest = cible / sous / x.name
            assert not dest.exists(), dest
            shutil.copy2(x, dest)


def _format1(plan_json: dict) -> dict:
    """Le même plan, tel que l'écrivait une version d'avant le format 2 : ni `enfants` ni `exige` (D182, D183), ni
    `genre` et `creation` à leur valeur par défaut (avant D114), empreinte sans les journaux annulés (D180)."""
    plan_json = json.loads(json.dumps(plan_json))
    for g in plan_json['groupes']:
        for o in g['operations']:
            for c in ('enfants', 'exige'):
                o.pop(c, None)
            if o.get('genre') == 'items':
                del o['genre']
            if o.get('creation') is False:
                del o['creation']
    groupes = [plans.Groupe(g['id'], g['titre'], [plans.Operation(**o) for o in g['operations']])
               for g in plan_json['groupes']]
    plan = plans.Plan(plan_json['etape'], plan_json['bibliotheque'], groupes, plan_json['description'],
                      plan_json['partiel'], plan_json['annule'], plan_json['cree'], 1)
    return dict(plan_json, format=1, empreinte=plan.empreinte)


def test_generer(scenario):
    for x in ('dossier', 'format1', 'configs', 'sauvegardes', 'attendu.json'):
        if (ICI / x).is_dir():
            shutil.rmtree(ICI / x)
        elif (ICI / x).exists():
            (ICI / x).unlink()
    travaux = {}
    for nom, fonction in (('tags', tags_), ('inbox', inbox), ('doublons', doublons), ('pieces', pdf_identiques),
                          ('metadonnees', metadonnees), ('cles', cles_), ('noms', noms_), ('rangement', rangement)):
        time.sleep(1.1)  # journaux et plans sont nommés à la seconde : aucun nom commun entre deux scénarios
        monde, cfg = scenario(nom)
        retour = fonction(monde, cfg)
        travaux[nom] = (cfg.dossier_travail, retour)
    dossier = ICI / 'dossier'
    _reunir([w for w, _ in travaux.values()], dossier, 'plans')
    _reunir([w for w, _ in travaux.values()], dossier, 'journal')
    (dossier / 'journal' / 'commandes.jsonl').unlink()  # durées de l'audit, propres à cette machine
    # Suivi : chaque fichier vient du scénario de son étape, le fonds et le rangement d'un seul scénario cohérent.
    (dossier / 'suivi').mkdir()
    origine = {'doublons.toml': 'doublons', 'pieces.toml': 'pieces', 'metadonnees.toml': 'metadonnees',
               'tags.toml': 'tags', 'cles.toml': 'cles', 'fonds.toml': 'rangement', 'fonds-validation.json': 'rangement',
               'rangement.toml': 'rangement', 'rangement-examinees.json': 'rangement',
               'rangement-laissees.json': 'rangement', 'fonds-collections.json': 'rangement', 'audits': 'rangement'}
    for fichier, nom in origine.items():
        source = travaux[nom][0] / 'suivi' / fichier
        (shutil.copytree if source.is_dir() else shutil.copy2)(source, dossier / 'suivi' / fichier)
    shutil.copytree(travaux['metadonnees'][0] / 'cache', dossier / 'cache')  # réponses des sources
    travail_rangement = travaux['rangement'][0]
    shutil.copy2(travail_rangement / 'plan.md', dossier / 'plan.md')
    config_toml = (travail_rangement / 'config.toml').read_text(encoding='utf-8')
    _, _, reste = config_toml.partition('\n')
    (dossier / 'config.toml').write_text(f'[zotero]\ndossier = "{ZOTERO}"\n' + reste.partition('\n')[2],
                                         encoding='utf-8')
    # Plans au format 1.
    (ICI / 'format1').mkdir()
    for chemin in sorted((dossier / 'plans').glob('*.json')):
        contenu = _format1(json.loads(chemin.read_text(encoding='utf-8')))
        (ICI / 'format1' / chemin.name).write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding='utf-8')
    # Configurations : minimale, écrite par `zc init`, et ancienne (une seule racine de projets, clé retirée).
    configs = ICI / 'configs'
    for nom in ('minimale', 'init', 'ancienne'):
        (configs / nom).mkdir(parents=True)
    (configs / 'minimale' / 'config.toml').write_text(f'[zotero]\ndossier = "{ZOTERO}"\n', encoding='utf-8')
    assert init.ecrire_config(configs / 'init', Path(ZOTERO), True, 'auteur@exemple.org')
    (configs / 'ancienne' / 'config.toml').write_text(
        f'[zotero]\ndossier = "{ZOTERO}"\n\n[methode]\nprojets = "10 Projets"\nmodele_fichier = "{{{{ authors }}}}"\n'
        'etats = ["à lire", "lu"]\n\n[sauvegarde]\ndossier = "/sauvegardes-factices"\ndelai_heures = 48\n'
        'conserver = 3\n\n[confidentialite]\ntags_exclus = ["_privé", "_perso"]\ncollections_exclues = ["Fonds/Privé"]\n'
        '\n[sources]\ncontact = "auteur@exemple.org"\nbnf = false\n\n[metadonnees]\nexclus_par_type = '
        '{ journalArticle = ["publisher"], book = ["series"] }\n\n[tags]\nproteges = ["à garder"]\n', encoding='utf-8')
    # Descriptif de la sauvegarde, sans la copie elle-même.
    faite = travaux['rangement'][1]
    descriptif = json.loads((faite / 'sauvegarde.json').read_text(encoding='utf-8'))
    descriptif['dossier_zotero'] = ZOTERO
    (ICI / 'sauvegardes' / faite.name).mkdir(parents=True)
    (ICI / 'sauvegardes' / faite.name / 'sauvegarde.json').write_text(
        json.dumps(descriptif, ensure_ascii=False, indent=1), encoding='utf-8')
    attendu = json.loads(json.dumps(resultats(ICI), ensure_ascii=False))
    (ICI / 'attendu.json').write_text(json.dumps(attendu, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
