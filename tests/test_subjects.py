import json
import textwrap

import pytest

from zot_clean import subjects as f, reader
from zot_clean.cli import main
from zot_clean.config import Config

OUTLINE = """\
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
    c = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    c.workspace.mkdir()
    c.privacy.excluded_collections = ['Vieux/Personnel']
    return c


@pytest.fixture
def biblio(zotero):
    """Messy filing on several levels (D107): project, archives, started subject collection, collection to distribute,
    thematic tags, collection excluded by the filter."""
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
        z.item(f'Perception des couleurs {i:02}', collections=(c['Vision'],), tags=('vision', 'couleur'))
    z.item('Illusions et attention', collections=(c['Vision'], c['Cours']), tags=('vision', 'attention'))
    z.item('Esthétique du beau', collections=(c['Divers'],), tags=('esthétique', ('Aesthetics', 1)))
    z.item('Piaget et le jeu', collections=(c['Divers'], c['Psy']), tags=('développement', '1 à lire', '_import'))
    z.item('Note profonde', collections=(c['Profond'],))
    z.item('Carnet de rêves', collections=(c['Secret'],), tags=('rêves',))
    z.item('Fiche confidentielle', collections=(c['Divers'],), tags=('_privé', 'secretissime'))
    z.item('Sans collection', tags=('vision',))
    z.item('Ancien cours', collections=(c['Ancien'],))
    z.save()
    return c


def take_inventory(cfg):
    b = reader.read(cfg.database)
    report, tracking, new_ones, vanished = f.inventory(b, cfg)
    f.write_tracking(cfg, tracking)
    return report, tracking, vanished


def by_path(tracking):
    return {c.path: c for c in tracking.collections}


def test_inventory_filters_and_prefills(cfg, biblio):
    report, tracking, _ = take_inventory(cfg)
    # Privacy filter: no titles, no tags, no excluded collections.
    for secret in ('Journal intime', 'Carnet de rêves', 'rêves', 'confidentielle', 'secretissime'):
        assert secret not in report
    assert 'Personnel' not in report
    # Status, technical and automatic tags left out.
    assert '1 à lire' not in report.split('## Tags thématiques')[1]
    assert '_import' not in report and 'Aesthetics' not in report
    assert '- vision (14)' in report and 'couleur + vision (12)' in report
    vision = report.split('### Vieux/Vision')[1].split('###')[0]
    assert vision.count('\n- Durand, 2020, ') == 10
    assert 'Références partagées avec Projets/Cours L1 (1)' in report
    assert 'dont 1 dans aucune collection' in report
    s = by_path(tracking)
    assert set(s) == {'Projets/Cours L1', 'Archives/Cours 2019', 'Fonds/Psychologie', 'Vieux', 'Vieux/Vision',
                      'Vieux/Divers', 'Vieux/Divers/Profond', 'Vieux/Personnel'}
    assert (s['Projets/Cours L1'].action, s['Projets/Cours L1'].target) == (f.PROJECT, 'Projets/Cours L1')
    assert s['Archives/Cours 2019'].action == f.ARCHIVES
    assert s['Vieux/Personnel'].action == f.OUTSIDE_OUTLINE
    assert s['Fonds/Psychologie'].action == '' and s['Vieux/Vision'].count == 13
    assert s['Vieux/Divers'].count == 2  # the excluded item does not count


def test_rerun_keeps_actions(cfg, biblio, zotero):
    take_inventory(cfg)
    text = (cfg.tracking / f.FILE).read_text(encoding='utf-8')
    text = text.replace('chemin = "Vieux/Vision"\neffectif = 13\nsort = ""\ncible = ""',
                          'chemin = "Vieux/Vision"\neffectif = 13\nsort = "theme"\ncible = "Psychologie/Perception"')
    text = text.replace('[tags]', '[tags]\n"vision" = "Psychologie/Perception"')
    (cfg.tracking / f.FILE).write_text(text, encoding='utf-8')
    zotero.db.execute('delete from collections where collectionID = ?', (biblio['Profond'],))
    zotero.collection('Nouvelle')
    zotero.save()
    _, tracking, vanished = take_inventory(cfg)
    s = by_path(tracking)
    assert (s['Vieux/Vision'].action, s['Vieux/Vision'].target) == (f.THEME, 'Psychologie/Perception')
    assert 'Nouvelle' in s and 'Vieux/Divers/Profond' not in s
    assert [c.path for c in vanished] == ['Vieux/Divers/Profond']
    assert f.load_tracking(cfg).tags == {'vision': 'Psychologie/Perception'}


def test_unknown_action(cfg, biblio):
    take_inventory(cfg)
    path = cfg.tracking / f.FILE
    path.write_text(path.read_text(encoding='utf-8').replace('sort = ""', 'sort = "jeter"', 1), encoding='utf-8')
    with pytest.raises(SystemExit, match='sort inconnu'):
        f.load_tracking(cfg)


def test_read_outline(cfg):
    p = f.read_outline(OUTLINE, cfg)
    assert list(p.nodes) == ['Psychologie', 'Psychologie/Perception', 'Psychologie/Développement', 'Philosophie',
                              'Philosophie/Esthétique']
    perception = p.nodes['Psychologie/Perception']
    assert perception.definition == 'Vision, audition, attention.'
    assert perception.includes == 'illusions visuelles.' and perception.excludes == 'neurophysiologie de la rétine.'
    assert not p.errors and not p.warnings


def test_outline_errors(cfg):
    text = textwrap.dedent("""\
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
    p = f.read_outline(text, cfg)
    errors = ' '.join(p.errors)
    assert 'existe déjà' in errors and 'au-delà de 3 niveaux' in errors and "nom d'une racine" in errors
    assert "n'a pas de parent" in errors and 'contenant « / »' in errors
    assert any('Perception' in a and 'définition' in a for a in p.warnings)
    assert 'aucune section' in f.read_outline('## Psychologie\n', cfg).errors[0]


