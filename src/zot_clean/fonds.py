"""Plan du fonds, étape 4 du nettoyage (D95 à D107). Lecture seule.

`inventaire` écrit un rapport sur le classement existant (arbre des
collections, tags thématiques) pour que l'agent propose un plan, et prépare
`suivi/fonds.toml`, qui donne un sort à chaque ancienne collection (D99, D100).
`valider` contrôle `plan.md` et `suivi/fonds.toml`, puis, sur demande,
enregistre l'empreinte de leur structure (D102). L'étape 5 refusera de
planifier le rangement si cette structure a changé depuis.

`plan.md` décrit le fonds sous un titre de premier niveau portant le nom de
la racine (`# Fonds`), avec `##` pour une discipline, `###` pour un thème et
`####` pour un sous-thème (D101). Les autres sections de premier niveau
(concepts, notes) sont ignorées ici. Les chemins sont relatifs au fonds
(`Sociologie/Méthodes`).
"""

import hashlib
import json
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from zot_clean import filtre
from zot_clean.audit import annee, ecrire_toml, norm
from zot_clean.config import Config
from zot_clean.doublons import _toml
from zot_clean.lecture import Bibliotheque, Element

FICHIER = 'fonds.toml'
VALIDATION = 'fonds-validation.json'
PLAN = 'plan.md'
THEME, REPARTIR, PROJET, ARCHIVES, DISSOUDRE, HORS_PLAN = (
    'thème', 'répartir', 'projet', 'archives', 'dissoudre', 'hors plan')
SORTS = {norm(s): s for s in (THEME, REPARTIR, PROJET, ARCHIVES, DISSOUDRE, HORS_PLAN)}
ECHANTILLON = 10
TAGS_DOMINANTS = 5
TAGS_MAX = 300
COOCCURRENCES_MAX = 60
NIVEAUX = {1: 'discipline', 2: 'thème', 3: 'sous-thème'}

EN_TETE = """\
# Correspondance entre l'ancien classement et le plan du fonds, préparée par `zc fonds inventaire`.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc fonds inventaire` le met à jour sans
# perdre les sorts déjà donnés, `zc fonds valider` le contrôle avec plan.md.
#
# Chaque ancienne collection reçoit un sort :
#   "thème"     elle devient la collection `cible` du plan (chemin dans le fonds, « Sociologie/Méthodes »).
#   "répartir"  ses fiches seront réparties une à une à l'étape 5, entre les `candidats` (chemins du plan). Une fois
#               marquée examinée (`zc fonds a-ranger --examinees`), elle va à la corbeille, les fiches laissées y
#               gardant leurs autres collections. Une collection déjà à un chemin du plan reste, elle.
#   "projet"    elle va sous une racine de projets, au chemin `cible`, qui commence par le nom de la racine
#               (« Projets/Cours L1 »). Vide, avec une seule racine de projets, elle y garde son nom.
#   "archives"  elle va sous la racine des archives, sous le nom `cible` (par défaut, son chemin actuel).
#   "dissoudre" elle va à la corbeille, ses fiches gardent leurs autres collections.
#   "hors plan" elle reste telle quelle, avec ses sous-collections.
# Un sort vide reste à donner. `candidats` ne sert qu'au sort « répartir ». `note` est libre.
#
# La table `racines` donne le nouveau nom de chaque racine, appliqué par `zc fonds planifier --racines`,
# par exemple "40 Fonds" = "Fonds". Une racine absente de la table garde son nom.
#
# La table `tags`, en fin de fichier, relie un tag thématique à un chemin du plan, comme indice pour ranger ses fiches à l'étape 5,
# par exemple "perception visuelle" = "Psychologie/Perception".
"""


# --- Plan ---------------------------------------------------------------------------

@dataclass
class Noeud:
    chemin: str
    niveau: int  # 1 discipline, 2 thème, 3 sous-thème
    ligne: int
    definition: str = ''
    inclut: str = ''
    exclut: str = ''


@dataclass
class Plan:
    noeuds: dict[str, Noeud] = field(default_factory=dict)
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)


