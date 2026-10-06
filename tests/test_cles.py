"""Clés de citation, étape 7 (D144, D146) : fonctions pures, puis plan sur la bibliothèque synthétique et le faux
serveur (application, conflit, annulation, relance, suivi, masquage)."""

import itertools
import tomllib

import pytest

from faux_serveur import FauxServeur
from test_appliquer import ecrire as ecrire_plan, sauvegarde_factice
from zot_clean import annulation, bbt, cles, lecture, plans
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.ecriture import Refus
from zot_clean.lecture import Bibliotheque, Element

_ids = itertools.count(1)


def fiche(cle_citation: str = '', ajout: str = '2026-01-01 00:00:00', cle: str | None = None, **champs) -> Element:
    n = next(_ids)
    if cle_citation:
        champs['citationKey'] = cle_citation
    return Element(n, cle or f'FICHE{n:03d}', 'journalArticle', ajout, True, champs)


def biblio(*fiches: Element) -> Bibliotheque:
    note = Element(next(_ids), 'NOTE0001', 'note', '2020-01-01', True, {'citationKey': 'durand2020'})
    return Bibliotheque(129, {e.id: e for e in (*fiches, note)}, {}, {}, {}, [])


def test_doubles_sans_tenir_compte_de_la_casse():
    b = biblio(fiche('Durand2020'), fiche('durand2020'), fiche('martin2019'), fiche())
    assert list(cles.doubles(b)) == ['durand2020']
    assert cles.doubles(b, casse=True) == {}


def test_doubles_tries_par_anciennete():
    recente = fiche('k', '2025-05-01 10:00:00', 'RECENTE1')
    ancienne = fiche('k', '2019-03-02 08:00:00', 'ANCIENNE')
    assert [e.cle for e in cles.doubles(biblio(recente, ancienne))['k']] == ['ANCIENNE', 'RECENTE1']


def test_lettres_comme_bbt():
    assert [cles.lettres(n) for n in (1, 2, 26, 27, 28, 52, 53)] == ['a', 'b', 'z', 'aa', 'ab', 'az', 'ba']


def test_suffixe_libre():
    assert cles.suffixe_libre('durand2020', {'durand2020'}) == 'a'
    assert cles.suffixe_libre('durand2020', {'durand2020', 'durand2020a'}) == 'b'
    assert cles.suffixe_libre('durand2020', {'Durand2020A'}) == 'b'
    assert cles.suffixe_libre('durand2020', {'Durand2020A'}, casse=True) == 'a'
    prises = {'k'} | {f'k{cles.lettres(n)}' for n in range(1, 27)}
    assert cles.suffixe_libre('k', prises) == 'aa'


def test_la_plus_ancienne_garde_la_cle_et_les_suffixes_sautent_les_cles_prises():
    a = fiche('durand2020', '2020-01-01', 'AAAAAAAA')
    b_ = fiche('Durand2020', '2021-01-01', 'BBBBBBBB')
    c = fiche('durand2020', '2022-01-01', 'CCCCCCCC')
    prise = fiche('durand2020a', '2023-01-01')
    d = cles.departager(biblio(c, prise, b_, a))
    assert not d.renvoyes and len(d.doubles) == 1
    double = d.doubles[0]
    assert double.cle == 'durand2020' and double.garde is a
    assert [(ch.fiche.cle, ch.avant, ch.apres) for ch in double.changements] == [
        ('BBBBBBBB', 'Durand2020', 'durand2020b'), ('CCCCCCCC', 'durand2020', 'durand2020c')]


def test_casse_distinguee_par_bbt():
    b = biblio(fiche('Durand2020', '2020-01-01'), fiche('durand2020', '2021-01-01'))
    assert cles.departager(b, casse=True).doubles == []
    assert len(cles.departager(b).doubles) == 1


def test_fiche_imposee_garde_la_cle():
    a = fiche('k2020', '2020-01-01', 'AAAAAAAA')
    b_ = fiche('k2020', '2021-01-01', 'BBBBBBBB')
    d = cles.departager(biblio(a, b_), gardes={'K2020': 'BBBBBBBB'})
    assert d.doubles[0].garde is b_ and d.doubles[0].changements[0].fiche is a
    # Une fiche imposée absente du groupe est ignorée.
    d = cles.departager(biblio(a, b_), gardes={'k2020': 'ZZZZZZZZ'})
    assert d.doubles[0].garde is a


