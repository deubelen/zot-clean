import json
from datetime import datetime, timedelta

import pytest

from faux_serveur import FauxServeur
from zot_clean import journal, plans
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.ecriture import ErreurAPI, Refus
from zot_clean.plans import Groupe, Operation, Plan


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def cfg(tmp_path, zotero):
    zotero.fiche('Une fiche')
    zotero.enregistrer()
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


def plan_titres(serveur, n, prefixe='Titre'):
    """Un groupe par fiche, qui change son titre."""
    groupes = []
    for i in range(n):
        cle = serveur.ajouter(title=f'{prefixe} {i}')
        groupes.append(Groupe(str(i), f'fiche {i}', [Operation(cle, {'title': f'{prefixe} {i}'},
                                                               {'title': f'{prefixe} {i} corrigé'})]))
    return Plan('test', serveur.utilisateur, groupes)


def ecrire(plan, cfg):
    return plans.ecrire(plan, cfg.plans, '# rapport')


def sauvegarde_factice(cfg, age_heures=1):
    d = cfg.sauvegardes / 'factice'
    d.mkdir(parents=True)
    date = datetime.now().astimezone() - timedelta(hours=age_heures)
    (d / 'sauvegarde.json').write_text(json.dumps({'date': date.isoformat(), 'methode': 'base',
                                                   'version_bibliotheque': 1, 'taille': 1}), encoding='utf-8')


def test_petit_plan_applique_en_entier_par_l_essai(serveur, cfg):
    plan = plan_titres(serveur, 3)
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plans.charger(chemin), chemin, serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['0', '1', '2'] and bilan.restants == 0
    assert all(d['title'].endswith('corrigé') for d in serveur.elements.values())
    lignes = journal.lire(bilan.journal)
    assert [l['type'] for l in lignes] == (['en-tete'] + ['intention'] * 3 + ['element'] * 3 + ['groupe'] * 3
                                           + ['fin'])
    assert lignes[4]['avant']['title'] == 'Titre 0' and lignes[4]['ecrit'] == {'title': 'Titre 0 corrigé'}
    assert lignes[0]['empreinte'] == plan.empreinte
    # Relancer ne refait rien.
    assert appliquer(plan, chemin, serveur.client(), cfg, TOUT).journal is None


def test_essai_puis_sauvegarde_exiges_au_dela(serveur, cfg):
    plan = plan_titres(serveur, 8)
    chemin = ecrire(plan, cfg)
    client = serveur.client()
    with pytest.raises(Refus, match='essai'):
        appliquer(plan, chemin, client, cfg, TOUT)
    bilan = appliquer(plan, chemin, client, cfg, ESSAI)
    assert len(bilan.faits) == 5 and bilan.restants == 3
    with pytest.raises(Refus, match='sauvegarde'):
        appliquer(plan, chemin, client, cfg, TOUT)
    sauvegarde_factice(cfg, age_heures=30)
    with pytest.raises(Refus, match='sauvegarde'):
        appliquer(plan, chemin, client, cfg, TOUT)
    (cfg.sauvegardes / 'factice' / 'sauvegarde.json').unlink()
    (cfg.sauvegardes / 'factice').rmdir()
    sauvegarde_factice(cfg)
    bilan = appliquer(plan, chemin, client, cfg, TOUT)
    assert bilan.faits == ['5', '6', '7'] and bilan.restants == 0


def test_petit_plan_de_gestion_sans_essai_ni_sauvegarde(serveur, cfg):
    # D136, D138 : un tri de l'Inbox de moins de 50 fiches s'applique d'un coup, sans essai ni sauvegarde.
    plan = plan_titres(serveur, 8)
    plan.etape = 'inbox'
    client = serveur.client()
    bilan = appliquer(plan, ecrire(plan, cfg), client, cfg, TOUT)
    assert len(bilan.faits) == 8 and bilan.restants == 0
    grand = plan_titres(serveur, 8, 'Autre')
    grand.etape = 'inbox'
    cfg.ecriture.petit_plan_de_gestion = 8
    chemin = ecrire(grand, cfg)
    with pytest.raises(Refus, match='essai'):
        appliquer(grand, chemin, client, cfg, TOUT)
    appliquer(grand, chemin, client, cfg, ESSAI)
    with pytest.raises(Refus, match='sauvegarde'):
        appliquer(grand, chemin, client, cfg, TOUT)