def lire_plan(texte: str, cfg: Config) -> Plan:
    m = cfg.methode
    p = Plan()
    dans_fonds, trouve, bloc_code = False, False, False
    pile: list[str] = []  # noms des titres ouverts, par niveau
    courant: Noeud | None = None
    for n, brut in enumerate(texte.splitlines(), 1):
        if brut.lstrip().startswith(('```', '~~~')):
            bloc_code = not bloc_code
            continue
        if bloc_code:
            continue
        titre = re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', brut)
        if titre and len(titre.group(1)) == 1:
            dans_fonds = titre.group(2) == m.fonds
            trouve = trouve or dans_fonds
            courant = None
            continue
        if not dans_fonds:
            continue
        if titre:
            niveau, nom = len(titre.group(1)) - 1, titre.group(2)
            courant = None
            if niveau > m.profondeur_max:
                p.erreurs.append(f'ligne {n} : « {nom} » est au-delà de {m.profondeur_max} niveaux.')
                continue
            if niveau > len(pile) + 1:
                p.erreurs.append(f'ligne {n} : « {nom} » ({NIVEAUX[niveau]}) n\'a pas de parent, '
                                 f'il manque un titre de niveau {"#" * (len(pile) + 2)} au-dessus.')
                continue
            if not nom or '/' in nom:
                p.erreurs.append(f'ligne {n} : nom vide ou contenant « / » (« {nom} »).')
                continue
            if niveau == 1 and nom in m.racines:
                p.erreurs.append(f'ligne {n} : « {nom} » est le nom d\'une racine, à ne pas donner à une discipline.')
            del pile[niveau - 1:]
            pile.append(nom)
            chemin = '/'.join(pile)
            if chemin in p.noeuds:
                p.erreurs.append(f'ligne {n} : « {chemin} » existe déjà (ligne {p.noeuds[chemin].ligne}), '
                                 'deux collections sœurs ne peuvent pas porter le même nom.')
                continue
            courant = p.noeuds[chemin] = Noeud(chemin, niveau, n)
            continue
        if courant is None or not brut.strip():
            continue
        texte_ligne = brut.strip()
        champ = re.match(r'^[*_]*(Inclut|Exclut)[*_]*\s*[:.]?\s*[*_]*\s*(.*)$', texte_ligne, re.I)
        if champ:
            attribut = champ.group(1).lower()
            setattr(courant, attribut, (getattr(courant, attribut) + ' ' + champ.group(2)).strip())
        else:
            courant.definition = (courant.definition + ' ' + texte_ligne).strip()
    if not trouve:
        p.erreurs.append(f'aucune section « # {m.fonds} », sous laquelle plan.md décrit le fonds.')
    elif not p.noeuds:
        p.erreurs.append(f'la section « # {m.fonds} » ne contient aucune discipline (titre ##).')
    for nd in p.noeuds.values():
        if not nd.definition:
            p.avertissements.append(f'« {nd.chemin} » ({NIVEAUX[nd.niveau]}) n\'a pas de définition.')
    if p.noeuds and not any(nd.niveau > 1 for nd in p.noeuds.values()):
        p.avertissements.append(
            f'aucune discipline n\'a de thème (titre ###). Les fiches seront rangées directement dans les '
            f'disciplines, ce qui convient à un petit fonds. Au-delà de {m.seuil_sous_theme} fiches, une discipline '
            'gagne à être découpée en thèmes.')
    return p


# --- Suivi --------------------------------------------------------------------------

@dataclass
class Ancienne:
    cle: str
    chemin: str
    effectif: int = 0
    sort: str = ''
    cible: str = ''
    candidats: list[str] = field(default_factory=list)
    note: str = ''
    prerempli: str = ''  # raison du sort prérempli, écrite en commentaire


@dataclass
class Suivi:
    collections: list[Ancienne] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    racines: dict[str, str] = field(default_factory=dict)  # nom actuel -> nouveau nom (D112)


def charger_suivi(cfg: Config) -> Suivi:
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return Suivi()
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    s = Suivi(tags={str(k): str(v) for k, v in brut.get('tags', {}).items()},
              racines={str(k): str(v) for k, v in brut.get('racines', {}).items()})
    for c in brut.get('collection', []):
        sort = c.get('sort', '')
        if sort and norm(sort) not in SORTS:
            raise SystemExit(f'{chemin} : sort inconnu « {sort} » pour {c.get("chemin", c.get("cle"))}. '
                             f'Sorts possibles : {", ".join(SORTS.values())}.')
        s.collections.append(Ancienne(c['cle'], c.get('chemin', ''), int(c.get('effectif', 0)),
                                      SORTS[norm(sort)] if sort else '', c.get('cible', ''),
                                      list(c.get('candidats', [])), c.get('note', '')))
    return s


