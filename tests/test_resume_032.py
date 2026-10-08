"""A working folder of version 0.3.2 taken over by 0.4 (D236).

The folder holds a real plan written by 0.3.2 (the filing plan of the golden fixtures, French, format 2) and the
journal of its trial only (groups 1 to 5 done), its 0.3.2 configuration, without a declared language, and the
skills of 0.3.2. The fake server is rebuilt in the state that trial left: groups 1 to 5 applied, 6 to 8 not. After
`zc init --update`, `zc apply <plan> --all` must take the plan up where the trial stopped, and `zc undo` must undo
both runs, through the commands as a user or an agent types them.
"""

import json
import shutil
from pathlib import Path

import pytest

from fake_server import FakeServer
from test_apply import fake_backup
from zot_clean import api, config
from zot_clean.cli import main

V032 = Path(__file__).parent / 'donnees' / 'v032' / 'dossier'
PLAN = '2026-10-06_164437_fonds_80559cfd1e18.json'
TRIAL_JOURNAL = '2026-10-06_164437_fonds.jsonl'


def server_left_by_the_trial(plan: dict) -> tuple[FakeServer, dict]:
    """Every object the plan touches, in the state after the trial: `apres` for the groups the journal records as
    done, `avant` for the others. Also returns the state before the plan, to compare after the undo."""
    lines = [json.loads(l) for l in (V032 / 'journal' / TRIAL_JOURNAL).read_text(encoding='utf-8').splitlines()]
    done = {l['id'] for l in lines if l['type'] == 'groupe' and l['statut'] == 'fait'}
    assert done == {'1', '2', '3', '4', '5'}
    server = FakeServer(plan['bibliotheque'])
    before = {}
    for g in plan['groupes']:
        for op in g['operations']:
            store = before.setdefault(op['genre'], {})
            if not op['creation']:
                store.setdefault(op['cle'], {}).update(op['avant'])
    parents = {v for g in plan['groupes'] for op in g['operations'] for k, v in (op['avant'] | op['apres']).items()
               if k == 'parentCollection' and v} | {c for g in plan['groupes'] for op in g['operations']
                                                    for c in (op['avant'] | op['apres']).get('collections', [])}
    created = {op['cle'] for g in plan['groupes'] for op in g['operations'] if op['creation']}
    for key in sorted(parents - created - set(before.get('collections', {}))):
        server.collection(f'Collection {key}', key=key)
    for g in plan['groupes']:
        for op in g['operations']:
            fields = op['apres'] if g['id'] in done else op['avant']
            if op['genre'] == 'collections':
                if op['cle'] in server.collections:
                    server.collections[op['cle']].update(fields)
                elif op['creation'] and g['id'] in done:
                    server.collection(fields['name'], fields.get('parentCollection'), key=op['cle'])
                elif not op['creation']:
                    server.collection(f'Collection {op["cle"]}', key=op['cle'], deleted=False)
                    server.collections[op['cle']].update(before['collections'][op['cle']])
                    server.collections[op['cle']].update(fields)
            else:
                if op['cle'] not in server.all_items:
                    server.add(title=f'Fiche {op["cle"]}', key=op['cle'], **({'deleted': False} | before['items'][op['cle']]))
                server.all_items[op['cle']].update(fields)
    return server, before


@pytest.fixture
def workspace(tmp_path, zotero, monkeypatch):
    zotero.save()
    folder = tmp_path / 'travail'
    (folder / 'plans').mkdir(parents=True)
    (folder / 'journal').mkdir()
    shutil.copy(V032 / 'plans' / PLAN, folder / 'plans' / PLAN)
    shutil.copy(V032 / 'journal' / TRIAL_JOURNAL, folder / 'journal' / TRIAL_JOURNAL)
    shutil.copy(V032 / 'plan.md', folder / 'plan.md')
    text = (V032 / 'config.toml').read_text(encoding='utf-8')
    (folder / 'config.toml').write_text(text.replace('/zotero-factice/Zotero', zotero.folder.as_posix()),
                                        encoding='utf-8')
    for root in ('.agents', '.claude'):
        for name in ('doublons', 'metadonnees', 'fonds', 'cles', 'noms', 'controle', 'inbox', 'tags'):
            skill = folder / root / 'skills' / name / 'SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text(f'---\nname: {name}\n---\nConsignes de la 0.3.2, `zc appliquer <plan> --essai`.\n',
                             encoding='utf-8')
    (folder / 'AGENTS.md').write_text('Consignes de la 0.3.2. Répondre en français.\n', encoding='utf-8')
    (folder / 'methode.md').write_text('# La méthode par défaut (0.3.2)\n', encoding='utf-8')
    return folder


def test_032_folder_taken_over(workspace, monkeypatch, capsys):
    plan = json.loads((workspace / 'plans' / PLAN).read_text(encoding='utf-8'))
    server, before = server_left_by_the_trial(plan)
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())

    # The update: instructions in English, old skills removed, guide and method of a French library.
    assert main(['init', '--update', str(workspace)]) == 0
    output = capsys.readouterr().out
    assert 'Retirés' in output and '.agents/skills/doublons/' in output
    assert not (workspace / '.claude' / 'skills' / 'fonds').exists()
    assert (workspace / '.claude' / 'skills' / 'subjects' / 'SKILL.md').is_file()
    assert 'zc config show' in (workspace / 'AGENTS.md').read_text(encoding='utf-8')
    assert (workspace / 'methode.md').read_text(encoding='utf-8').startswith('# La méthode par défaut\n')
    assert not (workspace / 'method.md').exists()
    cfg = config.load(workspace)
    assert (cfg.method.language, cfg.method.subjects) == ('fr', '40 Fonds')
    assert 'langue' not in (workspace / 'config.toml').read_text(encoding='utf-8')  # config.toml left as it was

    # The rest of the plan, in French like the library.
    fake_backup(cfg)
    assert main(['apply', str(workspace / 'plans' / PLAN), '--all', '--workspace', str(workspace)]) == 0
    output = capsys.readouterr().out
    assert 'corbeille' in output or 'groupe' in output
    assert server.collections['2222UUBC']['deleted'] and server.collections['2222UUB7']['deleted']
    assert server.all_items['2222UUBL']['deleted']
    assert main(['journal', '--workspace', str(workspace)]) == 0
    assert 'terminé' in capsys.readouterr().out

    # Undo of both runs, the trial of 0.3.2 and the rest applied by 0.4.
    assert main(['undo', str(workspace / 'plans' / PLAN), '--workspace', str(workspace)]) == 0
    capsys.readouterr()
    undo_plan = max((workspace / 'plans').glob('*_annulation_*.json'))
    assert main(['apply', str(undo_plan), '--trial', '--workspace', str(workspace)]) == 0
    assert main(['apply', str(undo_plan), '--all', '--workspace', str(workspace)]) == 0
    for kind, store in (('items', server.all_items), ('collections', server.collections)):
        for key, fields in before[kind].items():
            # Out of the trash, `deleted` is absent, as Zotero writes it, rather than false.
            assert {k: store[key].get(k, False if k == 'deleted' else None) for k in fields} == fields, key
    for key in ('IYL2RB7R', 'DFLSZE8K'):  # collections the plan created
        assert server.collections[key].get('deleted'), key
