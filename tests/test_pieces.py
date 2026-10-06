"""PDF identiques (D125) : repérage, corbeille et rattachement, garde-fou des copies annotées, annulation."""

import pytest

from faux_serveur import FauxServeur
from test_annulation import annuler
from test_appliquer import ecrire
from test_doublons import Double
from zot_clean import pieces as p
from zot_clean.appliquer import ESSAI, appliquer
from zot_clean.config import Config


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


@pytest.fixture
def monde(zotero, serveur):
    """Le PDF de Grant rattaché aussi à la fiche d'Ardery, Vygotsky avec deux fois le même PDF, un livre et son
    chapitre qui partagent le PDF du livre, et un PDF annoté sur la mauvaise fiche."""
    dd = Double(zotero, serveur)
    f = {n: dd.fiche(t) for n, t in (('grant', 'Paint and Be Happy'), ('ardery', 'Loser wins'),
                                     ('vygotsky', 'Mind in society'), ('livre', 'The practice turn'),
                                     ('chapitre', 'Throwing out the tacit rule book'), ('bon', 'Le bon article'),
                                     ('mauvais', 'Un autre article'))}
    c = {'grant': dd.pdf(f['grant'], 'grant.pdf', b'%PDF grant'),
         'ardery': dd.pdf(f['ardery'], 'grant.pdf', b'%PDF grant'),
         'v1': dd.pdf(f['vygotsky'], 'v.pdf', b'%PDF vygotsky'),
         'v2': dd.pdf(f['vygotsky'], 'v copie.pdf', b'%PDF vygotsky'),
         'livre': dd.pdf(f['livre'], 'livre.pdf', b'%PDF livre'),
         'chapitre': dd.pdf(f['chapitre'], 'livre.pdf', b'%PDF livre'),
         'bon': dd.pdf(f['bon'], 'a.pdf', b'%PDF annote'),
         'mauvais': dd.pdf(f['mauvais'], 'a.pdf', b'%PDF annote', annotee=True),
         'seul': dd.pdf(f['grant'], 'autre.pdf', b'%PDF unique')}
    return dd, f, c


def decider(cfg, b, decisions):
    entrees = p.chercher(b, cfg)
    for e in entrees:
        for copies, (decision, corbeille, rattacher) in decisions.items():
            if set(e.copies) == set(copies):
                e.decision, e.corbeille, e.rattacher = decision, corbeille, rattacher
    p.ecrire(cfg, entrees, b)


def test_chercher(monde, cfg):
    dd, f, c = monde
    entrees = p.chercher(dd.bibliotheque(), cfg)
    assert sorted(sorted(e.copies) for e in entrees) == sorted(sorted(g) for g in (
        (c['grant'], c['ardery']), (c['v1'], c['v2']), (c['livre'], c['chapitre']), (c['bon'], c['mauvais'])))
    texte = (cfg.suivi / p.FICHIER).read_text(encoding='utf-8')
    assert 'Loser wins' in texte and '1 annotation(s) ou note(s)' in texte


def test_corbeille_rattacher_et_annulation(monde, cfg, serveur):
    dd, f, c = monde
    b = dd.bibliotheque()
    decider(cfg, b, {(c['grant'], c['ardery']): (p.APPLIQUER, [c['ardery']], {}),
                     (c['v1'], c['v2']): (p.APPLIQUER, [c['v2']], {}),
                     (c['livre'], c['chapitre']): (p.GARDER, [], {}),
                     # La copie annotée est sur la mauvaise fiche : on la rattache, et l'autre va à la corbeille.
                     (c['bon'], c['mauvais']): (p.APPLIQUER, [c['bon']], {c['mauvais']: f['bon']})})
    plan, rapport = p.planifier(cfg, serveur.client(), b)
    assert len(plan.groupes) == 3 and 'Groupes écartés' not in rapport
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert not bilan.conflits and not bilan.erreurs
    el = serveur.elements
    assert el[c['ardery']]['deleted'] and el[c['v2']]['deleted'] and el[c['bon']]['deleted']
    assert el[c['mauvais']]['parentItem'] == f['bon'] and not el[c['grant']].get('deleted')
    # Une nouvelle recherche garde les décisions des groupes encore présents.
    assert {e.decision for e in p.chercher(b, cfg)} == {p.APPLIQUER, p.GARDER}
    plan_a, _, chemin_a = annuler(chemin, serveur, cfg)
    appliquer(plan_a, chemin_a, serveur.client(), cfg, ESSAI)
    assert not el[c['ardery']].get('deleted') and el[c['mauvais']]['parentItem'] == f['mauvais']


def test_garde_fous(monde, cfg, serveur):
    dd, f, c = monde
    b = dd.bibliotheque()
    decider(cfg, b, {(c['bon'], c['mauvais']): (p.APPLIQUER, [c['mauvais']], {}),
                     (c['v1'], c['v2']): (p.APPLIQUER, [c['v1'], c['v2']], {}),
                     (c['grant'], c['ardery']): (p.APPLIQUER, [c['seul']], {})})
    plan, rapport = p.planifier(cfg, serveur.client(), b)
    assert not plan.groupes
    assert 'porte des annotations ou des notes' in rapport
    assert 'toutes les copies iraient à la corbeille' in rapport
    assert 'ne fait pas partie des copies du groupe' in rapport


