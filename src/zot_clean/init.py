"""Création d'un dossier de travail (`zc init`, D10, D13).

Écrit `config.toml` (dossier Zotero, Better BibTeX détecté), `.env` (clé API
vérifiée par l'API web, jamais affichée, revérifiée à chaque relance et
redemandée si Zotero la refuse), `.gitignore`, `AGENTS.md` et les
skills (`.agents/skills/` et `.claude/skills/`), et crée `rapports/`, `journal/`, `plans/` et
`suivi/`. Les fichiers existants ne sont pas écrasés, sauf `AGENTS.md` et les
skills avec `--maj`.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from zot_clean import bbt
from zot_clean.config import FICHIER as CONFIG, lire_env

PAGE_CLES = 'https://www.zotero.org/settings/keys/new'
API = 'https://api.zotero.org'
GITIGNORE = '.env\ncache/\n'

MODELE_CONFIG = """\
# Configuration de zot-clean pour cette bibliothèque.
# Chaque réglage de [methode] a une valeur par défaut, décommenter pour la changer.
# Les raisons de la méthode par défaut sont expliquées dans methode.md, à côté de ce fichier.

[zotero]
dossier = "{dossier}"

[methode]
# Collections racines. Laisser vide ("") pour s'en passer.
# inbox = "Inbox"
# Racines des projets, une ou plusieurs, par exemple ["Cours", "Articles"]. Liste vide pour s'en passer.
# projets = ["Projets"]
# fonds = "Fonds"
# archives = "Archives"
# etats = ["1 à lire", "2 en cours", "3 lu"]
# autres_tags = ["★ essentiel", "papier"]
# Couleurs des états puis des autres tags, dans l'ordre. Un tag coloré reçoit la touche de son rang (1 à 9).
# couleurs = ["#FF6666", "#FF8C19", "#5FB236", "#FFD400", "#A28AE5"]
# prefixe_concept = "#"
# prefixe_technique = "_"
# Nombre de références au-delà duquel un thème du fonds peut recevoir des sous-thèmes.
# seuil_sous_theme = 40
# profondeur_max = 3
# Les noms des PDF suivent le modèle réglé dans Zotero (Réglages › Général › Renommage des fichiers).
# Mot qui joint deux auteurs dans ces noms. S'il reste vide, déduit des noms existants, sinon de la langue de Zotero.
# conjonction = "et"
# Clés de citation. Better BibTeX {bbt}.
{cles}

[ecriture]
# Nombre de groupes appliqués à l'essai avant l'application complète d'un plan.
# essai = 5

[sauvegarde]
# Dossier des sauvegardes, par défaut à côté du dossier Zotero (même disque, hors iCloud ou OneDrive).
# dossier = "~/Zotero-sauvegardes"
# Âge maximal, en heures, d'une sauvegarde pour autoriser une application complète.
# delai_heures = 24
# conserver = 2

[confidentialite]
# Fiches jamais transmises à l'agent ni cherchées par leur titre chez Crossref ou OpenAlex.
# tags_exclus = ["_privé"]
# collections_exclues = []

[sources]
# Adresse électronique de l'utilisateur de la bibliothèque, transmise seulement à Crossref et OpenAlex, qui
# répondent plus vite aux requêtes identifiées (étape 3). Facultative, laisser "" pour s'en passer.
contact = "{contact}"
# crossref = true
# openalex = true
# Livres : BnF, Sudoc et Open Library.
# bnf = true
# sudoc = true
# openlibrary = true
# Recherches OpenAlex par jour, avec la clé OPENALEX_API_KEY du fichier .env.
# plafond_openalex = 900

[metadonnees]
# Champs complétés quand ils sont vides. Ajouter "abstractNote" pour les résumés.
# champs = ["DOI", "ISBN", "ISSN", "date", "publicationTitle", "bookTitle", "proceedingsTitle", "volume", "issue", "pages", "publisher", "place", "language", "creators"]
# Champs jamais complétés pour un type (l'éditeur commercial d'une revue n'est pas utile).
# exclus_par_type = {{ journalArticle = ["publisher", "place"] }}
# seuil_sur = 0.95

