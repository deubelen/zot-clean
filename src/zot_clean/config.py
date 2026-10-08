"""Configuration of the working folder (`config.toml`, D10).

Every convention of the default method (D19 to D25) goes through here. A missing or
partial `config.toml` is completed with the default values, whose names follow the
language of the library (`PROFILES`, D227).

The sections and keys of `config.toml` form a frozen protocol, which the `KEYS`
table explicitly links to the Python attributes (D209). Renaming the code
therefore changes neither the accepted keys nor their meaning.
"""

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from zot_clean import lang
from zot_clean.lang import L

FILE = 'config.toml'


@dataclass
class Method:
    inbox: str = 'Inbox'
    projects: list[str] = field(default_factory=lambda: ['Projets'])  # several roots possible (D108)
    subjects: str = 'Fonds'
    archives: str = 'Archives'
    statuses: list[str] = field(default_factory=lambda: ['1 à lire', '2 en cours', '3 lu'])
    other_tags: list[str] = field(default_factory=lambda: ['★ essentiel', 'papier'])
    # Colors of the states, then of the other tags, in order, taken from the Zotero palette (D175). A colored tag
    # gets the key of its rank (1 to 9), e.g. « 1 à lire » on key 1. Empty list, no color offered.
    colors: list[str] = field(default_factory=lambda: ['#FF6666', '#FF8C19', '#5FB236', '#FFD400', '#A28AE5'])
    concept_prefix: str = '#'
    technical_prefix: str = '_'
    subtheme_threshold: int = 40
    max_depth: int = 3
    # Word that joins two authors in file names (« et », « and »), depending on the Zotero language. Empty,
    # deduced from the names Zotero has already given (D150). The name template is set in Zotero (D148).
    conjunction: str = ''
    use_citation_keys: bool = True
    # Language of the library, `fr` or `en` (D208, D221): conventions, reports and messages. Absent, French (D214).
    language: str = 'fr'

    @property
    def roots(self) -> list[str]:
        return [n for n in (self.inbox, *self.projects, self.subjects, self.archives) if n]


@dataclass
class Writing:
    # Number of groups of a plan applied as a trial, before the full application (D35).
    trial: int = 5
    # A management plan (Inbox sorting) that touches fewer items is applied without a trial or a recent
    # backup (D136, D138). 0 to keep the trial and the backup everywhere.
    small_management_plan: int = 50


@dataclass
class Backup:
    # By default, next to the Zotero folder (D41).
    folder: Path | None = None
    delay_hours: float = 24
    keep: int = 2


@dataclass
class Privacy:
    # Items never sent to the agent nor searched by title at the metadata services (D18, D65, D66).
    excluded_tags: list[str] = field(default_factory=lambda: ['_privé'])
    excluded_collections: list[str] = field(default_factory=list)  # path (« Fonds/Privé ») or name alone
    exclude_notes: bool = False  # no effect, still accepted. The text of notes is never shown (D191)
    exclude_full_text: bool = False


@dataclass
class Sources:
    contact: str = ''  # address sent to Crossref and OpenAlex (D17, D63)
    crossref: bool = True
    openalex: bool = True
    bnf: bool = True
    sudoc: bool = True
    openlibrary: bool = True
    rate: float = 3.0  # requests per second and per service
    openalex_cap: int = 900  # searches per day, a free key covers about 1,000 (D74)


@dataclass
class Metadata:
    # Fields filled in when they are empty (D61). Add "abstractNote" for abstracts.
    fields: list[str] = field(default_factory=lambda: [
        'DOI', 'ISBN', 'ISSN', 'date', 'publicationTitle', 'bookTitle', 'proceedingsTitle', 'volume', 'issue',
        'pages', 'publisher', 'place', 'language', 'creators', 'numPages', 'edition', 'series', 'seriesNumber'])
    # Fields never filled in for a type, such as the commercial publisher of a journal (D76).
    excluded_by_type: dict[str, list[str]] = field(default_factory=lambda: {'journalArticle': ['publisher', 'place']})
    certain_threshold: float = 0.95  # title similarity for a certain match (D62)
    mismatch_threshold: float = 0.8  # below this, a DOI designates another publication (D69)
    year_gap: int = 1


@dataclass
class Tags:
    # Step 6 (D151 to D156). An automatic tag carried by at least `seuil_candidat` items is proposed as an
    # exception to the rule that deletes them (D152).
    candidate_threshold: int = 5
    # An item carrying more than `seuil_mots_cles` manual tags outside the families, almost all rare, probably
    # comes from an import, its tags are publisher keywords (D153).
    keywords_threshold: int = 8
    # Number of themes of the fonds over which a tag must be spread to be proposed as a concept (D154).
    concept_dispersion: int = 2
    # Tags never proposed for change, besides the technical tags, the states, the marks and the colored tags.
    protected: list[str] = field(default_factory=list)


