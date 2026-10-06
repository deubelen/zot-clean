"""Configuration du dossier de travail (`config.toml`, D10).

Toute convention de la méthode par défaut (D19 à D25) passe par ici. Un
`config.toml` absent ou partiel est complété par les valeurs par défaut.
"""

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

FICHIER = 'config.toml'


@dataclass
class Methode:
    inbox: str = 'Inbox'
    projets: list[str] = field(default_factory=lambda: ['Projets'])  # plusieurs racines possibles (D108)
    fonds: str = 'Fonds'
    archives: str = 'Archives'
    etats: list[str] = field(default_factory=lambda: ['1 à lire', '2 en cours', '3 lu'])
    autres_tags: list[str] = field(default_factory=lambda: ['★ essentiel', 'papier'])
    # Couleur des états puis des autres tags, dans l'ordre, prises dans la palette de Zotero (D175). Un tag coloré
    # reçoit la touche de son rang (1 à 9) : « 1 à lire » sur la touche 1. Liste vide, aucune couleur proposée.
    couleurs: list[str] = field(default_factory=lambda: ['#FF6666', '#FF8C19', '#5FB236', '#FFD400', '#A28AE5'])
    prefixe_concept: str = '#'
    prefixe_technique: str = '_'
    seuil_sous_theme: int = 40
    profondeur_max: int = 3
    # Mot qui joint deux auteurs dans les noms de fichiers (« et », « and »), selon la langue de Zotero. Vide :
    # déduit des noms que Zotero a déjà donnés (D150). Le modèle de nom se règle dans Zotero (D148).
    conjonction: str = ''
    cles_citation: bool = True

    @property
    def racines(self) -> list[str]:
        return [n for n in (self.inbox, *self.projets, self.fonds, self.archives) if n]


@dataclass
class Ecriture:
    # Nombre de groupes d'un plan appliqués à l'essai, avant l'application complète (D35).
    essai: int = 5
    # Un plan de gestion (tri de l'Inbox) qui touche moins de fiches s'applique sans essai ni sauvegarde
    # récente (D136, D138). 0 pour garder l'essai et la sauvegarde partout.
    petit_plan_de_gestion: int = 50


@dataclass
class Sauvegarde:
    # Par défaut, à côté du dossier Zotero (D41).
    dossier: Path | None = None
    delai_heures: float = 24
    conserver: int = 2


@dataclass
class Confidentialite:
    # Fiches jamais transmises à l'agent ni cherchées par titre chez les services de métadonnées (D18, D65, D66).
    tags_exclus: list[str] = field(default_factory=lambda: ['_privé'])
    collections_exclues: list[str] = field(default_factory=list)  # chemin (« Fonds/Privé ») ou nom seul
    exclure_notes: bool = False  # sans effet, encore accepté : le texte des notes n'est jamais montré (D191)
    exclure_texte_integral: bool = False


@dataclass
class Sources:
    contact: str = ''  # adresse transmise à Crossref et OpenAlex (D17, D63)
    crossref: bool = True
    openalex: bool = True
    bnf: bool = True
    sudoc: bool = True
    openlibrary: bool = True
    debit: float = 3.0  # requêtes par seconde et par service
    plafond_openalex: int = 900  # recherches par jour, une clé gratuite en couvre environ 1 000 (D74)


@dataclass
class Metadonnees:
    # Champs complétés quand ils sont vides (D61). Ajouter "abstractNote" pour les résumés.
    champs: list[str] = field(default_factory=lambda: [
        'DOI', 'ISBN', 'ISSN', 'date', 'publicationTitle', 'bookTitle', 'proceedingsTitle', 'volume', 'issue',
        'pages', 'publisher', 'place', 'language', 'creators', 'numPages', 'edition', 'series', 'seriesNumber'])
    # Champs jamais complétés pour un type, comme l'éditeur commercial d'une revue (D76).
    exclus_par_type: dict[str, list[str]] = field(default_factory=lambda: {'journalArticle': ['publisher', 'place']})
    seuil_sur: float = 0.95  # similarité des titres pour un rattachement sûr (D62)
    seuil_discordance: float = 0.8  # en dessous, un DOI désigne une autre publication (D69)
    ecart_annees: int = 1


