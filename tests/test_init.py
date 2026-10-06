import json

import pytest

from zot_clean import bbt, config, init


@pytest.fixture
def cle_valide(monkeypatch):
    appels = []

    def verifier(cle):
        appels.append(cle)
        if cle != 'BONNE':
            raise init.CleRefusee('Clé refusée par Zotero (invalide ou révoquée).')
        return init.InfoCle(12345, 'durand', True, True, True)

    monkeypatch.setattr(init, 'verifier_cle', verifier)
    return appels


def lancer(dossier, zotero, reponses=(), secrets=(), maj=False):
    reponses, secrets, sortie = list(reponses), list(secrets), []
    code = init.initialiser(dossier, zotero.dossier, maj, lambda _: reponses.pop(0) if reponses else '',
                            lambda _: secrets.pop(0) if secrets else '',
                            sortie.append)
    return code, '\n'.join(sortie)


def test_cree_le_dossier_de_travail(tmp_path, zotero, cle_valide):
    zotero.enregistrer()
    (zotero.dossier / 'better-bibtex').mkdir()
    travail = tmp_path / 'travail'
    code, sortie = lancer(travail, zotero, secrets=['MAUVAISE', 'BONNE'])
    assert code == 0 and cle_valide == ['MAUVAISE', 'BONNE']
    assert 'Réessayer' in sortie and 'BONNE' not in sortie
    assert init.lire_env(travail) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '12345'}
    assert {p.name for p in travail.iterdir()} == {'config.toml', '.env', '.gitignore', 'AGENTS.md', 'guide.md', 'methode.md', '.agents', '.claude', 'rapports', 'journal', 'plans', 'suivi'}
    for racine in ('.agents', '.claude'):
        for skill in ('doublons', 'metadonnees', 'fonds', 'tags', 'cles'):
            assert (travail / racine / 'skills' / skill / 'SKILL.md').is_file()
    cfg = config.charger(travail)
    assert cfg.dossier_zotero == zotero.dossier and cfg.methode.cles_citation
    assert '.env' in (travail / '.gitignore').read_text(encoding='utf-8')


def test_sans_better_bibtex_les_cles_sont_desactivees(tmp_path, zotero, cle_valide):
    zotero.enregistrer()
    lancer(tmp_path, zotero, secrets=['BONNE'])
    assert config.charger(tmp_path).methode.cles_citation is False


def profil_zotero(tmp_path, monkeypatch, zotero, actif: bool, version: str = '9.1.0'):
    """Profil de Zotero qui sert le dossier de données de test, avec Better BibTeX actif ou désactivé."""
    racine = tmp_path / 'profils'
    profil = racine / 'Profiles' / 'x.default'
    profil.mkdir(parents=True)
    (racine / 'profiles.ini').write_text('[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/x.default\nDefault=1\n',
                                         encoding='utf-8')
    (profil / 'prefs.js').write_text(f'user_pref("extensions.zotero.dataDir", {json.dumps(str(zotero.dossier))});\n'
                                     'user_pref("extensions.zotero.useDataDir", true);\n', encoding='utf-8')
    (profil / 'extensions.json').write_text(json.dumps({'addons': [
        {'id': 'better-bibtex@iris-advies.com', 'version': version, 'active': actif}]}), encoding='utf-8')
    monkeypatch.setattr(bbt, 'dossiers_profils', lambda: [racine])


def test_better_bibtex_lu_dans_le_profil(tmp_path, zotero, cle_valide, monkeypatch):
    zotero.enregistrer()
    profil_zotero(tmp_path, monkeypatch, zotero, actif=True)
    travail = tmp_path / 'actif'
    _, sortie = lancer(travail, zotero, secrets=['BONNE'])
    assert 'Better BibTeX 9.1.0 actif' in sortie and config.charger(travail).methode.cles_citation


def test_better_bibtex_desactive_compte_comme_absent(tmp_path, zotero, cle_valide, monkeypatch):
    zotero.enregistrer()
    (zotero.dossier / 'better-bibtex').mkdir()  # vieux caches, ignorés puisque le profil répond
    profil_zotero(tmp_path, monkeypatch, zotero, actif=False)
    travail = tmp_path / 'inactif'
    _, sortie = lancer(travail, zotero, secrets=['BONNE'])
    assert 'désactivé dans Zotero' in sortie and config.charger(travail).methode.cles_citation is False


def test_cle_sans_droit_d_ecriture(tmp_path, zotero, monkeypatch):
    zotero.enregistrer()
    monkeypatch.setattr(init, 'verifier_cle', lambda cle: init.InfoCle(1, 'x', True, False, True))
    _, sortie = lancer(tmp_path, zotero, secrets=['LECTURE', ''])
    assert "sans droit d'écriture" in sortie and 'Étape passée' in sortie
    assert not (tmp_path / '.env').exists()


