"""Tags, étape 6 du nettoyage (D22, D151 à D156).

`inventaire` décrit tout le jeu de tags (usages, variantes, mots-clés importés,
états venus d'autres habitudes, concepts et tags qui doublent un thème, tags
protégés) et prépare `suivi/tags.toml`, qui décrit des règles par nom de tag,
jamais par fiche. La section `[automatiques]` porte la règle globale qui retire
les tags automatiques (D152), `[importes]` la même règle pour les mots-clés
importés en tags manuels (D153), chaque `[[tag]]` le sort d'un tag (exception à
la règle, état, concept, suppression, fusion) et chaque `[[variantes]]` un
groupe de noms ramenés à une forme. Les décisions sont gardées d'une fois sur
l'autre, et le fichier sert ensuite au tri de l'Inbox (D155).

`regles` et `tags_vises` donnent, sans réseau, la liste finale des tags d'un
élément d'après les règles acceptées. `planifier` en tire un plan d'une
opération par élément (fiche, pièce jointe, note ou annotation) qui écrit sa
liste complète de tags, types gardés (D156), sans `DELETE /tags`. Il compare
l'état réel aux règles et ne planifie que la différence (D119).

Sont protégés, c'est-à-dire inventoriés sans proposition et changés seulement
par une entrée de l'utilisateur (`source = "utilisateur"`), les tags
techniques, les états et marques de la méthode, les tags colorés, ceux de
`[tags] proteges` et ceux sur lesquels repose une proposition de rangement en
attente. Les tags de `tags_exclus` ne changent jamais. Un tag porté seulement
par des fiches confidentielles n'apparaît que sous un identifiant stable, et
seules les règles globales s'y appliquent sans entrée de l'utilisateur. Un tag
cité par une recherche enregistrée échappe aux règles globales.
"""

import hashlib
import re
import tomllib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

from zot_clean import filtre, fonds as f, rangement as r
from zot_clean.audit import annee, ecrire_toml, norm, pluriel
from zot_clean.config import Config
from zot_clean.doublons import _toml
from zot_clean.ecriture import Client
from zot_clean.lecture import Bibliotheque, Element
from zot_clean.plans import Groupe, Operation, Plan, normaliser

FICHIER = 'tags.toml'
ETAPE = 'tags'
SUPPRIMER, GARDER, CONCEPT, ETAT, FUSIONNER = 'supprimer', 'garder', 'concept', 'état', 'fusionner'
SORTS = {norm(s): s for s in (SUPPRIMER, GARDER, CONCEPT, ETAT, FUSIONNER)}
ACCEPTER, REFUSER = 'accepter', 'refuser'
ZC, AGENT, UTILISATEUR = 'zc', 'agent', 'utilisateur'
EVIDENT, DOUTEUX = 'évident', 'douteux'
MANUEL, AUTOMATIQUE, LES_DEUX = 'manuel', 'automatique', 'les deux'
MAX_COULEURS = 9
TITRES = 3
VOIR_MAX = 50

# Sortes de changement d'un plan, dans l'ordre du rapport.
SORTES = {
    'automatique': 'tags automatiques retirés par la règle globale',
    'importé': 'mots-clés importés retirés',
    'variante': 'variantes ramenées à leur forme',
    'état': 'tags ramenés à un état ou une marque de la méthode',
    'concept': 'tags convertis en concepts',
    'fusion': 'tags fusionnés dans un autre',
    'suppression': 'tags supprimés',
}
SORTE_DU_SORT = {CONCEPT: 'concept', ETAT: 'état', FUSIONNER: 'fusion'}

# États et marques venus d'autres habitudes (D156), rapprochés par leur forme de ceux de `[methode]` : numéro de
# l'état dans `etats` (0 à lire, 1 en cours, 2 lu) ou de la marque dans `autres_tags` (0 essentiel, 1 papier).
ETATS_ETRANGERS = {
    0: ('to read', 'toread', 'unread', 'à lire', 'non lu', 'pas lu', 'read later', 'à lire plus tard', 'reading list'),
    1: ('reading', 'en cours', 'en cours de lecture', 'en lecture', 'in progress', 'currently reading', 'commencé'),
    2: ('read', 'lu', 'déjà lu', 'already read', 'done', 'finished', 'fini', 'terminé', 'lu et annoté'),
}
MARQUES_ETRANGERES = {
    0: ('important', 'essentiel', 'essential', 'key paper', 'favorite', 'favourite', 'favori', 'must read',
        'incontournable', 'starred', 'étoile'),
    1: ('imprimé', 'printed', 'papier', 'version papier', 'hard copy', 'photocopie', 'copie papier'),
}

EN_TETE = """\
# Règles des tags, préparées par `zc tags inventaire` (étape 6) et lues par `zc tags planifier`, puis par
# le tri de l'Inbox. Ce fichier se relit et se modifie à la main ou avec l'agent. `zc tags inventaire` le met à jour
# sans perdre les décisions prises. Une règle porte sur un nom de tag, jamais sur une fiche. Les décisions
# s'écrivent avec `zc tags accepter`, `zc tags refuser` et `zc tags ajouter` (voir `zc tags accepter --help`).
#
# [automatiques] retire tous les tags automatiques (mots-clés des éditeurs), sauf les exceptions ci-dessous.
# [importes]     retire de même les mots-clés importés en tags manuels (fiches qui en portent beaucoup, et rares).
#
# [[tag]], un tag à juger.
#   sort     : "supprimer", "garder", "concept" (renommé en `cible`, qui commence par le préfixe des concepts),
#              "état" (renommé en un état ou une marque de la méthode), "fusionner" (renommé en `cible`).
#              Un tag automatique gardé reste automatique. Un tag renommé devient manuel.
#   source   : "zc" (proposé par zc), "agent", "utilisateur". Un tag protégé (technique, état, marque, coloré, liste
#              [tags] proteges de config.toml) ne change que par une entrée de source "utilisateur".
#   classe   : "évident" (à approuver en bloc) ou "douteux" (par paquets).
#   decision : "" (proposé), "accepter" ou "refuser". Seules les entrées acceptées s'appliquent. Tant qu'une entrée
#              attend, son tag échappe aux règles globales.
#   effectif (fiches qui le portent, directement ou par un enfant), dispersion (thèmes du fonds où elles sont),
#   themes, theme (thème qu'il double), recherches (recherches enregistrées qui le citent) : renseignés par zc.
#   variantes : autres noms de même forme, ramenés à `nom` avant d'appliquer le sort (par exemple supprimés avec
#              lui). zc les réunit ici plutôt que dans un [[variantes]] quand il propose de supprimer le tag.
#
# [[variantes]], des noms qui ne diffèrent que par la casse, les accents, les espaces, le préfixe ou le pluriel,
#   ramenés à `cible`, posée en tag manuel. "évident" quand seul le pluriel n'intervient pas. Un concept s'écrit en
#   minuscules sauf nom propre, dans la langue de l'utilisateur, espaces permis (« #cognition incarnée »).
#
# Un tag porté seulement par des fiches confidentielles apparaît sous un identifiant (« tag confidentiel 1a2b3c4d »),
# utilisable comme nom dans une entrée de source "utilisateur".
"""


# --- Formes -----------------------------------------------------------------------

def _mots(nom: str, cfg: Config) -> tuple[str, list[str]]:
    m = cfg.methode
    tete = ''
    if m.prefixe_technique and nom.startswith(m.prefixe_technique):
        tete = m.prefixe_technique  # « _lu » n'est pas une variante de « lu »
    if m.prefixe_concept and nom.startswith(m.prefixe_concept):
        nom = nom[len(m.prefixe_concept):]
    sans = ''.join(c for c in unicodedata.normalize('NFKD', nom) if not unicodedata.combining(c)).casefold()
    return tete, re.findall(r'[^\W_]+', sans)


def forme_faible(nom: str, cfg: Config) -> str:
    """Nom sans casse, accents, espaces, tirets ni préfixe des concepts."""
    tete, mots = _mots(nom, cfg)
    return tete + ''.join(mots) if mots else nom.casefold()


def forme(nom: str, cfg: Config) -> str:
    """Forme normalisée qui regroupe les variantes (D156), pluriel simple compris (`s`, `x`, `-aux`)."""
    tete, mots = _mots(nom, cfg)
    return tete + ''.join(_singulier(x) for x in mots) if mots else nom.casefold()


def _singulier(mot: str) -> str:
    if len(mot) > 3 and mot[-1] in 'sx':
        mot = mot[:-1]
    if len(mot) > 3 and mot.endswith('al'):
        mot = mot[:-2] + 'au'  # cheval et chevaux, réseau et réseaux
    return mot


def _marque_technique(nom: str, cfg: Config) -> bool:
    """Nom qui ne commence ni par une lettre, ni par un chiffre, ni par le préfixe des concepts : marque laissée par
    une application (« /unread », « _tablet », « @todo »), jamais une notion à proposer comme concept. Les tags
    techniques de la méthode (`_`) sont protégés avant d'arriver ici."""
    p = cfg.methode.prefixe_concept
    return bool(nom) and not nom[0].isalnum() and not (p and nom.startswith(p))


def nom_de_concept(nom: str, cfg: Config) -> str:
    """Nom de concept proposé pour un tag, suivant la convention du skill autant que zc le peut : préfixe des
    concepts, minuscules (un sigle comme « TDAH » reste en capitales), espaces à la place des soulignés. zc ne
    traduit rien, l'agent vérifie le nom et le met dans la langue de l'utilisateur."""
    p = cfg.methode.prefixe_concept
    corps = nom[len(p):] if p and nom.startswith(p) else nom
    mots = corps.replace('_', ' ').split()
    return p + ' '.join(m if len(m) > 1 and m.isupper() else m.lower() for m in mots)


def identifiant(nom: str) -> str:
    """Nom stable d'un tag porté seulement par des fiches confidentielles (D156)."""
    return 'tag confidentiel ' + hashlib.sha256(nom.encode('utf-8')).hexdigest()[:8]


# --- Usages -----------------------------------------------------------------------

