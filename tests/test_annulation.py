import pytest

from faux_serveur import FauxServeur
from test_appliquer import ecrire, plan_titres, sauvegarde_factice
from zot_clean import annulation, plans
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


def fusion(serveur):
    """Une fusion à la main : pièce jointe rattachée, fiche conservée complétée, absorbée à la corbeille."""
    m = serveur.ajouter(title='Titre', DOI='', collections=['AAAA2222'], relations={})
    a = serveur.ajouter(title='Titre', DOI='10.1/x', collections=['BBBB3333'])
    pj = serveur.ajouter('attachment', parentItem=a, title='PDF')
    uri = serveur.client().uri(a)
    g = Groupe('1', 'fusion', [
        Operation(pj, {'parentItem': a}, {'parentItem': m}, rang=0),
        Operation(m, {'DOI': '', 'collections': ['AAAA2222'], 'relations': {}},
                  {'DOI': '10.1/x', 'collections': ['AAAA2222', 'BBBB3333'], 'relations': {'dc:replaces': [uri]}},
                  rang=1),
        Operation(a, {'deleted': False}, {'deleted': True}, rang=2)])
    return Plan('doublons', serveur.utilisateur, [g]), m, a, pj


def annuler(chemin, serveur, cfg):
    plan, rapport = annulation.planifier(annulation.journaux_vises(chemin, cfg), serveur.client())
    chemin_annul = plans.ecrire(plan, cfg.plans, rapport)
    return plan, rapport, chemin_annul


def test_annulation_d_une_fusion(serveur, cfg):
    plan, m, a, pj = fusion(serveur)
    avant = {k: dict(serveur.elements[k]) for k in (m, a, pj)}
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert serveur.elements[a]['deleted'] and serveur.elements[pj]['parentItem'] == m
    plan_a, _, chemin_a = annuler(bilan.journal, serveur, cfg)
    assert [op.cle for op in plan_a.groupes[0].operations] == [a, m, pj]
    bilan_a = appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    assert bilan_a.faits == ['1']
    for k in (m, a, pj):
        apres = {c: v for c, v in serveur.elements[k].items() if c != 'version'}
        assert apres == {c: v for c, v in avant[k].items() if c != 'version'}


def test_champ_retouche_depuis_laisse_tel_quel(serveur, cfg):
    plan, m, a, pj = fusion(serveur)
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    serveur.modifier(m, DOI='10.1/corrigé-à-la-main')
    plan_a, _, chemin_a = annuler(bilan.journal, serveur, cfg)
    bilan_a = appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    assert 'DOI' in bilan_a.partiels['1']
    assert serveur.elements[m]['DOI'] == '10.1/corrigé-à-la-main'
    assert serveur.elements[m]['collections'] == ['AAAA2222'] and not serveur.elements[a].get('deleted')


def test_element_disparu_rend_le_groupe_non_annulable(serveur, cfg):
    plan, m, a, pj = fusion(serveur)
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    del serveur.elements[a]  # corbeille vidée
    plan_a, rapport, _ = annuler(bilan.journal, serveur, cfg)
    assert plan_a.groupes == [] and 'non annulables' in rapport and a in rapport


def test_annulation_de_tous_les_journaux_d_un_plan(serveur, cfg):
    plan = plan_titres(serveur, 8)
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    plan_a, _, chemin_a = annuler(chemin, serveur, cfg)
    assert len(plan_a.groupes) == 8 and len(plan_a.annule) == 2
    appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    appliquer(plan_a, chemin_a, serveur.client(), cfg, TOUT)
    assert not any(d['title'].endswith('corrigé') for d in serveur.elements.values())


def test_plan_recalcule_apres_annulation_se_reapplique(serveur, cfg):
    # Un plan recalculé à l'identique a la même empreinte : ses groupes défaits ne comptent plus comme faits.
    plan = plan_titres(serveur, 8)
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    plan_a, _, chemin_a = annuler(chemin, serveur, cfg)
    appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    appliquer(plan_a, chemin_a, serveur.client(), cfg, TOUT)
    assert not any(d['title'].endswith('corrigé') for d in serveur.elements.values())
    with pytest.raises(Exception, match='essai'):
        appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert bilan.faits and not bilan.conflits
    appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    assert sum(d['title'].endswith('corrigé') for d in serveur.elements.values()) == 8


def test_rapport_masque_les_fiches_confidentielles(serveur, cfg):
    plan, m, a, pj = fusion(serveur)
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    _, rapport = annulation.planifier([bilan.journal], serveur.client(), {m, a})
    assert "'Titre'" not in rapport and '10.1/x' not in rapport and f'{pj} ' in rapport
    _, rapport = annulation.planifier([bilan.journal], serveur.client())
    assert "'PDF'" not in rapport


def test_rapport_en_clair(serveur, cfg):
    plan, m, a, pj = fusion(serveur)
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    _, rapport = annulation.planifier([bilan.journal], serveur.client(), set())
    assert f'{a} « Titre » : sort de la corbeille' in rapport
    assert f'{pj} « PDF » : revient sur la fiche {a}' in rapport
    assert "le DOI redevient vide, retrouve ses collections d'avant, retrouve ses liens d'avant" in rapport
    assert '←' not in rapport


def test_seconde_annulation_d_un_plan_reapplique(serveur, cfg):
    # D180 : appliquer, annuler, réappliquer le même plan, puis annuler de nouveau. Le second plan d'annulation a
    # les mêmes groupes que le premier, mais pas les mêmes journaux, donc pas la même empreinte.
    plan = plan_titres(serveur, 2)
    chemin = ecrire(plan, cfg)
    client = serveur.client()
    for _ in range(2):
        bilan = appliquer(plan, chemin, client, cfg, ESSAI)
        assert bilan.faits == ['0', '1']
        plan_a, _, chemin_a = annuler(bilan.journal, serveur, cfg)
        assert appliquer(plan_a, chemin_a, client, cfg, ESSAI).faits == ['1', '0']
        assert sorted(d['title'] for d in serveur.elements.values()) == ['Titre 0', 'Titre 1']


def test_journaux_annules_dans_l_empreinte(serveur, cfg):
    plan = plan_titres(serveur, 1)
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    _, _, chemin_a = annuler(bilan.journal, serveur, cfg)
    texte = chemin_a.read_text(encoding='utf-8')
    chemin_a.write_text(texte.replace(bilan.journal.name, 'autre.jsonl'), encoding='utf-8')
    with pytest.raises(SystemExit, match='modifié'):
        plans.charger(chemin_a)


def test_plan_d_annulation_du_format_1_encore_lu(serveur, cfg):
    import json
    plan = plan_titres(serveur, 1)
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    plan_a, _, chemin_a = annuler(bilan.journal, serveur, cfg)
    ancien = Plan(plan_a.etape, plan_a.bibliotheque, plan_a.groupes, partiel=True, format=1)
    d = json.loads(chemin_a.read_text(encoding='utf-8'))
    d.update(format=1, empreinte=ancien.empreinte)
    chemin_a.write_text(json.dumps(d), encoding='utf-8')
    charge = plans.charger(chemin_a)
    assert charge.annule == [bilan.journal.name] and charge.empreinte == ancien.empreinte != plan_a.empreinte