def ecrire_suivi(cfg: Config, s: Suivi) -> None:
    lignes = [EN_TETE]
    for c in s.collections:
        lignes += ['[[collection]]']
        if c.prerempli:
            lignes.append(f'# {c.prerempli}')
        lignes += [f'cle = {_toml(c.cle)}', f'chemin = {_toml(c.chemin)}', f'effectif = {c.effectif}',
                   f'sort = {_toml(c.sort)}', f'cible = {_toml(c.cible)}',
                   f'candidats = {_toml(c.candidats if c.sort in (REPARTIR, "") else [])}',
                   f'note = {_toml(c.note)}', '']
    lignes += ['[racines]'] + [f'{_toml(k)} = {_toml(v)}' for k, v in s.racines.items()] + ['']
    lignes += ['[tags]'] + [f'{_toml(k)} = {_toml(v)}' for k, v in s.tags.items()]
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    ecrire_toml(cfg.suivi / FICHIER, lignes + [''])


# --- Inventaire ---------------------------------------------------------------------

def refus(cfg: Config) -> str:
    """Motif de refus de `zc fonds`, vide si l'étape peut se faire (D96)."""
    if not cfg.methode.fonds:
        return ('La racine du fonds est désactivée dans config.toml ([methode] fonds = ""). '
                "L'étape 4 construit le plan de cette racine, elle n'a donc pas lieu d'être.")
    return ''


def _racines(b: Bibliotheque) -> dict[str, int]:
    return {c.nom: c.id for c in b.collections.values() if c.parent is None}


def _sous(b: Bibliotheque, cid: int, racine: int | None) -> bool:
    return racine is not None and cid != racine and b.racine(cid) == racine


def _relatif(b: Bibliotheque, cid: int) -> str:
    """Chemin sans la racine."""
    return b.chemin(cid).split('/', 1)[1]


def collections_exclues(b: Bibliotheque, cfg: Config) -> tuple[set[int], set[int]]:
    """Collections désignées par le filtre (D18), et toutes celles qu'elles couvrent, descendantes comprises."""
    noms = set(cfg.confidentialite.collections_exclues)
    designees = {c for c in b.collections if b.collections[c].nom in noms or b.chemin(c) in noms}
    couvertes = {c for c in b.collections if filtre._exclue(b, c, noms)}
    # Une collection désignée sous une autre désignée est déjà couverte par son ancêtre.
    designees = {c for c in designees if not (b.collections[c].parent in couvertes)}
    return designees, couvertes


def _anciennes(b: Bibliotheque, cfg: Config, exclues: set[int]) -> dict[str, Ancienne]:
    """Une entrée par collection hors racines de la méthode, avec son sort prérempli (D99).

    Une fois `plan.md` écrit, une collection du fonds déjà à un chemin du plan (sous-thème créé par une passe du
    rangement, par exemple) reçoit le sort « thème » vers ce chemin."""
    m = cfg.methode
    chemin_plan = cfg.dossier_travail / PLAN
    noeuds = lire_plan(chemin_plan.read_text(encoding='utf-8'), cfg).noeuds if chemin_plan.is_file() else {}
    racines = _racines(b)
    designees, couvertes = collections_exclues(b, cfg)
    effectifs = Counter(c for e in b.fiches if e.id not in exclues for c in e.collections)
    res = {}
    for cid in sorted(b.collections, key=b.chemin):
        col = b.collections[cid]
        if col.parent is None and col.nom in m.racines:
            continue
        if cid in couvertes and cid not in designees:
            continue
        a = Ancienne(col.cle, b.chemin(cid), effectifs[cid])
        if cid in designees:
            a.sort, a.prerempli = HORS_PLAN, 'exclue par le filtre de confidentialité, absente de l\'inventaire'
        elif any(_sous(b, cid, racines.get(r)) for r in m.projets):
            a.sort, a.cible, a.prerempli = PROJET, b.chemin(cid), 'déjà sous une racine de projets'
        elif m.archives and _sous(b, cid, racines.get(m.archives)):
            a.sort, a.cible, a.prerempli = ARCHIVES, _relatif(b, cid), 'déjà sous la racine des archives'
        elif _sous(b, cid, racines.get(m.fonds)) and _relatif(b, cid) in noeuds:
            a.sort, a.cible, a.prerempli = THEME, _relatif(b, cid), 'déjà à sa place dans le plan'
        elif _sous(b, cid, racines.get(m.fonds)):
            a.prerempli = 'dans le fonds actuel, à garder, renommer ou fusionner'
        res[col.cle] = a
    return res


