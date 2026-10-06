import json
import textwrap

import pytest

from zot_clean import fonds as f, lecture
from zot_clean.cli import main
from zot_clean.config import Config

PLAN = """\
# Plan du fonds

Texte libre, ignoré.

# Fonds

## Psychologie

Étude de l'esprit et du comportement.

### Perception

Vision, audition, attention.
Inclut : illusions visuelles.
Exclut : neurophysiologie de la rétine.

### Développement

Enfance et apprentissage.

## Philosophie

Textes et commentaires.

### Esthétique

Théorie de l'art et du beau.

# Concepts

## Pas une discipline

Section ignorée.
"""


@pytest.fixture
def cfg(tmp_path, zotero):
    c = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    c.dossier_travail.mkdir()
    c.confidentialite.collections_exclues = ['Vieux/Personnel']
    return c


@pytest.fixture
def biblio(zotero):
    """Classement sale sur plusieurs niveaux (D107) : projet, archives, fonds commencé, collection à répartir,
    tags thématiques, collection exclue par le filtre."""
    z = zotero
    c = {'Inbox': z.collection('Inbox'), 'Projets': z.collection('Projets'), 'Fonds': z.collection('Fonds'),
         'Vieux': z.collection('Vieux'), 'Archives': z.collection('Archives')}
    c['Cours'] = z.collection('Cours L1', c['Projets'])
    c['Ancien'] = z.collection('Cours 2019', c['Archives'])
    c['Psy'] = z.collection('Psychologie', c['Fonds'])
    c['Vision'] = z.collection('Vision', c['Vieux'])
    c['Divers'] = z.collection('Divers', c['Vieux'])
    c['Profond'] = z.collection('Profond', c['Divers'])
    c['Perso'] = z.collection('Personnel', c['Vieux'])
    c['Secret'] = z.collection('Journal intime', c['Perso'])
    for i in range(12):
        z.fiche(f'Perception des couleurs {i:02}', collections=(c['Vision'],), tags=('vision', 'couleur'))
    z.fiche('Illusions et attention', collections=(c['Vision'], c['Cours']), tags=('vision', 'attention'))
    z.fiche('Esthétique du beau', collections=(c['Divers'],), tags=('esthétique', ('Aesthetics', 1)))
    z.fiche('Piaget et le jeu', collections=(c['Divers'], c['Psy']), tags=('développement', '1 à lire', '_import'))
    z.fiche('Note profonde', collections=(c['Profond'],))
    z.fiche('Carnet de rêves', collections=(c['Secret'],), tags=('rêves',))
    z.fiche('Fiche confidentielle', collections=(c['Divers'],), tags=('_privé', 'secretissime'))
    z.fiche('Sans collection', tags=('vision',))
    z.fiche('Ancien cours', collections=(c['Ancien'],))
    z.enregistrer()
    return c


def inventorier(cfg):
    b = lecture.lire(cfg.base)
    rapport, suivi, nouvelles, disparues = f.inventaire(b, cfg)
    f.ecrire_suivi(cfg, suivi)
    return rapport, suivi, disparues


def par_chemin(suivi):
    return {c.chemin: c for c in suivi.collections}