def test_groupe_confidentiel_masque(zotero, serveur, cfg):
    dd = Double(zotero, serveur)
    secrete = dd.fiche('Mon dossier médical', tags=('_privé',))
    autre = dd.fiche('Une fiche publique')
    copie = dd.pdf(secrete, 'a.pdf', b'%PDF secret')
    dd.pdf(autre, 'a.pdf', b'%PDF secret')
    b = dd.bibliotheque()
    p.chercher(b, cfg)
    texte = (cfg.suivi / p.FICHIER).read_text(encoding='utf-8')
    assert 'médical' not in texte and 'publique' not in texte and '(fiche confidentielle)' in texte
    decider(cfg, b, {tuple(e.copies): ('appliquer', [k for k in e.copies if k != copie], {})
                     for e in p.charger(cfg)})
    plan, rapport = p.planifier(cfg, serveur.client(), b)
    assert len(plan.groupes) == 1 and 'médical' not in rapport and 'publique' not in rapport


def test_avertissement_doublons_et_fichiers_absents(monde, cfg):
    """Un PDF partagé par deux fiches renvoie à `zc doublons chercher`, qui les propose (D125), et un PDF
    absent du disque est signalé (D168)."""
    from zot_clean import doublons
    dd, f, c = monde
    b = dd.bibliotheque()
    entrees = p.chercher(b, cfg)
    avert = p.avertissement(b, cfg, entrees)
    assert avert.startswith('3 PDF partagés par des fiches différentes') and 'zc doublons chercher' in avert
    assert 'absent' not in avert
    doublons.chercher(b, cfg)
    assert p.avertissement(b, cfg, entrees) == ''
    dd.pdf(f['bon'], 'absent.pdf', None)
    b = dd.bibliotheque()
    assert p.avertissement(b, cfg, p.chercher(b, cfg)).startswith('1 PDF absent du disque')


def test_decisions_par_commande(monde, cfg, monkeypatch, capsys):
    """D177 : chaque groupe se décide par commande, désigné par l'une de ses copies, avec les mêmes garde-fous que le
    plan (copie annotée jamais à la corbeille, une copie gardée au moins)."""
    from zot_clean import ecriture
    from zot_clean.cli import main
    dd, f, c = monde
    b = dd.bibliotheque()
    entrees = p.chercher(b, cfg)
    with pytest.raises(SystemExit, match=f'ne contient la copie {f["grant"]}'):  # clé de fiche, non de copie
        p.decider(entrees, b, [f['grant']])
    with pytest.raises(SystemExit, match='annotations ou des notes'):
        p.decider(entrees, b, [c['mauvais']])
    with pytest.raises(SystemExit, match='il faut en garder une'):
        p.decider(entrees, b, [c['v1'], c['v2']])
    entrees = p.chercher(b, cfg)
    assert p.decider(entrees, b, [c['bon']], {c['mauvais']: f['bon']}, raison='PDF annoté') == (1, 0)
    assert p.decider(entrees, b, garder=[c['chapitre']], raison='chapitre et livre') == (0, 1)
    with pytest.raises(SystemExit, match='déjà décidé'):
        p.decider(entrees, b, garder=[c['bon']])
    groupe = next(e for e in entrees if c['bon'] in e.copies)
    assert (groupe.decision, groupe.corbeille, groupe.rattacher, groupe.raison) == (
        p.APPLIQUER, [c['bon']], {c['mauvais']: f['bon']}, 'PDF annoté')

    # Par la ligne de commande.
    cfg.dossier_travail.mkdir(exist_ok=True)
    (cfg.dossier_travail / 'config.toml').write_text(f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n',
                                                     encoding='utf-8')

    def sans_cle(cfg):
        raise SystemExit('pas de clé')
    monkeypatch.setattr(ecriture, 'depuis_config', sans_cle)
    dossier = ['--dossier', str(cfg.dossier_travail)]
    assert main(['pieces', 'accepter', '--corbeille', c['v2'], *dossier]) == 0
    assert '1 groupe(s) à appliquer, 0 gardé(s)' in capsys.readouterr().out
    assert main(['pieces', 'refuser', c['livre'], '--raison', 'chapitre et livre', *dossier]) == 0
    assert main(['pieces', 'accepter', '--rattacher', c['mauvais'], *dossier]) == 1
    assert 'COPIE=FICHE' in capsys.readouterr().err
    relues = {frozenset(e.copies): e for e in p.charger(cfg)}
    assert relues[frozenset((c['v1'], c['v2']))].corbeille == [c['v2']]
    assert relues[frozenset((c['livre'], c['chapitre']))].decision == p.GARDER
    assert relues[frozenset((c['grant'], c['ardery']))].decision == ''
    assert 'Loser wins' in (cfg.suivi / p.FICHIER).read_text(encoding='utf-8')


def test_annotation_ajoutee_apres_le_plan(monde, cfg, serveur):
    # D182 : la copie était sans annotation au plan, elle en a reçu une avant l'application. Elle reste en place.
    dd, f, c = monde
    b = dd.bibliotheque()
    decider(cfg, b, {(c['v1'], c['v2']): (p.APPLIQUER, [c['v2']], {})})
    plan, _ = p.planifier(cfg, serveur.client(), b)
    assert [op.enfants for op in plan.groupes[0].operations] == [[]]
    annotation = serveur.ajouter('annotation', parentItem=c['v2'])
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert annotation in bilan.conflits['1'] and 'hors de la corbeille' in bilan.conflits['1']
    assert not serveur.elements[c['v2']].get('deleted')