def test_outline_without_theme_reported(cfg):
    p = f.read_outline('# Fonds\n## Psychologie\nEsprit.\n## Philosophie\nIdées.\n', cfg)
    assert not p.errors and any("aucune discipline n'a de thème" in a for a in p.warnings)
    assert not any('thème (titre' in a for a in f.read_outline(OUTLINE, cfg).warnings)


def test_validate_then_change(cfg, biblio, capsys):
    take_inventory(cfg)
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    folder = ['--workspace', str(cfg.workspace)]
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n', encoding='utf-8')
    assert main(['subjects', 'validate', *folder]) == 1
    assert "n'a pas de sort" in capsys.readouterr().out
    s = f.load_tracking(cfg)
    actions = {'Fonds/Psychologie': (f.THEME, 'Psychologie', []), 'Vieux': (f.DISSOLVE, '', []),
             'Vieux/Vision': (f.THEME, 'Psychologie/Perception', []),
             'Vieux/Divers': (f.DISTRIBUTE, '', ['Philosophie/Esthétique', 'Psychologie/Développement']),
             'Vieux/Divers/Profond': (f.ARCHIVES, '', [])}
    for c in s.collections:
        if c.path in actions:
            c.action, c.target, c.candidates = actions[c.path]
    s.tags['esthétique'] = 'Philosophie/Inexistant'
    f.write_tracking(cfg, s)
    assert main(['subjects', 'validate', *folder]) == 1
    assert "« Philosophie/Inexistant », qui n'est pas dans plan.md" in capsys.readouterr().out
    s.tags['esthétique'] = 'Philosophie/Esthétique'
    f.write_tracking(cfg, s)
    assert main(['subjects', 'validate', *folder]) == 0
    assert '--save' in capsys.readouterr().out and not (cfg.tracking / f.VALIDATION).exists()
    assert main(['subjects', 'validate', '--save', *folder]) == 0
    assert f.validation_up_to_date(cfg) == (True, [])
    # Editing a definition does not change the structure.
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE.replace('Théorie de l\'art', 'Philosophie de l\'art'),
                                               encoding='utf-8')
    assert f.validation_up_to_date(cfg) == (True, [])
    # One more theme does.
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE.replace('# Concepts', '### Éthique\n\nMorale.\n\n# Concepts'),
                                               encoding='utf-8')
    up_to_date, changes = f.validation_up_to_date(cfg)
    assert not up_to_date and changes == ['ajouté au plan : Philosophie/Éthique']
    capsys.readouterr()
    assert main(['subjects', 'validate', *folder]) == 0
    assert 'ajouté au plan : Philosophie/Éthique' in capsys.readouterr().out
    saved = json.loads((cfg.tracking / f.VALIDATION).read_text(encoding='utf-8'))
    assert 'Philosophie/Éthique' not in saved['structure']['plan']