def test_inventaire_filtre_et_preremplit(cfg, biblio):
    rapport, suivi, _ = inventorier(cfg)
    # Filtre de confidentialité : ni titres, ni tags, ni collections exclues.
    for secret in ('Journal intime', 'Carnet de rêves', 'rêves', 'confidentielle', 'secretissime'):
        assert secret not in rapport
    assert 'Personnel' not in rapport
    # Tags d'état, techniques et automatiques écartés.
    assert '1 à lire' not in rapport.split('## Tags thématiques')[1]
    assert '_import' not in rapport and 'Aesthetics' not in rapport
    assert '- vision (14)' in rapport and 'couleur + vision (12)' in rapport
    vision = rapport.split('### Vieux/Vision')[1].split('###')[0]
    assert vision.count('\n- Durand, 2020, ') == 10
    assert 'Références partagées avec Projets/Cours L1 (1)' in rapport
    assert 'dont 1 dans aucune collection' in rapport
    s = par_chemin(suivi)
    assert set(s) == {'Projets/Cours L1', 'Archives/Cours 2019', 'Fonds/Psychologie', 'Vieux', 'Vieux/Vision',
                      'Vieux/Divers', 'Vieux/Divers/Profond', 'Vieux/Personnel'}
    assert (s['Projets/Cours L1'].sort, s['Projets/Cours L1'].cible) == (f.PROJET, 'Projets/Cours L1')
    assert s['Archives/Cours 2019'].sort == f.ARCHIVES
    assert s['Vieux/Personnel'].sort == f.HORS_PLAN
    assert s['Fonds/Psychologie'].sort == '' and s['Vieux/Vision'].effectif == 13
    assert s['Vieux/Divers'].effectif == 2  # la fiche exclue ne compte pas


def test_relance_garde_les_sorts(cfg, biblio, zotero):
    inventorier(cfg)
    texte = (cfg.suivi / f.FICHIER).read_text(encoding='utf-8')
    texte = texte.replace('chemin = "Vieux/Vision"\neffectif = 13\nsort = ""\ncible = ""',
                          'chemin = "Vieux/Vision"\neffectif = 13\nsort = "theme"\ncible = "Psychologie/Perception"')
    texte = texte.replace('[tags]', '[tags]\n"vision" = "Psychologie/Perception"')
    (cfg.suivi / f.FICHIER).write_text(texte, encoding='utf-8')
    zotero.db.execute('delete from collections where collectionID = ?', (biblio['Profond'],))
    zotero.collection('Nouvelle')
    zotero.enregistrer()
    _, suivi, disparues = inventorier(cfg)
    s = par_chemin(suivi)
    assert (s['Vieux/Vision'].sort, s['Vieux/Vision'].cible) == (f.THEME, 'Psychologie/Perception')
    assert 'Nouvelle' in s and 'Vieux/Divers/Profond' not in s
    assert [c.chemin for c in disparues] == ['Vieux/Divers/Profond']
    assert f.charger_suivi(cfg).tags == {'vision': 'Psychologie/Perception'}


def test_sort_inconnu(cfg, biblio):
    inventorier(cfg)
    chemin = cfg.suivi / f.FICHIER
    chemin.write_text(chemin.read_text(encoding='utf-8').replace('sort = ""', 'sort = "jeter"', 1), encoding='utf-8')
    with pytest.raises(SystemExit, match='sort inconnu'):
        f.charger_suivi(cfg)


def test_lire_plan(cfg):
    p = f.lire_plan(PLAN, cfg)
    assert list(p.noeuds) == ['Psychologie', 'Psychologie/Perception', 'Psychologie/Développement', 'Philosophie',
                              'Philosophie/Esthétique']
    perception = p.noeuds['Psychologie/Perception']
    assert perception.definition == 'Vision, audition, attention.'
    assert perception.inclut == 'illusions visuelles.' and perception.exclut == 'neurophysiologie de la rétine.'
    assert not p.erreurs and not p.avertissements


def test_erreurs_du_plan(cfg):
    texte = textwrap.dedent("""\
        # Fonds
        ## Psychologie
        Définition.
        ### Perception
        ### Perception
        #### Couleur
        ##### Trop profond
        ## Archives
        #### Orphelin
        ## A/B
        """)
    p = f.lire_plan(texte, cfg)
    erreurs = ' '.join(p.erreurs)
    assert 'existe déjà' in erreurs and 'au-delà de 3 niveaux' in erreurs and "nom d'une racine" in erreurs
    assert "n'a pas de parent" in erreurs and 'contenant « / »' in erreurs
    assert any('Perception' in a and 'définition' in a for a in p.avertissements)
    assert 'aucune section' in f.lire_plan('## Psychologie\n', cfg).erreurs[0]