@dataclass
class Usage:
    nom: str
    types: set[int] = field(default_factory=set)
    occurrences: Counter = field(default_factory=Counter)  # type -> nombre d'éléments
    elements: set[int] = field(default_factory=set)
    fiches: set[int] = field(default_factory=set)  # fiches qui le portent, directement ou par un enfant
    enfants: int = 0
    annotations: int = 0
    themes: Counter = field(default_factory=Counter)  # thème du fonds -> fiches
    recherches: list[str] = field(default_factory=list)
    couleur: str = ''
    rang_couleur: int = 0
    confidentiel: bool = False

    @property
    def dispersion(self) -> int:
        return len(self.themes)

    @property
    def type_lisible(self) -> str:
        return LES_DEUX if len(self.types) > 1 else (AUTOMATIQUE if 1 in self.types else MANUEL)


def fiche_de(b: Bibliotheque, el: Element) -> int | None:
    """Fiche d'un élément, lui-même s'il en est une, sa fiche parente pour un enfant, None pour une note isolée."""
    if el.est_fiche:
        return el.id
    if el.id in b.pieces:
        return b.pieces[el.id].parent
    if el.id in b.notes:
        return b.notes[el.id]
    piece = b.annotation_de.get(el.id)
    return b.pieces[piece].parent if piece in b.pieces else None


def themes_des_fiches(b: Bibliotheque, cfg: Config) -> dict[int, set[str]]:
    """Thèmes du fonds de chaque fiche, au niveau de la discipline et du thème (un sous-thème compte pour son thème),
    hors collections exclues par le filtre."""
    e = r._Etat(b)
    racine = e.racine(cfg.methode.fonds) if cfg.methode.fonds else None
    if racine is None:
        return {}
    _, couvertes = f.collections_exclues(b, cfg)
    res: dict[int, set[str]] = defaultdict(set)
    for el in b.fiches:
        for cid in el.collections:
            k = e.cle[cid]
            if cid not in couvertes and k != racine and e.sous(k, racine):
                res[el.id].add('/'.join(e.chemin(k).split('/')[1:3]))
    return res


def _cite(operateur: str, valeur: str, nom: str) -> bool:
    if operateur in ('contains', 'doesNotContain'):
        return bool(valeur) and valeur.casefold() in nom.casefold()
    return valeur == nom


def usages(b: Bibliotheque, cfg: Config) -> dict[str, Usage]:
    masquees = filtre.cles_masquees(b, cfg)
    themes = themes_des_fiches(b, cfg)
    res: dict[str, Usage] = {}
    for el in b.elements.values():
        fiche = fiche_de(b, el)
        for nom, typ in el.tags:
            u = res.setdefault(nom, Usage(nom))
            u.types.add(typ)
            u.occurrences[typ] += 1
            u.elements.add(el.id)
            if not el.est_fiche:
                u.enfants += 1
                u.annotations += el.type == 'annotation'
            if fiche is not None and fiche in b.elements:
                u.fiches.add(fiche)
    for u in res.values():
        for fiche in u.fiches:
            u.themes.update(themes.get(fiche, ()))
        u.confidentiel = all(b.elements[i].cle in masquees for i in u.elements)
    for rang, (nom, couleur) in enumerate(b.couleurs, 1):
        if nom in res:
            res[nom].couleur, res[nom].rang_couleur = couleur, rang
    for recherche, operateur, valeur in b.recherches_tags:
        for nom, u in res.items():
            if _cite(operateur, valeur, nom) and recherche not in u.recherches:
                u.recherches.append(recherche)
    return res


def concepts_du_plan(cfg: Config) -> list[str]:
    """Concepts définis dans la section `# Concepts` de plan.md, un titre `## #nom` chacun (D154)."""
    chemin = cfg.dossier_travail / f.PLAN
    if not chemin.is_file():
        return []
    res, dedans = [], False
    for ligne in chemin.read_text(encoding='utf-8').splitlines():
        if m := re.match(r'^#\s+(.*?)\s*$', ligne):
            dedans = norm(m.group(1)) == 'concepts'
        elif dedans and (m := re.match(r'^##\s+(.*?)\s*$', ligne)):
            res.append(m.group(1))
    return res


# --- Fichier de suivi -------------------------------------------------------------

@dataclass
class Entree:
    nom: str
    type: str = ''
    effectif: int = 0
    dispersion: int = 0
    themes: list[str] = field(default_factory=list)
    theme: str = ''  # thème du plan que le tag double (D154)
    recherches: list[str] = field(default_factory=list)
    sort: str = ''
    cible: str = ''
    source: str = ZC
    classe: str = DOUTEUX
    decision: str = ''
    note: str = ''
    variantes: list[str] = field(default_factory=list)  # noms ramenés à `nom` avant le sort


@dataclass
class Variantes:
    noms: list[str]
    cible: str
    classe: str = DOUTEUX
    source: str = ZC
    decision: str = ''
    note: str = ''


@dataclass
class Suivi:
    automatiques: str = ''  # décision de la règle globale
    importes: str = ''  # décision pour les mots-clés importés
    tags: list[Entree] = field(default_factory=list)
    variantes: list[Variantes] = field(default_factory=list)
    # Renseignés par l'inventaire, écrits en commentaire ou dans rangement.toml.
    resume_automatiques: str = ''
    resume_importes: str = ''
    a_ranger: list = field(default_factory=list)  # propositions de rangement (rangement.Entree, source « tag »)


def _decision(v: str, ou: str, chemin) -> str:
    if v not in ('', ACCEPTER, REFUSER):
        raise SystemExit(f'{chemin} : décision inconnue « {v} » ({ou}). Décisions possibles : "", "{ACCEPTER}", '
                         f'"{REFUSER}".')
    return v


def charger(cfg: Config) -> Suivi:
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return Suivi()
    texte = chemin.read_text(encoding='utf-8')
    try:
        brut = tomllib.loads(texte)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    m = cfg.methode
    s = Suivi()
    for section in ('automatiques', 'importes'):
        d = brut.get(section, {})
        if d.get('sort', SUPPRIMER) != SUPPRIMER:
            raise SystemExit(f'{chemin} : [{section}] ne connaît que sort = "{SUPPRIMER}". Pour garder ces tags, '
                             f'écrire decision = "{REFUSER}".')
        setattr(s, section, _decision(d.get('decision', ''), f'[{section}]', chemin))
        # Résumé écrit par l'inventaire sous l'en-tête de la section, gardé quand une commande réécrit le fichier.
        if section in brut and (r := re.search(rf'^\[{section}\][ \t]*\r?\n# (.*?)\r?$', texte, re.M)):
            setattr(s, f'resume_{section}', r.group(1))
    for d in brut.get('tag', []):
        nom = d.get('nom', '')
        if not nom:
            raise SystemExit(f'{chemin} : une entrée [[tag]] n\'a pas de nom.')
        sort = d.get('sort', '')
        if sort and norm(sort) not in SORTS:
            raise SystemExit(f'{chemin} : sort inconnu « {sort} » pour « {nom} ». Sorts possibles : '
                             f'{", ".join(SORTS.values())}.')
        e = Entree(nom, d.get('type', ''), int(d.get('effectif', 0)), int(d.get('dispersion', 0)),
                   list(d.get('themes', [])), d.get('theme', ''), list(d.get('recherches', [])),
                   SORTS[norm(sort)] if sort else '', d.get('cible', ''), _source(d.get('source', ZC), nom, chemin),
                   d.get('classe', DOUTEUX), _decision(d.get('decision', ''), nom, chemin), d.get('note', ''),
                   list(d.get('variantes', [])))
        _verifier_cible(e.sort, e.cible, e.decision, nom, cfg, chemin)
        s.tags.append(e)
    for d in brut.get('variantes', []):
        noms, cible = list(d.get('noms', [])), d.get('cible', '')
        if not noms or not cible:
            raise SystemExit(f'{chemin} : un groupe [[variantes]] doit avoir des `noms` et une `cible` ({noms}).')
        if filtre.tag_exclu(cible, cfg):
            raise SystemExit(f'{chemin} : « {cible} » sert au filtre de confidentialité, il ne peut pas être une cible.')
        s.variantes.append(Variantes(noms, cible, d.get('classe', DOUTEUX), _source(d.get('source', ZC), cible, chemin),
                                     _decision(d.get('decision', ''), cible, chemin), d.get('note', '')))
    return s


def _source(v: str, nom: str, chemin) -> str:
    if v not in (ZC, AGENT, UTILISATEUR):
        raise SystemExit(f'{chemin} : source inconnue « {v} » pour « {nom} » ("{ZC}", "{AGENT}" ou "{UTILISATEUR}").')
    return v


def _verifier_cible(sort: str, cible: str, decision: str, nom: str, cfg: Config, chemin) -> None:
    m = cfg.methode
    if sort in (CONCEPT, ETAT, FUSIONNER) and decision == ACCEPTER and not cible:
        raise SystemExit(f'{chemin} : « {nom} » ({sort}) est accepté sans cible.')
    if not cible:
        return
    if filtre.tag_exclu(cible, cfg):
        raise SystemExit(f'{chemin} : « {cible} » sert au filtre de confidentialité, il ne peut pas être une cible.')
    if sort == CONCEPT and m.prefixe_concept and not cible.startswith(m.prefixe_concept):
        raise SystemExit(f'{chemin} : la cible du concept « {nom} » doit commencer par « {m.prefixe_concept} » '
                         f'(« {cible} »).')
    if sort == ETAT and cible not in (*m.etats, *m.autres_tags):
        raise SystemExit(f'{chemin} : « {cible} », cible de « {nom} », n\'est ni un état ni une marque de la méthode '
                         f'({", ".join((*m.etats, *m.autres_tags))}).')


def _titres(b: Bibliotheque, u: Usage | None, masquees: set[str]) -> str:
    if u is None:
        return ''
    fiches = sorted((b.elements[i] for i in u.fiches if b.elements[i].cle not in masquees), key=lambda e: norm(e.titre))
    return ' · '.join(f'{e.auteur or "?"} {annee(e) or "s. d."}, « {e.titre[:60] or "sans titre"} »'
                      for e in fiches[:TITRES])


