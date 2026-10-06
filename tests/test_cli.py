import pytest

from zot_clean import __version__
from zot_clean.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as fin:
        main(['--version'])
    assert fin.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_aide_sans_commande_remplacee(capsys):
    # `zc trier`, annoncée pour la v0.3, est devenue `zc inbox` : l'aide ne la montre plus.
    assert main([]) == 0
    sortie = capsys.readouterr().out
    assert 'inbox' in sortie and 'trier' not in sortie


def test_plan_remplace_signale(tmp_path, zotero, capsys):
    import json
    from zot_clean import plans
    from zot_clean.plans import Groupe, Operation, Plan
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    plan = Plan('doublons', 'u', [Groupe('1', 'titre', [Operation('AAAAAAAA', {'title': 'a'}, {'title': 'b'})])])
    ancien = plans.ecrire(plan, travail / 'plans', '# rapport')
    ancien = ancien.rename(ancien.with_name('2026-01-01_000000' + ancien.name[17:]))
    autre = Plan('pieces', 'u', plan.groupes)
    plans.ecrire(autre, travail / 'plans', '# rapport')
    assert plans.plus_recents(ancien, plan) == []
    assert main(['appliquer', str(ancien), '--dossier', str(travail)]) == 0
    assert 'plus récent' not in capsys.readouterr().out
    recent = plans.ecrire(plan, travail / 'plans', '# rapport')
    assert plans.plus_recents(ancien, plan) == [recent] and plans.plus_recents(recent, plan) == []
    assert main(['appliquer', str(ancien), '--dossier', str(travail)]) == 0
    assert 'Un plan plus récent de la même étape existe' in capsys.readouterr().out
    assert json.loads(ancien.read_text(encoding='utf-8'))['etape'] == 'doublons'


def test_refus_et_echecs_sortent_avec_un_code_non_nul(capsys):
    """Un agent qui teste le code de retour doit voir chaque refus (répétition du pilote)."""
    import argparse
    from zot_clean.cli import executer
    from zot_clean.ecriture import ErreurAPI, Refus

    def lever(e):
        def action(args):
            raise e
        return argparse.Namespace(action=action)

    for erreur in (SystemExit('Refusé, pour telle raison.'), Refus('Refusé, pour telle raison.'),
                   ErreurAPI('Refusé, pour telle raison.')):
        assert executer(lever(erreur)) == 1
        assert capsys.readouterr().err.strip() == 'Refusé, pour telle raison.'
    assert executer(lever(KeyboardInterrupt())) == 130
    with pytest.raises(SystemExit):
        executer(lever(SystemExit(0)))


def test_appliquer_et_journal(tmp_path, zotero, monkeypatch, capsys):
    from faux_serveur import FauxServeur
    from zot_clean import ecriture, plans
    from zot_clean.plans import Groupe, Operation, Plan
    zotero.fiche('Une fiche')
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    serveur = FauxServeur()
    cle = serveur.ajouter(title='Avant')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    plan = Plan('test', serveur.utilisateur, [Groupe('1', 'titre', [Operation(cle, {'title': 'Avant'},
                                                                              {'title': 'Après'})])])
    chemin = plans.ecrire(plan, travail / 'plans', '# rapport')
    assert main(['appliquer', str(chemin), '--dossier', str(travail)]) == 0
    assert '--essai' in capsys.readouterr().out and serveur.elements[cle]['title'] == 'Avant'
    assert main(['appliquer', str(chemin), '--essai', '--dossier', str(travail)]) == 0
    assert serveur.elements[cle]['title'] == 'Après'
    sortie = capsys.readouterr().out
    assert "l'essai l'a appliqué en entier" in sortie and f'Vérifier : zc voir {cle}' in sortie
    assert main(['appliquer', str(chemin), '--tout', '--dossier', str(travail)]) == 0
    assert 'Rien à appliquer' in capsys.readouterr().out
    assert main(['journal', '--dossier', str(travail)]) == 0
    assert 'terminé' in capsys.readouterr().out


def test_petit_plan_de_tri_sans_essai(tmp_path, zotero, capsys):
    """Le statut d'un petit plan de tri renvoie à `--tout` directement (D138), comme le skill inbox."""
    from zot_clean import plans
    from zot_clean.plans import Groupe, Operation, Plan
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    plan = Plan('inbox', 1, [Groupe('1', 'titre', [Operation('AAAAAAAA', {'title': 'A'}, {'title': 'B'})])])
    chemin = plans.ecrire(plan, travail / 'plans', '# rapport')
    assert main(['appliquer', str(chemin), '--dossier', str(travail)]) == 0
    sortie = capsys.readouterr().out
    assert '--tout' in sortie and 'sans essai' in sortie and '--essai' not in sortie


def test_cles_planifier(tmp_path, zotero, monkeypatch, capsys):
    from faux_serveur import FauxServeur
    from zot_clean import bbt, ecriture
    serveur = FauxServeur()
    for titre, ajout in (('Article A', '2020-01-01'), ('Article B', '2021-01-01')):
        cle = serveur.ajouter(title=titre, citationKey='durand2020')
        zotero.fiche(titre, cle=cle, citationKey='durand2020', ajout=ajout)
    zotero.synchroniser(serveur.version)
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    regenere = bbt.Etat(installe=True, actif=True, version='9.1.0', source=bbt.PROFIL, regenere=True)
    monkeypatch.setattr(bbt, 'detecter', lambda dossier: regenere)
    assert main(['cles', 'planifier', '--dossier', str(travail)]) == 0
    sortie = capsys.readouterr().out
    assert '1 groupe(s), 1 opération(s)' in sortie and 'Regenerate citation key' in sortie
    chemin = next((travail / 'plans').glob('*_cles_*.json'))
    assert main(['appliquer', str(chemin), '--essai', '--dossier', str(travail)]) == 0
    assert 'Regenerate citation key' in capsys.readouterr().out