@dataclass
class Config:
    workspace: Path
    zotero_dir: Path = field(default_factory=lambda: Path.home() / 'Zotero')
    method: Method = field(default_factory=Method)
    writing: Writing = field(default_factory=Writing)
    backup: Backup = field(default_factory=Backup)
    privacy: Privacy = field(default_factory=Privacy)
    sources: Sources = field(default_factory=Sources)
    metadata: Metadata = field(default_factory=Metadata)
    tags: Tags = field(default_factory=Tags)

    @property
    def database(self) -> Path:
        return self.zotero_dir / 'zotero.sqlite'

    @property
    def reports(self) -> Path:
        return self.workspace / 'rapports'

    @property
    def plans(self) -> Path:
        return self.workspace / 'plans'

    @property
    def journal(self) -> Path:
        return self.workspace / 'journal'

    @property
    def tracking(self) -> Path:
        return self.workspace / 'suivi'

    @property
    def cache(self) -> Path:
        return self.workspace / 'cache'

    @property
    def backups(self) -> Path:
        z = self.zotero_dir
        return self.backup.folder or z.parent / f'{z.name}-sauvegardes'


# Names of the default method in each language of the library (D227). Roles, colors, thresholds and protections are
# shared, only the names change. A key absent from config.toml takes the name of the library's language; the class
# defaults above are the French profile, that of a folder without a declared language (D214).
PROFILES = {
    'fr': {
        'methode': {'inbox': 'Inbox', 'projets': ['Projets'], 'fonds': 'Fonds', 'archives': 'Archives',
                    'etats': ['1 à lire', '2 en cours', '3 lu'], 'autres_tags': ['★ essentiel', 'papier']},
        'confidentialite': {'tags_exclus': ['_privé']},
    },
    'en': {
        'methode': {'inbox': 'Inbox', 'projets': ['Projects'], 'fonds': 'Subjects', 'archives': 'Archives',
                    'etats': ['1 to read', '2 reading', '3 read'], 'autres_tags': ['★ essential', 'printed']},
        'confidentialite': {'tags_exclus': ['_private']},
    },
}


def is_workspace(folder: Path) -> bool:
    """Does `folder` contain a zot-clean `config.toml`? The file must be readable and have a [zotero] section,
    which `zc init` always writes. A `config.toml` from other software is not taken for `zc`'s."""
    try:
        raw = tomllib.loads((folder / FILE).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    return isinstance(raw.get('zotero'), dict)


def find_workspace(start_dir: Path | None = None) -> Path | None:
    """First zot-clean working folder, going up from `start_dir`. Foreign `config.toml` files are skipped."""
    start_dir = (start_dir or Path.cwd()).resolve()
    for d in (start_dir, *start_dir.parents):
        if is_workspace(d):
            return d
    return None


def load(folder: Path | None = None) -> Config:
    """Configuration of the designated working folder (`--workspace`), which must contain a `config.toml`, or failing
    that of the first one found going up from the current folder. Outside a working folder, the command is refused,
    rather than creating `rapports/` or `suivi/` anywhere."""
    if folder is None:
        folder = find_workspace()
        if folder is None:
            here = Path.cwd()
            foreign = L(en=f' The {FILE} of this folder is not recognized, as it has no [zotero] section (the one '
                           '`zc init` writes, with the line dossier = …).',
                        fr=f" Le {FILE} de ce dossier n'est pas reconnu, faute de section [zotero] (celle qu'écrit "
                           "`zc init`, avec la ligne dossier = …).") if (here / FILE).is_file() else ''
            raise SystemExit(L(en=f'No zot-clean working folder here ({here}) nor in the folders above.{foreign} Go to '
                                  f'the folder created by `zc init` (the one that contains {FILE}) or designate it '
                                  'with --workspace. To create one, run `zc init`.',
                               fr=f"Aucun dossier de travail de zot-clean ici ({here}) ni dans les dossiers au-dessus."
                                  f"{foreign} Se placer dans le dossier créé par `zc init` (celui qui contient "
                                  f"{FILE}) ou le désigner par --workspace. Pour en créer un, lancer `zc init`."))
    elif not (folder / FILE).is_file():
        raise SystemExit(L(en=f'{folder} is not a zot-clean working folder (no {FILE}). Designate the folder created '
                              'by `zc init`, or create one with `zc init`.',
                           fr=f"{folder} n'est pas un dossier de travail de zot-clean (aucun {FILE}). Désigner le "
                              "dossier créé par `zc init`, ou en créer un avec `zc init`."))
    path = folder / FILE
    try:
        raw = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path} unreadable ({e}). Correct the file, for example a forgotten quotation mark.',
                           fr=f'{path} illisible ({e}). Corriger le fichier, par exemple un guillemet oublié.')) from None
    cfg = Config(workspace=folder)
    if d := raw.get('zotero', {}).get('dossier'):
        cfg.zotero_dir = Path(d).expanduser()
    method = raw.get('methode', {})
    language = method.get('langue', lang.DEFAULT) if isinstance(method, dict) else lang.DEFAULT
    if language not in lang.LANGUAGES:
        raise SystemExit(L(en=f'{path}: [methode] langue must be "fr" or "en", not {language!r}.',
                           fr=f'{path} : [methode] langue vaut "fr" ou "en", et non {language!r}.'))
    for name, (attribute, cls, _) in KEYS.items():
        setattr(cfg, attribute, _section(raw, name, cls, path, PROFILES[language].get(name, {})))
    if isinstance(cfg.method.projects, str):  # a single root, written as before D108
        cfg.method.projects = [cfg.method.projects] if cfg.method.projects else []
    if cfg.backup.folder:
        cfg.backup.folder = Path(cfg.backup.folder).expanduser()
    if not isinstance(cfg.backup.keep, int) or cfg.backup.keep < 1:
        # At 0, the backup just made would be deleted immediately.
        raise SystemExit(L(en=f'{path}: [sauvegarde] conserver must be at least 1 (number of backups kept), not '
                              f'{cfg.backup.keep!r}.',
                           fr=f'{path} : [sauvegarde] conserver doit valoir au moins 1 (nombre de sauvegardes '
                              f'gardées), et non {cfg.backup.keep!r}.'))
    return cfg