def mettre_a_jour_suivi(ancien: Suivi, detectees: dict[str, Ancienne]) -> tuple[Suivi, list[Ancienne], list[Ancienne]]:
    """Garde les sorts donnés, ajoute les nouvelles collections. Rend aussi les nouvelles et les disparues."""
    par_cle = {c.cle: c for c in ancien.collections}
    nouvelles = [d for cle, d in detectees.items() if cle not in par_cle]
    disparues = [c for c in ancien.collections if c.cle not in detectees]
    res = []
    for cle, d in detectees.items():
        a = par_cle.get(cle)
        if a and (a.sort or a.cible or a.candidats or a.note):
            a.chemin, a.effectif, a.prerempli = d.chemin, d.effectif, d.prerempli
            res.append(a)
        else:
            res.append(d)
    return Suivi(res, ancien.tags, ancien.racines), nouvelles, disparues


def suivre_racines(cfg: Config) -> int:
    """Après le renommage des racines (D112), reporte les nouveaux noms dans les chemins et les cibles de
    `fonds.toml` (une cible de projet commence par le nom de sa racine). Rend le nombre de collections touchées."""
    suivi = charger_suivi(cfg)
    actuelles = set(cfg.methode.racines)
    faits = {a: n for a, n in suivi.racines.items() if n in actuelles and a not in actuelles}

    def suivre(chemin: str) -> str:
        for ancien, nouveau in faits.items():
            if chemin == ancien or chemin.startswith(ancien + '/'):
                return nouveau + chemin[len(ancien):]
        return chemin

    n = 0
    for c in suivi.collections:
        chemin, cible = suivre(c.chemin), suivre(c.cible)
        if (chemin, cible) != (c.chemin, c.cible):
            c.chemin, c.cible, n = chemin, cible, n + 1
    if n:
        ecrire_suivi(cfg, suivi)
    return n


def racines_proposees(cfg: Config, deja: dict[str, str]) -> dict[str, str]:
    """Nouveaux noms des racines de la méthode, sans le numéro de tête (D112). Les choix déjà faits sont gardés."""
    res = dict(deja)
    for nom in cfg.methode.racines:
        if nom not in res and (m := re.fullmatch(r'\d+[\s._-]+(.+)', nom)):
            res[nom] = m.group(1)
    return res


def _tag_thematique(nom: str, typ: int, cfg: Config) -> bool:
    m = cfg.methode
    return typ == 0 and not (nom.startswith(m.prefixe_technique) or nom in m.etats or nom in m.autres_tags)


def _tags(e: Element, cfg: Config) -> set[str]:
    return {n for n, t in e.tags if _tag_thematique(n, t, cfg)}


def _echantillon(fiches: list[Element]) -> list[Element]:
    """Titres répartis dans l'ordre alphabétique, pour ne pas montrer que le début de la liste."""
    tries = sorted(fiches, key=lambda e: norm(e.titre))
    if len(tries) <= ECHANTILLON:
        return tries
    pas = len(tries) / ECHANTILLON
    return [tries[int(i * pas)] for i in range(ECHANTILLON)]


def _ligne_fiche(e: Element) -> str:
    auteur = e.auteur or '?'
    return f'{auteur}, {annee(e) or "s. d."}, {e.titre[:100] or "(sans titre)"}'