def test_init_hors_terminal_ne_demande_pas_la_cle(tmp_path, zotero, monkeypatch, capsys):
    import io
    zotero.enregistrer()
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    assert main(['init', str(tmp_path / 'travail'), '--dossier-zotero', str(zotero.dossier)]) == 0
    sortie = capsys.readouterr().out
    assert 'Pas de terminal interactif' in sortie and 'Étape passée' in sortie
    assert not (tmp_path / 'travail' / '.env').exists()


def test_duree_de_chaque_commande(tmp_path):
    """D173 : chaque commande lancée dans un dossier de travail laisse une ligne dans journal/commandes.jsonl,
    même quand elle refuse."""
    import json
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text('', encoding='utf-8')
    main(['journal', '--dossier', str(travail)])
    (travail / 'plan.json').write_text('{}', encoding='utf-8')
    main(['appliquer', str(travail / 'plan.json'), '--essai', '--dossier', str(travail)])
    lignes = [json.loads(x) for x in (travail / 'journal' / 'commandes.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [(x['commande'], x['code']) for x in lignes] == [('journal', 0), ('appliquer', 1)]
    assert lignes[1]['arguments'][1:3] == ['--essai', '--dossier'] and lignes[0]['duree'] >= 0
    main(['journal', '--dossier', str(tmp_path)])  # hors d'un dossier de travail : rien
    assert not (tmp_path / 'journal').exists()


def test_essai_relance_renvoie_vers_tout(tmp_path, zotero, monkeypatch, capsys):
    """D179 : un essai relancé une fois fait n'avance pas dans le plan et renvoie vers `--tout`."""
    from faux_serveur import FauxServeur
    from zot_clean import ecriture, plans
    from zot_clean.plans import Groupe, Operation, Plan
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n\n[ecriture]\n'
                                         'essai = 1\n', encoding='utf-8')
    serveur = FauxServeur()
    cles = [serveur.ajouter(title='Avant') for _ in range(2)]
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    plan = Plan('test', serveur.utilisateur, [Groupe(str(i), 'titre', [Operation(c, {'title': 'Avant'},
                                                                                 {'title': 'Après'})])
                                              for i, c in enumerate(cles)])
    chemin = plans.ecrire(plan, travail / 'plans', '# rapport')
    assert main(['appliquer', str(chemin), '--essai', '--dossier', str(travail)]) == 0
    capsys.readouterr()
    assert main(['appliquer', str(chemin), '--essai', '--dossier', str(travail)]) == 0
    assert "L'essai de ce plan est déjà fait, il reste 1 groupe(s)" in capsys.readouterr().out
    assert serveur.elements[cles[1]]['title'] == 'Avant'


def test_groupe_arrete_affiche_a_part(tmp_path, zotero, monkeypatch, capsys):
    from faux_serveur import FauxServeur
    from zot_clean import ecriture, plans
    from zot_clean.plans import Groupe, Operation, Plan
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    serveur = FauxServeur()
    a, b, c = (serveur.ajouter(title=t) for t in 'ABC')
    serveur.modifier(b, title='Corrigé à la main')
    serveur.modifier(c, title='Corrigé à la main')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    plan = Plan('test', serveur.utilisateur, [
        Groupe('1', 'fusion', [Operation(a, {'title': 'A'}, {'title': 'A2'}, rang=0),
                               Operation(b, {'title': 'B'}, {'title': 'B2'}, rang=1)]),
        Groupe('2', 'autre', [Operation(c, {'title': 'C'}, {'title': 'C2'})])])
    chemin = plans.ecrire(plan, travail / 'plans', '# rapport')
    assert main(['appliquer', str(chemin), '--essai', '--dossier', str(travail)]) == 1
    sortie = capsys.readouterr().out
    arretes, intacts = sortie.split('Arrêtés après une partie des écritures, à vérifier :')[1].split(
        'Conflits, laissés intacts :')
    assert 'groupe 1' in arretes and 'groupe 2' in intacts and 'groupe 1' not in intacts
    assert f'Vérifier : zc voir {a}' in sortie and b not in sortie.split('Vérifier :')[1]


def test_sortie_en_utf8_meme_redirigee_en_cp1252(tmp_path, zotero):
    # D193 : sous Windows, la sortie que lit un agent est un tube dans le jeu de caractères de la machine. Un titre
    # grec y arrêtait `zc voir`. Simulé ici par PYTHONIOENCODING, dans un sous-processus sans profil Zotero réel.
    import os
    import subprocess
    import sys
    zotero.fiche('Ἀριστοτέλης → la ψυχή', cle='ABCD2345')
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    env = os.environ | {'PYTHONIOENCODING': 'cp1252', 'HOME': str(tmp_path), 'APPDATA': str(tmp_path)}
    r = subprocess.run([sys.executable, '-m', 'zot_clean.cli', 'voir', 'ABCD2345', '--dossier', str(travail)],
                       capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr.decode('utf-8', 'replace')
    assert 'Ἀριστοτέλης → la ψυχή' in r.stdout.decode('utf-8')


def test_tilde_developpe(tmp_path, monkeypatch):
    # D193 : Windows PowerShell 5.1 ne développe pas `~` pour un programme, `zc` le fait.
    from zot_clean.cli import analyseur
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    args = analyseur().parse_args(['init', '~/Zotero-travail', '--dossier-zotero', '~/Zotero'])
    assert args.dossier == tmp_path / 'Zotero-travail' and args.dossier_zotero == tmp_path / 'Zotero'
