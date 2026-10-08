import os

import pytest

from zot_clean import __version__
from zot_clean.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as end:
        main(['--version'])
    assert end.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_without_command_replaced(capsys):
    # `zc trier`, announced for v0.3, became `zc inbox`: the help no longer shows it.
    assert main([]) == 0
    output = capsys.readouterr().out
    assert 'inbox' in output and 'trier' not in output


def test_replaced_plan_reported(tmp_path, zotero, capsys):
    import json
    from zot_clean import plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    plan = Plan('doublons', 'u', [Group('1', 'titre', [Operation('AAAAAAAA', {'title': 'a'}, {'title': 'b'})])])
    old = plans.write(plan, workspace / 'plans', '# rapport')
    old = old.rename(old.with_name('2026-01-01_000000' + old.name[17:]))
    other = Plan('pieces', 'u', plan.groups)
    plans.write(other, workspace / 'plans', '# rapport')
    assert plans.newer_plans(old, plan) == []
    assert main(['apply', str(old), '--workspace', str(workspace)]) == 0
    assert 'plus récent' not in capsys.readouterr().out
    recent = plans.write(plan, workspace / 'plans', '# rapport')
    assert plans.newer_plans(old, plan) == [recent] and plans.newer_plans(recent, plan) == []
    assert main(['apply', str(old), '--workspace', str(workspace)]) == 0
    assert 'Un plan plus récent de la même étape existe' in capsys.readouterr().out
    assert json.loads(old.read_text(encoding='utf-8'))['etape'] == 'doublons'


def test_refusals_and_failures_exit_with_nonzero_code(capsys):
    """An agent that tests the exit code must see every refusal (pilot rehearsal)."""
    import argparse
    from zot_clean.cli import run_command
    from zot_clean.api import APIError, Refusal

    def raise_error(e):
        def action(args):
            raise e
        return argparse.Namespace(handler=action)

    for error in (SystemExit('Refusé, pour telle raison.'), Refusal('Refusé, pour telle raison.'),
                   APIError('Refusé, pour telle raison.')):
        assert run_command(raise_error(error)) == 1
        assert capsys.readouterr().err.strip() == 'Refusé, pour telle raison.'
    assert run_command(raise_error(KeyboardInterrupt())) == 130
    with pytest.raises(SystemExit):
        run_command(raise_error(SystemExit(0)))


def test_apply_and_journal(tmp_path, zotero, monkeypatch, capsys):
    from fake_server import FakeServer
    from zot_clean import api, plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.item('Une fiche')
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    server = FakeServer()
    key = server.add(title='Avant')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    plan = Plan('test', server.user, [Group('1', 'titre', [Operation(key, {'title': 'Avant'},
                                                                              {'title': 'Après'})])])
    path = plans.write(plan, workspace / 'plans', '# rapport')
    assert main(['apply', str(path), '--workspace', str(workspace)]) == 0
    assert '--trial' in capsys.readouterr().out and server.all_items[key]['title'] == 'Avant'
    assert main(['apply', str(path), '--trial', '--workspace', str(workspace)]) == 0
    assert server.all_items[key]['title'] == 'Après'
    output = capsys.readouterr().out
    assert "l'essai l'a appliqué en entier" in output and f'Vérifier : zc show {key}' in output
    assert main(['apply', str(path), '--all', '--workspace', str(workspace)]) == 0
    assert 'Rien à appliquer' in capsys.readouterr().out
    assert main(['journal', '--workspace', str(workspace)]) == 0
    assert 'terminé' in capsys.readouterr().out


def test_small_sorting_plan_without_trial(tmp_path, zotero, capsys):
    """The status of a small sort plan points to `--all` directly (D138), like the inbox skill."""
    from zot_clean import plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    plan = Plan('inbox', 1, [Group('1', 'titre', [Operation('AAAAAAAA', {'title': 'A'}, {'title': 'B'})])])
    path = plans.write(plan, workspace / 'plans', '# rapport')
    assert main(['apply', str(path), '--workspace', str(workspace)]) == 0
    output = capsys.readouterr().out
    assert '--all' in output and 'sans essai' in output and '--trial' not in output


