"""Creation of a working folder (`zc init`, D10, D13).

Writes `config.toml` (Zotero folder, Better BibTeX detected), `.env` (API key
checked by the web API, never displayed, rechecked at every rerun and
asked for again if Zotero refuses it or if it is not the key of the account that Zotero
syncs on this computer), `.gitignore`, `AGENTS.md` and the
skills (`.agents/skills/` and `.claude/skills/`), and creates `rapports/`, `journal/`, `plans/` and
`suivi/`. Existing files are not overwritten, except `AGENTS.md` and the
skills with `--update`. The language of the library is chosen for a new folder
(`--library-language`, or a question in a terminal) and never changes (D214, D221).
"""

import http.client
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from zot_clean import apply, bbt, config, lang, reader
from zot_clean.config import FILE as CONFIG, read_env
from zot_clean.api import Refusal
from zot_clean.lang import L

KEYS_PAGE = 'https://www.zotero.org/settings/keys/new'
API = 'https://api.zotero.org'
GITIGNORE = '.env\ncache/\n'

def config_template() -> str:
    """Text of the `config.toml` written by `zc init`, its comments in the language of the library. Sections, keys
    and values stay those of version 0.3.2 in both languages (D209, D221)."""
    return L(en="""\
# Configuration of zot-clean for this library.
# The names of the root collections and of the tags are written out below. The other settings of [methode] have a
# default value, uncomment one to change it.
# The reasons for the default method are explained in method.md, next to this file.

[zotero]
dossier = "{dossier}"

[methode]
# Language of the library (fr or en): conventions, reports and messages. Set when the folder is created.
langue = "{langue}"
# Root collections. Leave empty ("") to do without one.
inbox = {inbox}
# Roots of the projects, one or several, for example ["Courses", "Papers"]. Empty list to do without.
projets = {projets}
fonds = {fonds}
archives = {archives}
# Reading statuses, then the other tags (marks).
etats = {etats}
autres_tags = {autres_tags}
# Colors of the statuses then of the other tags, in order. A colored tag gets the key of its rank (1 to 9).
# couleurs = ["#FF6666", "#FF8C19", "#5FB236", "#FFD400", "#A28AE5"]
# prefixe_concept = "#"
# prefixe_technique = "_"
# Number of items beyond which a theme of the subjects can get subthemes.
# seuil_sous_theme = 40
# profondeur_max = 3
# PDF names follow the template set in Zotero (Settings › General › File Renaming).
# Word that joins two authors in these names. If left empty, deduced from the existing names, otherwise from the
# language of Zotero.
# conjonction = "et"
# Citation keys. Better BibTeX {bbt}.
{cles}

[ecriture]
# Number of groups applied as a trial before the full application of a plan.
# essai = 5

[sauvegarde]
# Folder of the backups, by default next to the Zotero folder (same disk, outside iCloud or OneDrive).
# dossier = "~/Zotero-sauvegardes"
# Maximum age, in hours, of a backup to allow a full application.
# delai_heures = 24
# Number of backups kept, the most recent ones (at least 1).
# conserver = 2

[confidentialite]
# Items never sent to the agent nor looked up by their title at Crossref or OpenAlex.
tags_exclus = {tags_exclus}
# collections_exclues = []

[sources]
# Email address of the user of the library, sent only to Crossref and OpenAlex, which answer identified requests
# faster (step 3). Optional, leave "" to do without.
contact = "{contact}"
# crossref = true
# openalex = true
# Books: BnF, Sudoc and Open Library.
# bnf = true
# sudoc = true
# openlibrary = true
# OpenAlex searches per day, with the OPENALEX_API_KEY key of the .env file.
# plafond_openalex = 900

[metadonnees]
# Fields filled in when they are empty. Add "abstractNote" for the abstracts.
# champs = ["DOI", "ISBN", "ISSN", "date", "publicationTitle", "bookTitle", "proceedingsTitle", "volume", "issue", "pages", "publisher", "place", "language", "creators"]
# Fields never filled in for a type (the commercial publisher of a journal is not useful).
# exclus_par_type = {{ journalArticle = ["publisher", "place"] }}
# seuil_sur = 0.95

[tags]
# Step 6. An automatic tag carried by at least this many items is proposed as an exception to their deletion.
# seuil_candidat = 5
# Beyond this many rare manual tags on an item, they are probably imported keywords.
# seuil_mots_cles = 8
# Number of themes of the subjects over which a tag must be spread to become a concept.
# dispersion_concept = 2
# Tags never to change, besides the technical tags, the statuses, the marks and the colored tags.
# proteges = []
""", fr="""\
# Configuration de zot-clean pour cette bibliothèque.
# Les noms des collections racines et des tags sont écrits en clair ci-dessous. Les autres réglages de [methode] ont
# une valeur par défaut, décommenter pour en changer une.
# Les raisons de la méthode par défaut sont expliquées dans methode.md, à côté de ce fichier.

[zotero]
dossier = "{dossier}"

[methode]
# Langue de la bibliothèque (fr ou en), pour les conventions, les rapports et les messages. Fixée à la création du dossier.
langue = "{langue}"
# Collections racines. Laisser vide ("") pour s'en passer.
inbox = {inbox}
# Racines des projets, une ou plusieurs, par exemple ["Cours", "Articles"]. Liste vide pour s'en passer.
projets = {projets}
fonds = {fonds}
archives = {archives}
# États de lecture, puis les autres tags (marques).
etats = {etats}
autres_tags = {autres_tags}
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
# Nombre de sauvegardes gardées, les plus récentes (au moins 1).
# conserver = 2

[confidentialite]
# Fiches jamais transmises à l'agent ni cherchées par leur titre chez Crossref ou OpenAlex.
tags_exclus = {tags_exclus}
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
""")


