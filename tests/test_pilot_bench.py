"""Smoke test of the pilot test bench (D237, `outils/pilote/banc.py`): the real `zc`, end to end, on a synthetic
library and a fake zotero.org kept on disk, without network."""

import os
import socket
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'outils' / 'pilote'))
import banc  # noqa: E402


def local_version(bench: Path) -> int:
    db = sqlite3.connect(bench / banc.ZOTERO / 'zotero.sqlite')
    try:
        return db.execute('select version from libraries where libraryID = 1').fetchone()[0]
    finally:
        db.close()


def live_items(bench: Path) -> set[str]:
    return {k for k, d in banc.load_server(bench).all_items.items() if not d.get('deleted')}


def newest(work: Path, step: str) -> Path:
    return max((work / 'plans').glob(f'*_{step}_*.json'), key=lambda p: p.stat().st_mtime_ns)


@pytest.mark.parametrize('language', ['fr', 'en'])
def test_full_round_on_the_bench(tmp_path, monkeypatch, capsys, language):
    bench = tmp_path / 'banc'
    assert banc.create(bench, language, seed=2) == 0
    work = bench / banc.WORK
    assert (work / 'AGENTS.md').is_file() and (work / 'config.toml').is_file()
    assert f'langue = "{language}"' in (work / 'config.toml').read_text(encoding='utf-8')
    monkeypatch.chdir(work)

    def zc(*args: str) -> int:
        return banc.run(bench, list(args))

    before = live_items(bench)
    assert zc('audit') == 0
    assert zc('duplicates', 'find') == 0
    assert zc('duplicates', 'accept', '--certain') == 0
    assert zc('duplicates', 'plan') == 0
    plan = newest(work, 'doublons')
    capsys.readouterr()
    assert zc('backup') == 1  # Zotero is open
    assert 'Zotero' in capsys.readouterr().err
    assert banc.zotero(bench, 'close') == 0
    assert zc('backup') == 0
    assert banc.zotero(bench, 'open') == 0
    assert zc('apply', str(plan), '--trial') == 0
    assert local_version(bench) < banc.load_server(bench).version  # Zotero has not synced yet
    assert banc.sync(bench) == 0
    assert local_version(bench) == banc.load_server(bench).version
    groups = tomllib.loads((work / 'suivi' / 'doublons.toml').read_text(encoding='utf-8'))['groupe']
    key = groups[0]['cles'][0]
    capsys.readouterr()
    assert zc('show', key) == 0
    assert key in capsys.readouterr().out
    assert zc('apply', str(plan), '--all') == 0
    assert live_items(bench) < before  # the copies went to the trash
    assert zc('undo', str(plan)) == 0
    undo = newest(work, 'annulation')
    assert zc('apply', str(undo), '--trial') == 0
    assert zc('apply', str(undo), '--all') == 0
    assert live_items(bench) == before
    assert banc.sync(bench) == 0
    assert zc('audit') == 0
    assert not (bench / banc.NETWORK_LOG).exists()


def test_network_blocked_and_restored(tmp_path):
    bench = tmp_path / 'banc'
    assert banc.create(bench, 'fr', seed=1) == 0
    original = socket.create_connection
    with banc.bench_patches(bench, banc.load_server(bench)):
        with pytest.raises(OSError, match='blocked by the pilot bench'):
            socket.create_connection(('zotero.org', 443), timeout=1)
        with pytest.raises(OSError, match='blocked by the pilot bench'):
            socket.getaddrinfo('api.crossref.org', 443)
    assert socket.create_connection is original
    assert 'zotero.org' in (bench / banc.NETWORK_LOG).read_text(encoding='utf-8')


def test_rename_reaches_the_disk_at_sync(tmp_path, monkeypatch):
    """Step 8 changes `filename` on zotero.org, Zotero renames the file on the disk when it syncs."""
    bench = tmp_path / 'banc'
    assert banc.create(bench, 'en', seed=4) == 0
    monkeypatch.chdir(bench / banc.WORK)
    assert banc.run(bench, ['filenames', 'plan']) == 0
    assert banc.run(bench, ['apply', str(newest(bench / banc.WORK, 'noms')), '--trial']) == 0
    synced = local_version(bench)
    renamed = [d for d in banc.load_server(bench).all_items.values()
               if d.get('itemType') == 'attachment' and d['version'] > synced and d.get('filename')]
    assert renamed
    assert banc.sync(bench) == 0
    for d in renamed:
        assert (bench / banc.ZOTERO / 'storage' / d['key'] / d['filename']).is_file()


def test_autosync_and_user_gestures(tmp_path, monkeypatch):
    bench = tmp_path / 'banc'
    assert banc.create(bench, 'fr', seed=3) == 0
    monkeypatch.chdir(bench / banc.WORK)
    assert banc.zotero(bench, 'autosync', 'on') == 0
    assert banc.run(bench, ['citation-keys', 'plan']) == 0
    assert banc.run(bench, ['apply', str(newest(bench / banc.WORK, 'cles')), '--trial']) == 0
    assert local_version(bench) == banc.load_server(bench).version  # synced right after the command
    assert banc.new_collection(bench, 'Inbox', None) == 0
    assert banc.add_items(bench, 2) == 0
    inbox = next(k for k, c in banc.load_server(bench).collections.items() if c['name'] == 'Inbox')
    assert sum(inbox in d.get('collections', []) for d in banc.load_server(bench).all_items.values()) == 2
    assert banc.bbt_fill(bench) == 0
    assert all(d.get('citationKey') for d in banc.load_server(bench).all_items.values()
               if d['itemType'] not in banc.NON_REGULAR and not d.get('deleted'))
    assert banc.status(bench) == 0


@pytest.mark.skipif(os.name == 'nt', reason='the sh shim is for macOS and Linux')
def test_shim(tmp_path):
    bench = tmp_path / 'banc'
    assert banc.create(bench, 'fr', seed=1) == 0
    r = subprocess.run([str(bench / banc.BIN / 'zc'), 'config', 'show'], cwd=bench / banc.WORK, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert 'langue = "fr"' in r.stdout