def test_doublons_non_juges_renvoyes_a_l_etape_2():
    a, b_, c = (fiche('k2020', f'202{i}-01-01', f'{x * 8}') for i, x in enumerate('ABC'))
    autre_a, autre_b = fiche('m2020', cle='MMMMMMM1'), fiche('m2020', cle='MMMMMMM2')
    d = cles.departager(biblio(a, b_, c, autre_a, autre_b),
                        doublons_non_juges=[['AAAAAAAA', 'CCCCCCCC'], ['MMMMMMM1', 'XXXXXXXX']])
    assert list(d.renvoyes) == ['k2020'] and [e.cle for e in d.renvoyes['k2020']] == ['AAAAAAAA', 'BBBBBBBB', 'CCCCCCCC']
    # Une seule fiche du groupe de doublons dans le double : rien à fusionner entre elles, le double est départagé.
    assert [x.cle for x in d.doubles] == ['m2020']


def test_suffixes_uniques_entre_groupes():
    """Deux doubles dont les suffixes pourraient se rencontrer : chaque clé attribuée est réservée."""
    b = biblio(fiche('k', '2020-01-01'), fiche('k', '2021-01-01'), fiche('k', '2022-01-01'),
               fiche('ka', '2020-01-01'), fiche('KA', '2021-01-01'))
    nouvelles = [ch.apres.lower() for d in cles.departager(b).doubles for ch in d.changements]
    toutes = nouvelles + ['k', 'ka']
    assert len(set(toutes)) == len(toutes)


def test_restes_dans_extra():
    a = fiche('', extra='tex.ids: vieux\nCitation Key: durand2020\noriginal-date: 1938')
    b_ = fiche('durand2020', extra='citation key:  martin2019  ')
    c = fiche('x', extra='Pas de clé ici. Citation Key: dans une phrase')
    restes = cles.restes_extra(biblio(a, b_, c))
    assert [(e.cle, k) for e, k in restes] == [(a.cle, 'durand2020'), (b_.cle, 'martin2019')]


def test_cles_extra_et_sans_lignes():
    texte = 'tex.ids: vieux\r\ncitation key:  martin2019 \r\nCitation Key: autre\nnote libre'
    assert cles.cles_extra(texte) == ['martin2019', 'autre']
    assert cles.sans_lignes(texte) == 'tex.ids: vieux\r\nnote libre'


# --- Plan de l'étape 7 (D146) ---------------------------------------------------------

BBT = bbt.Etat(installe=True, actif=True, version='9.1.0', source=bbt.PROFIL)