def test_relance_sans_rien_ecraser_et_redemande_la_cle_manquante(tmp_path, zotero, cle_valide):
    zotero.enregistrer()
    lancer(tmp_path, zotero, secrets=[''])
    (tmp_path / 'config.toml').write_text('[methode]\ninbox = "Boîte"\n', encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('mes consignes', encoding='utf-8')
    _, sortie = lancer(tmp_path, zotero, secrets=['BONNE'])
    assert 'conservé' in sortie and init.lire_env(tmp_path)['ZOTERO_API_KEY'] == 'BONNE'
    assert config.charger(tmp_path).methode.inbox == 'Boîte'
    assert (tmp_path / 'AGENTS.md').read_text(encoding='utf-8') == 'mes consignes'
    _, sortie = lancer(tmp_path, zotero)
    assert 'déjà enregistrée' in sortie


def test_maj_remplace_agents_md_et_skills(tmp_path, zotero):
    (tmp_path / 'config.toml').write_text('', encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('ancien', encoding='utf-8')
    skill = tmp_path / '.agents' / 'skills' / 'doublons' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('ancien', encoding='utf-8')
    lancer(tmp_path, zotero, maj=True)
    assert 'zot-clean' in (tmp_path / 'AGENTS.md').read_text(encoding='utf-8')
    assert skill.read_text(encoding='utf-8').startswith('---\nname: doublons')


def test_dossier_zotero_introuvable(tmp_path):
    questions = []
    code = init.initialiser(tmp_path, tmp_path / 'nulle-part', False, lambda q: questions.append(q) or '',
                            lambda _: '', lambda _: None)
    assert code == 1 and 'introuvable' in questions[0]
    assert not (tmp_path / 'config.toml').exists()


def test_avertit_si_un_claude_md_masque_agents_md(tmp_path, zotero, monkeypatch):
    monkeypatch.setattr(init.Path, 'home', lambda: tmp_path / 'maison')
    zotero.enregistrer()
    travail = tmp_path / 'projets' / 'biblio'
    travail.mkdir(parents=True)
    (travail / 'config.toml').write_text('', encoding='utf-8')
    _, sortie = lancer(travail, zotero, maj=True)
    assert 'Attention' not in sortie
    (tmp_path / 'projets' / 'CLAUDE.md').write_text('consignes du dossier parent', encoding='utf-8')
    _, sortie = lancer(travail, zotero, maj=True)
    assert 'Attention' in sortie and '@AGENTS.md' in sortie
    (travail / 'CLAUDE.md').write_text('@AGENTS.md\n', encoding='utf-8')
    _, sortie = lancer(travail, zotero, maj=True)
    assert 'Attention' not in sortie


def test_claude_md_personnel_ignore(tmp_path, monkeypatch):
    maison = tmp_path / 'maison'
    monkeypatch.setattr(init.Path, 'home', lambda: maison)
    (maison / '.claude').mkdir(parents=True)
    (maison / '.claude' / 'CLAUDE.md').write_text('préférences', encoding='utf-8')
    assert init.claude_md_concurrents(maison / 'biblio') == []
    (maison / 'biblio').mkdir()
    (maison / 'biblio' / 'CLAUDE.local.md').write_text('x', encoding='utf-8')
    assert init.claude_md_concurrents(maison / 'biblio') == [maison / 'biblio' / 'CLAUDE.local.md']


def test_cle_openalex_facultative(tmp_path, zotero, cle_valide):
    zotero.enregistrer()
    code, sortie = lancer(tmp_path, zotero, secrets=['BONNE', 'CLE-OA'])
    assert code == 0 and 'CLE-OA' not in sortie
    assert init.lire_env(tmp_path) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '12345',
                                       'OPENALEX_API_KEY': 'CLE-OA'}


def test_maj_refuse_hors_dossier_de_travail(tmp_path, zotero):
    """Garde-fou : --maj dans un dossier sans config.toml (un dépôt de code, par exemple) n'écrit rien."""
    (tmp_path / 'AGENTS.md').write_text('consignes du projet', encoding='utf-8')
    code, sortie = lancer(tmp_path, zotero, maj=True)
    assert code == 1 and "n'est pas un dossier de travail" in sortie
    assert (tmp_path / 'AGENTS.md').read_text(encoding='utf-8') == 'consignes du projet'
    assert not (tmp_path / '.agents').exists() and not (tmp_path / '.claude').exists()


def test_cle_enregistree_revoquee_redemandee(tmp_path, zotero, cle_valide):
    zotero.enregistrer()
    init.ecrire_env(tmp_path, ZOTERO_API_KEY='REVOQUEE', ZOTERO_USER_ID='1', OPENALEX_API_KEY='OA')
    _, sortie = lancer(tmp_path, zotero, secrets=['BONNE'])
    assert 'à remplacer' in sortie and cle_valide == ['REVOQUEE', 'BONNE']
    assert init.lire_env(tmp_path) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '12345', 'OPENALEX_API_KEY': 'OA'}


def test_cle_enregistree_sans_droit_d_ecriture_redemandee(tmp_path, zotero, monkeypatch):
    zotero.enregistrer()
    init.ecrire_env(tmp_path, ZOTERO_API_KEY='LECTURE')
    monkeypatch.setattr(init, 'verifier_cle', lambda cle: init.InfoCle(1, 'x', True, cle != 'LECTURE', True))
    _, sortie = lancer(tmp_path, zotero, secrets=['COMPLETE'])
    assert "n'a plus droit d'écriture" in sortie and init.lire_env(tmp_path)['ZOTERO_API_KEY'] == 'COMPLETE'


def test_cle_enregistree_gardee_si_zotero_injoignable(tmp_path, zotero, monkeypatch):
    zotero.enregistrer()
    init.ecrire_env(tmp_path, ZOTERO_API_KEY='GARDEE')

    def injoignable(cle):
        raise init.urllib.error.URLError('pas de réseau')

    monkeypatch.setattr(init, 'verifier_cle', injoignable)
    _, sortie = lancer(tmp_path, zotero)
    assert 'non vérifiée' in sortie and init.lire_env(tmp_path)['ZOTERO_API_KEY'] == 'GARDEE'


def test_guide_et_methode_copies(tmp_path, zotero):
    """Le dépôt reste privé : le guide et la méthode voyagent avec le paquet, dans le dossier de travail."""
    lancer(tmp_path, zotero)
    assert '# ' in (tmp_path / 'guide.md').read_text(encoding='utf-8')
    assert (tmp_path / 'methode.md').is_file()
    assert 'methode.md' in (tmp_path / 'config.toml').read_text(encoding='utf-8')