def test_conflit_quand_le_champ_a_change(serveur, cfg):
    plan = plan_titres(serveur, 2)
    serveur.modifier(plan.groupes[0].operations[0].cle, title='Corrigé à la main')
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert list(bilan.conflits) == ['0'] and bilan.faits == ['1']
    assert serveur.elements[plan.groupes[0].operations[0].cle]['title'] == 'Corrigé à la main'
    assert bilan.restants == 1


def test_autre_champ_modifie_ailleurs_sans_conflit(serveur, cfg):
    plan = plan_titres(serveur, 1)
    cle = plan.groupes[0].operations[0].cle
    serveur.modifier(cle, date='1999')
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['0'] and serveur.elements[cle]['date'] == '1999'


def test_nouvel_essai_apres_412(serveur, cfg):
    plan = plan_titres(serveur, 1)
    cle = plan.groupes[0].operations[0].cle
    fois = []

    def synchronisation():
        if not fois:
            fois.append(1)
            serveur.modifier(cle, extra='modifié pendant l’écriture')
    serveur.avant_ecriture = synchronisation
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['0'] and serveur.elements[cle]['title'] == 'Titre 0 corrigé'
    assert len([r for r in serveur.requetes if r[0] == 'POST']) == 2


def test_rang_en_echec_arrete_le_groupe(serveur, cfg):
    a = serveur.ajouter(title='A')
    b = serveur.ajouter(title='B')
    g = Groupe('1', 'fusion', [Operation('DISPARU2', {'deleted': False}, {'deleted': True}, rang=0),
                               Operation(a, {'title': 'A'}, {'title': 'A2'}, rang=1)])
    g2 = Groupe('2', 'autre', [Operation(b, {'title': 'B'}, {'title': 'B2'})])
    plan = Plan('test', serveur.utilisateur, [g, g2])
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert "n'existe plus" in bilan.conflits['1'] and bilan.faits == ['2']
    assert serveur.elements[a]['title'] == 'A'


def test_corbeille_et_rattachement(serveur, cfg):
    p = serveur.ajouter(title='Parent')
    x = serveur.ajouter(title='Autre')
    pj = serveur.ajouter('attachment', parentItem=x, title='PDF')
    g = Groupe('1', 'fusion', [Operation(pj, {'parentItem': x}, {'parentItem': p}, rang=0),
                               Operation(x, {'deleted': False}, {'deleted': True}, rang=1)])
    plan = Plan('test', serveur.utilisateur, [g])
    appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert serveur.elements[pj]['parentItem'] == p and serveur.elements[x]['deleted'] is True


def test_plan_partiel_laisse_seulement_le_champ_en_conflit(serveur, cfg):
    a = serveur.ajouter(title='A2', date='2001')
    g = Groupe('1', 'annulation', [Operation(a, {'title': 'A2', 'date': '2001'}, {'title': 'A', 'date': '2000'})])
    plan = Plan('annulation', serveur.utilisateur, [g], partiel=True)
    serveur.modifier(a, title='Retouché')
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert '1' in bilan.partiels
    assert serveur.elements[a]['title'] == 'Retouché' and serveur.elements[a]['date'] == '2000'


def test_reprise_apres_interruption(serveur, cfg):
    plan = plan_titres(serveur, 60)
    chemin = ecrire(plan, cfg)
    client = serveur.client()
    cfg.ecriture.essai = 100
    postes = []

    def panne():
        postes.append(1)
        if len(postes) == 1:
            serveur.pannes = [503] * 10
    serveur.avant_ecriture = panne
    with pytest.raises(ErreurAPI):
        appliquer(plan, chemin, client, cfg, ESSAI)
    premier = journal.tous(cfg.journal)[0]
    assert not premier.termine and len(premier.groupes) == 50
    serveur.avant_ecriture, serveur.pannes = None, []
    bilan = appliquer(plan, chemin, client, cfg, ESSAI)
    assert len(bilan.faits) == 10 and journal.resumer(bilan.journal).en_tete['reprise']
    assert all(d['title'].endswith('corrigé') for d in serveur.elements.values())


