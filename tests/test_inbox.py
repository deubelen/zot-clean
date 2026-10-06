"""Tri de l'Inbox (D135), sur une bibliothèque synthétique déjà rangée, le faux serveur et les fausses sources."""

import itertools

import pytest

from faux_serveur import FauxServeur
from faux_sources import FauxServices, crossref_work
from test_appliquer import ecrire
from zot_clean import doublons, fonds as f, inbox as i, lecture, rangement as r, sources
from zot_clean.appliquer import ESSAI, appliquer
from zot_clean.config import Config

PLAN = """\
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
def serveur():
    return FauxServeur()


@pytest.fixture
def faux():
    return FauxServices()


@pytest.fixture
def cfg(tmp_path, zotero):
    c = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    c.dossier_travail.mkdir()
    c.methode.projets = ['Cours']
    return c


class Monde:
    def __init__(self, zotero, serveur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, nom, parent=None):
        cle = self.serveur.collection(nom, parent)
        self.ids[cle] = self.zotero.collection(nom, self.ids[parent] if parent else None, cle=cle)
        return cle

    def fiche(self, titre, *collections, auteur='Durand', **champs):
        cle = self.serveur._cle()
        self.zotero.fiche(titre, auteurs=(auteur,), collections=tuple(self.ids[c] for c in collections), cle=cle,
                          **champs)
        self.serveur.ajouter(title=titre, key=cle, collections=list(collections),
                             creators=[{'creatorType': 'author', 'lastName': auteur}], date='2020',
                             **(ARTICLE | champs))
        return cle

    def lire(self):
        self.zotero.synchroniser(self.serveur.version)
        return lecture.lire(self.zotero.enregistrer())


@pytest.fixture
def monde(zotero, serveur, cfg):
    m = Monde(zotero, serveur)
    k = {'Inbox': m.collection('Inbox'), 'Fonds': m.collection('Fonds'), 'Cours': m.collection('Cours')}
    k['Psy'] = m.collection('Psychologie', k['Fonds'])
    k['Perception'] = m.collection('Perception', k['Psy'])
    k['Arts'] = m.collection('Arts', k['Fonds'])
    k['L1'] = m.collection('Psy L1', k['Cours'])
    fiches = {
        'gibson': m.fiche('The ecological approach to visual perception', k['Perception'], auteur='Gibson'),
        'ancienne': m.fiche('Museum displays and their publics', k['Arts'], DOI='10.1111/musee'),
        'nouvelle': m.fiche('Perceptual learning revisited', k['Inbox'], auteur='Gibson', DOI='10.1111/appr'),
        'double': m.fiche('Museum displays and their publics', k['Inbox'], DOI='10.1111/musee'),
        'projet': m.fiche('Teaching perception to first-year students', k['L1']),
    }
    b = m.lire()
    (cfg.dossier_travail / f.PLAN).write_text(PLAN, encoding='utf-8')
    _, suivi, _, _ = f.inventaire(b, cfg)
    sorts = {'Fonds/Psychologie': (f.THEME, 'Psychologie'), 'Fonds/Psychologie/Perception':
             (f.THEME, 'Psychologie/Perception'), 'Fonds/Arts': (f.THEME, 'Arts')}
    for c in suivi.collections:
        if c.chemin in sorts:
            c.sort, c.cible = sorts[c.chemin]
    f.ecrire_suivi(cfg, suivi)
    controle = f.controler(cfg)
    assert not controle.erreurs, controle.erreurs
    f.enregistrer(cfg, controle)
    return m, k, fiches, b


def services(cfg, faux):
    return sources.depuis_config(cfg, client_http=faux.client(), attendre=lambda s: None)


def test_tri_de_bout_en_bout(monde, cfg, serveur, faux, zotero):
    m, k, fiches, b = monde
    faux.ajouter(doi='10.1111/appr', titre='Perceptual learning revisited', auteurs=(('Gibson', 'Eleanor'),),
                 annee=2020, volume='12', **{'container-title': ['Cognition']})
    faux.ajouter(doi='10.1111/musee', titre='Museum displays and their publics', auteurs=(('Durand', 'A'),),
                 annee=2020)
    schema = lecture.lire_types(zotero.base)
    rapport, liste = i.preparer(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert {a.fiche.cle for a in liste} == {fiches['nouvelle'], fiches['double'], fiches['projet']}
    assert "2 dans l'Inbox et 1 sans place dans le fonds" in rapport
    assert f"{fiches['ancienne']} / {fiches['double']}" in rapport or f"{fiches['double']} / {fiches['ancienne']}" in rapport
    assert 'thèmes voisins, même auteur : Psychologie/Perception (1)' in rapport
    assert f'depuis = "{k["Inbox"]}"' in rapport and 'action « ajouter »' in rapport
    # Répétition du pilote : situation des références hors de l'Inbox, absence de thème voisin dite.
    assert 'dont 0 hors de toute collection, 1 dans un projet.' in rapport
    assert 'action « ajouter », sans depuis, reste dans son projet' in rapport
    assert (cfg.suivi / r.FICHIER).read_text(encoding='utf-8').startswith(r.EN_TETE)

    # Jugement : fusion du doublon, rangement de la nouvelle et de celle du projet.
    entrees = doublons.charger_suivi(cfg)
    for e in entrees:
        e.decision, e.conserver = doublons.FUSIONNER, fiches['ancienne']
    doublons.ecrire_suivi(cfg, entrees, b)
    r.ecrire(cfg, [r.Entree(fiches['nouvelle'], r.DEPLACER, 'Psychologie/Perception', k['Inbox'], decision=r.ACCEPTER),
                   r.Entree(fiches['projet'], r.AJOUTER, 'Arts', decision=r.ACCEPTER)], b, set())

    plan, rapport = i.planifier(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert plan.etape == 'inbox' and [g.id for g in plan.groupes][0] == 'fusion-1'
    par_id = {g.id: g for g in plan.groupes}
    nouvelle = par_id[fiches['nouvelle']].operations
    assert [op.rang for op in nouvelle] == [1, 2]
    assert nouvelle[0].apres['volume'] == '12' and nouvelle[1].apres['collections'] == [k['Perception']]
    # La fiche gardée de la fusion ne reçoit pas l'Inbox de la fiche absorbée.
    gardee = next(op for op in par_id['fusion-1'].operations if op.cle == fiches['ancienne'])
    assert 'collections' not in gardee.apres
    assert 'entre dans Fonds/Psychologie/Perception' in rapport and 'quitte Inbox' in rapport

    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert not bilan.conflits and not bilan.erreurs and bilan.restants == 0
    assert serveur.elements[fiches['nouvelle']]['collections'] == [k['Perception']]
    assert serveur.elements[fiches['nouvelle']]['volume'] == '12'
    assert serveur.elements[fiches['projet']]['collections'] == [k['L1'], k['Arts']]
    assert serveur.elements[fiches['double']]['deleted'] is True
    assert serveur.elements[fiches['ancienne']]['collections'] == [k['Arts']]


def test_reference_hors_de_toute_collection(monde, cfg, serveur, faux, zotero):
    """Une référence sans collection est dite « hors de toute collection », pas « dans un projet », et l'absence de
    thème voisin est dite (répétition du pilote). Sans décision, le plan la cite parmi celles qui restent."""
    m, k, fiches, _ = monde
    libre = m.fiche('Un texte isolé', auteur='Personne')
    b = m.lire()
    schema = lecture.lire_types(zotero.base)
    rapport, _ = i.preparer(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert 'dont 1 hors de toute collection, 1 dans un projet.' in rapport
    ligne = rapport.split(f'- {libre} · ', 1)[1]
    assert 'dans aucune collection · action « ajouter », sans depuis\n  - aucun thème voisin trouvé' in ligne
    _, rapport = i.planifier(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert 'sans place dans le fonds, sans décision de rangement acceptée' in rapport and libre in rapport
    # Vue et laissée hors du fonds par décision (D176), elle n'est plus présentée, seulement comptée.
    r.laisser(b, cfg, [libre])
    rapport, liste = i.preparer(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert libre not in {x.fiche.cle for x in liste} and f'- {libre} · ' not in rapport
    assert '1 autre référence laissée hors du fonds par décision' in rapport
    _, rapport = i.planifier(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert libre not in rapport


def _pdf(zotero, serveur, parent_id, parent, nom, titre):
    cle = serveur._cle()
    zotero.pdf(parent_id, nom, nom.encode(), cle=cle, titre=titre)
    serveur.ajouter('attachment', key=cle, parentItem=parent, linkMode='imported_file', filename=nom, title=titre,
                    contentType='application/pdf')
    return cle


def test_nom_du_fichier_suit_le_plan_de_tri(monde, cfg, serveur, faux, zotero):
    # D149 : la date complétée et la fusion changent le nom du fichier principal, calculé d'après le plan.
    m, k, fiches, b = monde
    sans_date = serveur._cle()
    iid = zotero.fiche('Seeing affordances', auteurs=('Gibson',), date='', collections=(m.ids[k['Inbox']],),
                       cle=sans_date, DOI='10.1111/aff')
    serveur.ajouter(title='Seeing affordances', key=sans_date, collections=[k['Inbox']], date='', DOI='10.1111/aff',
                    creators=[{'creatorType': 'author', 'lastName': 'Gibson'}], **ARTICLE)
    ids = b.par_cle()
    pdf = _pdf(zotero, serveur, iid, sans_date, 'Gibson - Seeing affordances.pdf', 'Gibson - Seeing affordances.pdf')
    scan = _pdf(zotero, serveur, ids[fiches['double']].id, fiches['double'], 'scan.pdf', 'PDF')
    # Un nom en retard sur une fiche dont le plan ne change que le volume reste tel quel.
    vieux = _pdf(zotero, serveur, ids[fiches['nouvelle']].id, fiches['nouvelle'], 'vieux.pdf', 'PDF')
    b = m.lire()
    faux.ajouter(doi='10.1111/aff', titre='Seeing affordances', auteurs=(('Gibson', 'James'),), annee=2021)
    faux.ajouter(doi='10.1111/appr', titre='Perceptual learning revisited', auteurs=(('Gibson', 'Eleanor'),),
                 annee=2020, volume='12')
    faux.ajouter(doi='10.1111/musee', titre='Museum displays and their publics', auteurs=(('Durand', 'A'),),
                 annee=2020)
    schema = lecture.lire_types(zotero.base)
    i.preparer(b, cfg, services(cfg, faux), serveur.client(), schema)
    entrees = doublons.charger_suivi(cfg)
    for e in entrees:
        e.decision, e.conserver = doublons.FUSIONNER, fiches['ancienne']
    doublons.ecrire_suivi(cfg, entrees, b)

    plan, rapport = i.planifier(b, cfg, services(cfg, faux), serveur.client(), schema)
    par_id = {g.id: g for g in plan.groupes}
    op = next(op for op in par_id[sans_date].operations if op.cle == pdf)
    assert op.rang == i.RANG_NOM > 1
    assert op.apres == {'filename': 'Gibson - 2021 - Seeing affordances.pdf', 'title': 'PDF'}
    # Le PDF de la fiche absorbée devient le fichier principal de la fiche gardée, qui n'en avait pas.
    op = next(op for op in par_id['fusion-1'].operations if op.cle == scan and op.rang == i.RANG_NOM)
    assert op.apres == {'filename': 'Durand - 2020 - Museum displays and their publics.pdf'}
    assert vieux not in {op.cle for g in plan.groupes for op in g.operations}
    assert '« Gibson - Seeing affordances.pdf » → « Gibson - 2021 - Seeing affordances.pdf »' in rapport

    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert not bilan.conflits and not bilan.erreurs and bilan.restants == 0
    assert serveur.elements[pdf]['filename'] == 'Gibson - 2021 - Seeing affordances.pdf'
    assert serveur.elements[scan]['parentItem'] == fiches['ancienne']
    assert serveur.elements[scan]['filename'] == 'Durand - 2020 - Museum displays and their publics.pdf'


def test_cas_des_autres_fiches_gardes(monde, cfg, serveur, faux, zotero):
    # Limiter l'examen aux références à trier ne doit pas effacer les cas en attente des autres fiches.
    from zot_clean import metadonnees as md
    m, k, fiches, b = monde
    autre = md.Cas(fiches['gibson'], md.IDENTIFIANTS, 'doi_manquant', [md.Proposition({'DOI': '10.1/x'}, 'crossref')])
    md.ecrire_suivi(cfg, [autre], b)
    i.preparer(b, cfg, services(cfg, faux), serveur.client(), lecture.lire_types(zotero.base))
    assert fiches['gibson'] in {c.cle for c in md.charger_suivi(cfg)}


def test_sans_plan_du_fonds(zotero, serveur, cfg, faux):
    m = Monde(zotero, serveur)
    inbox = m.collection('Inbox')
    m.fiche('Une nouveauté', inbox)
    b = m.lire()
    rapport, liste = i.preparer(b, cfg, services(cfg, faux), serveur.client(), lecture.lire_types(zotero.base))
    assert len(liste) == 1 and "plan.md n'existe pas encore" in rapport


def test_tags_du_tri_suivent_les_regles(zotero, serveur, cfg, faux):
    # D155 : tags automatiques retirés selon la règle acceptée, tag manuel nouveau seulement signalé.
    from zot_clean import tags as tg
    m = Monde(zotero, serveur)
    inbox = m.collection('Inbox')
    cle = m.serveur._cle()
    zotero.fiche('Une nouveauté', collections=(m.ids[inbox],), cle=cle, tags=(('Neurosciences', 1), 'mon idée'))
    serveur.ajouter(title='Une nouveauté', key=cle, collections=[inbox], date='2020',
                    creators=[{'creatorType': 'author', 'lastName': 'Durand'}],
                    tags=[{'tag': 'Neurosciences', 'type': 1}, {'tag': 'mon idée'}], **ARTICLE)
    b = m.lire()
    s = tg.Suivi(automatiques=tg.ACCEPTER)
    tg.ecrire(cfg, s, b)
    schema = lecture.lire_types(zotero.base)
    rapport, _ = i.preparer(b, cfg, services(cfg, faux), serveur.client(), schema)
    assert 'tags hors familles, sans règle : mon idée' in rapport
    plan, rapport = i.planifier(b, cfg, services(cfg, faux), serveur.client(), schema)
    op = next(op for g in plan.groupes for op in g.operations if op.rang == 3)
    assert op.cle == cle and op.apres['tags'] == [{'tag': 'mon idée'}]
    assert '− Neurosciences' in rapport


# --- Clés de citation (D146) ------------------------------------------------------

def poser_cle(zotero, serveur, cle, cle_citation, ajout=None):
    """Clé de citation posée dans la base locale et sur le serveur, date d'ajout locale changée au besoin."""
    iid = zotero.db.execute('select itemID from items where key = ?', (cle,)).fetchone()[0]
    zotero._champs(iid, {'citationKey': cle_citation})
    if ajout:
        zotero.db.execute('update items set dateAdded = ? where itemID = ?', (ajout, iid))
    serveur.elements[cle]['citationKey'] = cle_citation