def test_plan_sans_theme_signale(cfg):
    p = f.lire_plan('# Fonds\n## Psychologie\nEsprit.\n## Philosophie\nIdées.\n', cfg)
    assert not p.erreurs and any("aucune discipline n'a de thème" in a for a in p.avertissements)
    assert not any('thème (titre' in a for a in f.lire_plan(PLAN, cfg).avertissements)


def test_valider_puis_changement(cfg, biblio, capsys):
    inventorier(cfg)
    (cfg.dossier_travail / f.PLAN).write_text(PLAN, encoding='utf-8')
    dossier = ['--dossier', str(cfg.dossier_travail)]
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n', encoding='utf-8')
    assert main(['fonds', 'valider', *dossier]) == 1
    assert "n'a pas de sort" in capsys.readouterr().out
    s = f.charger_suivi(cfg)
    sorts = {'Fonds/Psychologie': (f.THEME, 'Psychologie', []), 'Vieux': (f.DISSOUDRE, '', []),
             'Vieux/Vision': (f.THEME, 'Psychologie/Perception', []),
             'Vieux/Divers': (f.REPARTIR, '', ['Philosophie/Esthétique', 'Psychologie/Développement']),
             'Vieux/Divers/Profond': (f.ARCHIVES, '', [])}
    for c in s.collections:
        if c.chemin in sorts:
            c.sort, c.cible, c.candidats = sorts[c.chemin]
    s.tags['esthétique'] = 'Philosophie/Inexistant'
    f.ecrire_suivi(cfg, s)
    assert main(['fonds', 'valider', *dossier]) == 1
    assert "« Philosophie/Inexistant », qui n'est pas dans plan.md" in capsys.readouterr().out
    s.tags['esthétique'] = 'Philosophie/Esthétique'
    f.ecrire_suivi(cfg, s)
    assert main(['fonds', 'valider', *dossier]) == 0
    assert '--enregistrer' in capsys.readouterr().out and not (cfg.suivi / f.VALIDATION).exists()
    assert main(['fonds', 'valider', '--enregistrer', *dossier]) == 0
    assert f.validation_a_jour(cfg) == (True, [])
    # Retoucher une définition ne change pas la structure.
    (cfg.dossier_travail / f.PLAN).write_text(PLAN.replace('Théorie de l\'art', 'Philosophie de l\'art'),
                                               encoding='utf-8')
    assert f.validation_a_jour(cfg) == (True, [])
    # Un thème de plus, si.
    (cfg.dossier_travail / f.PLAN).write_text(PLAN.replace('# Concepts', '### Éthique\n\nMorale.\n\n# Concepts'),
                                               encoding='utf-8')
    a_jour, changements = f.validation_a_jour(cfg)
    assert not a_jour and changements == ['ajouté au plan : Philosophie/Éthique']
    capsys.readouterr()
    assert main(['fonds', 'valider', *dossier]) == 0
    assert 'ajouté au plan : Philosophie/Éthique' in capsys.readouterr().out
    enregistree = json.loads((cfg.suivi / f.VALIDATION).read_text(encoding='utf-8'))
    assert 'Philosophie/Éthique' not in enregistree['structure']['plan']