def ecrire(cfg: Config, s: Suivi, b: Bibliotheque) -> None:
    """Écrit `suivi/tags.toml`, et ajoute à `suivi/rangement.toml` les fiches à ranger avant de supprimer un tag
    qui double un thème (D154)."""
    u = usages(b, cfg)
    masquees = filtre.cles_masquees(b, cfg)

    def affiche(nom: str) -> str:
        return identifiant(nom) if nom in u and u[nom].confidentiel else nom

    L = [EN_TETE, '[automatiques]']
    if s.resume_automatiques:
        L.append(f'# {s.resume_automatiques}')
    L += [f'sort = "{SUPPRIMER}"', f'decision = {_toml(s.automatiques)}', '']
    if s.resume_importes or s.importes:
        L += ['[importes]'] + ([f'# {s.resume_importes}'] if s.resume_importes else [])
        L += [f'sort = "{SUPPRIMER}"', f'decision = {_toml(s.importes)}', '']
    for e in s.tags:
        L.append('[[tag]]')
        if t := _titres(b, u.get(e.nom), masquees):
            L.append(f'# {t}')
        L += [f'nom = {_toml(affiche(e.nom))}', f'type = {_toml(e.type)}', f'effectif = {e.effectif}',
              f'dispersion = {e.dispersion}', f'themes = {_toml(e.themes)}']
        L += [f'theme = {_toml(e.theme)}'] if e.theme else []
        L += [f'recherches = {_toml(e.recherches)}'] if e.recherches else []
        L += [f'variantes = {_toml([affiche(n) for n in e.variantes])}'] if e.variantes else []
        L += [f'sort = {_toml(e.sort)}', f'cible = {_toml(e.cible)}', f'source = {_toml(e.source)}',
              f'classe = {_toml(e.classe)}', f'decision = {_toml(e.decision)}']
        L += [f'note = {_toml(e.note)}'] if e.note else []
        L.append('')
    for g in s.variantes:
        L.append('[[variantes]]')
        L.append('# ' + ' · '.join(f'{affiche(n)} ({len(u[n].fiches)}, {u[n].type_lisible})' if n in u
                                   else f'{affiche(n)} (absent)' for n in g.noms))
        L += [f'noms = {_toml([affiche(n) for n in g.noms])}', f'cible = {_toml(g.cible)}',
              f'classe = {_toml(g.classe)}', f'source = {_toml(g.source)}', f'decision = {_toml(g.decision)}']
        L += [f'note = {_toml(g.note)}'] if g.note else []
        L.append('')
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    ecrire_toml(cfg.suivi / FICHIER, L)
    if s.a_ranger:
        r.ecrire(cfg, r.charger(cfg) + s.a_ranger, b, filtre.exclues(b, cfg))


# --- Décisions par commande (D177) ------------------------------------------------

REGLES = {'automatiques': 'des tags automatiques', 'importes': 'des mots-clés importés'}


def _nfc(nom: str) -> str:
    """Nom comparé sous une seule forme Unicode, celle que tape l'agent pouvant différer de celle de la base."""
    return unicodedata.normalize('NFC', nom)


def _sort(v: str) -> str:
    if norm(v) not in SORTS:
        raise SystemExit(f'Sort inconnu « {v} ». Sorts possibles : {", ".join(SORTS.values())}.')
    return SORTS[norm(v)]


def decider(s: Suivi, cfg: Config, decision: str, noms=(), variantes=(), evidents: bool = False, sauf=(),
            regles=(), sort: str = '', cible: str = '') -> int:
    """Décisions prises par commande (D177, sur le modèle de D172), au lieu d'écrire le fichier à la main. `noms`
    désigne des entrées [[tag]] par leur nom, `variantes` des groupes [[variantes]] par leur cible ou l'un de leurs
    noms, `regles` les sections [automatiques] et [importes]. `evidents` accepte toutes les entrées et tous les
    groupes évidents encore à juger, hors des noms de `sauf`. `sort` et `cible` changent la proposition des entrées
    données (qui passent en source « agent »), `cible` celle des groupes. Seules les règles encore à juger changent.
    Renvoie le nombre de décisions écrites."""
    chemin = cfg.suivi / FICHIER
    n = 0
    for section in regles:
        quoi = REGLES[section]
        if section == 'importes' and not s.resume_importes and not s.importes:
            raise SystemExit(f'{chemin} n\'a pas de section [importes] : aucune fiche ne porte de mots-clés importés.')
        if getattr(s, section):
            raise SystemExit(f'La règle {quoi} est déjà décidée (« {getattr(s, section)} ») dans {chemin}. Pour revenir '
                             f'dessus, changer decision à la main dans la section [{section}].')
        setattr(s, section, decision)
        n += 1

    tous = {_nfc(e.nom) for e in s.tags} | {_nfc(x) for g in s.variantes for x in (g.cible, *g.noms)}
    tags_a_juger: dict[str, list[Entree]] = defaultdict(list)
    for e in s.tags:
        if not e.decision:
            tags_a_juger[_nfc(e.nom)].append(e)
    groupes_a_juger: dict[str, list[Variantes]] = defaultdict(list)
    for g in s.variantes:
        if not g.decision:
            for x in dict.fromkeys((g.cible, *g.noms)):
                groupes_a_juger[_nfc(x)].append(g)

    def refuser_inconnus(demandes, a_juger, quoi: str, autre=None, ailleurs: str = '') -> None:
        inconnus = [x for x in demandes if _nfc(x) not in a_juger]
        if not inconnus:
            return
        morceaux = []
        if autre is not None and (mal_places := [x for x in inconnus if _nfc(x) in autre]):
            morceaux.append(f'«{"», «".join(f" {x} " for x in mal_places)}» désigne {ailleurs}.')
            inconnus = [x for x in inconnus if x not in mal_places]
        absents = '», «'.join(f' {x} ' for x in inconnus if _nfc(x) not in tous)
        decides = '», «'.join(f' {x} ' for x in inconnus if _nfc(x) in tous)
        if absents:
            morceaux.append(f'«{absents}» ne figure pas dans {chemin} ({quoi}). Vérifier le nom, en entier et entre '
                            'guillemets (non protégé, un nom qui commence par # est pris pour un commentaire), ou '
                            'relancer `zc tags inventaire`. Un tag sans entrée s\'ajoute par `zc tags ajouter`.')
        if decides:
            morceaux.append(f'«{decides}» : rien à juger sous ce nom ({quoi}), la décision est déjà prise. Une '
                            'décision prise se change à la main dans le fichier.')
        raise SystemExit(' '.join(morceaux))

    refuser_inconnus(noms, tags_a_juger, 'entrées [[tag]]', groupes_a_juger,
                     'un groupe [[variantes]] à juger, à donner après --variantes')
    refuser_inconnus(variantes, groupes_a_juger, 'groupes [[variantes]]', tags_a_juger,
                     'une entrée [[tag]] à juger, à donner sans --variantes')
    refuser_inconnus(sauf, dict.fromkeys(tous), 'noms de tags et de groupes')
    sort = _sort(sort) if sort else ''

    vus: set[int] = set()
    for nom in noms:
        for e in tags_a_juger[_nfc(nom)]:
            if id(e) in vus:
                continue
            vus.add(id(e))
            if sort or cible:
                if sort and sort != e.sort:
                    e.sort, e.cible = sort, ''
                e.cible = cible or e.cible
                e.source = AGENT if e.source == ZC else e.source
            if decision == ACCEPTER and not e.sort:
                raise SystemExit(f'« {e.nom} » n\'a pas de sort proposé. Le donner avec --sort.')
            e.decision = decision
            _verifier_cible(e.sort, e.cible, e.decision, e.nom, cfg, chemin)
            n += 1
    for nom in variantes:
        for g in groupes_a_juger[_nfc(nom)]:
            if id(g) in vus:
                continue
            vus.add(id(g))
            if cible:
                if filtre.tag_exclu(cible, cfg):
                    raise SystemExit(f'« {cible} » sert au filtre de confidentialité, il ne peut pas être une cible.')
                g.cible, g.source = cible, AGENT if g.source == ZC else g.source
            g.decision = decision
            n += 1
    if evidents:
        ecartes = {_nfc(x) for x in sauf}
        for e in s.tags:
            if e.classe == EVIDENT and not e.decision and e.sort and _nfc(e.nom) not in ecartes:
                e.decision = ACCEPTER
                _verifier_cible(e.sort, e.cible, e.decision, e.nom, cfg, chemin)
                n += 1
        for g in s.variantes:
            if g.classe == EVIDENT and not g.decision and not {_nfc(x) for x in (g.cible, *g.noms)} & ecartes:
                g.decision = ACCEPTER
                n += 1
    return n


def ajouter(s: Suivi, cfg: Config, b: Bibliotheque, noms, sort: str, cible: str = '',
            utilisateur: bool = False) -> int:
    """Entrées [[tag]] nouvelles, déjà acceptées, pour des tags que l'inventaire n'a pas proposés (tags hors familles
    signalés par le tri de l'Inbox, traductions, tag protégé à la demande de l'utilisateur). Source « agent », ou
    « utilisateur », seule source qui change un tag protégé ou confidentiel (D151, D156). Renvoie leur nombre."""
    chemin = cfg.suivi / FICHIER
    a = _Analyse(b, cfg)
    sort = _sort(sort)
    deja = {_nfc(e.nom) for e in s.tags}
    for nom in noms:
        if _nfc(nom) in deja:
            raise SystemExit(f'« {nom} » a déjà une entrée [[tag]] dans {chemin}. La juger avec `zc tags accepter` ou '
                             '`zc tags refuser`.')
        reel = next((n for n in (a.reel(nom), a.reel(_nfc(nom))) if n in a.u), None)
        if reel is None:
            raise SystemExit(f'Aucun tag « {nom} » dans la bibliothèque. Vérifier le nom, en entier et entre '
                             'guillemets.')
        e = a.stats(Entree(reel), a.u[reel])
        e.nom, e.sort, e.cible, e.decision = nom, sort, cible, ACCEPTER
        e.source = UTILISATEUR if utilisateur else AGENT
        _verifier_cible(e.sort, e.cible, e.decision, nom, cfg, chemin)
        s.tags.append(e)
        deja.add(_nfc(nom))
    s.tags.sort(key=lambda e: norm(e.nom))
    return len(noms)