def inventaire(b: Bibliotheque, cfg: Config, jour: date | None = None) -> tuple[str, Suivi, list, list]:
    """Rapport d'inventaire, suivi mis à jour, collections nouvelles et disparues depuis le dernier inventaire."""
    m = cfg.methode
    exclues = filtre.exclues(b, cfg)
    _, couvertes = collections_exclues(b, cfg)
    fiches = [e for e in b.fiches if e.id not in exclues]
    ancien = charger_suivi(cfg)
    suivi, nouvelles, disparues = mettre_a_jour_suivi(ancien, _anciennes(b, cfg, exclues))
    suivi.racines = racines_proposees(cfg, suivi.racines)
    sorts = {c.cle: c.sort for c in suivi.collections}
    racines = _racines(b)

    par_col: dict[int, list[Element]] = defaultdict(list)
    for e in fiches:
        for c in e.collections:
            par_col[c].append(e)
    enfants: dict[int | None, list[int]] = defaultdict(list)
    for cid, c in b.collections.items():
        if cid not in couvertes:
            enfants[c.parent].append(cid)

    def total(cid: int) -> set[int]:
        ids = {e.id for e in par_col[cid]}
        for x in enfants[cid]:
            ids |= total(x)
        return ids

    jour = jour or date.today()
    sans = sum(1 for e in fiches if not (e.collections - couvertes))
    L = [f'# Inventaire du classement pour le plan du fonds, {jour:%d/%m/%Y}', '',
         "Lecture seule, rien n'a été modifié. Cet inventaire sert à proposer le plan du fonds (`plan.md`) et le "
         'sort de chaque ancienne collection (`suivi/fonds.toml`).', '',
         f'{len(fiches)} références, dont {sans} dans aucune collection. '
         f'{len(b.collections) - len(couvertes)} collections.'
         + (f' {len(exclues)} références et {len(couvertes)} collections exclues par le filtre de confidentialité '
            "n'apparaissent pas ici." if exclues or couvertes else '')]
    if racines.get(m.fonds) is not None:
        L += ['', f'Une racine « {m.fonds} » existe déjà. Son arbre sert de brouillon au plan.']

    L += ['', '## Arbre des collections', '',
          'Pour chaque collection, les références rangées directement (et avec les sous-collections), la '
          'profondeur, les collections qui partagent des références, les tags dominants et un échantillon de '
          f'titres ({ECHANTILLON} au plus, tous pour une collection du fonds de plus de {m.seuil_sous_theme} '
          'références). Les sorts déjà donnés dans `suivi/fonds.toml` sont rappelés.']

    def dans_fonds(cid: int) -> bool:
        return _sous(b, cid, racines.get(m.fonds))

    def decrire(cid: int, niveau: int):
        col = b.collections[cid]
        directes = par_col[cid]
        tout = total(cid)
        effectif = f'{len(directes)} réf.' + (f', {len(tout)} avec les sous-collections' if enfants[cid] else '')
        sort = sorts.get(col.cle, '')
        L.extend(['', f'{"#" * min(niveau + 2, 6)} {b.chemin(cid)}', '',
                  f'{effectif}, profondeur {niveau}{f", sort « {sort} »" if sort else ""}.'])
        methode = col.parent is None and col.nom in m.racines
        communes = Counter(c for e in directes for c in e.collections if c != cid and c not in couvertes)
        if communes:
            L.append('Références partagées avec ' + ', '.join(
                f'{b.chemin(c)} ({n})' for c, n in communes.most_common(5)) + '.')
        dominants = Counter(t for e in directes for t in _tags(e, cfg)).most_common(TAGS_DOMINANTS)
        if dominants:
            L.append('Tags les plus portés, ' + ', '.join(f'{t} ({n})' for t, n in dominants) + '.')
        if directes and not methode and sort not in (PROJET, ARCHIVES):
            complet = dans_fonds(cid) and len(directes) > m.seuil_sous_theme
            if complet:
                L.append(f'Au-delà de {m.seuil_sous_theme} références, liste complète pour juger d\'un découpage '
                         'en sous-thèmes.')
            L.append('')
            choisies = sorted(directes, key=lambda e: norm(e.titre)) if complet else _echantillon(directes)
            L.extend(f'- {_ligne_fiche(e)}' for e in choisies)
        for x in sorted(enfants[cid], key=lambda x: norm(b.collections[x].nom)):
            decrire(x, niveau + 1)

    for cid in sorted(enfants[None], key=lambda x: (b.collections[x].nom not in m.racines, norm(b.collections[x].nom))):
        decrire(cid, 1)

    compte = Counter(t for e in fiches for t in _tags(e, cfg))
    listes = [(t, n) for t, n in compte.most_common() if n >= 2]
    uniques = sum(1 for n in compte.values() if n == 1)
    L += ['', '## Tags thématiques', '',
          'Tags manuels, sans les tags d\'état, ' + ''.join(f'`{t}`, ' for t in m.autres_tags)
          + f'ni les tags techniques (`{m.prefixe_technique}`). Les tags automatiques sont ignorés.', '',
          f'{len(compte)} tags, dont {uniques} posés une seule fois (non listés).', '']
    L += [f'- {t} ({n})' for t, n in listes[:TAGS_MAX]]
    if len(listes) > TAGS_MAX:
        L.append(f'- … et {len(listes) - TAGS_MAX} autres')
    paires = Counter()
    for e in fiches:
        ts = sorted(t for t in _tags(e, cfg) if compte[t] >= 2)
        for i, a in enumerate(ts):
            for c in ts[i + 1:]:
                paires[a, c] += 1
    frequentes = [(p, n) for p, n in paires.most_common(COOCCURRENCES_MAX) if n >= 3]
    if frequentes:
        L += ['', '## Tags qui reviennent ensemble', '', 'Paires portées par au moins trois mêmes références.', '']
        L += [f'- {a} + {c} ({n})' for (a, c), n in frequentes]
    if nouvelles and ancien.collections:
        L += ['', '## Collections nouvelles depuis le dernier inventaire', '']
        L += [f'- {c.chemin}' for c in nouvelles]
    if disparues:
        L += ['', '## Collections disparues depuis le dernier inventaire', '',
              'Retirées de `suivi/fonds.toml`, avec le sort qu\'elles avaient.', '']
        L += [f'- {c.chemin}{f" (sort « {c.sort} »)" if c.sort else ""}' for c in disparues]
    return '\n'.join(L) + '\n', suivi, nouvelles, disparues