def test_candidats_ignores_hors_repartir(cfg, biblio):
    """Une collection à répartir passée à « dissoudre » garde ses candidats dans le fichier écrit à la main : la
    validation les ignore, et `fonds.toml` réécrit les efface (répétition du pilote)."""
    inventorier(cfg)
    (cfg.dossier_travail / f.PLAN).write_text(PLAN, encoding='utf-8')
    s = f.charger_suivi(cfg)
    for c in s.collections:
        c.sort = f.DISSOUDRE
        if c.chemin == 'Vieux/Divers':
            c.sort, c.candidats = f.REPARTIR, ['Philosophie/Esthétique', 'Psychologie/Développement']
    f.ecrire_suivi(cfg, s)
    f.enregistrer(cfg, f.controler(cfg))
    chemin = cfg.suivi / f.FICHIER
    texte = chemin.read_text(encoding='utf-8')
    chemin.write_text(texte.replace('sort = "répartir"', 'sort = "dissoudre"'), encoding='utf-8')
    k = f.controler(cfg)
    assert any(c.endswith('« répartir » Philosophie/Esthétique, Psychologie/Développement → « dissoudre »')
               for c in k.changements), k.changements
    f.ecrire_suivi(cfg, f.charger_suivi(cfg))
    assert 'Esthétique' not in chemin.read_text(encoding='utf-8')
    # Une validation enregistrée avant ce changement, avec des candidats sur une collection dissoute, reste valable.
    f.enregistrer(cfg, k)
    validation = json.loads((cfg.suivi / f.VALIDATION).read_text(encoding='utf-8'))
    cle = next(c.cle for c in s.collections if c.chemin == 'Vieux/Divers')
    validation['structure']['collections'][cle][2] = ['Philosophie/Esthétique']
    validation['empreinte'] = f.empreinte(validation['structure'])
    (cfg.suivi / f.VALIDATION).write_text(json.dumps(validation), encoding='utf-8')
    assert f.validation_a_jour(cfg) == (True, [])


def test_fonds_desactive(tmp_path, zotero, capsys):
    zotero.enregistrer()
    (tmp_path / 'config.toml').write_text(
        f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n[methode]\nfonds = ""\n', encoding='utf-8')
    assert main(['fonds', 'inventaire', '--dossier', str(tmp_path)]) == 1
    assert 'désactivée' in capsys.readouterr().err


def test_commande_inventaire(cfg, biblio, capsys):
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n'
        '[confidentialite]\ncollections_exclues = ["Vieux/Personnel"]\n', encoding='utf-8')
    assert main(['fonds', 'inventaire', '--dossier', str(cfg.dossier_travail)]) == 0
    sortie = capsys.readouterr().out
    assert '8 ancienne(s) collection(s), dont 5 sans sort' in sortie
    assert list((cfg.dossier_travail / 'rapports').glob('fonds-inventaire-*.md'))


def test_plusieurs_racines_de_projets(cfg, biblio, zotero):
    """D108 : cours et articles dans deux racines de projets, la cible commence par la racine."""
    articles = zotero.collection('Articles')
    zotero.collection('Revue de littérature', articles)
    zotero.enregistrer()
    cfg.methode.projets = ['Projets', 'Articles']
    _, suivi, _ = inventorier(cfg)
    s = par_chemin(suivi)
    assert (s['Articles/Revue de littérature'].sort, s['Articles/Revue de littérature'].cible) == (f.PROJET, 'Articles/Revue de littérature')
    assert 'Articles' not in s  # racine de la méthode, sans sort à donner
    (cfg.dossier_travail / f.PLAN).write_text(PLAN, encoding='utf-8')
    for c in suivi.collections:
        c.sort, c.cible = (c.sort, c.cible) if c.sort else (f.DISSOUDRE, '')
    s['Vieux/Vision'].sort, s['Vieux/Vision'].cible = f.PROJET, 'Ailleurs/Vision'
    s['Vieux/Divers'].sort, s['Vieux/Divers'].cible = f.PROJET, ''
    f.ecrire_suivi(cfg, suivi)
    erreurs = ' '.join(f.controler(cfg).erreurs)
    assert 'ne commence pas par une racine de projets' in erreurs
    assert 'plusieurs racines de projets' in erreurs


def test_projets_ecrits_comme_avant(tmp_path):
    from zot_clean import config
    (tmp_path / 'config.toml').write_text('[methode]\nprojets = "Cours"\n', encoding='utf-8')
    assert config.charger(tmp_path).methode.projets == ['Cours']
    (tmp_path / 'config.toml').write_text('[methode]\nprojets = ""\n', encoding='utf-8')
    assert config.charger(tmp_path).methode.projets == []