def test_autre_compte_refuse(serveur, cfg):
    plan = plan_titres(serveur, 1)
    plan.bibliotheque = 1
    with pytest.raises(Refus, match='compte'):
        appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)


def test_cle_invalide_refuse(serveur, cfg, zotero):
    zotero.fiche('Clé cassée', cle='ABC0DEF1')
    zotero.enregistrer()
    plan = plan_titres(serveur, 1)
    with pytest.raises(Refus, match='clé invalide'):
        appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)


def test_plan_retouche_refuse(serveur, cfg):
    chemin = ecrire(plan_titres(serveur, 1), cfg)
    chemin.write_text(chemin.read_text(encoding='utf-8').replace('corrigé', 'autre'), encoding='utf-8')
    with pytest.raises(SystemExit, match='modifié'):
        plans.charger(chemin)


def test_annotations_non_synchronisees_signalees_a_part(tmp_path, zotero):
    from zot_clean.appliquer import controler_synchronisation
    fiche = zotero.fiche('Fiche')
    zotero.annotation(zotero.pdf(fiche, 'a.pdf'))
    zotero.db.execute("update items set synced = 0 where itemTypeID = (select itemTypeID from itemTypes "
                      "where typeName = 'annotation')")
    zotero.enregistrer()
    cfg = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    assert 'annotation(s) de PDF' in controler_synchronisation(cfg)


def test_reponse_perdue_ecriture_journalisee(serveur, cfg):
    # D178 : zotero.org fait l'écriture mais sa réponse se perd. Le nouvel essai reçoit un 412, la relecture trouve
    # les valeurs écrites, et l'intention inscrite avant l'envoi en fait une écriture journalisée, donc annulable.
    from zot_clean import annulation
    plan = plan_titres(serveur, 3)
    serveur.reponses_perdues = 1
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['0', '1', '2'] and bilan.elements_ecrits == 3
    lignes = journal.lire(bilan.journal)
    assert [l['avant']['title'] for l in lignes if l['type'] == 'element'] == ['Titre 0', 'Titre 1', 'Titre 2']
    assert not journal.en_suspens([bilan.journal])
    plan_a, _ = annulation.planifier([bilan.journal], serveur.client())
    assert len(plan_a.groupes) == 3


def test_collection_creee_reponse_perdue(serveur, cfg):
    cle = 'ARCH2345'
    plan = Plan('test', serveur.utilisateur, [Groupe('1', 'archives', [
        Operation(cle, {}, {'name': 'Archives', 'parentCollection': False}, genre='collections', creation=True)])])
    serveur.reponses_perdues = 1
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert bilan.faits == ['1'] and bilan.elements_ecrits == 1
    element = [l for l in journal.lire(bilan.journal) if l['type'] == 'element']
    assert element[0]['cle'] == cle and element[0]['cree']


def test_interruption_apres_envoi_reprise_puis_annulation(serveur, cfg):
    from zot_clean import annulation
    plan = plan_titres(serveur, 2)
    chemin = ecrire(plan, cfg)
    client = serveur.client()
    serveur.reponses_perdues = 10  # écrit au premier envoi, puis aucune réponse : la commande s'arrête
    with pytest.raises(ErreurAPI):
        appliquer(plan, chemin, client, cfg, ESSAI)
    premier = journal.tous(cfg.journal)[0].chemin
    assert len(journal.en_suspens([premier])) == 2
    assert all(d['title'].endswith('corrigé') for d in serveur.elements.values())
    serveur.reponses_perdues = 0
    bilan = appliquer(plan, chemin, client, cfg, ESSAI)  # la reprise reconnaît ses écritures
    assert bilan.faits == ['0', '1'] and bilan.elements_ecrits == 2
    assert not journal.en_suspens([premier, bilan.journal])
    plan_a, _ = annulation.planifier(annulation.journaux_vises(chemin, cfg), client)
    bilan_a = appliquer(plan_a, plans.ecrire(plan_a, cfg.plans, '#'), client, cfg, ESSAI)
    assert bilan_a.faits == ['1', '0'] and sorted(d['title'] for d in serveur.elements.values()) == ['Titre 0',
                                                                                                    'Titre 1']