# --- Analyse ----------------------------------------------------------------------

class _Analyse:
    """Usages et classements de la bibliothèque, partagés par l'inventaire, les règles et le plan."""

    def __init__(self, b: Bibliotheque, cfg: Config):
        self.b, self.cfg = b, cfg
        m = cfg.methode
        self.u = usages(b, cfg)
        self.masquees = filtre.cles_masquees(b, cfg)
        self.par_identifiant = {identifiant(n): n for n, x in self.u.items() if x.confidentiel}
        self.exclus = filtre.tags_exclus(cfg)
        self.couleurs = {n for n, _ in b.couleurs}
        self.etats = list(m.etats)
        fonds_toml = cfg.suivi / f.FICHIER
        self.lies = f.charger_suivi(cfg).tags if fonds_toml.is_file() else {}
        chemin_plan = cfg.dossier_travail / f.PLAN
        self.plan = f.lire_plan(chemin_plan.read_text(encoding='utf-8'), cfg) if chemin_plan.is_file() else None
        self.rangement = r.charger(cfg) if (cfg.suivi / r.FICHIER).is_file() else []
        self.attente = set()  # tags sur lesquels repose une proposition de rangement en attente (D156)
        for x in self.rangement:
            if x.decision == '' and x.source == r.TAG and (t := re.search(r'tag « (.+?) »', x.note)):
                self.attente.add(t.group(1))
        # Thèmes : collections sous la racine du fonds et chemins de plan.md, par forme du dernier nom.
        e = r._Etat(b)
        self.etat = e
        racine = e.racine(m.fonds) if m.fonds else None
        self.racine_fonds = racine
        _, couvertes = f.collections_exclues(b, cfg)
        cachees = {b.collections[c].cle for c in couvertes}
        chemins = {e.chemin(k).split('/', 1)[1] for k in e.nom
                   if racine and k != racine and e.sous(k, racine) and k not in cachees}
        if self.plan:
            chemins |= set(self.plan.noeuds)
        self.themes_par_forme = {forme(c.rsplit('/', 1)[-1], cfg): c for c in sorted(chemins, key=len, reverse=True)}
        self.lot, self.importes = self._lots()
        self.cumuls: dict[str, Usage] = {}  # cible d'un groupe de variantes -> usage réuni
        self.forts = {n for n, u in self.u.items() if 0 in u.types and n not in self.importes}
        self.concepts = {n for n in self.forts if self.est_concept(n)} | set(concepts_du_plan(cfg))
        self.formes_reference = ({forme(n, cfg) for n in self.forts} | {forme(c, cfg) for c in self.concepts}
                                 | set(self.themes_par_forme))
        self.formes_concepts_themes = {forme(c, cfg) for c in self.concepts} | set(self.themes_par_forme)
        self.etrangers = {}
        for table, noms in ((ETATS_ETRANGERS, m.etats), (MARQUES_ETRANGERES, m.autres_tags)):
            for i, alias in table.items():
                if i < len(noms):
                    for a in alias:
                        self.etrangers.setdefault(forme(a, cfg), noms[i])

    def reel(self, nom: str) -> str:
        """Nom réel d'un tag désigné par son identifiant confidentiel, ou le nom tel quel."""
        return self.par_identifiant.get(nom, nom)

    def est_concept(self, nom: str) -> bool:
        p = self.cfg.methode.prefixe_concept
        return bool(p) and nom.startswith(p) and len(nom) > len(p)

    def protection(self, nom: str) -> str:
        """Raison pour laquelle un tag est protégé (D151), vide sinon."""
        m = self.cfg.methode
        if filtre.forme(nom) in self.exclus:
            return 'filtre de confidentialité, ne change jamais'
        if m.prefixe_technique and nom.startswith(m.prefixe_technique):
            return 'tag technique'
        if nom in m.etats:
            return 'état de la méthode'
        if nom in m.autres_tags:
            return 'marque de la méthode'
        if nom in self.couleurs:
            return 'tag coloré'
        if nom in self.cfg.tags.proteges:
            return 'liste [tags] proteges'
        if nom in self.attente:
            return 'proposition de rangement en attente'
        return ''

    def hors_familles(self, nom: str) -> bool:
        return not self.est_concept(nom) and not self.protection(nom)

    def _lots(self) -> tuple[set[int], set[str]]:
        """Fiches qui portent plus de `seuil_mots_cles` tags manuels hors familles, rares pour la plupart, et noms dont
        toutes les occurrences manuelles sont sur ces fiches (D153). Les annotations n'y entrent jamais."""
        t = self.cfg.tags
        lot = set()
        for el in self.b.fiches:
            if el.cle in self.masquees:
                continue
            hors = {n for n, typ in el.tags if typ == 0 and self.hors_familles(n)}
            if len(hors) > t.seuil_mots_cles:
                rares = sum(1 for n in hors if len(self.u[n].fiches) < t.seuil_candidat)
                if 2 * rares > len(hors):
                    lot.add(el.id)
        importes = set()
        for n, u in self.u.items():
            if 0 not in u.types or u.confidentiel or not self.hors_familles(n):
                continue
            manuels = {i for i in u.elements if (n, 0) in self.b.elements[i].tags}
            if manuels and manuels <= lot:
                importes.add(n)
        return lot, importes

    def candidat(self, nom: str) -> bool:
        """Exception proposée à la règle globale (D152) : assez porté, ou de même forme qu'un tag manuel, un concept
        ou un thème."""
        u = self.u[nom]
        if len(u.fiches) >= self.cfg.tags.seuil_candidat:
            return True
        autres = {forme(n, self.cfg) for n in self.forts if n != nom} | self.formes_concepts_themes
        return forme(nom, self.cfg) in autres

    def ressemble(self, nom: str) -> bool:
        """Ressemblance avec un concept ou un thème, qui empêche de classer « évident » un tag à supprimer."""
        fo = forme(nom, self.cfg)
        for autre in self.formes_concepts_themes:
            if fo == autre or fo in autre or autre in fo:
                return True
            s = SequenceMatcher(None, fo, autre)
            if s.real_quick_ratio() >= 0.8 and s.quick_ratio() >= 0.8 and s.ratio() >= 0.8:
                return True
        return False

    # Variantes.

    def groupes(self) -> tuple[list[Variantes], list[list[str]]]:
        """Groupes de variantes proposés, et groupes laissés de côté parce qu'ils réunissent plusieurs tags protégés."""
        par_forme: dict[str, list[str]] = defaultdict(list)
        for n, u in self.u.items():
            if not u.confidentiel and filtre.forme(n) not in self.exclus:
                par_forme[forme(n, self.cfg)].append(n)
        res, ecartes = [], []
        for fo, noms in sorted(par_forme.items()):
            if len(noms) < 2:
                continue
            noms.sort(key=lambda n: (-len(self.u[n].fiches), n))
            fiches = set().union(*(self.u[n].fiches for n in noms))
            if not (any(n in self.forts for n in noms) or len(fiches) >= self.cfg.tags.seuil_candidat
                    or fo in self.formes_concepts_themes):
                continue  # automatiques ou importés seulement, et rares : la règle globale s'en charge
            proteges = [n for n in noms if self.protection(n)]
            if len(proteges) > 1:
                ecartes.append(noms)
                continue
            cible = proteges[0] if proteges else self._gagnante(noms)
            evident = len({forme_faible(n, self.cfg) for n in noms}) == 1
            res.append(Variantes(noms, cible, EVIDENT if evident else DOUTEUX,
                                 note='' if evident else 'pluriel ou autre différence que la casse et les accents'))
        return res, ecartes

    def _gagnante(self, noms: list[str]) -> str:
        """Le concept, puis le tag manuel le plus porté, puis la forme en minuscules accentuée (D156). Dès qu'un des
        noms est écrit en minuscules, la cible l'est aussi, pour que les cibles suivent une même casse (« #Mémoire »
        et « #memoire » donnent « #mémoire »). Les capitales ne restent que si tous les noms en portent (nom propre)."""
        def poids(n):
            return len(self.u[n].fiches), not n.isascii(), n == n.lower(), n
        concepts = [n for n in noms if self.est_concept(n)]
        forts = [n for n in noms if n in self.forts]
        if concepts:
            gagnante = max(concepts, key=poids)
        elif forts:
            gagnante = max(forts, key=poids)
        else:
            return max(noms, key=lambda n: (not n.isascii(), len(self.u[n].fiches), n)).lower()
        return gagnante.lower() if any(n == n.lower() for n in noms) else gagnante

    # Entrées [[tag]].

    def cumul(self, noms: list[str]) -> Usage:
        """Usage réuni des noms d'un groupe de variantes, porté par sa cible une fois le groupe fusionné."""
        c = Usage(noms[-1])
        for n in dict.fromkeys(noms):
            x = self.u.get(n)
            if x is None:
                continue
            c.types |= x.types
            c.occurrences.update(x.occurrences)
            c.elements |= x.elements
            c.fiches |= x.fiches
            c.enfants += x.enfants
            c.annotations += x.annotations
            c.recherches += [rech for rech in x.recherches if rech not in c.recherches]
        themes = themes_des_fiches(self.b, self.cfg) if c.fiches else {}
        for fiche in c.fiches:
            c.themes.update(themes.get(fiche, ()))
        return c

    def entrees(self, groupes: list[Variantes]) -> list[Entree]:
        dans_groupes = {n for g in groupes for n in g.noms if n != g.cible}
        self.cumuls = {g.cible: self.cumul([*g.noms, g.cible]) for g in groupes}
        res = []
        for n in sorted(set(self.u) | set(self.cumuls), key=norm):
            u = self.cumuls.get(n) or self.u[n]
            # Un tag protégé seulement par une proposition de rangement garde son entrée, qui attend ce rangement.
            if u.confidentiel or n in dans_groupes or self.est_concept(n) or (self.protection(n) and n not in self.attente):
                continue
            etat = self.etrangers.get(forme(n, self.cfg)) if 0 in u.types else None
            if etat and etat != n:
                e = self.stats(Entree(n), u)
                e.sort, e.cible, e.note = ETAT, etat, 'état ou marque venu d\'une autre habitude, à confirmer'
                res.append(e)
                continue
            if n not in self.cumuls and (u.types == {1} or n in self.importes) and not self.candidat(n) \
                    and not u.recherches:
                continue  # retiré par la règle globale, sans examen
            res.append(self.proposer(self.stats(Entree(n), u), u))
        return res

    def stats(self, e: Entree, u: Usage | None = None) -> Entree:
        u = u or self.u.get(e.nom)
        if u is None:
            e.effectif, e.dispersion, e.themes, e.recherches = 0, 0, [], []
            return e
        e.type = u.type_lisible + (', importé' if e.nom in self.importes else '')
        e.effectif, e.dispersion = len(u.fiches), u.dispersion
        e.themes = [t for t, _ in u.themes.most_common(3)]
        e.recherches = list(u.recherches)
        return e

    def proposer(self, e: Entree, u: Usage | None = None) -> Entree:
        n, u, cfg = e.nom, u or self.u[e.nom], self.cfg
        theme_meme_nom = self.themes_par_forme.get(forme(n, cfg))
        if n in self.lies:
            e.sort, e.theme = SUPPRIMER, self.lies[n]
            e.note = f'relié au thème « {e.theme} » dans suivi/fonds.toml, il le double'
        elif theme_meme_nom:
            e.sort, e.theme = SUPPRIMER, theme_meme_nom
            e.note = f'même nom que le thème « {e.theme} », il le double'
        elif _marque_technique(n, cfg):
            e.sort, e.classe = SUPPRIMER, EVIDENT
            e.note = "marque technique d'une application (« /unread », « _tablet »…), pas une notion"
        elif len(u.elements) == 1 and 0 in u.types and not u.annotations and not u.recherches and not self.ressemble(n):
            e.sort, e.classe, e.note = SUPPRIMER, EVIDENT, 'porté par une seule fiche, sans ressemblance avec un concept ou un thème'
        elif u.dispersion >= cfg.tags.dispersion_concept:
            e.sort, e.cible = CONCEPT, nom_de_concept(n, cfg)
            e.note = (f'réparti sur {u.dispersion} thèmes du fonds, nom à vérifier (minuscules sauf nom propre, dans la '
                      "langue de l'utilisateur) et définition à proposer")
        elif u.dispersion == 1 and len(u.fiches) > 1:
            e.sort, e.theme = SUPPRIMER, next(iter(u.themes))
            e.note = f'concentré dans le thème « {e.theme} », il le double'
        elif u.types == {0, 1}:
            e.sort, e.cible = FUSIONNER, n
            e.note = 'porté aussi en manuel, ses occurrences automatiques deviendraient manuelles'
        elif u.types == {1} or n in self.importes:
            e.sort, e.note = SUPPRIMER, 'la règle globale le retirerait sans cette exception'
        if u.recherches:
            e.note = (e.note + '. ' if e.note else '') + 'cité par une recherche enregistrée'
            e.classe = DOUTEUX
        return e

    def hors_du_theme(self, nom: str, theme: str, autres=()) -> set[int]:
        """Fiches qui portent `nom` (ou l'un des `autres` noms qui lui sont ramenés) sans être encore dans `theme` ou
        l'un de ses sous-thèmes."""
        fiches = set()
        for n in (nom, *autres):
            if (u := self.cumuls.get(n) or self.u.get(n)) is not None:
                fiches |= u.fiches
        if self.racine_fonds is None:
            return fiches
        e = self.etat
        res = set()
        for i in fiches:
            el = self.b.elements[i]
            chemins = [e.chemin(e.cle[c]).split('/', 1)[1] for c in el.collections
                       if e.cle[c] != self.racine_fonds and e.sous(e.cle[c], self.racine_fonds)]
            if not any(c == theme or c.startswith(theme + '/') for c in chemins):
                res.add(i)
        return res

    def propositions_rangement(self, s: Suivi) -> list[r.Entree]:
        """Fiches d'un tag qui double un thème, absentes de ce thème, proposées au rangement (D154, D116)."""
        if not self.plan or self.racine_fonds is None:
            return []
        e = self.etat
        deja = {x.cle for x in self.rangement}
        inbox = e.racine(self.cfg.methode.inbox) if self.cfg.methode.inbox else None
        res = []
        for x in s.tags:
            if x.sort != SUPPRIMER or not x.theme or x.decision == REFUSER or x.theme not in self.plan.noeuds:
                continue
            u = self.cumuls.get(x.nom) or self.u.get(x.nom)
            if u is None or u.confidentiel:
                continue
            for i in sorted(u.fiches, key=lambda i: self.b.elements[i].cle):
                el = self.b.elements[i]
                if el.cle in deja or el.cle in self.masquees:
                    continue
                chemins = [e.chemin(e.cle[c]).split('/', 1)[1] for c in el.collections
                           if e.cle[c] != self.racine_fonds and e.sous(e.cle[c], self.racine_fonds)]
                if any(c == x.theme or c.startswith(x.theme + '/') for c in chemins):
                    continue
                depuis = next((e.cle[c] for c in el.collections if inbox and e.sous(e.cle[c], inbox)), '')
                res.append(r.Entree(el.cle, r.DEPLACER if depuis else r.AJOUTER, x.theme, depuis, r.TAG, '',
                                    f'tag « {x.nom} »'))
                deja.add(el.cle)
        return res