# --- Validation ---------------------------------------------------------------------

@dataclass
class Controle:
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    structure: dict = field(default_factory=dict)
    changements: list[str] = field(default_factory=list)
    deja_valide: bool = False

    @property
    def empreinte(self) -> str:
        return empreinte(self.structure)


def empreinte(structure: dict) -> str:
    return hashlib.sha256(json.dumps(structure, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def structure(plan: Plan, s: Suivi) -> dict:
    """Ce que l'empreinte couvre, à savoir les chemins du plan, les sorts et les cibles (D102). Les candidats ne
    comptent que pour une collection à répartir, ceux d'une collection passée à un autre sort n'ont plus de sens."""
    return {
        'plan': sorted(plan.noeuds),
        'collections': {c.cle: [c.sort, c.cible, sorted(c.candidats) if c.sort == REPARTIR else []]
                        for c in s.collections},
        'tags': dict(sorted(s.tags.items())),
    }


def _sans_candidats_inutiles(structure: dict) -> dict:
    """Structure enregistrée avant que les candidats d'une collection non répartie ne soient ignorés."""
    res = dict(structure)
    res['collections'] = {cle: [v[0], v[1], v[2] if v[0] == REPARTIR else []]
                          for cle, v in structure.get('collections', {}).items()}
    return res


def controler(cfg: Config) -> Controle:
    m = cfg.methode
    k = Controle()
    chemin_plan = cfg.dossier_travail / PLAN
    if not chemin_plan.is_file():
        k.erreurs.append(f'{PLAN} absent du dossier de travail.')
        return k
    if not (cfg.suivi / FICHIER).is_file():
        k.erreurs.append(f'suivi/{FICHIER} absent. Lancer `zc fonds inventaire`.')
        return k
    plan = lire_plan(chemin_plan.read_text(encoding='utf-8'), cfg)
    s = charger_suivi(cfg)
    k.erreurs += [f'{PLAN}, {e}' for e in plan.erreurs]
    k.avertissements += [f'{PLAN}, {a}' for a in plan.avertissements]

    def existe(cible: str) -> bool:
        return cible in plan.noeuds

    for c in s.collections:
        nom = f'« {c.chemin} » ({c.cle})'
        if not c.sort:
            k.erreurs.append(f'{nom} n\'a pas de sort.')
        elif c.sort == THEME:
            if not c.cible:
                k.erreurs.append(f'{nom} devient un thème, mais sa cible est vide.')
            elif not existe(c.cible):
                k.erreurs.append(f'{nom} devient « {c.cible} », qui n\'est pas dans {PLAN}.')
        elif c.sort == REPARTIR:
            if not c.candidats:
                k.avertissements.append(f'{nom} est à répartir, sans thème candidat.')
            for x in c.candidats:
                if not existe(x):
                    k.erreurs.append(f'{nom} a pour candidat « {x} », qui n\'est pas dans {PLAN}.')
        elif c.sort == PROJET and not m.projets:
            k.erreurs.append(f'{nom} va dans les projets, mais aucune racine de projets n\'est déclarée.')
        elif c.sort == PROJET and c.cible and (c.cible.split('/')[0] not in m.projets or '/' not in c.cible):
            k.erreurs.append(f'{nom} va dans les projets, mais sa cible « {c.cible} » ne commence pas par une '
                             f'racine de projets ({", ".join(m.projets)}), suivie du nom du projet.')
        elif c.sort == PROJET and not c.cible and len(m.projets) > 1:
            k.erreurs.append(f'{nom} va dans les projets, sans cible, alors qu\'il y a plusieurs racines de projets.')
        elif c.sort == ARCHIVES and not m.archives:
            k.erreurs.append(f'{nom} va dans les archives, mais la racine des archives est désactivée.')
        if c.sort in (PROJET, ARCHIVES) and c.cible and any(not p.strip() for p in c.cible.split('/')):
            k.erreurs.append(f'{nom} a une cible mal formée (« {c.cible} »).')
    # Seules deux cibles explicites identiques réunissent des collections (D118).
    doubles = Counter((c.sort, c.cible) for c in s.collections if c.sort in (PROJET, ARCHIVES) and c.cible
                      and not reste_en_place(c, m))
    for (sort, cible), n in doubles.items():
        if n > 1:
            k.avertissements.append(f'{n} collections vont ensemble dans « {cible} » ({sort}), leurs fiches seront réunies.')
    for tag, cible in s.tags.items():
        if not existe(cible):
            k.erreurs.append(f'le tag « {tag} » renvoie à « {cible} », qui n\'est pas dans {PLAN}.')
    k.structure = structure(plan, s)
    ancienne = lire_validation(cfg)
    if ancienne:
        avant = _sans_candidats_inutiles(ancienne.get('structure', {}))
        k.deja_valide = k.empreinte in (ancienne.get('empreinte'), empreinte(avant))
        if not k.deja_valide:
            k.changements = differences(avant, k.structure)
    return k


def reste_en_place(c: Ancienne, m) -> bool:
    """Projet ou archive dont la cible désigne l'emplacement actuel (cible préremplie, D99)."""
    if c.sort == PROJET:
        return c.cible == c.chemin
    racine, _, reste = c.chemin.partition('/')
    return c.sort == ARCHIVES and racine == m.archives and c.cible == reste


def lire_validation(cfg: Config) -> dict:
    chemin = cfg.suivi / VALIDATION
    if not chemin.is_file():
        return {}
    return json.loads(chemin.read_text(encoding='utf-8'))


def enregistrer(cfg: Config, k: Controle) -> None:
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    donnees = {'empreinte': k.empreinte, 'date': datetime.now().isoformat(timespec='seconds'),
               'structure': k.structure}
    (cfg.suivi / VALIDATION).write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding='utf-8')


def differences(avant: dict, apres: dict) -> list[str]:
    res = []
    p0, p1 = set(avant.get('plan', [])), set(apres.get('plan', []))
    res += [f'ajouté au plan : {x}' for x in sorted(p1 - p0)]
    res += [f'retiré du plan : {x}' for x in sorted(p0 - p1)]
    c0, c1 = avant.get('collections', {}), apres.get('collections', {})
    for cle in sorted(set(c0) | set(c1)):
        if c0.get(cle) != c1.get(cle):
            res.append(f'collection {cle} : {_sort_lisible(c0.get(cle))} → {_sort_lisible(c1.get(cle))}')
    t0, t1 = avant.get('tags', {}), apres.get('tags', {})
    for t in sorted(set(t0) | set(t1)):
        if t0.get(t) != t1.get(t):
            res.append(f'tag « {t} » : {t0.get(t) or "aucun thème"} → {t1.get(t) or "aucun thème"}')
    return res


def _sort_lisible(v) -> str:
    if not v:
        return 'absente'
    sort, cible, candidats = v
    detail = cible or ', '.join(candidats)
    return f'« {sort or "sans sort"} »' + (f' {detail}' if detail else '')


def validation_a_jour(cfg: Config) -> tuple[bool, list[str]]:
    """Pour l'étape 5, la structure est-elle celle qui a été validée (D102) ?"""
    k = controler(cfg)
    if not lire_validation(cfg):
        return False, ['plan jamais validé (`zc fonds valider`).']
    return k.deja_valide and not k.erreurs, k.erreurs + k.changements