def test_citation_keys_make_plan(tmp_path, zotero, monkeypatch, capsys):
    from fake_server import FakeServer
    from zot_clean import bbt, api
    server = FakeServer()
    for title, date_added in (('Article A', '2020-01-01'), ('Article B', '2021-01-01')):
        key = server.add(title=title, citationKey='durand2020')
        zotero.item(title, key=key, citationKey='durand2020', date_added=date_added)
    zotero.sync(server.version)
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    regenerates = bbt.State(installed=True, active=True, version='9.1.0', source=bbt.PROFILE, regenerates=True)
    monkeypatch.setattr(bbt, 'detect', lambda folder: regenerates)
    assert main(['citation-keys', 'plan', '--workspace', str(workspace)]) == 0
    output = capsys.readouterr().out
    assert '1 groupe(s), 1 opération(s)' in output and 'Regenerate citation key' in output
    path = next((workspace / 'plans').glob('*_cles_*.json'))
    assert main(['apply', str(path), '--trial', '--workspace', str(workspace)]) == 0
    assert 'Regenerate citation key' in capsys.readouterr().out


def test_init_outside_terminal_does_not_ask_key(tmp_path, zotero, monkeypatch, capsys):
    import io
    zotero.save()
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    assert main(['init', str(tmp_path / 'travail'), '--zotero-dir', str(zotero.folder), '--library-language', 'fr']) == 0
    output = capsys.readouterr().out
    assert 'Pas de terminal interactif' in output and 'Étape passée' in output
    assert not (tmp_path / 'travail' / '.env').exists()


