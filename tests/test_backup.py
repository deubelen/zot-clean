import platform
from datetime import datetime, timedelta

import pytest

from zot_clean import backup
from zot_clean.config import Config
from zot_clean.api import Refusal


@pytest.fixture
def cfg(tmp_path, zotero):
    zotero.item('Une fiche')
    zotero.pdf(zotero.item('Avec PDF'), 'a.pdf')
    zotero.save()
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


def test_refusal_if_zotero_open(cfg):
    with pytest.raises(Refusal, match='ouvert'):
        backup.make_backup(cfg, is_open=lambda: True)
    assert not cfg.backups.exists()


def test_backup_next_to_zotero_dir(cfg):
    info = backup.make_backup(cfg, is_open=lambda: False)
    assert cfg.backups == cfg.zotero_dir.parent / 'Zotero-sauvegardes'
    assert info.folder.parent == cfg.backups and info.method in ('clone', 'base')
    if platform.system() == 'Darwin':
        assert info.method == 'clone'  # APFS
    if info.method == 'clone':
        assert (info.folder / 'Zotero' / 'zotero.sqlite').is_file()
        assert any((info.folder / 'Zotero' / 'storage').rglob('a.pdf'))
    else:
        assert (info.folder / 'zotero.sqlite').is_file()
    assert backup.latest(cfg).folder == info.folder


def test_only_most_recent_are_kept(cfg):
    start = datetime.now().astimezone() - timedelta(hours=3)
    made = [backup.make_backup(cfg, is_open=lambda: False, now=start + timedelta(hours=i))
             for i in range(3)]
    remaining_backups = backup.list_backups(cfg)
    assert [i.folder for i in remaining_backups] == [made[2].folder, made[1].folder]
    assert not made[0].folder.exists()


def test_recency_delay(cfg):
    backup.make_backup(cfg, is_open=lambda: False, now=datetime.now().astimezone() - timedelta(hours=30))
    assert backup.latest(cfg) is None
    cfg.backup.delay_hours = 48
    assert backup.latest(cfg) is not None


def test_foreign_folder_ignored(cfg):
    (cfg.backups / 'photos').mkdir(parents=True)
    backup.make_backup(cfg, is_open=lambda: False)
    assert (cfg.backups / 'photos').exists() and len(backup.list_backups(cfg)) == 1


def test_zotero_detection_without_error():
    assert backup.zotero_running() in (True, False)


def test_backups_excluded_from_backup_software(cfg, tmp_path):
    # D159 : CACHEDIR.TAG for Borg, restic and tar, Time Machine exclusion on macOS, only once.
    backup.make_backup(cfg, is_open=lambda: False)
    tag = cfg.backups / backup.CACHEDIR
    assert tag.read_text(encoding='utf-8').startswith(backup.SIGNATURE)
    assert len(backup.list_backups(cfg)) == 1
    calls = []
    mac, linux = tmp_path / 'mac', tmp_path / 'linux'
    for d, os_name in ((mac, 'Darwin'), (mac, 'Darwin'), (linux, 'Linux')):
        d.mkdir(exist_ok=True)
        backup.exclude_from_backups(d, os_name, calls.append)
    assert calls == [['tmutil', 'addexclusion', str(mac)]]
    assert (linux / backup.CACHEDIR).is_file()

    def failure(command):
        raise OSError('tmutil absent')
    (tmp_path / 'echec').mkdir()
    backup.exclude_from_backups(tmp_path / 'echec', 'Darwin', failure)


def test_zotero_process_names(monkeypatch):
    # D193 : depending on the Linux installation, the process is called zotero or zotero-bin.
    import subprocess
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, '', '')
    monkeypatch.setattr(backup.os, 'name', 'posix')
    monkeypatch.setattr(backup.subprocess, 'run', fake_run)
    assert backup.zotero_running() is False
    assert calls == [['pgrep', '-i', '-x', 'zotero|zotero-bin']]


def test_at_least_one_backup_kept(cfg, tmp_path):
    from zot_clean import config
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "/nulle/part"\n\n[sauvegarde]\nconserver = 0\n',
                                          encoding='utf-8')
    with pytest.raises(SystemExit, match='au moins 1'):
        config.load(tmp_path)
    # A configuration built without config.toml still keeps the backup it has just made.
    cfg.backup.keep = 0
    info = backup.make_backup(cfg, is_open=lambda: False)
    assert info.folder.is_dir() and [i.folder for i in backup.list_backups(cfg)] == [info.folder]


def test_backup_of_another_zotero_dir(cfg, tmp_path):
    """A backup folder shared by two libraries: the other one's backup does not count as recent."""
    cfg.backup.folder = tmp_path / 'sauvegardes'
    backup.make_backup(cfg, is_open=lambda: False)
    assert backup.latest(cfg) is not None
    other = Config(workspace=cfg.workspace, zotero_dir=tmp_path / 'AutreZotero')
    other.backup.folder = cfg.backup.folder
    assert backup.latest(other) is None


def test_refusal_in_english(cfg):
    from zot_clean.lang import language
    with language('en'):
        with pytest.raises(Refusal, match=r'Zotero is open.*`zc backup`'):
            backup.make_backup(cfg, is_open=lambda: True)