def mettre_a_jour(ancien: Suivi, detecte: Suivi, a: _Analyse) -> Suivi:
    """Garde les décisions et les entrées de l'agent ou de l'utilisateur, renouvelle les propositions de zc encore en
    attente, retire celles dont les tags ont disparu. Une règle décidée reste, pour le tri des références à venir."""
    s = Suivi(ancien.automatiques, ancien.importes)
    gardees = {e.nom: e for e in ancien.tags if e.decision or e.source != ZC}
    vus = set()
    for e in ancien.tags:
        if e.nom in gardees and e.nom not in vus:
            nom = a.reel(e.nom)
            ref = a.stats(Entree(nom), a.cumuls.get(nom))
            e.type = ref.type or e.type
            e.effectif, e.dispersion, e.themes, e.recherches = ref.effectif, ref.dispersion, ref.themes, ref.recherches
            s.tags.append(e)
            vus.add(e.nom)
    s.tags += [e for e in detecte.tags if e.nom not in gardees]
    s.tags.sort(key=lambda e: norm(e.nom))

    figes = [g for g in ancien.variantes if g.decision or g.source != ZC]
    s.variantes = list(figes)
    for d in detecte.variantes:
        couverts = set()
        cible = d.cible
        for g in figes:
            membres = set(g.noms) | {g.cible}
            if membres & set(d.noms):
                couverts |= membres
                cible = g.cible
        reste = [n for n in d.noms if n not in couverts]
        if not reste:
            continue
        if couverts:
            d = Variantes([*reste, *([cible] if cible in a.u and cible not in reste else [])], cible, d.classe,
                          note='nouveaux noms pour une forme déjà jugée')
        s.variantes.append(d)
    return s


def fondre(s: Suivi) -> list[Variantes]:
    """Réunit dans l'entrée [[tag]] de sa cible un groupe de variantes proposé par zc vers un nom que zc propose de
    supprimer, pour ne pas proposer à la fois de ramener des noms à un tag et de supprimer ce tag. Les noms du groupe
    passent dans `variantes` de l'entrée, supprimés avec elle. Rend les groupes retirés."""
    par_nom = {e.nom: e for e in s.tags}
    couverts = {v for e in s.tags for v in e.variantes}
    gardes, fondus = [], []
    for g in s.variantes:
        if g.source != ZC or g.decision:
            gardes.append(g)
            continue
        autres = [n for n in g.noms if n != g.cible and n not in couverts]
        e = par_nom.get(g.cible)
        if not autres:
            fondus.append(g)  # déjà réunis dans une entrée [[tag]]
        elif e is not None and e.sort == SUPPRIMER and not e.decision and e.source == ZC:
            e.variantes += [n for n in autres if n not in e.variantes]
            couverts |= set(autres)
            fondus.append(g)
        else:
            if e is not None and e.sort == SUPPRIMER and e.decision == ACCEPTER:
                g.note = (g.note + '. ' if g.note else '') + (f'« {g.cible} » est déjà supprimé par une règle acceptée, '
                                                              'accepter ce groupe supprime aussi ces noms')
            gardes.append(g)
    s.variantes = gardes
    return fondus


# --- Inventaire -------------------------------------------------------------------

def inventaire(b: Bibliotheque, cfg: Config, jour: date | None = None) -> tuple[str, Suivi]:
    """Rapport d'inventaire et suivi mis à jour (à écrire par `ecrire`), lecture seule."""
    a = _Analyse(b, cfg)
    groupes, ecartes = a.groupes()
    detecte = Suivi(tags=a.entrees(groupes), variantes=groupes)
    suivi = mettre_a_jour(charger(cfg), detecte, a)
    fondus = fondre(suivi)
    suivi.a_ranger = a.propositions_rangement(suivi)
    a.attente |= {x.note[len('tag « '):-len(' »')] for x in suivi.a_ranger}

    # Ce que les règles globales retireraient, une fois acceptées, avec les exceptions en attente.
    simule = _regles(a, suivi, simuler=True)
    retires: dict[str, Counter] = {'automatique': Counter(), 'importé': Counter()}
    for el in b.elements.values():
        for nom, sorte in _viser(el.tags, el.type == 'annotation', simule, el.id).retires:
            if sorte in retires:
                retires[sorte][nom] += 1
    autos = {n: u for n, u in a.u.items() if 1 in u.types}
    occ_autos = sum(u.occurrences[1] for u in autos.values())
    suivi.resume_automatiques = (
        f"{pluriel(len(autos), 'nom')} automatique(s), {occ_autos} occurrence(s). La règle en retire "
        f"{len(retires['automatique'])} nom(s) et {sum(retires['automatique'].values())} occurrence(s), les "
        'exceptions sont dans les [[tag]] et [[variantes]] en attente.')
    if a.lot:
        suivi.resume_importes = (
            f"{pluriel(len(a.lot), 'fiche')} porte(nt) plus de {cfg.tags.seuil_mots_cles} tags manuels hors familles, "
            f"rares pour la plupart (mots-clés importés). {len(retires['importé'])} nom(s) et "
            f"{sum(retires['importé'].values())} occurrence(s) retirés si la règle est acceptée.")
    groupes = [g for g in groupes if not any(g is x for x in fondus)]
    return _rapport_inventaire(a, suivi, groupes, ecartes, retires, jour or date.today(), len(fondus)), suivi