[tags]
# Étape 6. Un tag automatique porté par au moins tant de fiches est proposé comme exception à leur suppression.
# seuil_candidat = 5
# Au-delà de tant de tags manuels rares sur une fiche, ce sont sans doute des mots-clés importés.
# seuil_mots_cles = 8
# Nombre de thèmes du fonds sur lesquels un tag doit se répartir pour devenir un concept.
# dispersion_concept = 2
# Tags à ne jamais changer, en plus des tags techniques, des états, des marques et des tags colorés.
# proteges = []
"""


@dataclass
class InfoCle:
    utilisateur: int
    nom: str
    lecture: bool
    ecriture: bool
    notes: bool


class CleRefusee(Exception):
    pass


def verifier_cle(cle: str) -> InfoCle:
    """Interroge l'API web sur la clé elle-même (identifiant du compte et droits)."""
    req = urllib.request.Request(f'{API}/keys/current', headers={'Zotero-API-Key': cle, 'Zotero-API-Version': '3',
                                                                'User-Agent': 'zot-clean'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise CleRefusee('Clé refusée par Zotero (invalide ou révoquée).' if e.code in (403, 404)
                         else f'Réponse inattendue de Zotero ({e.code}).') from None
    droits = d.get('access', {}).get('user', {})
    return InfoCle(int(d['userID']), d.get('username', ''), bool(droits.get('library')), bool(droits.get('write')),
                   bool(droits.get('notes')))


def droits_manquants(info: InfoCle) -> list[str]:
    return [d for d, ok in (('accès à la bibliothèque', info.lecture), ('accès aux notes', info.notes),
                            ("droit d'écriture", info.ecriture)) if not ok]


def cle_enregistree_valide(dossier: Path, afficher) -> bool:
    """Revérifie la clé de `.env`. Une clé refusée ou privée d'un droit est à remplacer, une clé que Zotero,
    injoignable, n'a pas pu vérifier est gardée."""
    cle = lire_env(dossier).get('ZOTERO_API_KEY')
    if not cle:
        return False
    try:
        info = verifier_cle(cle)
    except CleRefusee as e:
        afficher(f'{e} La clé enregistrée dans .env est à remplacer.')
        return False
    except urllib.error.URLError:
        afficher('Clé API déjà enregistrée dans .env, non vérifiée (Zotero injoignable).')
        return True
    if manques := droits_manquants(info):
        afficher(f"La clé enregistrée dans .env n'a plus {', '.join(manques)}. Elle est à remplacer.")
        return False
    afficher(f'Clé API déjà enregistrée dans .env, vérifiée pour le compte {info.nom} ({info.utilisateur}).')
    return True


def ecrire_config(dossier: Path, dossier_zotero: Path, avec_bbt: bool, contact: str = '') -> bool:
    chemin = dossier / CONFIG
    if chemin.exists():
        return False
    texte = MODELE_CONFIG.format(
        contact=contact.replace('"', ''),
        dossier=str(dossier_zotero).replace('\\', '/'),
        bbt='détecté' if avec_bbt else 'non détecté',
        cles='# cles_citation = true' if avec_bbt else 'cles_citation = false')
    chemin.write_text(texte, encoding='utf-8')
    return True


def ecrire_env(dossier: Path, **nouvelles: str) -> None:
    valeurs = dict(lire_env(dossier), **nouvelles)
    chemin = dossier / '.env'
    chemin.write_text(''.join(f'{k}={v}\n' for k, v in valeurs.items()), encoding='utf-8')
    if os.name == 'posix':
        chemin.chmod(0o600)


# `.agents/skills/` est lu par Codex, Cursor, Gemini CLI et d'autres, Claude Code ne lit que `.claude/skills/` (D44).
DOSSIERS_SKILLS = ('.agents', '.claude')
# Guide pas à pas et méthode par défaut, pour l'utilisateur, copiés dans le dossier de travail comme AGENTS.md.
DOCUMENTS = ('guide.md', 'methode.md')


def ecrire_skills(dossier: Path, maj: bool) -> list[str]:
    """Skills livrés avec le paquet, copiés à l'identique dans chaque dossier de skills."""
    ecrits = []
    for skill in files('zot_clean').joinpath('modeles/skills').iterdir():
        if not skill.is_dir():
            continue
        for racine in DOSSIERS_SKILLS:
            cible = dossier / racine / 'skills' / skill.name
            if cible.exists() and not maj:
                continue
            cible.mkdir(parents=True, exist_ok=True)
            for f in skill.iterdir():
                if f.is_file():
                    (cible / f.name).write_text(f.read_text(encoding='utf-8'), encoding='utf-8')
            ecrits.append(f'{racine}/skills/{skill.name}/')
    return ecrits


def ecrire_fichiers_fixes(dossier: Path, maj: bool = False) -> list[str]:
    ecrits = []
    agents = dossier / 'AGENTS.md'
    if maj or not agents.exists():
        agents.write_text(files('zot_clean').joinpath('modeles/AGENTS.md').read_text(encoding='utf-8'),
                          encoding='utf-8')
        ecrits.append('AGENTS.md')
    for nom in DOCUMENTS:
        cible = dossier / nom
        if maj or not cible.exists():
            cible.write_text(files('zot_clean').joinpath(f'modeles/{nom}').read_text(encoding='utf-8'), encoding='utf-8')
            ecrits.append(nom)
    ecrits += ecrire_skills(dossier, maj)
    gitignore = dossier / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE, encoding='utf-8')
        ecrits.append('.gitignore')
    for sous in ('rapports', 'journal', 'plans', 'suivi'):
        if not (dossier / sous).exists():
            (dossier / sous).mkdir()
            ecrits.append(sous + '/')
    return ecrits


def claude_md_concurrents(dossier: Path) -> list[Path]:
    """Fichiers qui empêchent Claude Code de lire `AGENTS.md` (D10, D44).

    Claude Code ignore `AGENTS.md` dès qu'un `CLAUDE.md`, `.claude/CLAUDE.md` ou `CLAUDE.local.md` se trouve dans
    le dossier ou au-dessus, sauf le fichier personnel `~/.claude/CLAUDE.md`. Un `CLAUDE.md` du dossier de travail
    qui importe `@AGENTS.md` règle la question."""
    local = dossier / 'CLAUDE.md'
    if local.is_file() and '@AGENTS.md' in local.read_text(encoding='utf-8', errors='replace'):
        return []
    personnel = Path.home() / '.claude' / 'CLAUDE.md'
    trouves = []
    for d in (dossier, *dossier.parents):
        for f in (d / 'CLAUDE.md', d / '.claude' / 'CLAUDE.md', d / 'CLAUDE.local.md'):
            if f.is_file() and f != personnel:
                trouves.append(f)
    return trouves


def avertir_claude_md(dossier: Path, afficher) -> None:
    trouves = claude_md_concurrents(dossier)
    if trouves:
        afficher(f"\nAttention, pour Claude Code. Ce dossier est sous {', '.join(str(f) for f in trouves)}. Claude Code "
                 "lit alors ce fichier à la place de AGENTS.md, et n'aura pas les consignes de zot-clean. Pour y "
                 f"remédier, ajouter la ligne @AGENTS.md dans {dossier / 'CLAUDE.md'} (le créer au besoin), ou "
                 "déplacer le dossier de travail. Les autres agents (Codex, Cursor…) ne sont pas concernés.")


def initialiser(dossier: Path, dossier_zotero: Path | None, maj: bool, demander, demander_secret, afficher) -> int:
    if maj and not (dossier / CONFIG).is_file():
        # Garde-fou : --maj remplace AGENTS.md sans demander, il ne doit toucher qu'un dossier de travail.
        afficher(f"{dossier} n'est pas un dossier de travail zot-clean (pas de {CONFIG}). Rien n'a été écrit. "
                 "Lancer `zc init --maj` dans le dossier de travail, ou `zc init` pour en créer un.")
        return 1
    dossier.mkdir(parents=True, exist_ok=True)
    if maj:
        ecrits = ecrire_fichiers_fixes(dossier, maj=True)
        afficher(f"Mis à jour : {', '.join(ecrits)}.")
        avertir_claude_md(dossier, afficher)
        return 0

    dossier_zotero = dossier_zotero or Path.home() / 'Zotero'
    while not (dossier_zotero / 'zotero.sqlite').is_file():
        reponse = demander(f"Base Zotero introuvable dans {dossier_zotero}. Dossier de données de Zotero "
                           "(Zotero › Réglages › Avancé › Fichiers et dossiers), ou Entrée pour abandonner : ").strip()
        if not reponse:
            return 1
        dossier_zotero = Path(reponse).expanduser()
    afficher(f'Base Zotero trouvée dans {dossier_zotero}.')
    etat_bbt = bbt.detecter(dossier_zotero)
    afficher(bbt.decrire(etat_bbt) + ('' if etat_bbt.present else ' Le contrôle des clés de citation sera désactivé.'))

    if not cle_enregistree_valide(dossier, afficher):
        afficher(f"\nzot-clean écrit dans Zotero par l'API web, avec une clé personnelle. Pour la créer, ouvrir\n"
                 f"  {PAGE_CLES}\ncocher « Allow library access », « Allow notes access » et « Allow write access »,\n"
                 "enregistrer, puis coller la clé ici (elle ne s'affiche pas pendant la saisie).")
        while True:
            cle = demander_secret('Clé API (Entrée pour passer cette étape) : ').strip()
            if not cle:
                afficher("Étape passée. L'audit fonctionne sans clé, relancer `zc init` avant tout nettoyage.")
                break
            try:
                info = verifier_cle(cle)
            except (CleRefusee, urllib.error.URLError) as e:
                afficher(f'{e} Réessayer.')
                continue
            if manques := droits_manquants(info):
                afficher(f"Clé valide mais sans {', '.join(manques)}. Modifier la clé sur zotero.org, puis la recoller.")
                continue
            ecrire_env(dossier, ZOTERO_API_KEY=cle, ZOTERO_USER_ID=str(info.utilisateur))
            afficher(f'Clé vérifiée pour le compte {info.nom} ({info.utilisateur}), enregistrée dans .env.')
            break

    if not lire_env(dossier).get('OPENALEX_API_KEY'):
        afficher("\nOpenAlex complète Crossref pour trouver les DOI manquants. Ses recherches demandent une clé "
                 "gratuite (https://openalex.org, compte puis « API key »). Sans elle, zot-clean n'utilise OpenAlex "
                 "que pour lire les DOI déjà connus.")
        cle_oa = demander_secret('Clé OpenAlex (Entrée pour passer) : ').strip()
        if cle_oa:
            ecrire_env(dossier, OPENALEX_API_KEY=cle_oa)
            afficher('Clé OpenAlex enregistrée dans .env.')

    contact = ''
    if not (dossier / CONFIG).exists():
        contact = demander("\nAdresse électronique de contact pour Crossref et OpenAlex, qui répondent mieux aux "
                           "requêtes identifiées (facultatif, Entrée pour passer) : ").strip()
    if ecrire_config(dossier, dossier_zotero, etat_bbt.present, contact):
        afficher('config.toml écrit, avec la méthode par défaut (modifiable).')
    else:
        afficher('config.toml existe déjà, conservé tel quel.')
    ecrits = ecrire_fichiers_fixes(dossier)
    if ecrits:
        afficher(f"Créés : {', '.join(ecrits)}.")
    avertir_claude_md(dossier, afficher)
    afficher(f'\nDossier de travail prêt : {dossier}\nÉtape suivante, `zc audit` dans ce dossier.')
    return 0