def test_cles_de_citation_du_tri(monde, cfg, serveur, faux, zotero):
    m, k, fiches, _ = monde
    (zotero.dossier / 'better-bibtex').mkdir()  # Better BibTeX actif, détecté par son dossier
    faux.ajouter(doi='10.1111/appr', titre='Perceptual learning revisited', auteurs=(('Gibson', 'Eleanor'),),
                 annee=2020, volume='12', **{'container-title': ['Cognition']})
    # La nouvelle référence a reçu la clé d'une fiche plus ancienne. Celle du projet, plus ancienne que la fiche
    # du fonds dont elle partage la clé, la garde : c'est l'autre fiche qui reçoit le suffixe.
    poser_cle(zotero, serveur, fiches['gibson'], 'gibson2020')
    poser_cle(zotero, serveur, fiches['nouvelle'], 'Gibson2020')
    poser_cle(zotero, serveur, fiches['projet'], 'durand2020', ajout='2010-01-01 00:00:00')
    poser_cle(zotero, serveur, fiches['ancienne'], 'durand2020')
    b = m.lire()
    schema = lecture.lire_types(zotero.base)

    rapport, _ = i.preparer(b, cfg, services(cfg, faux), serveur.client(), schema)
    lignes = {ligne.split(' · ')[0][2:]: ligne for ligne in rapport.splitlines() if ligne.startswith('- ')}
    assert 'sans clé de citation' in lignes[fiches['double']]
    assert 'sans clé de citation' not in lignes[fiches['nouvelle']] and 'Better BibTeX › Fill' in rapport

    plan, rapport = i.planifier(b, cfg, services(cfg, faux), serveur.client(), schema)
    par_id = {g.id: g for g in plan.groupes}
    # La clé de la référence triée rejoint ses champs, en une seule opération au rang 1.
    rang1 = [op for op in par_id[fiches['nouvelle']].operations if op.rang == 1]
    assert len(rang1) == 1 and rang1[0].apres['volume'] == '12' and rang1[0].apres['citationKey'] == 'gibson2020a'
    # L'autre fiche du double est départagée dans le groupe de la référence triée.
    op = next(op for op in par_id[fiches['projet']].operations if op.cle == fiches['ancienne'])
    assert op.rang == 1 and op.apres == {'citationKey': 'durand2020a'}
    assert f"champs ({fiches['ancienne']}) citationKey = 'durand2020a'" in rapport
    assert fiches['gibson'] not in par_id

    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert not bilan.conflits and not bilan.erreurs
    assert serveur.elements[fiches['nouvelle']]['citationKey'] == 'gibson2020a'
    assert serveur.elements[fiches['ancienne']]['citationKey'] == 'durand2020a'
    assert serveur.elements[fiches['gibson']]['citationKey'] == 'gibson2020'