def test_duration_of_each_command(tmp_path):
    """D173: each command run in a workspace leaves a line in journal/commandes.jsonl,
    even when it refuses."""
    import json
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text('', encoding='utf-8')
    main(['journal', '--workspace', str(workspace)])
    (workspace / 'plan.json').write_text('{}', encoding='utf-8')
    main(['apply', str(workspace / 'plan.json'), '--trial', '--workspace', str(workspace)])
    lines = [json.loads(x) for x in (workspace / 'journal' / 'commandes.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [(x['commande'], x['code']) for x in lines] == [('journal', 0), ('apply', 1)]
    assert lines[1]['arguments'][1:3] == ['--trial', '--workspace'] and lines[0]['duree'] >= 0
    main(['journal', '--workspace', str(tmp_path)])  # outside a workspace: nothing
    assert not (tmp_path / 'journal').exists()


def test_rerun_trial_points_to_all(tmp_path, zotero, monkeypatch, capsys):
    """D179: a trial rerun once done does not advance in the plan and points to `--all`."""
    from fake_server import FakeServer
    from zot_clean import api, plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n\n[ecriture]\n'
                                         'essai = 1\n', encoding='utf-8')
    server = FakeServer()
    keys = [server.add(title='Avant') for _ in range(2)]
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    plan = Plan('test', server.user, [Group(str(i), 'titre', [Operation(c, {'title': 'Avant'},
                                                                                 {'title': 'Après'})])
                                              for i, c in enumerate(keys)])
    path = plans.write(plan, workspace / 'plans', '# rapport')
    assert main(['apply', str(path), '--trial', '--workspace', str(workspace)]) == 0
    capsys.readouterr()
    assert main(['apply', str(path), '--trial', '--workspace', str(workspace)]) == 0
    assert "L'essai de ce plan est déjà fait, il reste 1 groupe(s)" in capsys.readouterr().out
    assert server.all_items[keys[1]]['title'] == 'Avant'


def test_stopped_group_shown_apart(tmp_path, zotero, monkeypatch, capsys):
    from fake_server import FakeServer
    from zot_clean import api, plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    server = FakeServer()
    a, b, c = (server.add(title=t) for t in 'ABC')
    server.modify(b, title='Corrigé à la main')
    server.modify(c, title='Corrigé à la main')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    plan = Plan('test', server.user, [
        Group('1', 'fusion', [Operation(a, {'title': 'A'}, {'title': 'A2'}, rank=0),
                               Operation(b, {'title': 'B'}, {'title': 'B2'}, rank=1)]),
        Group('2', 'autre', [Operation(c, {'title': 'C'}, {'title': 'C2'})])])
    path = plans.write(plan, workspace / 'plans', '# rapport')
    assert main(['apply', str(path), '--trial', '--workspace', str(workspace)]) == 1
    output = capsys.readouterr().out
    stopped, intact = output.split('Arrêtés après une partie des écritures, à vérifier :')[1].split(
        'Conflits, laissés intacts :')
    assert 'groupe 1' in stopped and 'groupe 2' in intact and 'groupe 1' not in intact
    assert f'Vérifier : zc show {a}' in output and b not in output.split('Vérifier :')[1]


def test_output_in_utf8_even_redirected_in_cp1252(tmp_path, zotero):
    # D193: under Windows, the output an agent reads is a pipe in the machine's character set. A Greek title
    # stopped `zc show` there. Simulated here by PYTHONIOENCODING, in a subprocess without a real Zotero profile.
    import os
    import subprocess
    import sys
    zotero.item('Ἀριστοτέλης → la ψυχή', key='ABCD2345')
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    env = os.environ | {'PYTHONIOENCODING': 'cp1252', 'HOME': str(tmp_path), 'APPDATA': str(tmp_path)}
    r = subprocess.run([sys.executable, '-m', 'zot_clean.cli', 'show', 'ABCD2345', '--workspace', str(workspace)],
                       capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr.decode('utf-8', 'replace')
    assert 'Ἀριστοτέλης → la ψυχή' in r.stdout.decode('utf-8')


def test_tilde_expanded(tmp_path, monkeypatch):
    # D193: Windows PowerShell 5.1 does not expand `~` for a program, `zc` does.
    from zot_clean.cli import build_parser
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    args = build_parser().parse_args(['init', '~/Zotero-travail', '--zotero-dir', '~/Zotero'])
    assert args.folder == tmp_path / 'Zotero-travail' and args.zotero_dir == tmp_path / 'Zotero'


def test_outside_workspace(tmp_path, zotero, monkeypatch, capsys):
    """A foreign config.toml in a parent folder is not taken for zc's, and a command run outside a
    workspace is refused without creating anything."""
    from zot_clean import config
    zotero.save()
    (tmp_path / 'config.toml').write_text('[tool.autre]\nnom = "x"\n', encoding='utf-8')  # another tool's
    elsewhere = tmp_path / 'ailleurs'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert config.find_workspace() is None
    assert main(['audit', '--offline']) == 1
    assert 'No zot-clean working folder here' in capsys.readouterr().err  # outside a working folder: English (D222)
    assert sorted(p.name for p in elsewhere.iterdir()) == [] and not (tmp_path / 'rapports').exists()
    monkeypatch.chdir(tmp_path)
    assert main(['audit', '--offline']) == 1
    assert 'is not recognized' in capsys.readouterr().err and not (tmp_path / 'rapports').exists()
    assert main(['audit', '--offline', '--workspace', str(elsewhere)]) == 1
    assert 'is not a zot-clean working folder' in capsys.readouterr().err
    # A real workspace further up is found, over the foreign config.toml of a subfolder.
    workspace = tmp_path / 'travail'
    (workspace / 'projet').mkdir(parents=True)
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    (workspace / 'projet' / 'config.toml').write_text('titre = "pas zc"\n', encoding='utf-8')
    monkeypatch.chdir(workspace / 'projet')
    assert config.find_workspace() == workspace.resolve()
    assert main(['audit', '--offline', '--no-hashes']) == 0
    assert (workspace / 'rapports').is_dir() and not (workspace / 'projet' / 'rapports').exists()


@pytest.mark.parametrize('arguments, expected', [
    ('subjects pending --reviewed', 'argument --reviewed: expected at least one argument'),
    ('audit --workspace', 'argument --workspace: expected one argument'),
    ('apply', 'the following arguments are required: plan'),
    ('apply x --trial --all', 'argument --all: not allowed with argument --trial'),
    ('inbox unknown', "invalid choice: 'unknown'"),
    ('audit too much', 'unrecognized arguments: too much'),
    ('tags add x --action supprimé', "argument --action: invalid choice: 'supprimé'"),
])
def test_argument_errors_in_english(arguments, expected, capsys, tmp_path):
    """D215: the help and the argparse errors are in English, whatever the language of the library."""
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "x"\n', encoding='utf-8')  # French library
    with pytest.raises(SystemExit) as end:
        main([*arguments.split(), '--workspace', str(tmp_path)] if arguments != 'audit --workspace'
             else arguments.split())
    assert end.value.code == 2
    error = capsys.readouterr().err
    assert expected in error and 'zc' in error and ': error:' in error


def test_help_in_english(capsys):
    with pytest.raises(SystemExit):
        main(['duplicates', 'accept', '--help'])
    output = capsys.readouterr().out
    assert 'usage: zc duplicates accept' in output and '--certain' in output and 'show this help message' in output
    assert 'groupes' not in output


@pytest.mark.parametrize('former, equivalent, renamed', [
    ('doublons planifier', 'zc duplicates plan', '`doublons` is now `duplicates`'),
    ('duplicates chercher', 'zc duplicates find', '`chercher` is now `find`'),
    ('apply x.json --essai', 'zc apply x.json --trial', '`--essai` is now `--trial`'),
    ('fonds a-ranger --laisser ABCD2345', 'zc subjects pending --leave-out ABCD2345', '`--laisser` is now `--leave-out`'),
    ('tags accept rouge --action supprimer', 'zc tags accept rouge --action delete', '`supprimer` is now `delete`'),
    ('citation-keys decide ABCD2345=écarter', 'zc citation-keys decide ABCD2345=skip', '`ABCD2345=écarter`'),
    ('init --maj', 'zc init --update', '`--maj` is now `--update`'),
    ('voir --tag "mémoire de travail"', "zc show --tag 'mémoire de travail'", '`voir` is now `show`'),
])
def test_former_names_refused_with_equivalent(former, equivalent, renamed, capsys, tmp_path, monkeypatch):
    """D213: an old command, subcommand, option or value is refused, with the full equivalent line, outside a
    working folder in English (D222)."""
    import shlex
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as end:
        main(shlex.split(former))
    assert end.value.code == 2
    error = capsys.readouterr().err
    if os.name == 'nt':  # cmd and PowerShell: double quotes (test_equivalent_line_quoted_for_the_shell)
        equivalent = equivalent.replace("'", '"')
    assert error.endswith(f'Run instead\n  {equivalent}\n') and renamed in error
    assert 'version 0.4.0' in error


def test_former_names_refused_in_the_language_of_the_library(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text('[zotero]\ndossier = "x"\n', encoding='utf-8')  # French by default
    with pytest.raises(SystemExit) as end:
        main(['doublons', 'accepter', '--surs', '--dossier', str(workspace)])
    assert end.value.code == 2
    error = capsys.readouterr().err
    assert '`doublons` devient `duplicates`, `accepter` devient `accept`, `--surs` devient `--certain`' in error
    assert f'Lancer plutôt\n  zc duplicates accept --certain --workspace {workspace}\n' in error
    (workspace / 'config.toml').write_text('[zotero]\ndossier = "x"\n[methode]\nlangue = "en"\n', encoding='utf-8')
    monkeypatch.chdir(workspace)  # the working folder found from the current one
    with pytest.raises(SystemExit):
        main(['journal', '--dossier'])
    assert 'Run instead\n  zc journal --workspace\n' in capsys.readouterr().err
    assert not (workspace / 'journal').exists()  # refused before anything runs


def test_english_values_translated_to_stored_words(tmp_path):
    from zot_clean.cli import build_parser
    args = build_parser().parse_args(['tags', 'add', 'x', '--action', 'Status'])
    assert args.action == 'état'  # the word stored in suivi/tags.toml (D209)
    args = build_parser().parse_args(['tags', 'accept', 'x', '--action=delete'])
    assert args.action == 'supprimer' and args.tracking_action == 'accept'


def test_config_show(tmp_path, capsys):
    """`zc config show` prints the effective configuration, defaults included, as TOML (D221)."""
    import tomllib
    from zot_clean import config
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "/z/Zotero"\n[methode]\nlangue = "en"\ninbox = "Boîte"\n'
                                          '[metadonnees]\nexclus_par_type = { "book section" = ["place"] }\n',
                                          encoding='utf-8')
    assert main(['config', 'show', '--workspace', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith('# Language of the library: English (en). Roles of the [methode] names: inbox = the Inbox')
    shown = tomllib.loads(out)
    stored = config.to_stored(config.load(tmp_path))
    assert shown['methode']['langue'] == 'en' and shown['methode']['inbox'] == 'Boîte'
    assert shown['ecriture']['essai'] == 5 and shown['metadonnees']['exclus_par_type'] == {'book section': ['place']}
    assert shown == {s: {k: v for k, v in values.items() if v is not None} for s, values in stored.items()}
    assert 'dossier' not in shown['sauvegarde']  # computed default, next to the Zotero folder
    assert (tmp_path / 'config.toml').read_text(encoding='utf-8').count('Boîte') == 1  # read-only


def test_messages_in_english(tmp_path, zotero, monkeypatch, capsys):
    """A library declared English gets the messages of zc in English (D215)."""
    from zot_clean import plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.save()
    workspace = tmp_path / 'work'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n[methode]\n'
                                           'langue = "en"\n', encoding='utf-8')
    plan = Plan('doublons', 'u', [Group('1', 'title', [Operation('AAAAAAAA', {'title': 'a'}, {'title': 'b'})])])
    path = plans.write(plan, workspace / 'plans', '# report')
    assert main(['apply', str(path), '--workspace', str(workspace)]) == 0
    output = capsys.readouterr().out
    assert '1 group(s), 1 operation(s).' in output and f'Next step, `zc apply {path.resolve()} --trial`' in output
    assert 'Readable report:' in output and 'Rapport' not in output
    assert main(['journal', '--workspace', str(workspace)]) == 0
    assert capsys.readouterr().out == 'No journaled write.\n'
    assert main(['show', '--workspace', str(workspace)]) == 1
    assert capsys.readouterr().err == 'Give item keys, or a tag with --tag.\n'
    monkeypatch.chdir(tmp_path)
    assert main(['audit']) == 1  # outside a working folder: English (D222)
    assert 'No zot-clean working folder here' in capsys.readouterr().err


def test_key_of_another_account_rejected_by_commands(tmp_path, zotero, monkeypatch, capsys):
    """Audit, reading and planning refuse the key of an account other than the one Zotero syncs, before
    any request. `--offline`, which does not use the key, audits the local copy, with a
    warning."""
    from fake_server import FakeServer
    from zot_clean import api
    server = FakeServer(user=9999)
    zotero.item('Une fiche', key='AAAAAAAA')
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    assert main(['audit', '--no-hashes', '--workspace', str(workspace)]) == 1
    error = capsys.readouterr().err
    assert 'La clé API est celle du compte zotero.org n° 9999' in error and 'n° 4242' in error
    assert '`zc audit --offline`' in error and not (workspace / 'rapports').exists()
    assert main(['audit', '--offline', '--no-hashes', '--workspace', str(workspace)]) == 0
    assert capsys.readouterr().out.startswith('Attention. La clé API est celle du compte zotero.org n° 9999')
    for command in (['show', 'AAAAAAAA'], ['duplicates', 'find'], ['duplicates', 'plan'], ['tags', 'plan'],
                     ['inbox', 'prepare']):
        assert main([*command, '--workspace', str(workspace)]) == 1, command
        assert 'il modifierait donc une autre bibliothèque' in capsys.readouterr().err, command
    assert server.requests == []


def test_timer_under_terminal(monkeypatch):
    # D207: in a terminal, a continuously updated line shows that the command is running, erased before each message,
    # and the duration at the end. Nothing when the output is not a terminal.
    import io
    import sys
    import time
    from zot_clean.cli import Timer

    class Terminal(io.StringIO):
        def isatty(self):
            return True
    screen, output = Terminal(), io.StringIO()
    monkeypatch.setattr(sys, 'stdout', output)
    monkeypatch.setattr(sys, 'stderr', screen)
    with Timer('zc audit', interval=0.05, threshold=0):
        print('message de la commande', file=sys.stderr)
        time.sleep(0.2)
        print('résultat')
    text = screen.getvalue()
    assert text.startswith('zc audit en cours… 0 s') and '\r\x1b[Kmessage de la commande\n' in text
    assert text.endswith('zc audit terminé en 0 s.\n') and output.getvalue() == 'résultat\n'
    assert sys.stdout is output and sys.stderr is screen
    silent = io.StringIO()
    with Timer('zc audit', silent, threshold=0):
        pass
    assert silent.getvalue() == ''


@pytest.mark.parametrize('system, word, expected', [
    ('posix', 'plain', 'plain'), ('posix', 'a b', "'a b'"), ('posix', '/tmp/x', '/tmp/x'),
    ('nt', r'C:\Users\x\travail', r'C:\Users\x\travail'), ('nt', r'C:\Mes documents\travail', r'"C:\Mes documents\travail"'),
])
def test_equivalent_line_quoted_for_the_shell(monkeypatch, system, word, expected):
    """CI under Windows: a backslash path must not be put between single quotes, which cmd does not understand."""
    from zot_clean import cli
    monkeypatch.setattr(cli.os, 'name', system)
    assert cli._shell_word(word) == expected


def test_reading_commands_read_what_zotero_has_not_received(monkeypatch):
    """D171, D174, D240: the commands that prepare a judgment read zotero.org for what the local copy lacks (pilot
    bench: `zc subjects pending` gave paths of collections merged by the previous pass). The audit alone reads the
    local copy (D171)."""
    import inspect
    from zot_clean import cli
    for f in (cli.subjects_inventory, cli.subjects_track, cli.subjects_titles, cli.subjects_pending, cli._inbox,
              cli.show):
        source = inspect.getsource(f)
        assert 'reader.read(cfg.database)' not in source and 'read_up_to_date' in source, f.__name__
    assert 'reader.read(cfg.database)' in inspect.getsource(cli.audit)


def test_journal_modes_and_undo_note_in_english(tmp_path, zotero, monkeypatch, capsys):
    """D242, pilot bench: `zc journal` printed the stored « essai » in an English library, and an undo did not say
    that the decisions of the tracking file would plan the same changes again."""
    from fake_server import FakeServer
    from zot_clean import api, plans
    from zot_clean.plans import Group, Operation, Plan
    zotero.item('Une fiche')
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n[methode]\nlangue = "en"\n',
                                           encoding='utf-8')
    server = FakeServer()
    key = server.add(title='Before', tags=[{'tag': 'old'}])
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    plan = Plan('tags', server.user, [Group('1', 'old', [Operation(key, {'tags': [{'tag': 'old'}]}, {'tags': []})])])
    path = plans.write(plan, workspace / 'plans', '# report')
    assert main(['apply', str(path), '--trial', '--workspace', str(workspace)]) == 0
    capsys.readouterr()
    assert main(['journal', '--workspace', str(workspace)]) == 0
    line = capsys.readouterr().out
    assert '  trial ' in line and 'essai' not in line
    assert main(['undo', str(path), '--workspace', str(workspace)]) == 0
    assert 'The decisions of suivi/tags.toml are unchanged: `zc tags plan` would propose' in capsys.readouterr().out
