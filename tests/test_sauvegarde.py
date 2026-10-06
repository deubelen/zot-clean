import platform
from datetime import datetime, timedelta

import pytest

from zot_clean import sauvegarde
from zot_clean.config import Config
from zot_clean.ecriture import Refus


@pytest.fixture
def cfg(tmp_path, zotero):
    zotero.fiche('Une fiche')
    zotero.pdf(zotero.fiche('Avec PDF'), 'a.pdf')
    zotero.enregistrer()
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


def test_refus_si_zotero_ouvert(cfg):
    with pytest.raises(Refus, match='ouvert'):
        sauvegarde.sauvegarder(cfg, ouvert=lambda: True)
    assert not cfg.sauvegardes.exists()


def test_sauvegarde_a_cote_du_dossier_zotero(cfg):
    info = sauvegarde.sauvegarder(cfg, ouvert=lambda: False)
    assert cfg.sauvegardes == cfg.dossier_zotero.parent / 'Zotero-sauvegardes'
    assert info.dossier.parent == cfg.sauvegardes and info.methode in ('clone', 'base')
    if platform.system() == 'Darwin':
        assert info.methode == 'clone'  # APFS
    if info.methode == 'clone':
        assert (info.dossier / 'Zotero' / 'zotero.sqlite').is_file()
        assert any((info.dossier / 'Zotero' / 'storage').rglob('a.pdf'))
    else:
        assert (info.dossier / 'zotero.sqlite').is_file()
    assert sauvegarde.recente(cfg).dossier == info.dossier


def test_seules_les_plus_recentes_sont_gardees(cfg):
    debut = datetime.now().astimezone() - timedelta(hours=3)
    infos = [sauvegarde.sauvegarder(cfg, ouvert=lambda: False, maintenant=debut + timedelta(hours=i))
             for i in range(3)]
    restantes = sauvegarde.lister(cfg)
    assert [i.dossier for i in restantes] == [infos[2].dossier, infos[1].dossier]
    assert not infos[0].dossier.exists()


def test_delai_de_recence(cfg):
    sauvegarde.sauvegarder(cfg, ouvert=lambda: False, maintenant=datetime.now().astimezone() - timedelta(hours=30))
    assert sauvegarde.recente(cfg) is None
    cfg.sauvegarde.delai_heures = 48
    assert sauvegarde.recente(cfg) is not None


def test_dossier_etranger_ignore(cfg):
    (cfg.sauvegardes / 'photos').mkdir(parents=True)
    sauvegarde.sauvegarder(cfg, ouvert=lambda: False)
    assert (cfg.sauvegardes / 'photos').exists() and len(sauvegarde.lister(cfg)) == 1


def test_detection_de_zotero_sans_erreur():
    assert sauvegarde.zotero_ouvert() in (True, False)


def test_sauvegardes_ecartees_des_logiciels_de_sauvegarde(cfg, tmp_path):
    # D159 : CACHEDIR.TAG pour Borg, restic et tar, exclusion de Time Machine sur macOS, une seule fois.
    sauvegarde.sauvegarder(cfg, ouvert=lambda: False)
    tag = cfg.sauvegardes / sauvegarde.CACHEDIR
    assert tag.read_text(encoding='utf-8').startswith(sauvegarde.SIGNATURE)
    assert len(sauvegarde.lister(cfg)) == 1
    appels = []
    mac, linux = tmp_path / 'mac', tmp_path / 'linux'
    for d, systeme in ((mac, 'Darwin'), (mac, 'Darwin'), (linux, 'Linux')):
        d.mkdir(exist_ok=True)
        sauvegarde.exclure_des_sauvegardes(d, systeme, appels.append)
    assert appels == [['tmutil', 'addexclusion', str(mac)]]
    assert (linux / sauvegarde.CACHEDIR).is_file()

    def echec(commande):
        raise OSError('tmutil absent')
    (tmp_path / 'echec').mkdir()
    sauvegarde.exclure_des_sauvegardes(tmp_path / 'echec', 'Darwin', echec)


def test_noms_du_processus_zotero(monkeypatch):
    # D193 : selon l'installation sous Linux, le processus s'appelle zotero ou zotero-bin.
    import subprocess
    appels = []

    def faux_run(args, **kw):
        appels.append(args)
        return subprocess.CompletedProcess(args, 1, '', '')
    monkeypatch.setattr(sauvegarde.os, 'name', 'posix')
    monkeypatch.setattr(sauvegarde.subprocess, 'run', faux_run)
    assert sauvegarde.zotero_ouvert() is False
    assert appels == [['pgrep', '-i', '-x', 'zotero|zotero-bin']]