@pytest.mark.parametrize('faite', [True, False])
def test_annulation_d_une_ecriture_incertaine(serveur, cfg, faite):
    # Commande interrompue sans reprise : l'annulation défait l'écriture si elle a eu lieu, et ne touche à rien sinon.
    from zot_clean import annulation
    plan = plan_titres(serveur, 1)
    client = serveur.client()
    coupe = serveur.client()
    if faite:
        serveur.reponses_perdues = 10
    else:
        def ecriture_coupee(*a, **k):
            raise ErreurAPI('zotero.org injoignable')
        coupe.ecrire = ecriture_coupee
    with pytest.raises(ErreurAPI):
        appliquer(plan, ecrire(plan, cfg), coupe, cfg, ESSAI)
    serveur.reponses_perdues = 0
    j = journal.tous(cfg.journal)[0].chemin
    plan_a, rapport = annulation.planifier([j], client)
    assert 'sans que Zotero en confirme le résultat' in rapport
    bilan_a = appliquer(plan_a, plans.ecrire(plan_a, cfg.plans, rapport), client, cfg, ESSAI)
    assert bilan_a.faits == ['0'] and bilan_a.elements_ecrits == (1 if faite else 0)
    assert [d['title'] for d in serveur.elements.values()] == ['Titre 0']


def test_essai_relance_n_avance_pas_dans_le_plan(serveur, cfg):
    # D179 : un `--essai` relancé ne reprend que les groupes de l'essai, jamais les suivants, et rien ne passe
    # au-delà sans sauvegarde.
    plan = plan_titres(serveur, 12)
    chemin = ecrire(plan, cfg)
    client = serveur.client()
    cle = plan.groupes[1].operations[0].cle
    serveur.modifier(cle, title='Corrigé à la main')
    bilan = appliquer(plan, chemin, client, cfg, ESSAI)
    assert bilan.faits == ['0', '2', '3', '4'] and list(bilan.conflits) == ['1']
    serveur.modifier(cle, title='Titre 1')
    bilan = appliquer(plan, chemin, client, cfg, ESSAI)
    assert bilan.faits == ['1'] and bilan.restants == 7
    bilan = appliquer(plan, chemin, client, cfg, ESSAI)
    assert bilan.journal is None and bilan.restants == 7
    assert sum(d['title'].endswith('corrigé') for d in serveur.elements.values()) == 5
    with pytest.raises(Refus, match='sauvegarde'):
        appliquer(plan, chemin, client, cfg, TOUT)


def test_groupe_arrete_apres_une_partie_des_ecritures(serveur, cfg):
    # D181 : le premier rang est écrit, le second est en conflit. Le groupe n'est pas présenté comme intact.
    a = serveur.ajouter(title='A')
    b = serveur.ajouter(title='B')
    c = serveur.ajouter(title='C')
    plan = Plan('test', serveur.utilisateur, [
        Groupe('1', 'fusion', [Operation(a, {'title': 'A'}, {'title': 'A2'}, rang=0),
                               Operation(b, {'title': 'B'}, {'title': 'B2'}, rang=1)]),
        Groupe('2', 'autre', [Operation(c, {'title': 'Autre'}, {'title': 'C2'})])])
    serveur.modifier(b, title='Corrigé à la main')
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert set(bilan.conflits) == {'1', '2'} and bilan.arretes == {'1': [a]}
    assert f"après l'écriture de {a}" in bilan.conflits['1']