def test_tri_sans_bbt_ne_signale_pas_les_cles(monde, cfg, serveur, faux, zotero):
    m, k, fiches, b = monde
    rapport, _ = i.preparer(b, cfg, services(cfg, faux), serveur.client(), lecture.lire_types(zotero.base))
    assert 'sans clé de citation' not in rapport


def test_cle_partagee_avec_une_fiche_confidentielle(monde, cfg, serveur, faux, zotero):
    # D126, D188 : la référence triée reçoit la clé d'une fiche confidentielle plus ancienne. Le rapport du tri ne
    # montre pas la clé, qui peut dire le sujet de la fiche.
    m, k, fiches, _ = monde
    (zotero.dossier / 'better-bibtex').mkdir()
    poser_cle(zotero, serveur, fiches['projet'], 'secret2020', ajout='2010-01-01 00:00:00')
    poser_cle(zotero, serveur, fiches['nouvelle'], 'secret2020')
    zotero.tags(zotero.db.execute('select itemID from items where key = ?', (fiches['projet'],)).fetchone()[0],
                ['_privé'])
    serveur.elements[fiches['projet']]['tags'] = [{'tag': '_privé'}]
    plan, rapport = i.planifier(m.lire(), cfg, services(cfg, faux), serveur.client(), lecture.lire_types(zotero.base))
    ops = [op for g in plan.groupes for op in g.operations if op.cle == fiches['nouvelle']]
    assert any(op.apres.get('citationKey') == 'secret2020a' for op in ops)
    assert 'secret2020' not in rapport