@dataclass
class KeyInfo:
    user: int
    name: str
    reading: bool
    writing: bool
    notes: bool


class KeyRejected(Exception):
    pass


class ZoteroUnreachable(urllib.error.URLError):
    """Network down, timeout or unreadable response. Subclass of `URLError`, which callers already treat
    as « Zotero injoignable », with a message in the language of the library."""

    def __str__(self):
        return L(en=f'Zotero unreachable ({self.reason}).', fr=f'Zotero injoignable ({self.reason}).')


def check_key(key: str) -> KeyInfo:
    """Queries the web API about the key itself (account identifier and rights)."""
    req = urllib.request.Request(f'{API}/keys/current', headers={'Zotero-API-Key': key, 'Zotero-API-Version': '3',
                                                                'User-Agent': 'zot-clean'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise KeyRejected(L(en='Key refused by Zotero (invalid or revoked).',
                            fr='Clé refusée par Zotero (invalide ou révoquée).') if e.code in (403, 404)
                          else L(en=f'Unexpected answer from Zotero ({e.code}).',
                                 fr=f'Réponse inattendue de Zotero ({e.code}).')) from None
    except TimeoutError:  # while reading the response, outside `URLError`
        raise ZoteroUnreachable(L(en='20-second timeout exceeded', fr='délai de 20 secondes dépassé')) from None
    except urllib.error.URLError as e:
        raise ZoteroUnreachable(e.reason) from None
    except (OSError, http.client.HTTPException, ValueError) as e:  # connection dropped, response truncated or unreadable
        raise ZoteroUnreachable(L(en=f'answer interrupted or unreadable, {type(e).__name__}',
                                  fr=f'réponse interrompue ou illisible, {type(e).__name__}')) from None
    rights = d.get('access', {}).get('user', {})
    return KeyInfo(int(d['userID']), d.get('username', ''), bool(rights.get('library')), bool(rights.get('write')),
                   bool(rights.get('notes')))


def missing_rights(info: KeyInfo) -> list[str]:
    return [d for d, ok in ((L(en='library access', fr='accès à la bibliothèque'), info.reading),
                            (L(en='notes access', fr='accès aux notes'), info.notes),
                            (L(en='write access', fr="droit d'écriture"), info.writing)) if not ok]


def key_matches_account(user: int, account: reader.Account | None, show, remedy: str) -> bool:
    """Is the key of the account `user` that of the account the database syncs? If not, the refusal of the base
    layer (`apply.check_account`) is shown, with `remedy`. `account` None: no database to compare."""
    try:
        if account is not None:
            apply.check_account(user, account, remedy)
        return True
    except Refusal as e:
        show(str(e))
        return False


def saved_key_valid(folder: Path, show, account: reader.Account | None = None) -> bool:
    """Rechecks the key of `.env`. A key that is refused, lacks a right or belongs to another account than the one
    Zotero syncs (`account`) must be replaced. A key that could not be checked because Zotero was unreachable is
    kept, if the account noted with it is the right one."""
    env = read_env(folder)
    if not (key := env.get('ZOTERO_API_KEY')):
        return False
    remedy = L(en='It must be replaced by a key created while logged in on zotero.org to the account {compte}.',
               fr='Elle est à remplacer par une clé créée en étant connecté sur zotero.org au compte {compte}.')
    try:
        info = check_key(key)
    except KeyRejected as e:
        show(L(en=f'{e} The key saved in .env must be replaced.', fr=f'{e} La clé enregistrée dans .env est à remplacer.'))
        return False
    except urllib.error.URLError:
        if (n := env.get('ZOTERO_USER_ID', '')).isdigit() and not key_matches_account(int(n), account, show, remedy):
            return False
        show(L(en='API key already saved in .env, not checked (Zotero unreachable).',
               fr='Clé API déjà enregistrée dans .env, non vérifiée (Zotero injoignable).'))
        return True
    if gaps := missing_rights(info):
        show(L(en=f"The key saved in .env no longer has {', '.join(gaps)}. It must be replaced.",
               fr=f"La clé enregistrée dans .env n'a plus {', '.join(gaps)}. Elle est à remplacer."))
        return False
    if not key_matches_account(info.user, account, show, remedy):
        return False
    show(L(en=f'API key already saved in .env, checked for the account {info.name} ({info.user}).',
           fr=f'Clé API déjà enregistrée dans .env, vérifiée pour le compte {info.name} ({info.user}).'))
    return True


def write_config(folder: Path, zotero_dir: Path, with_bbt: bool, contact: str = '', language: str = lang.DEFAULT) -> bool:
    path = folder / CONFIG
    if path.exists():
        return False
    # A new folder writes the names of its profile in full rather than depending on the defaults (D227).
    profile = {k: _toml(v) for section in config.PROFILES[language].values() for k, v in section.items()}
    with lang.language(language):
        text = config_template().format(
            contact=contact.replace('"', ''),
            dossier=str(zotero_dir).replace('\\', '/'),
            langue=language,
            bbt=L(en='detected', fr='détecté') if with_bbt else L(en='not detected', fr='non détecté'),
            cles='# cles_citation = true' if with_bbt else 'cles_citation = false',
            **profile)
    path.write_text(text, encoding='utf-8')
    return True


def _toml(value: str | list[str]) -> str:
    """A name or a list of names, written as TOML."""
    if isinstance(value, list):
        return '[' + ', '.join(_toml(v) for v in value) + ']'
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def write_env(folder: Path, **new_ones: str) -> None:
    values = dict(read_env(folder), **new_ones)
    path = folder / '.env'
    path.write_text(''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')
    if os.name == 'posix':
        path.chmod(0o600)


# `.agents/skills/` is read by Codex, Cursor, Gemini CLI and others, Claude Code reads only `.claude/skills/` (D44).
SKILL_FOLDERS = ('.agents', '.claude')
# Step-by-step guide and default method, for the user, copied into the working folder next to AGENTS.md, in the
# language of the library (D216, D229).
DOCUMENTS = {'fr': ('guide.md', 'methode.md'), 'en': ('guide.md', 'method.md')}
# Skills shipped under a name of version 0.3.2, removed by `zc init --update` so that no outdated set stays active
# next to the new one (D230). `inbox` and `tags` kept their name and are simply replaced.
FORMER_SKILLS = ('doublons', 'metadonnees', 'fonds', 'cles', 'noms', 'controle')


def write_skills(folder: Path, update: bool) -> list[str]:
    """Skills shipped with the package, copied identically into each skills folder."""
    writes = []
    for skill in files('zot_clean').joinpath('templates/skills').iterdir():
        if not skill.is_dir():
            continue
        for root in SKILL_FOLDERS:
            target = folder / root / 'skills' / skill.name
            if target.exists() and not update:
                continue
            target.mkdir(parents=True, exist_ok=True)
            for f in skill.iterdir():
                if f.is_file():
                    (target / f.name).write_text(f.read_text(encoding='utf-8'), encoding='utf-8')
            writes.append(f'{root}/skills/{skill.name}/')
    return writes


def remove_former_skills(folder: Path) -> list[str]:
    """Skills of version 0.3.2 left in the working folder. Only the `SKILL.md` that zc wrote is removed, then the
    folder if nothing else is in it."""
    removed = []
    for root in SKILL_FOLDERS:
        for name in FORMER_SKILLS:
            old = folder / root / 'skills' / name
            if (old / 'SKILL.md').is_file():
                (old / 'SKILL.md').unlink()
                if not any(old.iterdir()):
                    old.rmdir()
                removed.append(f'{root}/skills/{name}/')
    return removed


def write_fixed_files(folder: Path, update: bool = False, language: str | None = None) -> list[str]:
    """AGENTS.md, skills, guide and method, `.gitignore` and the subfolders. The guide and the method are those of the
    language of the library, read in `config.toml` unless given."""
    language = language or lang.of_workspace(folder)
    writes = []
    agents = folder / 'AGENTS.md'
    if update or not agents.exists():
        agents.write_text(files('zot_clean').joinpath('templates/AGENTS.md').read_text(encoding='utf-8'),
                          encoding='utf-8')
        writes.append('AGENTS.md')
    for name in DOCUMENTS[language]:
        target = folder / name
        if update or not target.exists():
            target.write_text(files('zot_clean').joinpath(f'templates/{language}/{name}').read_text(encoding='utf-8'),
                              encoding='utf-8')
            writes.append(name)
    writes += write_skills(folder, update)
    gitignore = folder / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE, encoding='utf-8')
        writes.append('.gitignore')
    for under in ('rapports', 'journal', 'plans', 'suivi'):
        if not (folder / under).exists():
            (folder / under).mkdir()
            writes.append(under + '/')
    return writes


def competing_claude_md(folder: Path) -> list[Path]:
    """Files that prevent Claude Code from reading `AGENTS.md` (D10, D44).

    Claude Code ignores `AGENTS.md` as soon as a `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` is in
    the folder or above it, except the personal file `~/.claude/CLAUDE.md`. A `CLAUDE.md` in the working folder
    that imports `@AGENTS.md` settles the matter."""
    local = folder / 'CLAUDE.md'
    if local.is_file() and '@AGENTS.md' in local.read_text(encoding='utf-8', errors='replace'):
        return []
    personal = Path.home() / '.claude' / 'CLAUDE.md'
    found_list = []
    for d in (folder, *folder.parents):
        for f in (d / 'CLAUDE.md', d / '.claude' / 'CLAUDE.md', d / 'CLAUDE.local.md'):
            if f.is_file() and f != personal:
                found_list.append(f)
    return found_list


def warn_claude_md(folder: Path, show) -> None:
    found_list = competing_claude_md(folder)
    if found_list:
        show(L(en=f"\nWarning, for Claude Code. This folder is under {', '.join(str(f) for f in found_list)}. Claude "
                  "Code then reads that file instead of AGENTS.md, and will not have the instructions of zot-clean. To "
                  f"fix it, add the line @AGENTS.md in {folder / 'CLAUDE.md'} (create it if needed), or move the "
                  "working folder. The other agents (Codex, Cursor…) are not concerned.",
               fr=f"\nAttention, pour Claude Code. Ce dossier est sous {', '.join(str(f) for f in found_list)}. Claude "
                  "Code lit alors ce fichier à la place de AGENTS.md, et n'aura pas les consignes de zot-clean. Pour y "
                  f"remédier, ajouter la ligne @AGENTS.md dans {folder / 'CLAUDE.md'} (le créer au besoin), ou "
                  "déplacer le dossier de travail. Les autres agents (Codex, Cursor…) ne sont pas concernés."))


def _language_name(code: str) -> str:
    return {'fr': L(en='French', fr='français'), 'en': L(en='English', fr='anglais')}[code]


def choose_language(folder: Path, requested: str | None, update: bool, ask, show) -> str | None:
    """Language of the library for `zc init` (D221). A working folder keeps its own: a different
    `--library-language` is refused, since nothing converts a library from one language to the other (D214). A new
    folder takes the option, or else the answer to a question asked under a terminal (`ask`); without a terminal
    (`ask` None) the option is required. None when refused, after a message, in English for a new folder (D222)."""
    if (folder / CONFIG).is_file():
        current = lang.of_workspace(folder)
        if requested and requested != current:
            show(L(en=f'{folder} is already a working folder, for a library in {_language_name(current)}. Its language '
                      f'does not change (no conversion), so --library-language {requested} is refused. Run `zc init` '
                      'without --library-language, or create another working folder.',
                   fr=f'{folder} est déjà un dossier de travail, pour une bibliothèque en {_language_name(current)}. Sa '
                      f'langue ne change pas (aucune conversion), --library-language {requested} est donc refusé. '
                      'Relancer `zc init` sans --library-language, ou créer un autre dossier de travail.'))
            return None
        return current
    if update or requested:
        return requested or lang.OUTSIDE  # --update outside a working folder: refused by `initialize`
    if ask is None:
        show(L(en='No interactive terminal to ask for the language of the library. Run `zc init --library-language fr` '
                  '(French) or `zc init --library-language en` (English). It sets the names proposed for the '
                  'classification, the reports and the messages, and does not change afterwards.',
               fr="Pas de terminal interactif pour demander la langue de la bibliothèque. Lancer "
                  "`zc init --library-language fr` (français) ou `zc init --library-language en` (anglais). Elle fixe "
                  "les noms proposés pour le classement, les rapports et les messages, et ne change plus ensuite."))
        return None
    show(L(en='Language of the library, for the names proposed for the classification, the reports and the messages. '
              'It does not change afterwards.',
           fr='Langue de la bibliothèque, pour les noms proposés pour le classement, les rapports et les messages. '
              'Elle ne change plus ensuite.'))
    while True:
        answer = ask(L(en='fr (français) or en (English), Enter to give up: ',
                       fr='fr (français) ou en (English), Entrée pour abandonner : ')).strip().lower()
        if answer in lang.LANGUAGES:
            return answer
        if not answer:
            show(L(en='No language chosen, nothing was written.', fr="Aucune langue choisie, rien n'a été écrit."))
            return None


def initialize(folder: Path, zotero_dir: Path | None, update: bool, ask, ask_secret, show,
               language: str = lang.DEFAULT) -> int:
    """Creates or completes the working folder. `language` is that of the library, chosen beforehand by
    `choose_language` and written in a new `config.toml` only."""
    if update and not (folder / CONFIG).is_file():
        # Safeguard: --update replaces AGENTS.md without asking, it must only touch a working folder.
        show(L(en=f'{folder} is not a zot-clean working folder (no {CONFIG}). Nothing was written. Run '
                  '`zc init --update` in the working folder, or `zc init` to create one.',
               fr=f"{folder} n'est pas un dossier de travail zot-clean (pas de {CONFIG}). Rien n'a été écrit. "
                  "Lancer `zc init --update` dans le dossier de travail, ou `zc init` pour en créer un."))
        return 1
    folder.mkdir(parents=True, exist_ok=True)
    if update:
        writes = write_fixed_files(folder, update=True)
        show(L(en=f"Updated: {', '.join(writes)}.", fr=f"Mis à jour : {', '.join(writes)}."))
        if removed := remove_former_skills(folder):
            show(L(en=f"Removed, skills renamed in version 0.4: {', '.join(removed)}.",
                   fr=f"Retirés, skills renommés en version 0.4 : {', '.join(removed)}."))
        warn_claude_md(folder, show)
        return 0

    zotero_dir = zotero_dir or Path.home() / 'Zotero'
    while not (zotero_dir / 'zotero.sqlite').is_file():
        answer = ask(L(en=f'Zotero database not found in {zotero_dir}. Zotero data folder (Zotero › Settings › '
                          'Advanced › Files and Folders), or Enter to give up: ',
                       fr=f"Base Zotero introuvable dans {zotero_dir}. Dossier de données de Zotero "
                          "(Zotero › Réglages › Avancé › Fichiers et dossiers), ou Entrée pour abandonner : ")).strip()
        if not answer:
            return 1
        zotero_dir = Path(answer).expanduser()
    show(L(en=f'Zotero database found in {zotero_dir}.', fr=f'Base Zotero trouvée dans {zotero_dir}.'))
    bbt_state = bbt.detect(zotero_dir)
    show(bbt.describe(bbt_state) + ('' if bbt_state.present else L(en=' Checking citation keys will be disabled.',
                                                                   fr=' Le contrôle des clés de citation sera désactivé.')))

    # The key must be that of the account Zotero syncs here: the plans are built on that basis.
    try:
        account = reader.synced_account(zotero_dir / 'zotero.sqlite')
    except reader.UnknownSchema as e:
        show(str(e))
        return 1
    name = (L(en=f'“{account.name}” (no. {account.id})', fr=f'« {account.name} » (n° {account.id})') if account.name
            else L(en=f'no. {account.id}', fr=f'n° {account.id}'))
    if account.id is None:
        show(L(en=f'\n{apply.never_synced()} Then run `zc init` again to save the API key. The audit works without a '
                  'key in the meantime, no cleanup command works without it.',
               fr=f"\n{apply.never_synced()} Relancer ensuite `zc init` pour enregistrer la clé API. "
                  "L'audit fonctionne sans clé en attendant, aucune commande de nettoyage ne fonctionne sans elle."))
    elif not saved_key_valid(folder, show, account):
        show(L(en=f'\nzot-clean writes to Zotero through the web API, with a personal key. To create it, log in\n'
                  f'on zotero.org with the account that Zotero syncs on this computer, {name}, open\n'
                  f'  {KEYS_PAGE}\ntick “Allow library access”, “Allow notes access” and “Allow write access”,\n'
                  'save, then paste the key here (it is not shown while you type it).',
               fr=f"\nzot-clean écrit dans Zotero par l'API web, avec une clé personnelle. Pour la créer, se connecter\n"
                  f"sur zotero.org avec le compte que Zotero synchronise sur cet ordinateur, {name}, ouvrir\n"
                  f"  {KEYS_PAGE}\ncocher « Allow library access », « Allow notes access » et « Allow write access »,\n"
                  "enregistrer, puis coller la clé ici (elle ne s'affiche pas pendant la saisie)."))
        while True:
            key = ask_secret(L(en='API key (Enter to skip this step): ',
                               fr='Clé API (Entrée pour passer cette étape) : ')).strip()
            if not key:
                show(L(en='Step skipped. The audit works without a key, run `zc init` again before any cleanup.',
                       fr="Étape passée. L'audit fonctionne sans clé, relancer `zc init` avant tout nettoyage."))
                break
            try:
                info = check_key(key)
            except (KeyRejected, urllib.error.URLError) as e:
                show(L(en=f'{e} Try again.', fr=f'{e} Réessayer.'))
                continue
            if gaps := missing_rights(info):
                show(L(en=f"Valid key but without {', '.join(gaps)}. Change the key on zotero.org, then paste it again.",
                       fr=f"Clé valide mais sans {', '.join(gaps)}. Modifier la clé sur zotero.org, puis la recoller."))
                continue
            if not key_matches_account(info.user, account, show, L(
                    en='Paste a key created while logged in on zotero.org to the account {compte}, or Enter to skip '
                       'this step.',
                    fr='Coller une clé créée en étant connecté sur zotero.org au compte {compte}, ou Entrée pour '
                       'passer cette étape.')):
                continue
            write_env(folder, ZOTERO_API_KEY=key, ZOTERO_USER_ID=str(info.user))
            show(L(en=f'Key checked for the account {info.name} ({info.user}), saved in .env.',
                   fr=f'Clé vérifiée pour le compte {info.name} ({info.user}), enregistrée dans .env.'))
            break

    if not read_env(folder).get('OPENALEX_API_KEY'):
        show(L(en='\nOpenAlex completes Crossref to find the missing DOIs. Its searches need a free key '
                  '(https://openalex.org, account then “API key”). Without it, zot-clean uses OpenAlex only to read '
                  'the DOIs already known.',
               fr="\nOpenAlex complète Crossref pour trouver les DOI manquants. Ses recherches demandent une clé "
                  "gratuite (https://openalex.org, compte puis « API key »). Sans elle, zot-clean n'utilise OpenAlex "
                  "que pour lire les DOI déjà connus."))
        oa_key = ask_secret(L(en='OpenAlex key (Enter to skip): ', fr='Clé OpenAlex (Entrée pour passer) : ')).strip()
        if oa_key:
            write_env(folder, OPENALEX_API_KEY=oa_key)
            show(L(en='OpenAlex key saved in .env.', fr='Clé OpenAlex enregistrée dans .env.'))

    contact = ''
    if not (folder / CONFIG).exists():
        contact = ask(L(en='\nContact email address for Crossref and OpenAlex, which answer identified requests better '
                           '(optional, Enter to skip): ',
                        fr="\nAdresse électronique de contact pour Crossref et OpenAlex, qui répondent mieux aux "
                           "requêtes identifiées (facultatif, Entrée pour passer) : ")).strip()
    if write_config(folder, zotero_dir, bbt_state.present, contact, language):
        show(L(en='config.toml written, with the default method (can be changed).',
               fr='config.toml écrit, avec la méthode par défaut (modifiable).'))
    else:
        show(L(en='config.toml already exists, kept as it is.', fr='config.toml existe déjà, conservé tel quel.'))
    writes = write_fixed_files(folder, language=language)
    if writes:
        show(L(en=f"Created: {', '.join(writes)}.", fr=f"Créés : {', '.join(writes)}."))
    warn_claude_md(folder, show)
    show(L(en=f'\nWorking folder ready: {folder}\nNext step, `zc audit` in this folder.',
           fr=f'\nDossier de travail prêt : {folder}\nÉtape suivante, `zc audit` dans ce dossier.'))
    return 0