@dataclass
class Tags:
    # Étape 6 (D151 à D156). Un tag automatique porté par au moins `seuil_candidat` fiches est proposé comme
    # exception à la règle qui les supprime (D152).
    seuil_candidat: int = 5
    # Une fiche qui porte plus de `seuil_mots_cles` tags manuels hors familles, presque tous rares, vient sans doute
    # d'un import, ses tags sont des mots-clés d'éditeurs (D153).
    seuil_mots_cles: int = 8
    # Nombre de thèmes du fonds sur lesquels un tag doit se répartir pour être proposé comme concept (D154).
    dispersion_concept: int = 2
    # Tags jamais proposés au changement, en plus des tags techniques, des états, des marques et des tags colorés.
    proteges: list[str] = field(default_factory=list)


@dataclass
class Config:
    dossier_travail: Path
    dossier_zotero: Path = field(default_factory=lambda: Path.home() / 'Zotero')
    methode: Methode = field(default_factory=Methode)
    ecriture: Ecriture = field(default_factory=Ecriture)
    sauvegarde: Sauvegarde = field(default_factory=Sauvegarde)
    confidentialite: Confidentialite = field(default_factory=Confidentialite)
    sources: Sources = field(default_factory=Sources)
    metadonnees: Metadonnees = field(default_factory=Metadonnees)
    tags: Tags = field(default_factory=Tags)

    @property
    def base(self) -> Path:
        return self.dossier_zotero / 'zotero.sqlite'

    @property
    def rapports(self) -> Path:
        return self.dossier_travail / 'rapports'

    @property
    def plans(self) -> Path:
        return self.dossier_travail / 'plans'

    @property
    def journal(self) -> Path:
        return self.dossier_travail / 'journal'

    @property
    def suivi(self) -> Path:
        return self.dossier_travail / 'suivi'

    @property
    def cache(self) -> Path:
        return self.dossier_travail / 'cache'

    @property
    def sauvegardes(self) -> Path:
        z = self.dossier_zotero
        return self.sauvegarde.dossier or z.parent / f'{z.name}-sauvegardes'


def trouver_dossier(depart: Path | None = None) -> Path | None:
    """Premier dossier contenant un `config.toml`, en remontant depuis `depart`."""
    depart = (depart or Path.cwd()).resolve()
    for d in (depart, *depart.parents):
        if (d / FICHIER).is_file():
            return d
    return None


def charger(dossier: Path | None = None) -> Config:
    dossier = dossier or trouver_dossier() or Path.cwd()
    chemin = dossier / FICHIER
    brut = tomllib.loads(chemin.read_text(encoding='utf-8')) if chemin.is_file() else {}
    cfg = Config(dossier_travail=dossier)
    if d := brut.get('zotero', {}).get('dossier'):
        cfg.dossier_zotero = Path(d).expanduser()
    cfg.methode = _section(brut, 'methode', Methode, chemin)
    if isinstance(cfg.methode.projets, str):  # une seule racine, écrite comme avant D108
        cfg.methode.projets = [cfg.methode.projets] if cfg.methode.projets else []
    cfg.ecriture = _section(brut, 'ecriture', Ecriture, chemin)
    cfg.sauvegarde = _section(brut, 'sauvegarde', Sauvegarde, chemin)
    cfg.confidentialite = _section(brut, 'confidentialite', Confidentialite, chemin)
    cfg.sources = _section(brut, 'sources', Sources, chemin)
    cfg.metadonnees = _section(brut, 'metadonnees', Metadonnees, chemin)
    cfg.tags = _section(brut, 'tags', Tags, chemin)
    if cfg.sauvegarde.dossier:
        cfg.sauvegarde.dossier = Path(cfg.sauvegarde.dossier).expanduser()
    return cfg


# Clés retirées, ignorées sans erreur dans un ancien config.toml.
OBSOLETES = {'methode': {'modele_fichier'}}  # D148 : le modèle de nom se lit dans Zotero


def _section(brut: dict, nom: str, classe, chemin: Path):
    valeurs = {k: v for k, v in brut.get(nom, {}).items() if k not in OBSOLETES.get(nom, set())}
    inconnues = set(valeurs) - {f.name for f in fields(classe)}
    if inconnues:
        raise SystemExit(f"{chemin} : clés inconnues dans [{nom}] : {', '.join(sorted(inconnues))}")
    return classe(**valeurs)


def lire_env(dossier: Path) -> dict[str, str]:
    """Clé API et identifiant du compte, dans le `.env` du dossier de travail (D13)."""
    chemin = dossier / '.env'
    if not chemin.exists():
        return {}
    return dict(l.strip().split('=', 1) for l in chemin.read_text(encoding='utf-8').splitlines() if '=' in l)