def test_candidates_ignored_outside_distribute(cfg, biblio):
    """A collection to distribute switched to « dissoudre » keeps its candidates in the hand-written file: validation
    ignores them, and a rewritten `fonds.toml` erases them (pilot rehearsal)."""
    take_inventory(cfg)
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    s = f.load_tracking(cfg)
    for c in s.collections:
        c.action = f.DISSOLVE
        if c.path == 'Vieux/Divers':
            c.action, c.candidates = f.DISTRIBUTE, ['Philosophie/Esthétique', 'Psychologie/Développement']
    f.write_tracking(cfg, s)
    f.save(cfg, f.check(cfg))
    path = cfg.tracking / f.FILE
    text = path.read_text(encoding='utf-8')
    path.write_text(text.replace('sort = "répartir"', 'sort = "dissoudre"'), encoding='utf-8')
    k = f.check(cfg)
    assert any(c.endswith('« répartir » Philosophie/Esthétique, Psychologie/Développement → « dissoudre »')
               for c in k.changes), k.changes
    f.write_tracking(cfg, f.load_tracking(cfg))
    assert 'Esthétique' not in path.read_text(encoding='utf-8')
    # A validation recorded before this change, with candidates on a dissolved collection, stays valid.
    f.save(cfg, k)
    validation = json.loads((cfg.tracking / f.VALIDATION).read_text(encoding='utf-8'))
    key = next(c.key for c in s.collections if c.path == 'Vieux/Divers')
    validation['structure']['collections'][key][2] = ['Philosophie/Esthétique']
    validation['empreinte'] = f.fingerprint(validation['structure'])
    (cfg.tracking / f.VALIDATION).write_text(json.dumps(validation), encoding='utf-8')
    assert f.validation_up_to_date(cfg) == (True, [])


def test_subjects_disabled(tmp_path, zotero, capsys):
    zotero.save()
    (tmp_path / 'config.toml').write_text(
        f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n[methode]\nfonds = ""\n', encoding='utf-8')
    assert main(['subjects', 'inventory', '--workspace', str(tmp_path)]) == 1
    assert 'désactivée' in capsys.readouterr().err


def test_inventory_command(cfg, biblio, capsys):
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n'
        '[confidentialite]\ncollections_exclues = ["Vieux/Personnel"]\n', encoding='utf-8')
    assert main(['subjects', 'inventory', '--workspace', str(cfg.workspace)]) == 0
    output = capsys.readouterr().out
    assert '8 ancienne(s) collection(s), dont 5 sans sort' in output
    assert list((cfg.workspace / 'rapports').glob('fonds-inventaire-*.md'))


def test_several_project_roots(cfg, biblio, zotero):
    """D108: courses and articles in two project roots, the target starts with the root."""
    articles = zotero.collection('Articles')
    zotero.collection('Revue de littérature', articles)
    zotero.save()
    cfg.method.projects = ['Projets', 'Articles']
    _, tracking, _ = take_inventory(cfg)
    s = by_path(tracking)
    assert (s['Articles/Revue de littérature'].action, s['Articles/Revue de littérature'].target) == (f.PROJECT, 'Articles/Revue de littérature')
    assert 'Articles' not in s  # method root, with no fate to give
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    for c in tracking.collections:
        c.action, c.target = (c.action, c.target) if c.action else (f.DISSOLVE, '')
    s['Vieux/Vision'].action, s['Vieux/Vision'].target = f.PROJECT, 'Ailleurs/Vision'
    s['Vieux/Divers'].action, s['Vieux/Divers'].target = f.PROJECT, ''
    f.write_tracking(cfg, tracking)
    errors = ' '.join(f.check(cfg).errors)
    assert 'ne commence pas par une racine de projets' in errors
    assert 'plusieurs racines de projets' in errors


def test_projects_written_as_before(tmp_path):
    from zot_clean import config
    (tmp_path / 'config.toml').write_text('[methode]\nprojets = "Cours"\n', encoding='utf-8')
    assert config.load(tmp_path).method.projects == ['Cours']
    (tmp_path / 'config.toml').write_text('[methode]\nprojets = ""\n', encoding='utf-8')
    assert config.load(tmp_path).method.projects == []


