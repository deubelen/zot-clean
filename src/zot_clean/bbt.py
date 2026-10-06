"""Better BibTeX et synchronisation des fichiers, lus dans le profil de Zotero (D145, D157).

Seul module à connaître le profil de Zotero et les fichiers de Better BibTeX
(BBT), comme `lecture.py` pour le schéma de la base. Le dossier des profils
dépend du système. Son `profiles.ini` liste les profils, et le `prefs.js` de
chacun désigne le dossier de données qu'il sert. Dans le profil retenu,
`extensions.json` donne la version et l'état de BBT, et `prefs.js` ses
réglages, lus par une expression régulière sans rien exécuter. Une
préférence absente de `prefs.js` garde la valeur par défaut de BBT.

Quand aucun profil ne sert le dossier de données (profil déplacé, système non
prévu), la détection se replie sur la recherche d'un dossier `better-bibtex/`
ou d'une base `better-bibtex*.sqlite` dans le dossier de données, sans version
ni réglages, et le dit (`source`). Rien n'est jamais écrit dans le profil.

Le même `prefs.js` dit où Zotero synchronise les fichiers de la bibliothèque
personnelle (zotero.org, WebDAV ou nulle part), ce que l'audit utilise pour
parler des fichiers absents (D157).
"""

import configparser
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ID_BBT = 'better-bibtex@iris-advies.com'
PREFIXE = 'extensions.zotero.translators.better-bibtex.'
PROFIL, DOSSIER_DONNEES = 'profil', 'dossier de données'

# Valeurs par défaut de BBT 9 (fichier `prefs.js` de l'extension), utilisées quand le profil ne dit rien.
FORMULE_BBT = 'auth.lower + shorttitle(3,3) + year'
REMPLISSAGE_BBT = 2.0
# Formule de la méthode par défaut (D24). Elle vit dans BBT et n'est pas recopiée dans config.toml (D145),
# elle ne sert qu'à signaler une formule différente, sans en faire un problème.
FORMULE_METHODE = 'auth.lower + shorttitle(3, 3) + year'
# Synchronisation des fichiers (D157). INCONNU quand aucun profil ne sert le dossier de données.
ZOTERO_ORG, WEBDAV, AUCUNE, INCONNU = 'zotero.org', 'webdav', 'aucune', ''
# Première version de BBT qui range les clés dans le champ natif de Zotero (D145).
VERSION_MIN = 8

_PREF = re.compile(r'^\s*user_pref\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(.*?)\s*\)\s*;\s*$', re.M)


@dataclass
class Etat:
    installe: bool = False  # extension présente, même désactivée
    actif: bool = False
    version: str = ''
    formule: str = FORMULE_BBT
    remplissage: float = REMPLISSAGE_BBT  # secondes avant que BBT remplisse une clé vide, 0 = sur demande
    regenere: bool = False  # BBT refait la clé d'une fiche à chaque modification (resetKeyOnChange)
    casse: bool = False  # BBT distingue la casse pour juger deux clés identiques
    source: str = ''  # PROFIL ou DOSSIER_DONNEES (repli)
    profil: Path | None = None

    @property
    def present(self) -> bool:
        """Un BBT installé mais désactivé compte comme absent (D145)."""
        return self.installe and self.actif

    @property
    def majeure(self) -> int | None:
        m = re.match(r'\d+', self.version)
        return int(m.group()) if m else None

    @property
    def trop_ancien(self) -> bool:
        return self.majeure is not None and self.majeure < VERSION_MIN

    @property
    def formule_methode(self) -> bool:
        return ''.join(self.formule.split()) == ''.join(FORMULE_METHODE.split())