def _rapport_inventaire(a: _Analyse, s: Suivi, groupes: list[Variantes], ecartes: list[list[str]],
                        retires: dict[str, Counter], jour: date, fondus: int = 0) -> str:
    b, cfg, u = a.b, a.cfg, a.u
    publics = {n: x for n, x in u.items() if not x.confidentiel}
    occurrences = sum(sum(x.occurrences.values()) for x in u.values())
    manuels = sum(1 for x in u.values() if 0 in x.types)
    autos = sum(1 for x in u.values() if 1 in x.types)
    L = [f'# Inventaire des tags, {jour:%d/%m/%Y}', '',
         "Lecture seule, rien n'a été modifié. Les règles à juger sont dans `suivi/tags.toml`, qui garde les décisions "
         "d'une fois sur l'autre. `zc tags planifier` applique les règles acceptées.", '',
         f"{pluriel(len(u), 'nom')} de tags, {occurrences} occurrence(s) sur les fiches, pièces jointes, notes et "
         f"annotations (corbeille exclue). {manuels} nom(s) posé(s) en manuel, {autos} en automatique "
         '(mots-clés des éditeurs, ajoutés par Zotero).']

    L += ['', '## Règle globale des tags automatiques', '', s.resume_automatiques,
          f"Décision actuelle : « {s.automatiques or 'à prendre'} ». Une seule approbation suffit. Les exceptions sont "
          f"les tags automatiques portés par au moins {cfg.tags.seuil_candidat} fiches ou de même forme qu'un tag "
          'manuel, un concept ou un thème. Les tags protégés et ceux cités par une recherche enregistrée y échappent.']
    if retires['automatique']:
        L += ['', 'Les plus portés parmi les noms retirés : ' + ', '.join(
            f'{_affiche(a, n)} ({k})' for n, k in retires['automatique'].most_common(15)) + '.']

    if a.lot:
        L += ['', '## Mots-clés importés en tags manuels', '', s.resume_importes,
              f"Décision actuelle : « {s.importes or 'à prendre'} ». Exemples de fiches :", '']
        for i in sorted(a.lot, key=lambda i: norm(b.elements[i].titre))[:10]:
            el = b.elements[i]
            hors = [n for n, t in el.tags if t == 0 and n in a.importes]
            L.append(f'- {el.cle} · {_ligne(el)} · {len(hors)} tags, dont ' + ', '.join(hors[:6]))

    evidents = [g for g in groupes if g.classe == EVIDENT]
    L += ['', '## Variantes', '',
          f"{pluriel(len(groupes), 'groupe')} de noms de même forme, dont {len(evidents)} évident(s) (casse, accents, "
          "espaces, tirets ou préfixe seulement, à approuver en bloc) et les autres douteux (pluriel, par paquets de "
          "10). La cible suit la règle fixe (concept, puis tag manuel le plus porté, puis forme en minuscules "
          "accentuée). Les traductions ne sont pas repérées, l'agent peut en proposer.", '']
    L += [f"- {g.classe} : {' / '.join(_affiche(a, n) for n in g.noms)} → {g.cible}" for g in groupes]
    if fondus:
        L += ['', f"{pluriel(fondus, 'autre groupe')} réuni(s) à l'entrée `[[tag]]` de sa cible, que zc propose de "
                  "supprimer (champ `variantes`). Accepter l'entrée supprime aussi ces noms, la garder les y ramène."]
    if ecartes:
        L += ['', 'Groupes qui réunissent plusieurs tags protégés, laissés de côté (à régler dans Zotero, '
                  '« Renommer le tag… ») :', '']
        L += [f"- {' / '.join(n)}" for n in ecartes]

    def section(titre: str, texte: str, entrees: list[Entree]):
        if entrees:
            L.extend(['', f'## {titre}', '', texte, ''])
            L.extend(_ligne_entree(e) for e in entrees)

    attente = [e for e in s.tags if not e.decision]
    section('États et marques venus d\'autres habitudes', 'Rapprochés des états et marques de la méthode par un petit '
            'dictionnaire. Rien d\'office. Une fiche qui recevrait deux états garde le plus avancé.',
            [e for e in attente if e.sort == ETAT])
    section('Concepts proposés', f'Tags répartis sur au moins {cfg.tags.dispersion_concept} thèmes du fonds. '
            "L'agent propose le nom (`cible`) et une définition courte pour la section `# Concepts` de plan.md.",
            [e for e in attente if e.sort == CONCEPT])
    section('Tags qui doublent un thème', 'Proposés à la suppression. Les fiches qui portent le tag sans être '
            'dans le thème sont d\'abord proposées dans `suivi/rangement.toml` (source « tag »), et le tag reste '
            'en place tant que ces propositions attendent.', [e for e in attente if e.sort == SUPPRIMER and e.theme])
    if s.a_ranger:
        L += ['', f"{pluriel(len(s.a_ranger), 'proposition')} de rangement ajoutée(s) à `suivi/rangement.toml`."]
    uniques = [e for e in attente if e.sort == SUPPRIMER and e.classe == EVIDENT]
    section('Tags portés par une seule fiche', 'Sans ressemblance avec un concept ou un thème, évidents à supprimer, '
            'à approuver en bloc (liste complète).', uniques)
    autres = [e for e in attente if e not in uniques and e.sort not in (ETAT, CONCEPT)
              and not (e.sort == SUPPRIMER and e.theme)]
    section('Autres tags à juger', 'Tags manuels hors familles et exceptions à la règle globale, par paquets de 20 avec '
            'leur effectif, leur dispersion et trois titres (dans `suivi/tags.toml`). Sorts possibles : supprimer, '
            'garder, concept, fusionner. Garder est légitime.', autres)
    decidees = [e for e in s.tags if e.decision]
    if decidees:
        L += ['', '## Règles déjà décidées', '',
              f"{pluriel(len(decidees), 'entrée')} jugée(s), dont {sum(e.decision == ACCEPTER for e in decidees)} "
              'acceptée(s). Elles restent dans le fichier et servent au tri des références à venir.']

    proteges = sorted(((n, a.protection(n)) for n in publics if a.protection(n)), key=lambda x: norm(x[0]))
    L += ['', '## Tags protégés', '',
          'Inventoriés sans proposition. Ils ne changent que par une entrée de source « utilisateur ». Pour renommer '
          'un tag coloré, passer par « Renommer le tag… » dans Zotero, qui reporte la couleur.', '']
    L += [f'- {n} ({raison}, {len(u[n].fiches)} fiche(s))' for n, raison in proteges] or ['- aucun']
    L += ['', f"Tags colorés : {len(b.couleurs)} sur {MAX_COULEURS}, {MAX_COULEURS - len(b.couleurs)} place(s) libre(s)."]
    for rang, (n, couleur) in enumerate(b.couleurs, 1):
        L.append(f'- {rang}. {_affiche(a, n)} ({couleur})' + ('' if n in u else ', porté par aucun élément'))

    cites = [(rech, op, val) for rech, op, val in b.recherches_tags]
    if cites:
        L += ['', '## Recherches enregistrées qui citent un tag', '',
              "Un tag cité échappe aux règles globales, et n'est supprimé ou renommé que par une entrée acceptée. Le "
              'rapport du plan rappelle alors de mettre la recherche à jour dans Zotero.', '']
        for rech, op, val in cites:
            noms = [_affiche(a, n) for n, x in u.items() if rech in x.recherches]
            L.append(f'- « {rech} » : tag {op} « {_affiche(a, val) if val in u else val} »'
                     + (f" ({', '.join(noms)})" if noms else ', aucun tag porté ne correspond'))

    confidentiels = sorted((n for n, x in u.items() if x.confidentiel), key=identifiant)
    if confidentiels:
        L += ['', '## Tags de fiches confidentielles', '',
              'Portés seulement par des fiches exclues par le filtre, ils apparaissent sous un identifiant. Seules les '
              'règles globales s\'y appliquent, le reste par une entrée de source « utilisateur » nommée par '
              "l'identifiant.", '']
        L += [f'- {identifiant(n)} ({u[n].type_lisible}, {len(u[n].elements)} élément(s))' for n in confidentiels]

    enfants = sorted(n for n, x in publics.items() if x.enfants == len(x.elements))
    if enfants:
        L += ['', '## Tags portés seulement par des pièces jointes, notes ou annotations', '',
              'Les mêmes règles s\'y appliquent. Les tags d\'annotations, posés à la main dans le lecteur, ne comptent '
              'jamais parmi les mots-clés importés.', '']
        L += [f'- {n} ({len(u[n].elements)} élément(s), dont {u[n].annotations} annotation(s))' for n in enfants]
    return '\n'.join(L) + '\n'


def _ligne(el: Element) -> str:
    return f'{el.auteur or "?"}, {annee(el) or "s. d."}, {el.titre[:80] or "(sans titre)"}'


def _ligne_entree(e: Entree) -> str:
    morceaux = [f'{e.type}', f'{e.effectif} fiche(s)', f'dispersion {e.dispersion}']
    if e.themes:
        morceaux.append('thèmes ' + ', '.join(e.themes))
    propose = e.sort + (f' → {e.cible}' if e.cible else '') + (f' (double {e.theme})' if e.theme else '')
    if e.variantes:
        propose += f", avec ses variantes {', '.join(e.variantes)}"
    return f"- {e.nom} ({', '.join(morceaux)})" + (f' : {propose}' if e.sort else ' : sort à proposer') + \
        (f'. {e.note}' if e.note else '')