def test_liste_complete_au_dela_du_seuil(cfg, biblio, zotero):
    """D109 : tous les titres d'une collection du fonds qui dépasse le seuil."""
    for i in range(6):
        zotero.fiche(f'Stade {i} du développement', collections=(biblio['Psy'],))
    zotero.enregistrer()
    cfg.methode.seuil_sous_theme = 5
    rapport, _, _ = inventorier(cfg)
    psy = rapport.split('### Fonds/Psychologie')[1].split('###')[0]
    assert 'liste complète' in psy and psy.count('\n- ') == 7
    vision = rapport.split('### Vieux/Vision')[1].split('\n## ')[0]
    assert 'liste complète' not in vision and vision.count('\n- ') == 10  # hors du fonds, échantillon


def test_racines_proposees_sans_numero(cfg, biblio, zotero):
    """D112 : la table [racines] propose les noms sans numéro, et garde les choix faits."""
    cfg.methode.fonds, cfg.methode.archives = '40 Fonds', '80 Archives'
    s = f.racines_proposees(cfg, {'80 Archives': 'Vieilleries'})
    assert s['40 Fonds'] == 'Fonds' and s['80 Archives'] == 'Vieilleries' and 'Inbox' not in s
    cfg.methode.fonds, cfg.methode.archives = 'Fonds', 'Archives'
    _, suivi, _ = inventorier(cfg)
    assert suivi.racines == {} and f.charger_suivi(cfg).racines == {}


def test_archives_de_meme_nom_sans_avertissement(cfg, zotero):
    """D118 : deux sœurs archivées sur place gardent chacune leur place, sans fusion annoncée."""
    arch = zotero.collection('Archives')
    ancien = zotero.collection('Ancien projet', arch)
    for _ in range(2):
        zotero.fiche('Fiche', collections=(zotero.collection('Méthodes', ancien),))
    zotero.enregistrer()
    inventorier(cfg)
    (cfg.dossier_travail / f.PLAN).write_text(PLAN, encoding='utf-8')
    k = f.controler(cfg)
    assert not k.erreurs and not any('réunies' in a for a in k.avertissements)
    s = f.charger_suivi(cfg)
    for c in s.collections:
        if c.chemin == 'Archives/Ancien projet/Méthodes':
            c.cible = 'Ailleurs'
    f.ecrire_suivi(cfg, s)
    assert any('réunies' in a for a in f.controler(cfg).avertissements)


def test_suivre_racines_renommees(cfg):
    """Après `planifier --racines` et la mise à jour de config.toml, les chemins et les cibles de projet de fonds.toml
    suivent les nouveaux noms (trouvé sur la vraie bibliothèque, où toutes les cibles de projet étaient devenues invalides)."""
    cfg.methode.projets, cfg.methode.fonds = ['Cours'], 'Fonds'
    f.ecrire_suivi(cfg, f.Suivi([
        f.Ancienne('AAAA2345', '20 Cours/Psy L1', 3, f.PROJET, '20 Cours/Psy L1'),
        f.Ancienne('BBBB2345', '40 Fonds/Psychologie', 5, f.THEME, 'Psychologie'),
        f.Ancienne('CCCC2345', '20 Coursiers', 1, f.HORS_PLAN)], {}, {'20 Cours': 'Cours', '40 Fonds': 'Fonds'}))
    assert f.suivre_racines(cfg) == 2
    s = {c.cle: (c.chemin, c.cible) for c in f.charger_suivi(cfg).collections}
    assert s == {'AAAA2345': ('Cours/Psy L1', 'Cours/Psy L1'), 'BBBB2345': ('Fonds/Psychologie', 'Psychologie'),
                 'CCCC2345': ('20 Coursiers', '')}
    assert f.suivre_racines(cfg) == 0