def test_full_list_beyond_threshold(cfg, biblio, zotero):
    """D109: all the titles of a subject collection that exceeds the threshold."""
    for i in range(6):
        zotero.item(f'Stade {i} du développement', collections=(biblio['Psy'],))
    zotero.save()
    cfg.method.subtheme_threshold = 5
    report, _, _ = take_inventory(cfg)
    psy = report.split('### Fonds/Psychologie')[1].split('###')[0]
    assert 'liste complète' in psy and psy.count('\n- ') == 7
    vision = report.split('### Vieux/Vision')[1].split('\n## ')[0]
    assert 'liste complète' not in vision and vision.count('\n- ') == 10  # outside the subject collections, a sample


def test_roots_proposed_without_number(cfg, biblio, zotero):
    """D112: the [racines] table proposes the names without a number, and keeps the choices made."""
    cfg.method.subjects, cfg.method.archives = '40 Fonds', '80 Archives'
    s = f.proposed_roots(cfg, {'80 Archives': 'Vieilleries'})
    assert s['40 Fonds'] == 'Fonds' and s['80 Archives'] == 'Vieilleries' and 'Inbox' not in s
    cfg.method.subjects, cfg.method.archives = 'Fonds', 'Archives'
    _, tracking, _ = take_inventory(cfg)
    assert tracking.roots == {} and f.load_tracking(cfg).roots == {}


def test_archives_with_same_name_without_warning(cfg, zotero):
    """D118: two sister collections archived in place each keep their place, with no merge announced."""
    arch = zotero.collection('Archives')
    old = zotero.collection('Ancien projet', arch)
    for _ in range(2):
        zotero.item('Fiche', collections=(zotero.collection('Méthodes', old),))
    zotero.save()
    take_inventory(cfg)
    (cfg.workspace / f.OUTLINE).write_text(OUTLINE, encoding='utf-8')
    k = f.check(cfg)
    assert not k.errors and not any('réunies' in a for a in k.warnings)
    s = f.load_tracking(cfg)
    for c in s.collections:
        if c.path == 'Archives/Ancien projet/Méthodes':
            c.target = 'Ailleurs'
    f.write_tracking(cfg, s)
    assert any('réunies' in a for a in f.check(cfg).warnings)


def test_track_renamed_roots(cfg):
    """After `planifier --racines` and the update of config.toml, the paths and the project targets of fonds.toml
    follow the new names (found on the real library, where all the project targets had become invalid)."""
    cfg.method.projects, cfg.method.subjects = ['Cours'], 'Fonds'
    f.write_tracking(cfg, f.Tracking([
        f.OldCollection('AAAA2345', '20 Cours/Psy L1', 3, f.PROJECT, '20 Cours/Psy L1'),
        f.OldCollection('BBBB2345', '40 Fonds/Psychologie', 5, f.THEME, 'Psychologie'),
        f.OldCollection('CCCC2345', '20 Coursiers', 1, f.OUTSIDE_OUTLINE)], {}, {'20 Cours': 'Cours', '40 Fonds': 'Fonds'}))
    assert f.track_roots(cfg) == 2
    s = {c.key: (c.path, c.target) for c in f.load_tracking(cfg).collections}
    assert s == {'AAAA2345': ('Cours/Psy L1', 'Cours/Psy L1'), 'BBBB2345': ('Fonds/Psychologie', 'Psychologie'),
                 'CCCC2345': ('20 Coursiers', '')}
    assert f.track_roots(cfg) == 0


def test_inventory_report_and_errors_in_english(cfg, biblio):
    from zot_clean.lang import language
    with language('en'):
        report, tracking, _ = take_inventory(cfg)
        errors = ' '.join(f.read_outline('# Fonds\n## Psychologie\n#### Orphelin\n## A/B\n', cfg).errors)
        header = f.header()
    assert '# Inventory of the classification for the subjects outline' in report
    assert '## Thematic tags' in report and '## Collection tree' in report
    assert 'Items shared with Projets/Cours L1 (1)' in report and '1 of them in no collection' in report
    assert 'has no parent' in errors and 'empty name or name containing "/"' in errors
    assert header.startswith('# Correspondence between the old classification') and '`zc subjects validate`' in header
    assert by_path(tracking)['Vieux/Personnel'].prefilled.startswith('excluded by the privacy filter')
    assert f.header().startswith('# Correspondance entre')  # French outside the block