def _affiche(a: _Analyse, nom: str) -> str:
    return identifiant(nom) if nom in a.u and a.u[nom].confidentiel else nom


# --- Règles -----------------------------------------------------------------------

@dataclass
class Regles:
    automatiques: bool = False
    importes: set[str] = field(default_factory=set)
    exclus: set[str] = field(default_factory=set)
    proteges: set[str] = field(default_factory=set)
    exemptes: set[str] = field(default_factory=set)  # échappent aux règles globales
    renommer: dict[str, tuple[str, str]] = field(default_factory=dict)  # nom -> (cible, sorte)
    supprimer: set[str] = field(default_factory=set)
    etats: list[str] = field(default_factory=list)
    confidentiels: set[str] = field(default_factory=set)
    cites: dict[str, list[str]] = field(default_factory=dict)  # tag -> recherches enregistrées qui le citent
    # Tag qui double un thème -> fiches pas encore dans ce thème, où il reste jusqu'au rangement (D154).
    garder_sur: dict[str, set[int]] = field(default_factory=dict)
    fiche_de: dict[int, int] = field(default_factory=dict)  # élément -> sa fiche
    problemes: list[str] = field(default_factory=list)

    def suivre(self, nom: str) -> tuple[str, set[str]]:
        """Cible finale d'un renommage, en suivant les chaînes (variante, puis concept), et sortes rencontrées."""
        sortes, vus = set(), {nom}
        while nom in self.renommer:
            cible, sorte = self.renommer[nom]
            sortes.add(sorte)
            if cible in vus or cible == nom:
                return cible, sortes
            vus.add(cible)
            nom = cible
        return nom, sortes


def regles(suivi: Suivi, cfg: Config, b: Bibliotheque) -> Regles:
    """Règles acceptées de `suivi/tags.toml`. La bibliothèque sert à reconnaître les tags protégés (colorés, en
    attente d'un rangement), cités par une recherche ou confidentiels, et les mots-clés importés."""
    return _regles(_Analyse(b, cfg), suivi)


def _regles(a: _Analyse, s: Suivi, simuler: bool = False) -> Regles:
    R = Regles(automatiques=simuler or s.automatiques == ACCEPTER, exclus=set(a.exclus), etats=list(a.etats))
    R.fiche_de = {el.id: f for el in a.b.elements.values() if (f := fiche_de(a.b, el)) is not None}
    if simuler or s.importes == ACCEPTER:
        R.importes = set(a.importes)
    R.proteges = {n for n in a.u if a.protection(n)} | set(a.cfg.tags.proteges) | set(a.cfg.methode.etats) \
        | set(a.cfg.methode.autres_tags) | a.couleurs | a.attente
    R.confidentiels = {n for n, x in a.u.items() if x.confidentiel}
    R.cites = {n: x.recherches for n, x in a.u.items() if x.recherches}
    R.exemptes = set(R.cites)

    def autorise(nom: str, source: str) -> bool:
        if nom in a.attente:
            R.problemes.append(f'« {_affiche(a, nom)} » attend le jugement de propositions de rangement qui reposent '
                               'sur lui (suivi/rangement.toml). Règle appliquée une fois ces propositions jugées.')
            return False
        if nom in R.exclus:
            R.problemes.append(f'« {_affiche(a, nom)} » sert au filtre de confidentialité, il ne change jamais.')
            return False
        if (nom in R.proteges or nom in R.confidentiels) and source != UTILISATEUR:
            quoi = 'protégé' if nom in R.proteges else 'porté seulement par des fiches confidentielles'
            R.problemes.append(f'« {_affiche(a, nom)} » est {quoi}, seule une entrée de source « utilisateur » le '
                               'change. Règle ignorée.')
            return False
        return True

    for g in s.variantes:
        noms = [a.reel(n) for n in g.noms]
        if g.decision == '':
            R.exemptes |= set(noms)
        elif g.decision == ACCEPTER:
            for n in noms:
                if autorise(n, g.source):
                    R.renommer[n] = (g.cible, 'variante')
            R.exemptes.add(g.cible)
    for e in s.tags:
        n = a.reel(e.nom)
        variantes = [a.reel(v) for v in e.variantes]
        if e.decision == '':
            R.exemptes |= {n, *variantes}
            continue
        if e.decision == REFUSER:
            continue
        if not autorise(n, e.source):
            R.exemptes |= {n, *variantes}
            continue
        for v in variantes:  # ramenées au nom de l'entrée, puis soumises à son sort
            if v != n and autorise(v, e.source):
                R.renommer[v] = (n, 'variante')
        if e.sort == SUPPRIMER:
            R.supprimer.add(n)
            ramenes = [v for v, (c, _) in R.renommer.items() if c == n]
            if e.theme and (hors := a.hors_du_theme(n, e.theme, ramenes)):
                R.garder_sur[n] = hors
                R.problemes.append(f'« {_affiche(a, n)} » double le thème « {e.theme} », mais '
                                   f'{pluriel(len(hors), "fiche")} qui le {"portent" if len(hors) > 1 else "porte"} '
                                   f"n'{'y sont' if len(hors) > 1 else 'y est'} pas encore. Il y reste jusqu'à "
                                   f"{'leur' if len(hors) > 1 else 'son'} rangement.")
        elif e.sort == GARDER:
            R.exemptes.add(n)
        elif e.sort in SORTE_DU_SORT:
            R.renommer[n] = (e.cible, SORTE_DU_SORT[e.sort])
        else:
            R.problemes.append(f'« {_affiche(a, n)} » est accepté sans sort. Règle ignorée.')
            R.exemptes.add(n)
    return R


@dataclass
class Vise:
    tags: list[dict]
    sortes: set[str] = field(default_factory=set)
    retires: list[tuple[str, str]] = field(default_factory=list)  # (nom, sorte)
    renommes: list[tuple[str, str, str]] = field(default_factory=list)  # (nom, cible, sorte)


def _viser(tags: list[tuple[str, int]], annotation: bool, R: Regles, element: int | None = None) -> Vise:
    """`element` (identifiant) sert à garder un tag qui double un thème sur une fiche pas encore rangée (D154)."""
    res: dict[str, int] = {}
    fiche = R.fiche_de.get(element) if element is not None else None

    def supprime(nom: str) -> bool:
        return nom in R.supprimer and fiche not in R.garder_sur.get(nom, ())

    v = Vise([])
    etat_ajoute = False

    def poser(nom: str, typ: int):
        res[nom] = min(res.get(nom, typ), typ)

    for nom, typ in tags:
        if nom in R.exclus:
            poser(nom, typ)
            continue
        if nom in R.renommer:
            cible, sortes = R.suivre(nom)
            if supprime(cible):
                v.retires.append((nom, 'suppression'))
                v.sortes.add('suppression')
                continue
            poser(cible, 0)
            if (cible, 0) != (nom, typ):
                sorte = sorted(sortes)[0] if len(sortes) == 1 else ('variante' if 'variante' in sortes else
                                                                    sorted(sortes)[0])
                v.renommes.append((nom, cible, sorte))
                v.sortes |= sortes
                etat_ajoute |= cible in R.etats and cible != nom
            continue
        if supprime(nom):
            v.retires.append((nom, 'suppression'))
            v.sortes.add('suppression')
            continue
        libre = nom not in R.proteges and nom not in R.exemptes
        if libre and typ == 1 and R.automatiques:
            v.retires.append((nom, 'automatique'))
            v.sortes.add('automatique')
            continue
        if libre and typ == 0 and nom in R.importes and not annotation:
            v.retires.append((nom, 'importé'))
            v.sortes.add('importé')
            continue
        poser(nom, typ)
    if etat_ajoute:
        presents = [e for e in R.etats if e in res]
        for e in presents[:-1]:  # l'état le plus avancé l'emporte (D156)
            del res[e]
            v.retires.append((e, 'état'))
            v.sortes.add('état')
    v.tags = [{'tag': n} if t == 0 else {'tag': n, 'type': 1} for n, t in res.items()]
    return v


def tags_vises(element: Element, R: Regles) -> list[dict]:
    """Liste complète des tags d'un élément après les règles, au format de l'API (`{"tag": …}` pour un tag manuel,
    `{"tag": …, "type": 1}` pour un automatique conservé), sans doublon. Fonction pure, reprise par le tri."""
    return _viser(element.tags, element.type == 'annotation', R, element.id).tags


def a_signaler(element: Element, R: Regles, cfg: Config) -> list[str]:
    """Tags manuels hors familles d'un élément qu'aucune règle ne couvre, à soumettre à l'utilisateur (D155)."""
    m = cfg.methode
    connus = R.proteges | R.exemptes | set(R.renommer) | R.supprimer | R.importes | R.exclus
    return [n for n, t in element.tags if t == 0 and n not in connus
            and not (m.prefixe_concept and n.startswith(m.prefixe_concept))
            and not (m.prefixe_technique and n.startswith(m.prefixe_technique))]


# --- Plan -------------------------------------------------------------------------

def _tags_api(data: dict) -> list[tuple[str, int]]:
    return [(t['tag'], int(t.get('type', 0))) for t in data.get('tags') or []]