def chemins_profils(systeme: str, personnel: Path, appdata: str | None = None) -> list[Path]:
    """Dossiers qui peuvent contenir le `profiles.ini` de Zotero, selon le système."""
    if systeme == 'darwin':
        return [personnel / 'Library' / 'Application Support' / 'Zotero']
    if systeme.startswith('win'):
        racine = Path(appdata) if appdata else personnel / 'AppData' / 'Roaming'
        return [racine / 'Zotero' / 'Zotero']
    # Linux et autres Unix, avec l'installation Flatpak.
    return [personnel / '.zotero' / 'zotero', personnel / '.var' / 'app' / 'org.zotero.Zotero' / '.zotero' / 'zotero']


def dossiers_profils() -> list[Path]:
    return chemins_profils(sys.platform, Path.home(), os.environ.get('APPDATA'))


def profils(racine: Path) -> list[Path]:
    """Profils listés par `racine/profiles.ini`, le profil par défaut en premier."""
    ini = racine / 'profiles.ini'
    if not ini.is_file():
        return []
    lecteur = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        lecteur.read_string(ini.read_text(encoding='utf-8', errors='replace'))
    except configparser.Error:
        return []
    trouves = []
    for nom in lecteur.sections():
        s = lecteur[nom]
        if not nom.lower().startswith('profile') or not s.get('path'):
            continue
        chemin = racine / s['path'] if s.get('isrelative', '1') == '1' else Path(s['path'])
        trouves.append((s.get('default') != '1', chemin))
    return [c for _, c in sorted(trouves, key=lambda t: t[0])]


def _valeur(brut: str):
    if brut.startswith('"'):
        try:
            return json.loads(brut)
        except json.JSONDecodeError:
            return brut.strip('"')
    if brut in ('true', 'false'):
        return brut == 'true'
    try:
        return int(brut)
    except ValueError:
        try:
            return float(brut)
        except ValueError:
            return brut


def lire_prefs(profil: Path) -> dict:
    """Préférences `user_pref(...)` de `prefs.js`, sans rien exécuter."""
    chemin = profil / 'prefs.js'
    if not chemin.is_file():
        return {}
    texte = chemin.read_text(encoding='utf-8', errors='replace')
    return {m.group(1): _valeur(m.group(2)) for m in _PREF.finditer(texte)}


def _normal(p: Path) -> str:
    return os.path.normcase(str(Path(p).expanduser().resolve()))


def dossier_donnees(prefs: dict, personnel: Path) -> Path:
    """Dossier de données servi par un profil : `dataDir` quand `useDataDir` est vrai, sinon `~/Zotero`."""
    if prefs.get('extensions.zotero.useDataDir') is True and prefs.get('extensions.zotero.dataDir'):
        return Path(str(prefs['extensions.zotero.dataDir']))
    return personnel / 'Zotero'


def profil_du_dossier(dossier_zotero: Path, racines: list[Path] | None = None,
                      personnel: Path | None = None) -> Path | None:
    racines = dossiers_profils() if racines is None else racines
    personnel = personnel or Path.home()
    cible = _normal(dossier_zotero)
    for racine in racines:
        for profil in profils(racine):
            if _normal(dossier_donnees(lire_prefs(profil), personnel)) == cible:
                return profil
    return None


