"""Plans sur les collections (D114) : création sous une clé tirée par le plan, rangement, relance, annulation."""

import hashlib
import json
from dataclasses import asdict

import pytest

from faux_serveur import FauxServeur
from test_annulation import annuler
from test_appliquer import ecrire
from zot_clean import journal, plans
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.plans import Groupe, Operation, Plan


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def cfg(tmp_path, zotero):
    zotero.fiche('Une fiche')
    zotero.enregistrer()
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


def creer(cle, nom, parent=False):
    return Operation(cle, {}, {'name': nom, 'parentCollection': parent}, genre='collections', creation=True)


def plan_sous_theme(serveur):
    """Un thème existant, renommé, un sous-thème créé, une fiche qui passe du thème au sous-thème."""
    theme = serveur.collection('Ethologie')
    fiche = serveur.ajouter(title='Cultures in chimpanzees', collections=[theme])
    sous = 'PRIM2345'
    g = Groupe('1', 'Éthologie/Primates', [
        Operation(theme, {'name': 'Ethologie'}, {'name': 'Éthologie'}, genre='collections'),
        creer(sous, 'Primates', theme),
        Operation(fiche, {'collections': [theme]}, {'collections': [sous]}, rang=1)])
    return Plan('fonds', serveur.utilisateur, [g]), theme, sous, fiche


def test_creation_et_rangement(serveur, cfg):
    plan, theme, sous, fiche = plan_sous_theme(serveur)
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plans.charger(chemin), chemin, serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['1'] and not bilan.conflits and not bilan.erreurs
    assert serveur.collections[theme]['name'] == 'Éthologie'
    assert (serveur.collections[sous]['name'], serveur.collections[sous]['parentCollection']) == ('Primates', theme)
    assert serveur.elements[fiche]['collections'] == [sous]
    lignes = [l for l in journal.lire(bilan.journal) if l['type'] == 'element']
    assert [(l.get('genre', 'items'), l.get('cree', False)) for l in lignes] == [
        ('collections', False), ('collections', True), ('items', False)]
    # Relancer ne refait rien, le groupe est fait.
    assert appliquer(plan, chemin, serveur.client(), cfg, TOUT).journal is None


def test_collection_deja_creee_par_une_execution_interrompue(serveur, cfg):
    plan, theme, sous, fiche = plan_sous_theme(serveur)
    serveur.collection('Primates', theme, key=sous)
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['1'] and serveur.elements[fiche]['collections'] == [sous]


def test_cle_deja_prise_par_une_autre_collection(serveur, cfg):
    plan, theme, sous, fiche = plan_sous_theme(serveur)
    serveur.collection('Autre chose', key=sous)
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert '1' in bilan.conflits and 'existe déjà' in bilan.conflits['1']
    assert serveur.elements[fiche]['collections'] == [theme]


def test_annulation_remet_la_fiche_et_met_la_collection_creee_a_la_corbeille(serveur, cfg):
    plan, theme, sous, fiche = plan_sous_theme(serveur)
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    plan_a, rapport, chemin_a = annuler(chemin, serveur, cfg)
    assert [op.genre for op in plan_a.groupes[0].operations] == ['items', 'collections', 'collections']
    assert 'Primates' in rapport
    bilan = appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['1']
    assert serveur.elements[fiche]['collections'] == [theme]
    assert serveur.collections[sous]['deleted'] is True
    assert serveur.collections[theme]['name'] == 'Ethologie'


def test_fiche_vers_une_collection_inexistante_refusee(serveur, cfg):
    theme = serveur.collection('Thème')
    fiche = serveur.ajouter(title='Titre', collections=[theme])
    plan = Plan('fonds', serveur.utilisateur, [Groupe('1', 'x', [
        Operation(fiche, {'collections': [theme]}, {'collections': ['NULLE234']})])])
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert '1' in bilan.erreurs and serveur.elements[fiche]['collections'] == [theme]


def test_empreinte_des_anciens_plans_inchangee():
    """Les champs ajoutés pour les collections, à leur valeur par défaut, n'entrent pas dans l'empreinte."""
    plan = Plan('test', 1, [Groupe('1', 't', [Operation('ABCD2345', {'title': 'a'}, {'title': 'b'})])])
    ancien = [{k: v for k, v in asdict(g).items()} for g in plan.groupes]
    for g in ancien:
        g['operations'] = [{k: v for k, v in o.items() if k not in ('genre', 'creation', 'enfants', 'exige')} for o in g['operations']]
    contenu = {'etape': 'test', 'bibliotheque': 1, 'partiel': False, 'groupes': ancien}
    attendu = hashlib.sha256(json.dumps(contenu, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    assert plan.empreinte == attendu


def test_annulation_rejoue_les_groupes_du_dernier_au_premier(serveur, cfg):
    """Une collection créée par un groupe et une autre déplacée dedans par un groupe suivant : l'annulation sort
    d'abord la seconde, puis met la première à la corbeille (trouvé par l'essai sur le compte de test)."""
    ancienne = serveur.collection('Vieux classement')
    archives = 'ARCH2345'
    plan = Plan('fonds', serveur.utilisateur, [
        Groupe('1', 'Archives', [creer(archives, 'Archives')]),
        Groupe('2', 'Archives/Vieux classement', [
            Operation(ancienne, {'parentCollection': False}, {'parentCollection': archives}, genre='collections')])])
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    plan_a, _, _ = annuler(chemin, serveur, cfg)
    assert [g.id for g in plan_a.groupes] == ['2', '1']


@pytest.mark.parametrize('retouche', ['renommee', 'fiche ajoutee', 'sous-collection'])
def test_annulation_garde_une_collection_creee_reprise_depuis(serveur, cfg, retouche):
    # D183 : une collection créée par la passe, renommée ou remplie depuis par l'utilisateur, reste en place. Le
    # reste de la passe est défait.
    plan, theme, sous, fiche = plan_sous_theme(serveur)
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    if retouche == 'renommee':
        serveur.collections[sous]['name'] = 'Projet ajouté à la main'
    elif retouche == 'fiche ajoutee':
        serveur.ajouter(title='Ajoutée à la main', collections=[sous])
    else:
        serveur.collection('Ajoutée à la main', sous)
    plan_a, _, chemin_a = annuler(chemin, serveur, cfg)
    bilan = appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    assert sous in bilan.conflits['1'] and bilan.arretes['1']
    assert not serveur.collections[sous].get('deleted')
    assert serveur.elements[fiche]['collections'] == [theme]