# Section of config.toml -> (attribute of Config, class, key -> attribute of the class), in file order.
# The keys stay those of version 0.3.2, whatever the names in the code (D209).
KEYS = {
    'methode': ('method', Method, {
        'inbox': 'inbox', 'projets': 'projects', 'fonds': 'subjects', 'archives': 'archives', 'etats': 'statuses',
        'autres_tags': 'other_tags', 'couleurs': 'colors', 'prefixe_concept': 'concept_prefix',
        'prefixe_technique': 'technical_prefix', 'seuil_sous_theme': 'subtheme_threshold',
        'profondeur_max': 'max_depth', 'conjonction': 'conjunction', 'cles_citation': 'use_citation_keys',
        'langue': 'language'}),
    'ecriture': ('writing', Writing, {'essai': 'trial', 'petit_plan_de_gestion': 'small_management_plan'}),
    'sauvegarde': ('backup', Backup, {'dossier': 'folder', 'delai_heures': 'delay_hours',
                                              'conserver': 'keep'}),
    'confidentialite': ('privacy', Privacy, {
        'tags_exclus': 'excluded_tags', 'collections_exclues': 'excluded_collections', 'exclure_notes': 'exclude_notes',
        'exclure_texte_integral': 'exclude_full_text'}),
    'sources': ('sources', Sources, {
        'contact': 'contact', 'crossref': 'crossref', 'openalex': 'openalex', 'bnf': 'bnf', 'sudoc': 'sudoc',
        'openlibrary': 'openlibrary', 'debit': 'rate', 'plafond_openalex': 'openalex_cap'}),
    'metadonnees': ('metadata', Metadata, {
        'champs': 'fields', 'exclus_par_type': 'excluded_by_type', 'seuil_sur': 'certain_threshold',
        'seuil_discordance': 'mismatch_threshold', 'ecart_annees': 'year_gap'}),
    'tags': ('tags', Tags, {'seuil_candidat': 'candidate_threshold', 'seuil_mots_cles': 'keywords_threshold',
                            'dispersion_concept': 'concept_dispersion', 'proteges': 'protected'}),
}

# Keys removed, ignored without error in an old config.toml.
OBSOLETE = {'methode': {'modele_fichier'}}  # D148: the name template is read in Zotero


def _section(raw: dict, name: str, cls, path: Path, profile: dict):
    keys = KEYS[name][2]
    values = {k: v for k, v in raw.get(name, {}).items() if k not in OBSOLETE.get(name, set())}
    unknowns = set(values) - set(keys)
    if unknowns:
        raise SystemExit(L(en=f"{path}: unknown keys in [{name}]: {', '.join(sorted(unknowns))}",
                           fr=f"{path} : clés inconnues dans [{name}] : {', '.join(sorted(unknowns))}"))
    return cls(**{keys[k]: v for k, v in (copy.deepcopy(profile) | values).items()})


def to_stored(cfg: Config) -> dict:
    """Effective configuration, defaults included, under the sections and keys of config.toml."""
    def raw(v):
        return v.as_posix() if isinstance(v, Path) else v
    res = {'zotero': {'dossier': cfg.zotero_dir.as_posix()}}
    for name, (attribute, _, keys) in KEYS.items():
        section = getattr(cfg, attribute)
        res[name] = {key: raw(getattr(section, a)) for key, a in keys.items()}
    return res


def read_env(folder: Path) -> dict[str, str]:
    """API key and account identifier, in the `.env` of the working folder (D13)."""
    path = folder / '.env'
    if not path.exists():
        return {}
    return dict(l.strip().split('=', 1) for l in path.read_text(encoding='utf-8').splitlines() if '=' in l)