def _extension(profil: Path) -> dict | None:
    chemin = profil / 'extensions.json'
    try:
        donnees = json.loads(chemin.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return next((a for a in donnees.get('addons', []) if a.get('id') == ID_BBT), None)


def _nombre(v, defaut: float) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else defaut


def detecter(dossier_zotero: Path, racines: list[Path] | None = None, personnel: Path | None = None) -> Etat:
    """État de BBT pour le dossier de données `dossier_zotero` (D145)."""
    profil = profil_du_dossier(dossier_zotero, racines, personnel)
    if profil is None:
        trouve = (dossier_zotero / 'better-bibtex').exists() or any(dossier_zotero.glob('better-bibtex*.sqlite'))
        return Etat(installe=trouve, actif=trouve, source=DOSSIER_DONNEES)
    ext = _extension(profil)
    if ext is None:
        return Etat(source=PROFIL, profil=profil)
    prefs = lire_prefs(profil)

    def pref(nom, defaut):
        return prefs.get(PREFIXE + nom, defaut)

    formule = pref('citekeyFormat', FORMULE_BBT)
    return Etat(installe=True, actif=ext.get('active') is True, version=str(ext.get('version', '')),
                formule=(formule if isinstance(formule, str) and formule.strip() else FORMULE_BBT).strip(),
                remplissage=_nombre(pref('fillKeyAfter', REMPLISSAGE_BBT), REMPLISSAGE_BBT),
                regenere=pref('resetKeyOnChange', False) is True,
                casse=pref('citekeyCaseInsensitive', True) is False,
                source=PROFIL, profil=profil)


def stockage_fichiers(dossier_zotero: Path, racines: list[Path] | None = None,
                      personnel: Path | None = None) -> str:
    """Où Zotero synchronise les fichiers de la bibliothèque personnelle (D157). Une préférence absente de
    `prefs.js` garde la valeur par défaut de Zotero (synchronisation active, par zotero.org)."""
    profil = profil_du_dossier(dossier_zotero, racines, personnel)
    if profil is None:
        return INCONNU
    prefs = lire_prefs(profil)
    if prefs.get('extensions.zotero.sync.storage.enabled', True) is False:
        return AUCUNE
    return WEBDAV if prefs.get('extensions.zotero.sync.storage.protocol', 'zotero') == 'webdav' else ZOTERO_ORG


def langue_zotero(dossier_zotero: Path, racines: list[Path] | None = None, personnel: Path | None = None) -> str:
    """Langue de l'interface de Zotero (« fr », « en »…), vide si le profil ne la dit pas. `intl.locale.requested`
    quand l'utilisateur l'a choisie dans Zotero, sinon la première langue de `intl.accept_languages`, que Zotero
    règle d'après la langue du système."""
    profil = profil_du_dossier(dossier_zotero, racines, personnel)
    if profil is None:
        return ''
    prefs = lire_prefs(profil)
    for nom in ('intl.locale.requested', 'intl.accept_languages'):
        if isinstance(v := prefs.get(nom), str) and v.strip():
            return v.split(',')[0].strip().split('-')[0].lower()
    return ''


def decrire(etat: Etat) -> str:
    """Une phrase sur BBT, pour `zc init` et l'audit."""
    if etat.source == DOSSIER_DONNEES:
        if etat.present:
            return ('Better BibTeX détecté par son dossier dans le dossier de données (profil de Zotero introuvable, '
                    'version et réglages inconnus).')
        return 'Better BibTeX non détecté (profil de Zotero introuvable).'
    if not etat.installe:
        return 'Better BibTeX absent du profil de Zotero.'
    if not etat.actif:
        return f'Better BibTeX {etat.version} installé mais désactivé dans Zotero, compté comme absent.'
    texte = f'Better BibTeX {etat.version} actif, formule « {etat.formule} ».'
    if etat.trop_ancien:
        texte += (f' Cette version est trop ancienne, l\'étape des clés de citation demande Better BibTeX '
                  f'{VERSION_MIN} et Zotero 8 au moins, qui rangent les clés dans le champ natif de Zotero.')
    return texte


def tags_automatiques(dossier_zotero: Path, racines: list[Path] | None = None,
                      personnel: Path | None = None) -> bool | None:
    """Réglage « Ajouter automatiquement des tags à partir des mots-clés et des vedettes-matières » de Zotero (D155),
    vrai par défaut, écrit dans `prefs.js` seulement s'il diffère. None quand aucun profil ne sert le dossier de
    données. Le réglage du connecteur, propre au navigateur, n'est pas lisible ici."""
    profil = profil_du_dossier(dossier_zotero, racines, personnel)
    if profil is None:
        return None
    return lire_prefs(profil).get('extensions.zotero.automaticTags', True) is not False
