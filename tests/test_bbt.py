"""Détection de Better BibTeX dans un faux profil de Zotero (D145)."""

import json
from pathlib import Path

from zot_clean import bbt

PREFIXE = 'extensions.zotero.translators.better-bibtex.'


def ecrire_profil(racine: Path, nom: str, donnees: Path | None, extension: dict | None, prefs: dict = (),
                  defaut: bool = False) -> Path:
    """Profil `racine/Profiles/<nom>` qui sert le dossier de données `donnees` (None, dossier par défaut)."""
    profil = racine / 'Profiles' / nom
    profil.mkdir(parents=True)
    lignes = ['// Mozilla User Preferences', '']
    valeurs = dict(prefs)
    if donnees is not None:
        valeurs |= {'extensions.zotero.dataDir': str(donnees), 'extensions.zotero.useDataDir': True}
    for k, v in valeurs.items():
        lignes.append(f'user_pref({json.dumps(k)}, {json.dumps(v)});')
    (profil / 'prefs.js').write_text('\n'.join(lignes) + '\n', encoding='utf-8')
    if extension is not None:
        addons = [{'id': 'autre@exemple.org', 'version': '1.0', 'active': True}]
        if extension:
            addons.append(dict({'id': bbt.ID_BBT}, **extension))
        (profil / 'extensions.json').write_text(json.dumps({'schemaVersion': 36, 'addons': addons}), encoding='utf-8')
    ini = racine / 'profiles.ini'
    texte = ini.read_text(encoding='utf-8') if ini.exists() else '[General]\nStartWithLastProfile=1\nVersion=2\n'
    n = texte.count('[Profile')
    texte += f'\n[Profile{n}]\nName={nom}\nIsRelative=1\nPath=Profiles/{nom}\n' + ('Default=1\n' if defaut else '')
    ini.write_text(texte, encoding='utf-8')
    return profil


def deux_profils(tmp_path, extension_test: dict | None = None, prefs_test: dict = ()) -> tuple[Path, Path, Path]:
    racine = tmp_path / 'Zotero-profils'
    principal, test = tmp_path / 'Zotero', tmp_path / 'Zotero Test'
    ecrire_profil(racine, 'a1.default', principal, {'version': '9.1.0', 'active': True}, defaut=True)
    profil_test = ecrire_profil(racine, 'b2.Test', test, extension_test, prefs_test)
    return racine, test, profil_test


def detecter(dossier, racine, personnel):
    return bbt.detecter(dossier, [racine], personnel)


def test_reglage_des_tags_automatiques(tmp_path):
    """D155 : le réglage n'est écrit dans prefs.js que s'il diffère du défaut (vrai)."""
    racine, test, _ = deux_profils(tmp_path, prefs_test={'extensions.zotero.automaticTags': False})
    assert bbt.tags_automatiques(test, [racine], tmp_path) is False
    assert bbt.tags_automatiques(tmp_path / 'Zotero', [racine], tmp_path) is True
    assert bbt.tags_automatiques(tmp_path / 'Ailleurs', [racine], tmp_path) is None


def test_choisit_le_profil_du_dossier_de_donnees(tmp_path):
    prefs = {PREFIXE + 'citekeyFormat': 'auth.lower + year', PREFIXE + 'fillKeyAfter': 0,
             PREFIXE + 'resetKeyOnChange': True, PREFIXE + 'citekeyCaseInsensitive': False}
    racine, test, profil = deux_profils(tmp_path, {'version': '9.0.40', 'active': True}, prefs)
    etat = detecter(test, racine, tmp_path)
    assert etat.profil == profil and etat.source == bbt.PROFIL
    assert etat.present and etat.version == '9.0.40' and etat.majeure == 9 and not etat.trop_ancien
    assert etat.formule == 'auth.lower + year' and not etat.formule_methode
    assert etat.remplissage == 0 and etat.regenere and etat.casse
    principal = detecter(tmp_path / 'Zotero', racine, tmp_path)
    assert principal.version == '9.1.0' and principal.profil.name == 'a1.default'


def test_preferences_absentes_valeurs_par_defaut_de_bbt(tmp_path):
    racine, test, _ = deux_profils(tmp_path, {'version': '9.1.0', 'active': True})
    etat = detecter(test, racine, tmp_path)
    assert etat.formule == bbt.FORMULE_BBT and etat.formule_methode
    assert etat.remplissage == 2 and not etat.regenere and not etat.casse


def test_formule_avec_parentheses_et_guillemets(tmp_path):
    racine, test, _ = deux_profils(tmp_path, {'version': '9.1.0', 'active': True},
                                   {PREFIXE + 'citekeyFormat': 'auth.lower + "-" + shorttitle(3, 3) + year'})
    assert detecter(test, racine, tmp_path).formule == 'auth.lower + "-" + shorttitle(3, 3) + year'


def test_bbt_desactive_compte_comme_absent(tmp_path):
    racine, test, _ = deux_profils(tmp_path, {'version': '9.1.0', 'active': False})
    etat = detecter(test, racine, tmp_path)
    assert etat.installe and not etat.actif and not etat.present
    assert 'désactivé' in bbt.decrire(etat)


def test_bbt_absent_du_profil(tmp_path):
    for extension in ({}, None):  # entrée absente de extensions.json, ou pas de extensions.json
        racine, test, _ = deux_profils(tmp_path / str(extension is None), extension)
        etat = detecter(test, racine, tmp_path / str(extension is None))
        assert not etat.present and not etat.installe and etat.source == bbt.PROFIL
    # Le vieux dossier de caches de BBT ne compte plus quand le profil dit que BBT est absent.
    (test / 'better-bibtex').mkdir(parents=True)
    assert not detecter(test, racine, tmp_path / 'True').present