def planifier(b: Bibliotheque, cfg: Config, client: Client, jour: date | None = None) -> tuple[Plan, str]:
    """Plan d'une opération par élément dont les tags changent, d'après les règles acceptées (D156)."""
    if (serveur := client.version_serveur()) > b.version:
        raise SystemExit(f'Zotero n\'a pas encore reçu les derniers changements de la bibliothèque (version locale '
                         f'{b.version}, version du serveur {serveur}). Vérifier que Zotero est ouvert et synchronise, '
                         'puis relancer.')
    a = _Analyse(b, cfg)
    suivi = charger(cfg)
    R = _regles(a, suivi)

    def actuels(tags):
        return normaliser('tags', [{'tag': n, 'type': t} for n, t in tags])

    candidats = [el for el in b.elements.values()
                 if normaliser('tags', _viser(el.tags, el.type == 'annotation', R, el.id).tags) != actuels(el.tags)]
    api = client.fiches([el.cle for el in candidats])
    retenus: list[tuple[Element, Operation, Vise]] = []
    for el in candidats:
        d = api.get(el.cle)
        if d is None:
            R.problemes.append(f'L\'élément {el.cle} n\'existe plus dans Zotero, laissé de côté.')
            continue
        avant = list(d.get('tags') or [])
        v = _viser(_tags_api(d), el.type == 'annotation', R, el.id)
        if normaliser('tags', v.tags) == normaliser('tags', avant):
            continue
        op = Operation(el.cle, {'tags': avant}, {'tags': v.tags}, nature=', '.join(s for s in SORTES if s in v.sortes))
        retenus.append((el, op, v))

    couleurs = _couleurs(cfg, client.reglages([COULEURS])[COULEURS]['value'])
    essai = cfg.ecriture.essai - bool(couleurs)
    retenus = _ordonner(retenus, essai, a.masquees)
    groupes = [Groupe(el.cle, _titre(b, el, a.masquees), [op]) for el, op, _ in retenus]
    if couleurs:  # premier groupe, donc dans l'essai
        groupes.insert(0, Groupe(COULEURS, 'couleurs des tags de la méthode', [couleurs]))
    plan = Plan(ETAPE, client.utilisateur, groupes, description=f"Tags, {pluriel(len(retenus), 'élément')}"
                + (', et couleurs des tags de la méthode.' if couleurs else '.'))
    return plan, _rapport_plan(a, R, retenus, essai, jour or date.today(), couleurs)


COULEURS = 'tagColors'


def _couleurs(cfg: Config, actuelles) -> Operation | None:
    """Tags de la méthode colorés et placés en tête, dans l'ordre des états puis des autres tags, pour recevoir les
    touches 1, 2, 3… (D175). Un tag de la méthode déjà coloré garde sa couleur. Les autres tags colorés gardent la
    leur et suivent. Colorés même encore inutilisés, pour être visibles et à portée de touche dès le départ."""
    m = cfg.methode
    actuelles = [c for c in actuelles or [] if isinstance(c, dict) and c.get('name')]
    deja = {c['name']: c for c in actuelles}
    methode = [{'name': n, 'color': deja[n]['color'] if n in deja else couleur}
               for n, couleur in zip([*m.etats, *m.autres_tags], m.couleurs)]
    noms = {c['name'] for c in methode}
    voulues = methode + [c for c in actuelles if c['name'] not in noms]
    if voulues == actuelles or not methode:
        return None
    return Operation(COULEURS, {'value': actuelles or None}, {'value': voulues},
                     nature='couleurs des tags de la méthode', genre='settings')


def _ordonner(retenus: list, essai: int, masquees: set[str]) -> list:
    """Les premiers groupes, appliqués par l'essai, couvrent chaque sorte de changement présente (D156)."""
    def cle(x):
        el = x[0]
        return norm(el.titre), el.cle

    restants = sorted(retenus, key=cle)
    reste = set().union(*(x[2].sortes for x in restants)) if restants else set()
    premiers = []
    while reste and len(premiers) < essai:
        # Le plus de sortes encore absentes, une fiche visible plutôt qu'un enfant ou une fiche confidentielle,
        # puis l'ordre des titres.
        _, x = max(enumerate(restants), key=lambda ix: (len(ix[1][2].sortes & reste), ix[1][0].est_fiche,
                                                         ix[1][0].cle not in masquees, -ix[0]))
        premiers.append(x)
        restants.remove(x)
        reste -= x[2].sortes
    return premiers + restants


def _titre(b: Bibliotheque, el: Element, masquees: set[str]) -> str:
    if el.cle in masquees:
        return filtre.MASQUE
    if el.est_fiche:
        return _ligne(el)
    fiche = fiche_de(b, el)
    quoi = {'attachment': 'pièce jointe', 'note': 'note', 'annotation': 'annotation'}.get(el.type, el.type)
    if fiche is None:
        return f'{quoi} isolée'
    return f'{quoi} de « {b.elements[fiche].titre[:60] or "sans titre"} »'


def _liste(tags: list, a: _Analyse) -> str:
    return ', '.join(f"{_affiche(a, t['tag'])}{' (auto)' if t.get('type') == 1 else ''}" for t in tags) or 'aucun'


def _rapport_couleurs(op: Operation) -> list[str]:
    avant = {c['name']: (i, c['color']) for i, c in enumerate(op.avant['value'] or [], 1)}
    L = ['', '## Couleurs', '',
         'Les tags de la méthode reçoivent une couleur et les premiers rangs du sélecteur de tags. Dans Zotero, la '
         'touche du rang (1 à 9) pose ou retire le tag sur les fiches sélectionnées, et une pastille de sa couleur '
         'marque chaque fiche qui le porte. Le premier groupe du plan, donc dans l\'essai.', '']
    for i, c in enumerate(op.apres['value'], 1):
        if c['name'] not in avant:
            quoi = 'nouvelle couleur'
        elif avant[c['name']][0] != i:
            quoi = f'gardait le rang {avant[c["name"]][0]}, touche changée'
        else:
            continue
        L.append(f"- {i}. {c['name']} ({c['color']}), {quoi}" if i <= 9 else f"- {i}. {c['name']}, {quoi}, sans touche")
    if len(op.apres['value']) > 9:
        L.append(f"- Au-delà du rang 9, {pluriel(len(op.apres['value']) - 9, 'tag coloré')} sans touche.")
    return L


def _rapport_plan(a: _Analyse, R: Regles, retenus: list, essai: int, jour: date,
                  couleurs: Operation | None = None) -> str:
    b = a.b
    fiches = sum(1 for el, _, _ in retenus if el.est_fiche)
    L = [f'# Plan des tags du {jour:%d/%m/%Y}', '']
    if not retenus:
        L.append('Aucun tag à changer sur les éléments, seulement les couleurs.')
    else:
        L.append(f"{pluriel(len(retenus), 'élément')} à modifier, dont {fiches} fiche(s) et "
                 f'{len(retenus) - fiches} pièce(s) jointe(s), note(s) ou annotation(s). Un groupe par élément, qui '
                 'reçoit sa liste complète de tags. Un '
                 'tag automatique conservé garde son type, un tag renommé devient manuel.')
    if couleurs:
        L += _rapport_couleurs(couleurs)
    par_sorte = Counter(s for _, _, v in retenus for s in v.sortes)
    if par_sorte:
        L += ['', '## Par sorte de changement', '']
        L += [f'- {SORTES[s]} : {par_sorte[s]} élément(s)' for s in SORTES if par_sorte[s]]

    premiers = retenus[:essai]
    if premiers and len(retenus) > essai:
        L += ['', '## Essai', '',
              f'Les {len(premiers)} premiers groupes, appliqués par `zc appliquer <plan> --essai`, couvrent chaque '
              'sorte de changement. À vérifier avec `zc voir` :', '']
        for el, op, v in premiers:
            if el.cle in a.masquees:
                L.append(f'- {el.cle} · {filtre.MASQUE} ({op.nature})')
            else:
                L.append(f'- {el.cle} · {_titre(b, el, a.masquees)} ({op.nature}) : avant {_liste(op.avant["tags"], a)}'
                         f' ; après {_liste(op.apres["tags"], a)}')

    retires = Counter(n for _, _, v in retenus for n, s in v.retires if s != 'automatique')
    raisons = {n: {'importé': 'mot-clé importé', 'état': "état moins avancé qu'un autre de la fiche"}.get(s, '')
               for _, _, v in retenus for n, s in v.retires}
    renommes = Counter((n, c) for _, _, v in retenus for n, c, _ in v.renommes)
    autos = Counter(n for _, _, v in retenus for n, s in v.retires if s == 'automatique')
    if autos:
        L += ['', '## Tags automatiques retirés par la règle globale', '',
              f"{pluriel(len(autos), 'nom')}, {sum(autos.values())} occurrence(s). Les plus portés : "
              + ', '.join(f'{_affiche(a, n)} ({k})' for n, k in autos.most_common(20)) + '.']
    if retires:
        L += ['', '## Tags retirés', '']
        L += [f"- {_affiche(a, n)} ({k}{', ' + raisons[n] if raisons.get(n) else ''})"
              for n, k in sorted(retires.items(), key=lambda x: norm(x[0]))]
    if renommes:
        L += ['', '## Tags renommés', '']
        L += [f'- {_affiche(a, n)} → {c} ({k})' for (n, c), k in sorted(renommes.items(), key=lambda x: norm(x[0][0]))]

    touches = set(retires) | set(autos) | {n for n, _ in renommes}
    a_jour = sorted((rech, n) for n, rechs in R.cites.items() if n in touches for rech in rechs)
    if a_jour:
        L += ['', '## Recherches enregistrées à mettre à jour dans Zotero', '']
        L += [f'- « {rech} » cite « {_affiche(a, n)} », retiré ou renommé par ce plan' for rech, n in a_jour]
    disparus = {n for n in touches if not any(n == t['tag'] for _, op, _ in retenus for t in op.apres['tags'])}
    corbeille = sum(b.tags_corbeille.get(n, 0) for n in disparus)
    if corbeille:
        L += ['', f'{corbeille} occurrence(s) de ces tags restent sur des éléments de la corbeille, qui ne sont pas '
                  'touchés. Elles disparaîtront en vidant la corbeille.']
    if R.problemes:
        L += ['', '## À regarder', '']
        L += [f'- {p}' for p in dict.fromkeys(R.problemes)]

    L += ['', '## Groupes', ''] if retenus else []
    for el, op, v in retenus:
        if el.cle in a.masquees:
            L.append(f'- {el.cle} · {filtre.MASQUE} : {op.nature}')
            continue
        morceaux = [f'retire {", ".join(_affiche(a, n) for n, _ in v.retires)}'] if v.retires else []
        morceaux += [f'{_affiche(a, n)} → {c}' for n, c, _ in v.renommes]
        L.append(f'- {el.cle} · {_titre(b, el, a.masquees)} : ' + ' ; '.join(morceaux))
    return '\n'.join(L) + '\n'