class Monde:
    """Fiches créées à la fois dans la base synthétique et sur le faux serveur, avec la même clé."""

    def __init__(self, zotero, serveur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def fiche(self, titre, cle_citation='', extra='', ajout='2026-01-01', tags=(), DOI=''):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.fiche(titre, cle=cle, ajout=f'{ajout} 00:00:00', tags=tags, DOI=DOI,
                                          citationKey=cle_citation, extra=extra)
        self.serveur.ajouter(key=cle, title=titre, citationKey=cle_citation, extra=extra, DOI=DOI,
                             dateAdded=f'{ajout}T00:00:00Z', tags=[{'tag': t} for t in tags])
        return cle

    def synchroniser(self):
        """Clés et Extra du serveur reportés dans la base locale, comme après une synchronisation de Zotero."""
        for cle, iid in self.ids.items():
            d = self.serveur.elements[cle]
            self.zotero.db.execute("delete from itemData where itemID = ? and fieldID in (select fieldID from fields "
                                   "where fieldName in ('citationKey', 'extra'))", (iid,))
            self.zotero._champs(iid, {'citationKey': d.get('citationKey', ''), 'extra': d.get('extra', '')})

    def lire(self):
        self.zotero.synchroniser(self.serveur.version)
        return lecture.lire(self.zotero.enregistrer())


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


@pytest.fixture
def monde(zotero, serveur):
    m = Monde(zotero, serveur)
    x = {
        # Une clé portée trois fois, à la casse près, et le premier suffixe déjà pris.
        'a': m.fiche('Article A', 'durand2020', ajout='2020-01-01'),
        'b': m.fiche('Article B', 'Durand2020', ajout='2021-01-01'),
        'c': m.fiche('Article C', 'durand2020', ajout='2022-01-01'),
        'd': m.fiche('Article D', 'durand2020a', ajout='2023-01-01'),
        # Lignes d'Extra : vers le champ natif vide, identique, différente.
        'e': m.fiche('Article E', extra='tex.ids: vieux\nCitation Key: martin2019\noriginal-date: 1938'),
        'f': m.fiche('Article F', 'lee2018', extra='Citation Key: lee2018'),
        'g': m.fiche('Article G', 'kim2017', extra='Citation Key: park2017'),
        # Une clé unique, et une clé qui sort d'Extra pour la rejoindre : la fiche plus récente reçoit le suffixe.
        'h': m.fiche('Article H', 'zhang2016', ajout='2016-01-01'),
        'k': m.fiche('Article K', extra='Citation Key: zhang2016', ajout='2025-01-01'),
        # Clé partagée avec une fiche confidentielle : tout le groupe est masqué.
        's1': m.fiche('Mon dossier médical', 'secret2020', ajout='2020-01-01', tags=('_privé',)),
        's2': m.fiche('Autre article', 'Secret2020', ajout='2021-01-01'),
        # Doublons non jugés qui partagent leur clé : renvoyés à l'étape 2.
        'u1': m.fiche('Article U', 'dup2020', DOI='10.1/dup', ajout='2020-01-01'),
        'u2': m.fiche('Article U bis', 'dup2020', DOI='10.1/dup', ajout='2021-01-01'),
    }
    return m, x


def ops_du_plan(plan) -> dict:
    return {op.cle: op for g in plan.groupes for op in g.operations}


def test_plan_et_suivi(monde, cfg, serveur):
    m, x = monde
    cfg.ecriture.essai = 2
    plan, rapport = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    ops = ops_du_plan(plan)
    assert ops[x['b']].apres == {'citationKey': 'durand2020b'} and ops[x['c']].apres == {'citationKey': 'durand2020c'}
    assert ops[x['b']].avant == {'citationKey': 'Durand2020'}
    assert ops[x['e']].apres == {'citationKey': 'martin2019', 'extra': 'tex.ids: vieux\noriginal-date: 1938'}
    assert ops[x['f']].apres == {'extra': ''} and ops[x['f']].avant == {'extra': 'Citation Key: lee2018'}
    # La clé sortie d'Extra rejoint un double : suffixe et Extra en une seule opération, dans le groupe du double.
    assert ops[x['k']].apres == {'citationKey': 'zhang2016a', 'extra': ''}
    assert ops[x['s2']].apres == {'citationKey': 'secret2020a'}
    # Rien pour une clé unique, la fiche qui garde la clé, une ligne différente (à juger) ou des doublons non jugés.
    for k in ('a', 'd', 'g', 'h', 's1', 'u1', 'u2'):
        assert x[k] not in ops
    assert sorted(g.id for g in plan.groupes) == sorted(
        [f"double-{x['a']}", f"double-{x['h']}", f"double-{x['s1']}", x['e'], x['f']])
    # Les deux premiers groupes (l'essai) couvrent les trois sortes de changement.
    sortes = {s for g in plan.groupes[:2] for op in g.operations for s in op.nature.split(', ')}
    assert sortes == {cles.SUFFIXE, cles.VERS_NATIF, cles.RETIREE}

    assert '## Essai' in rapport and "## Renvoyés à l'étape 2" in rapport and 'dup2020' in rapport
    assert 'park2017' in rapport and '## À juger' in rapport
    suivi = (cfg.suivi / cles.FICHIER).read_text(encoding='utf-8')
    brut = tomllib.loads(suivi)
    assert {tuple(d['fiches']) for d in brut['double']} == {
        (x['a'], x['b'], x['c']), (x['h'], x['k']), (x['s1'], x['s2']), (x['u1'], x['u2'])}
    assert [e['fiche'] for e in brut['extra']] == [x['g']]
    assert '→ durand2020c' in suivi and 'renvoyé' in suivi
    assert 'Article A, ajoutée le 2020-01-01, garde la clé' in suivi and 'Article A garde la clé' in rapport
    # Fiche confidentielle (D126) : ni son titre ni la clé de citation dans le rapport et le suivi, titre du groupe
    # masqué dans le plan, qui garde les valeurs nécessaires à l'écriture.
    for texte in (rapport, suivi):
        assert 'médical' not in texte and 'ecret2020' not in texte.lower()
    assert next(g.titre for g in plan.groupes if g.id == f"double-{x['s1']}") == '(fiche confidentielle)'
    assert f"{x['s2']} reçoit un suffixe" in rapport
    # La clé suffixée reprend le titre d'une autre fiche : le rapport propose de la régénérer dans Better BibTeX.
    assert "→ durand2020b (clé tirée du titre d'une autre fiche)" in rapport and 'Better BibTeX › Refresh' in rapport


def test_essai_application_conflit_annulation_relance(monde, cfg, serveur):
    m, x = monde
    cfg.ecriture.essai = 2
    plan, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    chemin = ecrire_plan(plan, cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert len(bilan.faits) == 2 and bilan.restants == 3
    with pytest.raises(Refus, match='sauvegarde'):
        appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    sauvegarde_factice(cfg)
    # Une clé changée dans Zotero entre-temps met son groupe en conflit, cette fiche reste intacte.
    groupe = f"double-{x['a']}"
    assert groupe not in bilan.faits
    serveur.modifier(x['c'], citationKey='durandArticle2022')
    bilan = appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    el = serveur.elements
    assert list(bilan.conflits) == [groupe]
    assert el[x['c']]['citationKey'] == 'durandArticle2022'
    assert el[x['e']]['citationKey'] == 'martin2019' and el[x['e']]['extra'] == 'tex.ids: vieux\noriginal-date: 1938'
    assert el[x['f']]['extra'] == '' and el[x['f']]['citationKey'] == 'lee2018'
    assert el[x['k']]['citationKey'] == 'zhang2016a' and el[x['h']]['citationKey'] == 'zhang2016'
    assert el[x['s2']]['citationKey'] == 'secret2020a' and el[x['g']]['extra'] == 'Citation Key: park2017'
    # La clé remise dans Zotero, la relance du même plan termine le groupe.
    serveur.modifier(x['c'], citationKey='durand2020')
    assert not appliquer(plan, chemin, serveur.client(), cfg, TOUT).conflits
    assert el[x['b']]['citationKey'] == 'durand2020b' and el[x['c']]['citationKey'] == 'durand2020c'

    # Relance après synchronisation : plus rien à faire, le cas à juger reste signalé (D119).
    m.synchroniser()
    reste, rapport = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    assert reste.groupes == [] and 'park2017' in rapport

    # Annulation : clés et Extra d'avant reviennent.
    for journal in annulation.journaux_vises(chemin, cfg):
        p_ann, _ = annulation.planifier([journal], serveur.client(), set())
        c_ann = plans.ecrire(p_ann, cfg.plans, '# annulation')
        appliquer(p_ann, c_ann, serveur.client(), cfg, ESSAI)
        appliquer(p_ann, c_ann, serveur.client(), cfg, TOUT)
    assert el[x['e']]['citationKey'] == '' and el[x['e']]['extra'].startswith('tex.ids: vieux\nCitation Key: martin')
    assert el[x['k']]['citationKey'] == '' and el[x['k']]['extra'] == 'Citation Key: zhang2016'
    assert el[x['b']]['citationKey'] == 'Durand2020' and el[x['f']]['extra'] == 'Citation Key: lee2018'


def test_relance_apres_un_essai_ne_planifie_que_la_difference(monde, cfg, serveur):
    m, x = monde
    cfg.ecriture.essai = 2
    plan, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    appliquer(plan, ecrire_plan(plan, cfg), serveur.client(), cfg, ESSAI)
    m.synchroniser()
    reste, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    assert {g.id for g in reste.groupes} == {g.id for g in plan.groupes[2:]}


def test_decisions_du_suivi(monde, cfg, serveur):
    m, x = monde
    cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    chemin = cfg.suivi / cles.FICHIER
    texte = chemin.read_text(encoding='utf-8')
    # La fiche C garde la clé, le double de zhang2016 est écarté, la clé d'Extra de G remplace la clé native.
    remplacements = {
        f'fiches = ["{x["a"]}", "{x["b"]}", "{x["c"]}"]\ngarde = ""':
            f'fiches = ["{x["a"]}", "{x["b"]}", "{x["c"]}"]\ngarde = "{x["c"]}"',
        f'fiches = ["{x["h"]}", "{x["k"]}"]\ngarde = ""\ndecision = ""':
            f'fiches = ["{x["h"]}", "{x["k"]}"]\ngarde = ""\ndecision = "écarter"',
        f'fiche = "{x["g"]}"\ndecision = ""': f'fiche = "{x["g"]}"\ndecision = "extra"'}
    for avant, apres in remplacements.items():
        assert avant in texte
        texte = texte.replace(avant, apres)
    chemin.write_text(texte, encoding='utf-8')
    plan, rapport = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    ops = ops_du_plan(plan)
    assert x['c'] not in ops and ops[x['a']].apres == {'citationKey': 'durand2020b'}
    assert ops[x['b']].apres == {'citationKey': 'durand2020c'}
    # Le double écarté reste tel quel, mais la ligne d'Extra de K passe quand même dans le champ natif.
    assert x['h'] not in ops and ops[x['k']].apres == {'citationKey': 'zhang2016', 'extra': ''}
    assert ops[x['g']].apres == {'citationKey': 'park2017', 'extra': ''} and cles.REMPLACEE in ops[x['g']].nature
    assert '1 cas écarté' in rapport
    # Les décisions sont gardées à la réécriture du suivi, celle de G aussi, jusqu'à ce que son cas soit réglé dans
    # Zotero (D177).
    brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    assert [d['decision'] for d in brut['double'] if x['h'] in d['fiches']] == ['écarter']
    assert [d['garde'] for d in brut['double'] if x['a'] in d['fiches']] == [x['c']]
    assert [(d['fiche'], d['decision']) for d in brut['extra']] == [(x['g'], 'extra')]
    plan, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    assert ops_du_plan(plan)[x['g']].apres == {'citationKey': 'park2017', 'extra': ''}

    # « natif » garde la clé native et retire la ligne.
    chemin.write_text(cles.EN_TETE + f'\n[[extra]]\nfiche = "{x["g"]}"\ndecision = "natif"\n', encoding='utf-8')
    plan, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    assert ops_du_plan(plan)[x['g']].apres == {'extra': ''}
    # Une décision inconnue est refusée.
    chemin.write_text(cles.EN_TETE + f'\n[[extra]]\nfiche = "{x["g"]}"\ndecision = "peut-être"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='décision inconnue'):
        cles.planifier(m.lire(), cfg, serveur.client(), BBT)


def test_decisions_par_commande(monde, cfg, serveur, monkeypatch, capsys):
    """D177 : les mêmes décisions que ci-dessus, par commande, sur les seuls cas qui attendent."""
    from zot_clean import ecriture
    from zot_clean.cli import main
    m, x = monde
    cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    s = cles.charger(cfg)
    with pytest.raises(SystemExit, match='ne figure dans aucun cas'):
        cles.decider(s, {'ZZZZZZZZ': 'garder'})
    with pytest.raises(SystemExit, match="pas de ligne d'Extra à juger"):
        cles.decider(s, {x['a']: 'natif'})
    with pytest.raises(SystemExit, match='décision inconnue « peut-être »'):
        cles.decider(s, {x['g']: 'peut-être'})
    with pytest.raises(SystemExit, match='Une seule décision par clé en double'):
        cles.decider(s, {x['a']: 'garder', x['c']: 'garder'})

    cfg.dossier_travail.mkdir(exist_ok=True)
    (cfg.dossier_travail / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n',
                                                     encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    monkeypatch.setattr(bbt, 'detecter', lambda dossier: BBT)
    dossier = ['--dossier', str(cfg.dossier_travail)]
    assert main(['cles', 'decider', f'{x["c"].lower()}=garder', f'{x["h"]}=ecarter', f'{x["g"]}=extra',
                 '--raison', 'cité ainsi', *dossier]) == 0
    assert '3 cas décidé(s)' in capsys.readouterr().out
    assert main(['cles', 'decider', f'{x["h"]}=écarter', *dossier]) == 1
    assert 'déjà prise' in capsys.readouterr().err
    assert main(['cles', 'decider', x['g'], *dossier]) == 1
    assert 'FICHE=décision' in capsys.readouterr().err
    texte = (cfg.suivi / cles.FICHIER).read_text(encoding='utf-8')
    assert texte.startswith(cles.EN_TETE) and 'Article A, ajoutée le 2020-01-01' in texte
    brut = tomllib.loads(texte)
    assert [(d['decision'], d['raison']) for d in brut['double'] if x['h'] in d['fiches']] == [('écarter', 'cité ainsi')]
    assert [d['garde'] for d in brut['double'] if x['a'] in d['fiches']] == [x['c']]
    assert [(d['fiche'], d['decision']) for d in brut['extra']] == [(x['g'], 'extra')]
    plan, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    ops = ops_du_plan(plan)
    assert x['c'] not in ops and x['h'] not in ops
    assert ops[x['g']].apres == {'citationKey': 'park2017', 'extra': ''}


def test_sans_bbt_seuls_les_doubles(monde, cfg, serveur):
    m, x = monde
    plan, rapport = cles.planifier(m.lire(), cfg, serveur.client(), bbt.Etat())
    ops = ops_du_plan(plan)
    assert x['b'] in ops and x['e'] not in ops and x['f'] not in ops and x['k'] not in ops
    assert "Better BibTeX n'est pas actif" in rapport and '4 fiches dont Extra garde une ligne « Citation Key: » attendent Better BibTeX' in rapport


def test_refus_et_avertissements(monde, cfg, serveur, zotero):
    m, x = monde
    b = m.lire()
    with pytest.raises(Refus, match='propre base'):
        cles.planifier(b, cfg, serveur.client(), bbt.Etat(installe=True, actif=True, version='7.0.5'))
    cfg.methode.cles_citation = False
    with pytest.raises(Refus, match='cles_citation = false'):
        cles.planifier(b, cfg, serveur.client(), BBT)
    cfg.methode.cles_citation = True
    zotero.db.execute("delete from fields where fieldName = 'citationKey'")
    with pytest.raises(Refus, match='Zotero 7'):
        cles.planifier(lecture.lire(zotero.enregistrer()), cfg, serveur.client(), BBT)
    serveur.modifier(x['a'], title='Changé ailleurs')
    with pytest.raises(Refus, match='pas encore reçu'):
        cles.planifier(b, cfg, serveur.client(), BBT)


def test_reglages_de_bbt_signales(zotero, serveur, cfg):
    m = Monde(zotero, serveur)
    m.fiche('Article A', 'durand2020')
    m.fiche('Sans clé')
    etat = bbt.Etat(installe=True, actif=True, version='9.1.0', source=bbt.PROFIL, regenere=True, remplissage=0)
    _, rapport = cles.planifier(m.lire(), cfg, serveur.client(), etat)
    assert 'Regenerate citation key' in rapport and 'Automatically fill citation key after' in rapport
    assert 'clic droit, Better BibTeX › Fill' in rapport


def test_fiche_modifiee_depuis_la_copie_locale(monde, cfg, serveur):
    m, x = monde
    b = m.lire()
    serveur.elements[x['e']]['extra'] = 'Citation Key: autre2019'  # sans nouvelle version de la bibliothèque
    plan, rapport = cles.planifier(b, cfg, serveur.client(), BBT)
    assert x['e'] not in ops_du_plan(plan)
    assert f"La fiche {x['e']} a changé depuis la copie locale" in rapport


def test_suivi_pas_ecrit_sans_cas(zotero, serveur, cfg):
    m = Monde(zotero, serveur)
    m.fiche('Article F', 'lee2018', extra='Citation Key: lee2018')
    plan, _ = cles.planifier(m.lire(), cfg, serveur.client(), BBT)
    assert len(plan.groupes) == 1 and not (cfg.suivi / cles.FICHIER).exists()


def test_renvoi_au_suivi_seulement_s_il_y_a_des_cas(zotero, serveur, tmp_path, monkeypatch, capsys):
    from zot_clean import ecriture
    from zot_clean.cli import main
    m = Monde(zotero, serveur)
    m.fiche('Article A', 'durand2020')
    m.lire()
    travail = tmp_path / 'travail'
    (travail / 'suivi').mkdir(parents=True)
    (travail / 'suivi' / cles.FICHIER).write_text(cles.EN_TETE, encoding='utf-8')  # en-tête seul, après une passe
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    monkeypatch.setattr(bbt, 'detecter', lambda dossier: BBT)
    main(['cles', 'planifier', '--dossier', str(travail)])
    sortie = capsys.readouterr().out
    assert 'Rien à faire' in sortie and 'Cas qui demandent' not in sortie


def test_suffixe_continue_la_serie_de_bbt():
    from zot_clean import cles as c
    assert c.base_de('durand2020a') == 'durand2020' and c.base_de('DURAND2020A') == 'DURAND2020'
    assert c.base_de('sacksLhommeQuiPrenait1988') == 'sacksLhommeQuiPrenait1988'
    base = c.base_de('auteurTitre2000a')
    assert base + c.suffixe_libre(base, ['auteurTitre2000a', 'AUTEURTITRE2000A']) == 'auteurTitre2000b'