def test_bbt_7_trop_ancien(tmp_path):
    racine, test, _ = deux_profils(tmp_path, {'version': '7.0.5', 'active': True})
    etat = detecter(test, racine, tmp_path)
    assert etat.present and etat.majeure == 7 and etat.trop_ancien
    assert 'trop ancienne' in bbt.decrire(etat)


def test_profil_sans_dossier_de_donnees_sert_zotero_du_dossier_personnel(tmp_path):
    racine = tmp_path / 'profils'
    ecrire_profil(racine, 'c3.default', None, {'version': '9.1.0', 'active': True}, defaut=True)
    assert detecter(tmp_path / 'Zotero', racine, tmp_path).present
    # useDataDir à faux : dataDir n'est pas suivi.
    ecrire_profil(racine, 'd4.autre', None, {'version': '8.0.1', 'active': True},
                  {'extensions.zotero.dataDir': str(tmp_path / 'Ailleurs'), 'extensions.zotero.useDataDir': False})
    assert detecter(tmp_path / 'Ailleurs', racine, tmp_path).source == bbt.DOSSIER_DONNEES


def test_repli_sur_le_dossier_de_donnees(tmp_path):
    racine, _, _ = deux_profils(tmp_path, {'version': '9.1.0', 'active': True})
    autre = tmp_path / 'Autre'
    autre.mkdir()
    etat = detecter(autre, racine, tmp_path)
    assert etat.source == bbt.DOSSIER_DONNEES and not etat.present
    assert 'profil de Zotero introuvable' in bbt.decrire(etat)
    (autre / 'better-bibtex.sqlite').write_bytes(b'')
    etat = detecter(autre, racine, tmp_path)
    assert etat.present and etat.version == '' and etat.majeure is None and not etat.trop_ancien
    # Sans aucun dossier de profils non plus.
    assert bbt.detecter(autre, [], tmp_path).present


def test_chemins_des_profils_par_systeme(tmp_path):
    assert bbt.chemins_profils('darwin', tmp_path) == [tmp_path / 'Library' / 'Application Support' / 'Zotero']
    assert bbt.chemins_profils('win32', tmp_path) == [tmp_path / 'AppData' / 'Roaming' / 'Zotero' / 'Zotero']
    assert bbt.chemins_profils('win32', tmp_path, str(tmp_path / 'Roaming')) == [
        tmp_path / 'Roaming' / 'Zotero' / 'Zotero']
    assert bbt.chemins_profils('linux', tmp_path)[0] == tmp_path / '.zotero' / 'zotero'


def test_profil_trouve_sous_le_dossier_personnel(tmp_path, monkeypatch):
    """Chemin réel du système courant, avec un dossier personnel remplacé."""
    import os
    import sys
    racine = bbt.chemins_profils(sys.platform, tmp_path, str(tmp_path / 'AppData' / 'Roaming'))[0]
    ecrire_profil(racine, 'e5.default', tmp_path / 'Données', {'version': '9.1.0', 'active': True}, defaut=True)
    monkeypatch.undo()  # retire le garde de conftest, qui empêche de lire les profils
    monkeypatch.setattr(bbt.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setitem(os.environ, 'APPDATA', str(tmp_path / 'AppData' / 'Roaming'))
    assert bbt.dossiers_profils()[0] == racine
    etat = bbt.detecter(tmp_path / 'Données')
    assert etat.source == bbt.PROFIL and etat.version == '9.1.0'


def test_profil_au_chemin_absolu(tmp_path):
    racine = tmp_path / 'profils'
    racine.mkdir()
    ailleurs = tmp_path / 'ailleurs'
    ecrire_profil(ailleurs, 'f6', tmp_path / 'Z', {'version': '9.0.0', 'active': True})
    (racine / 'profiles.ini').write_text(f'[Profile0]\nName=x\nIsRelative=0\nPath={ailleurs / "Profiles" / "f6"}\n',
                                         encoding='utf-8')
    assert detecter(tmp_path / 'Z', racine, tmp_path).version == '9.0.0'


def test_stockage_des_fichiers_lu_dans_le_profil(tmp_path):
    # D157 : zotero.org par défaut, WebDAV, synchronisation des fichiers désactivée, profil introuvable.
    racine = tmp_path / 'Zotero-profils'
    cas = {'Defaut': ({}, bbt.ZOTERO_ORG),
           'Webdav': ({'extensions.zotero.sync.storage.protocol': 'webdav'}, bbt.WEBDAV),
           'Aucune': ({'extensions.zotero.sync.storage.enabled': False,
                       'extensions.zotero.sync.storage.protocol': 'webdav'}, bbt.AUCUNE)}
    for nom, (prefs, attendu) in cas.items():
        ecrire_profil(racine, nom, tmp_path / nom, None, prefs)
        assert bbt.stockage_fichiers(tmp_path / nom, [racine], tmp_path) == attendu
    assert bbt.stockage_fichiers(tmp_path / 'Ailleurs', [racine], tmp_path) == bbt.INCONNU


def test_langue_de_zotero(tmp_path):
    racine = tmp_path / 'Zotero-profils'
    cas = {'Choisie': ({'intl.locale.requested': 'de', 'intl.accept_languages': 'fr, en'}, 'de'),
           'Systeme': ({'intl.accept_languages': 'fr-BE, fr, en-us'}, 'fr'), 'Rien': ({}, '')}
    for nom, (prefs, attendu) in cas.items():
        ecrire_profil(racine, nom, tmp_path / nom, None, prefs)
        assert bbt.langue_zotero(tmp_path / nom, [racine], tmp_path) == attendu
    assert bbt.langue_zotero(tmp_path / 'Ailleurs', [racine], tmp_path) == ''
