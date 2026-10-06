"""Rangement, étape 5 du nettoyage (D112 à D122).

`planifier` compare l'état réel de la bibliothèque à l'état visé par le plan
validé (`plan.md`, `suivi/fonds.toml`) et par les décisions acceptées de
`suivi/rangement.toml`, et ne planifie que la différence (D119). Il se relance
donc sans danger, après une passe interrompue, une retouche dans Zotero ou une
annulation.

Le fonds se transforme sur place (D113). Chaque chemin du plan est incarné
par une collection. C'est l'ancienne collection qui y est destinée (sort
« thème »), celle qui y est déjà, ou une collection créée sous une clé tirée
ici (D114). Plusieurs anciennes collections de même cible sont fusionnées dans
l'une d'elles, les autres vont à la corbeille une fois vidées (D117). Projets
et archives sont déplacés, les collections dissoutes vont à la corbeille. Les
anciennes collections sont désignées par leur clé (D118).

Le plan a un groupe par collection cible, dans l'ordre de l'arbre (D120),
avec son changement de collection au rang 0 et les fiches qui y entrent au
rang 1. Viennent ensuite projets et archives, les collections à mettre à la
corbeille, les fiches à mettre à la corbeille, puis les racines (D112), qui
ne sont renommées qu'à la demande.
"""

import json
import re
import secrets
import tomllib
from dataclasses import dataclass, field
from datetime import date

from zot_clean import filtre, fonds as f, plans
from zot_clean.appliquer import copie_en_retard
from zot_clean.audit import annee, ecrire_toml, nom_type, norm, pluriel
from zot_clean.config import Config
from zot_clean.doublons import _toml
from zot_clean.ecriture import Client
from zot_clean.lecture import CLE_VALIDE, Bibliotheque, Element
from zot_clean.plans import Groupe, Operation, Plan

FICHIER = 'rangement.toml'
DEPLACER, AJOUTER, CORBEILLE = 'déplacer', 'ajouter', 'corbeille'
ACTIONS = {norm(a): a for a in (DEPLACER, AJOUTER, CORBEILLE)}
ACCEPTER, REFUSER = 'accepter', 'refuser'
AGENT, TAG, CONSIGNE = 'agent', 'tag', 'consigne'
ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'
PAQUET = 50

EN_TETE = """\
# Décisions de rangement fiche par fiche, lues par `zc fonds planifier` et `zc inbox planifier`.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc fonds a-ranger` y ajoute les propositions
# tirées des tags reliés à un thème, sans toucher aux entrées existantes.
#
# Une table [[fiche]] par décision, une seule par fiche en général (une seconde pour « ajouter » une autre place).
# cle      : clé de la fiche, donnée par les rapports (`zc fonds a-ranger`, `zc inbox preparer`).
# action   : "déplacer" (vers `cible`, en quittant `depuis`), "ajouter" (dans `cible`, sans rien quitter),
#            "corbeille" (la fiche va à la corbeille de Zotero).
# cible    : chemin du plan, sans la racine du fonds (« Philosophie/Philosophie des sciences »).
# depuis   : clé de la collection quittée, celle que le rapport donne pour le paquet. Vide, la fiche quitte les
#            thèmes du fonds qui contiennent la cible. Pour une fiche hors de toute collection, `depuis` reste vide,
#            et « déplacer » ou « ajouter » reviennent au même. Une fiche d'un projet reçoit « ajouter » et y reste.
# source   : "agent", "tag" ou "consigne" (demande de l'utilisateur).
# decision : "" (proposé), "accepter" ou "refuser". Seules les entrées acceptées entrent dans le plan.
# note     : libre, une phrase qui justifie la proposition.
#
# Exemple, à recopier sans les dièses :
# [[fiche]]
# cle = "ABCD2345"
# action = "déplacer"
# cible = "Psychologie/Perception"
# depuis = "WXYZ6789"
# source = "agent"
# decision = ""
# note = "Psychophysique des couleurs, dans les « Inclut » de Perception."
"""


# --- Fichier de suivi -------------------------------------------------------------

@dataclass
class Entree:
    cle: str
    action: str
    cible: str = ''
    depuis: str = ''
    source: str = AGENT
    decision: str = ''
    note: str = ''


def charger(cfg: Config) -> list[Entree]:
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return []
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    res = []
    for d in brut.get('fiche', []):
        action = ACTIONS.get(norm(d.get('action', '')))
        if not action:
            raise SystemExit(f'{chemin} : action inconnue « {d.get("action")} » pour {d.get("cle")}. '
                             f'Actions possibles : {", ".join(ACTIONS.values())}.')
        decision = d.get('decision', '')
        if decision not in ('', ACCEPTER, REFUSER):
            raise SystemExit(f'{chemin} : décision inconnue « {decision} » pour {d.get("cle")}.')
        if action != CORBEILLE and not d.get('cible'):
            raise SystemExit(f'{chemin} : {d.get("cle")} ({action}) sans cible.')
        res.append(Entree(d['cle'], action, d.get('cible', ''), d.get('depuis', ''), d.get('source', AGENT),
                          decision, d.get('note', '')))
    return res


def ecrire(cfg: Config, entrees: list[Entree], b: Bibliotheque, exclues: set[int]) -> None:
    par_cle = b.par_cle()
    lignes = [EN_TETE]
    for e in entrees:
        fiche = par_cle.get(e.cle)
        lignes.append('[[fiche]]')
        if fiche and fiche.id not in exclues:
            lignes.append(f'# {_ligne(fiche)} · ' + ', '.join(sorted(b.chemin(c) for c in fiche.collections)))
        lignes += [f'cle = {_toml(e.cle)}', f'action = {_toml(e.action)}', f'cible = {_toml(e.cible)}',
                   f'depuis = {_toml(e.depuis)}', f'source = {_toml(e.source)}', f'decision = {_toml(e.decision)}',
                   f'note = {_toml(e.note)}', '']
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    ecrire_toml(cfg.suivi / FICHIER, lignes)


def creer_si_absent(cfg: Config) -> bool:
    """Écrit le fichier, avec son seul en-tête et son exemple, s'il n'existe pas encore. Rend True s'il est créé."""
    if (cfg.suivi / FICHIER).is_file():
        return False
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    (cfg.suivi / FICHIER).write_text(EN_TETE, encoding='utf-8')
    return True


def _ligne(e: Element) -> str:
    auteur = e.auteur or '?'
    return f'{auteur}, {annee(e) or "s. d."}, {e.titre[:100] or "(sans titre)"}'


# --- État visé --------------------------------------------------------------------

@dataclass
class CollVisee:
    cle: str
    nom: str
    parent: str | None  # None à la racine
    creation: bool = False
    categorie: str = 'fonds'  # fonds, projet, archives, intermédiaire, racine
    ordre: tuple = ()


@dataclass
class Vise:
    racine_fonds: str = ''
    noeuds: dict[str, str] = field(default_factory=dict)  # chemin du plan -> clé
    collections: dict[str, CollVisee] = field(default_factory=dict)  # clé -> état visé, pour celles qui changent
    corbeille_collections: list[str] = field(default_factory=list)
    fusions: dict[str, str] = field(default_factory=dict)  # clé fusionnée -> clé gardée
    fiches: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)  # clé -> (retirées, ajoutées)
    corbeille_fiches: list[str] = field(default_factory=list)
    racines: dict[str, str] = field(default_factory=dict)  # clé -> nouveau nom
    problemes: list[str] = field(default_factory=list)
    sans_place: list[str] = field(default_factory=list)  # fiches sans place dans le fonds après le rangement
    reparties: dict[str, int] = field(default_factory=dict)  # collection répartie et examinée -> fiches laissées (D167)
    laissees: list[str] = field(default_factory=list)  # sans place, mais laissées hors du fonds par décision (D176)


class _Etat:
    """Collections actuelles de la copie locale, par clé."""

    def __init__(self, b: Bibliotheque):
        self.b = b
        self.cle = {cid: c.cle for cid, c in b.collections.items()}
        self.nom = {c.cle: c.nom for c in b.collections.values()}
        self.parent = {c.cle: (self.cle[c.parent] if c.parent else None) for c in b.collections.values()}
        self.enfants: dict[str | None, list[str]] = {}
        for k, p in self.parent.items():
            self.enfants.setdefault(p, []).append(k)
        self.cles_prises = set(self.nom) | {e.cle for e in b.elements.values()}

    def racine(self, nom: str) -> str | None:
        return next((k for k in self.enfants.get(None, []) if self.nom[k] == nom), None)

    def enfant(self, parent: str | None, nom: str) -> str | None:
        return next((k for k in self.enfants.get(parent, []) if self.nom[k] == nom), None)

    def chemin(self, k: str) -> str:
        p = self.parent[k]
        return (self.chemin(p) + '/' if p else '') + self.nom[k]

    def sous(self, k: str, racine: str) -> bool:
        while k is not None:
            if k == racine:
                return True
            k = self.parent.get(k)
        return False

    def nouvelle_cle(self) -> str:
        while True:
            k = ''.join(secrets.choice(ALPHABET) for _ in range(8))
            if k not in self.cles_prises and CLE_VALIDE.match(k):
                self.cles_prises.add(k)
                return k


def viser(b: Bibliotheque, cfg: Config, plan: f.Plan, suivi: f.Suivi, entrees: list[Entree],
          avec_racines: bool = False, examinees: dict[str, set[str]] | None = None,
          laissees: set[str] = frozenset()) -> Vise:
    m = cfg.methode
    e = _Etat(b)
    v = Vise()
    effectifs: dict[str, int] = {}
    fiches_de: dict[str, set[str]] = {}
    for el in b.elements.values():
        for cid in el.collections:
            effectifs[e.cle[cid]] = effectifs.get(e.cle[cid], 0) + 1
            fiches_de.setdefault(e.cle[cid], set()).add(el.cle)
    anciennes = {a.cle: a for a in suivi.collections if a.cle in e.nom}

    # Racine du fonds.
    F = e.racine(m.fonds)
    if F is None:
        F = e.nouvelle_cle()
        v.collections[F] = CollVisee(F, m.fonds, None, creation=True, categorie='racine', ordre=(0, m.fonds))
    v.racine_fonds = F

    def relatif(k: str) -> str | None:
        return e.chemin(k).split('/', 1)[1] if F in e.nom and e.sous(k, F) and k != F else None

    # 1. Chemins du plan incarnés par les anciennes collections destinées à ce thème.
    destinees: dict[str, list[str]] = {}
    for a in anciennes.values():
        if a.sort == f.THEME and a.cible in plan.noeuds:
            destinees.setdefault(a.cible, []).append(a.cle)
    for chemin, cles in destinees.items():
        garde = sorted(cles, key=lambda k: (relatif(k) != chemin, -effectifs.get(k, 0), k))[0]
        v.noeuds[chemin] = garde
        for k in cles:
            if k != garde:
                v.fusions[k] = garde
    # Une collection à répartir qui se trouve déjà à un chemin du plan l'incarne (ses fiches y restent, D115).
    for a in anciennes.values():
        if a.sort == f.REPARTIR and (r := relatif(a.cle)) in plan.noeuds and r not in v.noeuds:
            v.noeuds[r] = a.cle
    # 2. Chemins incarnés par une collection déjà en place (créée par une passe précédente), sinon créés.
    envoyees_ailleurs = {k for k, a in anciennes.items() if a.sort not in (f.HORS_PLAN, '')} - set(v.noeuds.values())
    prises = set(v.noeuds.values())
    for chemin, nd in plan.noeuds.items():
        if chemin in v.noeuds:
            continue
        parent_plan = chemin.rpartition('/')[0]
        parent = v.noeuds.get(parent_plan) if parent_plan else F
        existante = e.enfant(parent, chemin.rpartition('/')[2]) if parent in e.nom else None
        if existante and existante not in envoyees_ailleurs and existante not in prises:
            v.noeuds[chemin] = existante
            prises.add(existante)
        else:
            v.noeuds[chemin] = e.nouvelle_cle()
    v.noeuds = {chemin: v.noeuds[chemin] for chemin in plan.noeuds}  # ordre de l'arbre (D120)
    ordre_plan = {chemin: i for i, chemin in enumerate(plan.noeuds)}
    for chemin, k in v.noeuds.items():
        parent_plan = chemin.rpartition('/')[0]
        visee = CollVisee(k, chemin.rpartition('/')[2], v.noeuds[parent_plan] if parent_plan else F,
                          creation=k not in e.nom, ordre=(1, ordre_plan[chemin]))
        if visee.creation or e.nom[k] != visee.nom or e.parent[k] != visee.parent:
            v.collections[k] = visee

    # 3. Projets et archives, déplacés sous leur racine (les parents avant les enfants).
    chemins_vises: dict[str, str] = {}  # chemin complet visé -> clé, pour les parents intermédiaires

    def racine_de(nom: str) -> str:
        k = e.racine(nom)
        if k is None:
            k = chemins_vises.get(nom) or e.nouvelle_cle()
            if k not in v.collections:
                v.collections[k] = CollVisee(k, nom, None, creation=True, categorie='racine', ordre=(0, nom))
            chemins_vises[nom] = k
        return k

    def parent_de(chemin: str, categorie: str) -> str:
        tete, _, reste = chemin.partition('/')
        k = racine_de(tete)
        vu = tete
        for nom in reste.split('/')[:-1] if reste else []:
            vu += '/' + nom
            if vu in chemins_vises:
                k = chemins_vises[vu]
                continue
            enfant = e.enfant(k, nom) if k in e.nom else None
            if enfant is None:
                enfant = e.nouvelle_cle()
                v.collections[enfant] = CollVisee(enfant, nom, k, creation=True, categorie='intermédiaire',
                                                  ordre=(2, vu))
            chemins_vises[vu] = k = enfant
        return k

    archives = e.racine(m.archives) if m.archives else None
    for a in sorted(anciennes.values(), key=lambda a: e.chemin(a.cle).count('/')):
        if a.sort not in (f.PROJET, f.ARCHIVES) or f.reste_en_place(a, m):
            continue
        if a.sort == f.ARCHIVES and not a.cible and archives and e.sous(a.cle, archives):
            # Sans cible, une archive va à son chemin d'avant. Déjà sous les archives (passe précédente), elle est à sa
            # place : son chemin actuel n'est plus une cible, sinon « Archives/Archives/… » (répétition du pilote).
            continue
        if a.sort == f.PROJET:
            if not m.projets:
                v.problemes.append(f'{a.chemin} va dans les projets, sans racine de projets déclarée.')
                continue
            cible = a.cible or f'{m.projets[0]}/{e.nom[a.cle]}'
        else:
            cible = f'{m.archives}/{a.cible or e.chemin(a.cle)}'
        mere = anciennes.get(e.parent[a.cle] or '')
        if not a.cible and mere and mere.sort == a.sort and not mere.cible:
            parent = e.parent[a.cle]  # suit sa mère, elle-même déplacée avec son nom (D118)
        else:
            parent = parent_de(cible, a.sort)
        chemins_vises.setdefault(cible, a.cle)
        visee = CollVisee(a.cle, cible.rpartition('/')[2], parent, categorie=a.sort,
                          ordre=(3 if a.sort == f.PROJET else 4, cible))
        if e.nom[a.cle] != visee.nom or e.parent[a.cle] != visee.parent:
            v.collections[a.cle] = visee

    # 4. Fiches : fusions, puis décisions acceptées de rangement.toml.
    def changer(cle: str, retirer: set[str], ajouter: set[str]):
        r, a = v.fiches.setdefault(cle, (set(), set()))
        a -= retirer
        r |= retirer
        a |= ajouter
        r -= ajouter

    for k, garde in v.fusions.items():
        for cle in fiches_de.get(k, ()):
            changer(cle, {k}, {garde})
    elements = b.par_cle()
    ancetres = {chemin: {v.noeuds[chemin[:i]] for i in [m_.start() for m_ in re.finditer('/', chemin)]}
                for chemin in plan.noeuds}
    # Décisions en chaîne sur une même fiche (A vers B, puis B vers C) : la fiche va directement en C. Sinon B, qu'elle
    # ne contient pas encore ou plus, lui serait ajoutée par la première (trouvé sur la vraie bibliothèque).
    suites = {(en.cle, v.fusions.get(en.depuis, en.depuis)): v.noeuds[en.cible] for en in entrees
              if en.decision == ACCEPTER and en.action == DEPLACER and en.depuis and en.cible in v.noeuds}
    for en in entrees:
        if en.decision != ACCEPTER:
            continue
        if en.cle not in elements:
            v.problemes.append(f'rangement.toml : la fiche {en.cle} n\'existe plus, entrée ignorée.')
            continue
        if en.action == CORBEILLE:
            v.corbeille_fiches.append(en.cle)
            continue
        if en.cible not in v.noeuds:
            v.problemes.append(f'rangement.toml : {en.cle} vise « {en.cible} », qui n\'est pas dans plan.md, '
                               'entrée ignorée.')
            continue
        cible, vues = v.noeuds[en.cible], set()
        while (suite := suites.get((en.cle, cible))) and cible not in vues:
            vues.add(cible)
            cible = suite
        if en.action == AJOUTER:
            changer(en.cle, set(), {cible})
            continue
        actuelles = {e.cle[c] for c in elements[en.cle].collections}
        if en.depuis:
            quitter = {v.fusions.get(en.depuis, en.depuis)}
        else:
            quitter = ancetres[en.cible] | ({k for k in actuelles if v.fusions.get(k) in ancetres[en.cible]})
        changer(en.cle, quitter & (actuelles | set(v.fusions.values())), {cible})

    # 5. Collections à mettre à la corbeille : fusionnées, dissoutes, ou à répartir hors plan et vidées. Une collection
    #    à répartir est vidée quand il n'y reste que des fiches jugées et laissées là (D124, D167). Elles gardent leurs
    #    autres collections, celles qui n'en ont pas d'autre dans le fonds sont présentées comme sans place.
    examinees = examinees or {}
    restent = {}  # collection -> fiches qui y restent après le rangement
    for k in e.nom:
        dedans = {c for c in fiches_de.get(k, ()) if k not in v.fiches.get(c, (set(), set()))[0]}
        dedans |= {c for c, (_, a) in v.fiches.items() if k in a}
        restent[k] = dedans
    parent_vise = {k: (v.collections[k].parent if k in v.collections else e.parent[k]) for k in e.nom}
    reparties = {k for k, a in anciennes.items() if a.sort == f.REPARTIR and k not in v.noeuds.values() and (
        not restent[k] or (k in examinees and restent[k] <= examinees[k]))}
    jetees = {k for k, a in anciennes.items() if k in v.fusions or a.sort == f.DISSOUDRE or k in reparties}
    # Une collection qui garde une sous-collection reste. Une sous-collection jetée dans la même passe ne la retient
    # pas (répartie avec ses sous-collections, répétition du pilote).
    while gardees := {k for k in jetees if any(parent_vise[x] == k and x not in jetees for x in e.nom)}:
        jetees -= gardees
    for k, a in anciennes.items():
        if k in v.fusions or a.sort == f.DISSOUDRE or k in reparties:
            if k not in jetees:
                v.problemes.append(f'{a.chemin} garde des sous-collections, elle n\'est pas mise à la corbeille.')
                continue
            v.corbeille_collections.append(k)
            if k in reparties and restent[k]:
                v.reparties[k] = len(restent[k])

    # 6. Racines renommées à la demande (D112).
    if avec_racines:
        for ancien, nouveau in suivi.racines.items():
            k = e.racine(ancien)
            if k is None or ancien == nouveau:
                continue
            if e.racine(nouveau) is not None:
                v.problemes.append(f'La racine « {ancien} » ne peut pas devenir « {nouveau} », qui existe déjà.')
                continue
            v.racines[k] = nouveau

    # 7. Fiches qui n'auront aucune place dans le fonds (D20), hors Inbox et hors filtre.
    exclues = filtre.exclues(b, cfg)
    fonds_vise = set(v.noeuds.values()) | {F}
    inbox = e.racine(m.inbox) if m.inbox else None
    corbeille = set(v.corbeille_collections)
    for el in b.fiches:
        if el.id in exclues or el.cle in v.corbeille_fiches:
            continue
        retirees, ajoutees = v.fiches.get(el.cle, (set(), set()))
        apres = ({e.cle[c] for c in el.collections} - retirees | ajoutees) - corbeille
        if inbox and any(e.sous(k, inbox) for k in apres):
            continue
        if not apres & fonds_vise and not any(e.sous(k, F) for k in apres if k in e.nom and F in e.nom):
            # Une fiche laissée hors du fonds par décision (D176) ne l'est plus si le plan change ses collections.
            laissee = el.cle in laissees and not any(v.fiches.get(el.cle, (set(), set()))) \
                and not {e.cle[c] for c in el.collections} & corbeille
            (v.laissees if laissee else v.sans_place).append(el.cle)
    return v


# --- Plan ---------------------------------------------------------------------------

def planifier(b: Bibliotheque, cfg: Config, client: Client, avec_racines: bool = False,
              afficher=None) -> tuple[Plan, str]:
    a_jour, raisons = f.validation_a_jour(cfg)
    if not a_jour:
        raise SystemExit('Le plan du fonds n\'est pas validé dans son état actuel :\n  '
                         + '\n  '.join(raisons) + '\nRelancer `zc fonds valider`, puis `--enregistrer` après accord.')
    concordance(b, cfg)
    # L'état réel est lu sur la copie locale (D119). Si Zotero n'a pas encore reçu les derniers changements (ceux
    # d'une passe précédente, par exemple), les collections déjà créées n'y sont pas et seraient recréées.
    if (serveur := client.version_serveur()) > b.version:
        raise SystemExit(copie_en_retard(b.version, serveur))
    plan_fonds = f.lire_plan((cfg.dossier_travail / f.PLAN).read_text(encoding='utf-8'), cfg)
    v = viser(b, cfg, plan_fonds, f.charger_suivi(cfg), charger(cfg), avec_racines, charger_examinees(cfg),
              charger_laissees(b, cfg))
    e = _Etat(b)
    exclues = filtre.exclues(b, cfg)
    par_cle = b.par_cle()

    cles_coll = [k for k in (*v.collections, *v.corbeille_collections, *v.racines) if k in e.nom]
    if afficher:
        afficher(f'État visé calculé. Lecture sur zotero.org de {pluriel(len(cles_coll), "collection")} et '
                 f'{pluriel(len(v.fiches) + len(v.corbeille_fiches), "fiche")} touchées par le plan.')
    api_coll = client.collections(cles_coll)
    api_fiches = client.fiches([*v.fiches, *v.corbeille_fiches])

    groupes: dict[tuple, Groupe] = {}
    titres: dict[tuple, str] = {}

    def groupe(ordre: tuple, titre: str) -> Groupe:
        if ordre not in groupes:
            groupes[ordre] = Groupe('', titre, [])
        return groupes[ordre]

    def chemin_vise(k: str) -> str:
        c = v.collections.get(k)
        if c:
            return (chemin_vise(c.parent) + '/' if c.parent else '') + c.nom
        return e.chemin(k) if k in e.nom else k

    ordre_de: dict[str, tuple] = {}
    for k, c in v.collections.items():
        ordre_de[k] = c.ordre
    for chemin, k in v.noeuds.items():
        ordre_de.setdefault(k, (1, list(v.noeuds).index(chemin)))

    for k, c in sorted(v.collections.items(), key=lambda x: x[1].ordre):
        g = groupe(c.ordre, chemin_vise(k))
        if c.creation:
            g.operations.append(Operation(k, {}, {'name': c.nom, 'parentCollection': c.parent or False},
                                          nature='création', genre='collections', creation=True))
            continue
        d = api_coll.get(k)
        if d is None:
            v.problemes.append(f'La collection {e.chemin(k)} ({k}) n\'existe plus dans Zotero, laissée de côté.')
            continue
        avant = {'name': d.get('name', ''), 'parentCollection': d.get('parentCollection') or False}
        apres = {'name': c.nom, 'parentCollection': c.parent or False}
        changes = {x: apres[x] for x in apres if avant[x] != apres[x]}
        if changes:
            g.operations.append(Operation(k, {x: avant[x] for x in changes}, changes,
                                          nature='renommage' if 'name' in changes else 'déplacement',
                                          genre='collections'))

    for cle, (retirees, ajoutees) in sorted(v.fiches.items()):
        d = api_fiches.get(cle)
        if d is None:
            v.problemes.append(f'La fiche {cle} n\'existe plus dans Zotero, laissée de côté.')
            continue
        avant = list(d.get('collections') or [])
        apres = [k for k in avant if k not in retirees] + [k for k in sorted(ajoutees) if k not in avant]
        if sorted(apres) == sorted(avant):
            continue
        entrees = [k for k in apres if k not in avant]
        ordre = min((ordre_de.get(k, (5, k)) for k in entrees), default=(5, 'fiches'))
        g = groupe(ordre, chemin_vise(entrees[0]) if entrees else 'fiches retirées de collections')
        g.operations.append(Operation(cle, {'collections': avant}, {'collections': apres}, rang=1,
                                      nature='rangement'))

    for k in v.corbeille_collections:
        if k in api_coll or k in e.nom:
            titre = f'corbeille : {e.chemin(k)}'
            if k in v.reparties:
                titre += ' (répartie et examinée)'
            g = groupe((6, e.chemin(k)), titre)
            g.operations.append(Operation(k, {'deleted': False}, {'deleted': True}, nature='corbeille',
                                          genre='collections'))
    enfants = b.enfants()
    for i in range(0, len(v.corbeille_fiches), PAQUET):
        g = groupe((7, i), 'fiches à la corbeille')
        for cle in v.corbeille_fiches[i:i + PAQUET]:
            if cle in api_fiches and not api_fiches[cle].get('deleted'):
                g.operations.append(Operation(cle, {'deleted': False}, {'deleted': True}, nature='corbeille',
                                              enfants=enfants.get(cle, [])))
    for k, nom in v.racines.items():
        d = api_coll.get(k)
        if d:
            g = groupe((8, nom), f'racine : {e.nom[k]} → {nom}')
            g.operations.append(Operation(k, {'name': d['name']}, {'name': nom}, nature='racine',
                                          genre='collections'))

    liste = []
    for ordre in sorted(groupes, key=_cle_tri):
        g = groupes[ordre]
        if g.operations:
            g.id = str(len(liste) + 1)
            liste.append(g)
    plan = Plan('fonds', client.utilisateur, liste,
                description=f'Rangement du fonds, {len(liste)} groupe(s).')
    return plan, rapport(plan, v, b, e, exclues, par_cle, chemin_vise)


def _cle_tri(ordre: tuple):
    return tuple((0, x) if isinstance(x, int) else (1, str(x)) for x in ordre)


def concordance(b: Bibliotheque, cfg: Config) -> None:
    """Les racines de config.toml doivent exister, sinon un renommage n'y a pas été reporté (D112)."""
    m = cfg.methode
    presentes = {c.nom for c in b.collections.values() if c.parent is None}
    manquantes = [n for n in (m.fonds, *m.projets, m.archives) if n and n not in presentes]
    if manquantes:
        suivi = f.charger_suivi(cfg)
        renommees = {a: n for a, n in suivi.racines.items() if a in manquantes and n in presentes}
        if renommees:
            raise SystemExit('Racines renommées dans Zotero, à reporter dans config.toml ([methode]) et dans le titre '
                             'de plan.md : ' + ', '.join(f'« {a} » → « {n} »' for a, n in renommees.items()) + '.')


def _decrire_collection(op: Operation, e: _Etat, chemin_vise) -> str:
    def lieu(k):
        return chemin_vise(k) if k else 'la racine'
    if op.creation:
        return f'création de « {op.apres["name"]} » sous {lieu(op.apres["parentCollection"])}'
    if op.nature == 'corbeille':
        return f'{e.chemin(op.cle)} à la corbeille'
    morceaux = []
    if 'name' in op.apres:
        morceaux.append(f'« {op.avant.get("name", "")} » renommée « {op.apres["name"]} »')
    if 'parentCollection' in op.apres:
        morceaux.append(f'déplacée de {lieu(op.avant.get("parentCollection"))} vers '
                        f'{lieu(op.apres["parentCollection"])}')
    return ', '.join(morceaux)


def rapport(plan: Plan, v: Vise, b: Bibliotheque, e: _Etat, exclues: set[int], par_cle: dict, chemin_vise,
            jour: date | None = None) -> str:
    jour = jour or date.today()
    ops = [op for g in plan.groupes for op in g.operations]
    compte = {n: sum(1 for op in ops if op.nature == n) for n in
              ('création', 'renommage', 'déplacement', 'rangement', 'corbeille', 'racine')}
    L = [f'# Plan de rangement du {jour:%d/%m/%Y}', '',
         f'{len(plan.groupes)} groupe(s), {len(ops)} opération(s). Collections créées {compte["création"]}, '
         f'renommées {compte["renommage"]}, déplacées {compte["déplacement"]}. Fiches rangées {compte["rangement"]}. '
         f'Mises à la corbeille {compte["corbeille"]}. Racines renommées {compte["racine"]}.', '',
         'Un groupe correspond à une collection du fonds, avec les fiches qui y entrent. L\'essai applique '
         'les premiers groupes, à vérifier avec `zc voir`.']
    if v.fusions:
        L += ['', '## Fusions', '']
        L += [f'- {e.chemin(k)} dans {chemin_vise(g)}' for k, g in v.fusions.items()]
    if v.reparties:
        L += ['', '## Collections réparties', '',
              'Entièrement jugées (`zc fonds a-ranger --examinees`), elles vont à la corbeille. Les fiches laissées '
              'en place y gardent leurs autres collections, et celles qui n\'en ont aucune dans le fonds sont comptées '
              'ci-dessous parmi les fiches sans place.', '']
        L += [f'- {e.chemin(k)}, {pluriel(n, "fiche laissée")}' for k, n in v.reparties.items()]
    if v.problemes:
        L += ['', '## À regarder', '']
        L += [f'- {p}' for p in v.problemes]
    if v.sans_place or v.laissees:
        texte = []
        if v.sans_place:
            texte.append(f'{len(v.sans_place)} fiche(s) n\'auront aucune place dans le fonds après ce plan. '
                         '`zc fonds a-ranger` les présente par paquets, pour leur proposer un thème.')
        if v.laissees:
            n = len(v.laissees)
            texte.append(f'{pluriel(n, ("autre " if v.sans_place else "") + "fiche laissée")} hors du fonds par '
                         f'décision (`zc fonds a-ranger --laisser`), non présentée{"s" if n > 1 else ""}.')
        L += ['', '## Fiches sans place dans le fonds', '', ' '.join(texte)]
    L += ['', '## Groupes']
    for g in plan.groupes:
        L += ['', f'### {g.id}. {g.titre}', '']
        for op in g.operations:
            if op.genre == 'collections':
                L.append(f'- collection {op.cle} : ' + _decrire_collection(op, e, chemin_vise))
            else:
                el = par_cle.get(op.cle)
                qui = _ligne(el) if el and el.id not in exclues else filtre.MASQUE
                if op.nature == 'corbeille':
                    L.append(f'- {op.cle} · {qui} : à la corbeille')
                else:
                    nouvelles = [chemin_vise(k) for k in op.apres['collections'] if k not in op.avant['collections']]
                    quittees = [chemin_vise(k) for k in op.avant['collections'] if k not in op.apres['collections']]
                    L.append(f'- {op.cle} · {qui}' + (f' : entre dans {", ".join(nouvelles)}' if nouvelles else '')
                             + (f', quitte {", ".join(quittees)}' if quittees else ''))
    return '\n'.join(L) + '\n'


# --- Fiches à juger ------------------------------------------------------------------

EXAMINEES = 'rangement-examinees.json'


def charger_examinees(cfg: Config) -> dict[str, set[str]]:
    """Fiches laissées en place dans chaque collection à répartir entièrement jugée (D124)."""
    try:
        brut = json.loads((cfg.suivi / EXAMINEES).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    return {k: set(d['fiches']) for k, d in brut.items()}


def marquer_examinees(b: Bibliotheque, cfg: Config, cles: list[str]) -> dict[str, int]:
    """Note les fiches qu'une collection à répartir contient encore une fois jugée. `a-ranger` ne les présente plus,
    seulement celles qui y arrivent ensuite (D124). Refuse tant qu'une proposition depuis cette collection attend."""
    suivi = f.charger_suivi(cfg)
    a_repartir = {a.cle for a in suivi.collections if a.sort == f.REPARTIR}
    e = _Etat(b)
    for k in cles:
        if k not in a_repartir or k not in e.nom:
            raise SystemExit(f'{k} n\'est pas une collection à répartir de suivi/fonds.toml.')
    contenu = {k: {el.cle for el in b.elements.values() if el.est_fiche and any(e.cle[c] == k for c in el.collections)}
               for k in cles}
    proposees = {x.cle for x in charger(cfg) if x.decision == ''}
    attente = [k for k in cles if contenu[k] & proposees]
    if attente:
        raise SystemExit('Propositions encore en attente sur des fiches de ' + ', '.join(e.chemin(k) for k in attente)
                         + '. Les faire juger avant de marquer la collection comme examinée.')
    try:
        brut = json.loads((cfg.suivi / EXAMINEES).read_text(encoding='utf-8'))
    except FileNotFoundError:
        brut = {}
    res = {}
    for k in cles:
        dedans = contenu[k] | set(brut.get(k, {}).get('fiches', []))
        brut[k] = {'chemin': e.chemin(k), 'date': date.today().isoformat(), 'fiches': sorted(dedans)}
        res[e.chemin(k)] = len(dedans)
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    (cfg.suivi / EXAMINEES).write_text(json.dumps(brut, ensure_ascii=False, indent=1), encoding='utf-8')
    return res


LAISSEES = 'rangement-laissees.json'


def _collections_de(b: Bibliotheque, el: Element) -> list[str]:
    cle = {cid: c.cle for cid, c in b.collections.items()}
    return sorted(cle[c] for c in el.collections)


def charger_laissees(b: Bibliotheque, cfg: Config) -> set[str]:
    """Fiches vues et laissées hors du fonds par décision (D176), tant que leurs collections n'ont pas changé."""
    try:
        brut = json.loads((cfg.suivi / LAISSEES).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return set()
    par_cle = b.par_cle()
    return {k for k, d in brut.items() if k in par_cle and _collections_de(b, par_cle[k]) == d['collections']}


def laisser(b: Bibliotheque, cfg: Config, cles: list[str]) -> list[str]:
    """Note des fiches sans place dans le fonds comme vues et laissées hors du fonds (D176). `a-ranger`, le tri de
    l'Inbox et l'audit ne les présentent plus, tant qu'elles restent dans les mêmes collections. Refuse une fiche de
    l'Inbox, une fiche qui a déjà sa place dans le fonds, et une fiche qui a une décision en attente ou acceptée."""
    m = cfg.methode
    e = _Etat(b)
    par_cle = b.par_cle()
    fonds = e.racine(m.fonds) if m.fonds else None
    inbox = e.racine(m.inbox) if m.inbox else None
    decidees = {x.cle for x in charger(cfg) if x.decision != REFUSER}
    for k in cles:
        el = par_cle.get(k)
        if el is None or not el.est_fiche:
            raise SystemExit(f'Aucune fiche de clé {k}.')
        dans = [e.cle[c] for c in el.collections]
        if inbox and any(e.sous(c, inbox) for c in dans):
            raise SystemExit(f'{k} est dans l\'Inbox. Une fiche de l\'Inbox se trie (`zc inbox preparer`), elle ne '
                             'se laisse pas hors du fonds.')
        if fonds and any(e.sous(c, fonds) for c in dans):
            raise SystemExit(f'{k} a déjà sa place dans le fonds.')
        if k in decidees:
            raise SystemExit(f'{k} a une décision en attente ou acceptée dans suivi/{FICHIER}. La passer à '
                             '« refuser » avant de laisser la fiche hors du fonds.')
    try:
        brut = json.loads((cfg.suivi / LAISSEES).read_text(encoding='utf-8'))
    except FileNotFoundError:
        brut = {}
    for k in cles:
        brut[k] = {'date': date.today().isoformat(), 'collections': _collections_de(b, par_cle[k])}
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    (cfg.suivi / LAISSEES).write_text(json.dumps(brut, ensure_ascii=False, indent=1, sort_keys=True),
                                      encoding='utf-8')
    return sorted(cles)


@dataclass
class Paquet:
    source: str  # chemin de la collection d'origine, ou « sans place dans le fonds »
    depuis: str  # clé de la collection quittée, vide pour une fiche sans place
    candidats: list[str]
    fiches: list[Element]


def a_ranger(b: Bibliotheque, cfg: Config) -> tuple[str, list[Paquet], int]:
    """Rapport des fiches à répartir ou à placer (D121), paquets, et nombre de propositions ajoutées par les tags."""
    plan_fonds = f.lire_plan((cfg.dossier_travail / f.PLAN).read_text(encoding='utf-8'), cfg)
    suivi = f.charger_suivi(cfg)
    entrees = charger(cfg)
    examinees = charger_examinees(cfg)
    v = viser(b, cfg, plan_fonds, suivi, entrees, examinees=examinees, laissees=charger_laissees(b, cfg))
    exclues = filtre.exclues(b, cfg)
    e = _Etat(b)
    decidees = {x.cle for x in entrees}
    par_cle = b.par_cle()

    def a_juger(el: Element) -> bool:
        return el.est_fiche and el.id not in exclues and el.cle not in decidees and el.cle not in v.corbeille_fiches

    paquets: list[Paquet] = []
    for a in suivi.collections:
        if a.sort != f.REPARTIR or a.cle not in e.nom:
            continue
        fiches = sorted((el for el in b.elements.values() if a_juger(el)
                         and any(e.cle[c] == a.cle for c in el.collections)
                         and a.cle not in v.fiches.get(el.cle, (set(), set()))[0]
                         and el.cle not in examinees.get(a.cle, ())), key=lambda el: norm(el.titre))
        for i in range(0, len(fiches), PAQUET):
            paquets.append(Paquet(e.chemin(a.cle), a.cle, a.candidats, fiches[i:i + PAQUET]))
    # Une fiche déjà présentée avec sa collection à répartir ne revient pas parmi les fiches sans place.
    presentees = {el.cle for p in paquets for el in p.fiches}
    sans = sorted((par_cle[c] for c in v.sans_place if a_juger(par_cle[c]) and c not in presentees),
                  key=lambda el: norm(el.titre))
    disciplines = [c for c, nd in plan_fonds.noeuds.items() if nd.niveau == 1]
    for i in range(0, len(sans), PAQUET):
        paquets.append(Paquet('sans place dans le fonds', '', disciplines, sans[i:i + PAQUET]))

    # Propositions tirées des tags reliés à un thème (D100, D116), pour les fiches à juger seulement.
    ajouts = []
    for p in paquets:
        for el in p.fiches:
            cibles = [suivi.tags[n] for n, t in el.tags if n in suivi.tags and suivi.tags[n] in plan_fonds.noeuds]
            if cibles:
                ajouts.append(Entree(el.cle, DEPLACER, cibles[0], p.depuis, TAG, '',
                                     f'tag « {next(n for n, _ in el.tags if n in suivi.tags)} »'))
    if ajouts:
        ecrire(cfg, entrees + ajouts, b, exclues)
    creer_si_absent(cfg)
    return _rapport_a_ranger(paquets, plan_fonds, ajouts, e, len(v.laissees)), paquets, len(ajouts)


def _rapport_a_ranger(paquets: list[Paquet], plan_fonds: f.Plan, ajouts: list[Entree], e: _Etat, laissees: int = 0,
                      jour: date | None = None) -> str:
    jour = jour or date.today()
    total = sum(len(p.fiches) for p in paquets)
    L = [f'# Fiches à ranger, {jour:%d/%m/%Y}', '',
         f'{total} fiche(s) en {len(paquets)} paquet(s) de {PAQUET} au plus, sans celles déjà décidées dans '
         '`suivi/rangement.toml` ni celles exclues par le filtre de confidentialité. Pour chaque fiche, proposer '
         'une cible parmi les candidats, ou la laisser en place. Écrire les propositions dans `suivi/rangement.toml` '
         '(une table `[[fiche]]` par fiche, comme dans l\'exemple de l\'en-tête, avec `depuis` = la clé donnée pour '
         'le paquet), puis les faire approuver paquet par paquet. Une fiche n\'apparaît que dans un seul paquet.']
    if laissees:
        L += ['', 'Fiches laissées hors du fonds par décision (`zc fonds a-ranger --laisser`), non présentées tant '
                  f'que leurs collections ne changent pas, {laissees}.']
    if ajouts:
        L += ['', f'{len(ajouts)} proposition(s) tirée(s) des tags reliés à un thème ont été ajoutées à '
                  '`suivi/rangement.toml`, à approuver comme les autres (fiches marquées « tag » ci-dessous).']
    proposees = {x.cle: x.cible for x in ajouts}
    for n, p in enumerate(paquets, 1):
        L += ['', f'## Paquet {n} · {p.source}' + (f' (depuis = "{p.depuis}")' if p.depuis else ' (depuis = "")'), '']
        if not p.depuis:
            L += ['`depuis` reste vide. Pour une fiche hors de toute collection, « déplacer » ou « ajouter » reviennent '
                  'au même. Une fiche rangée hors du fonds (projet, archives) reçoit « ajouter » et y reste.', '']
        L += ['Candidats :', '']
        for c in p.candidats:
            nd = plan_fonds.noeuds.get(c)
            if nd:
                ligne = f'- **{c}**. {nd.definition}'
                ligne += f' Inclut : {nd.inclut}' if nd.inclut else ''
                ligne += f' Exclut : {nd.exclut}' if nd.exclut else ''
                L.append(ligne)
        L += ['', 'Fiches :', '']
        for el in p.fiches:
            tags = ', '.join(n for n, t in el.tags if t == 0)
            autres = ', '.join(sorted(e.chemin(e.cle[c]) for c in el.collections if e.cle[c] != p.depuis))
            L.append(f'- {el.cle} · {_ligne(el)} · {nom_type(el.type)}' + (f' · tags {tags}' if tags else '')
                     + (f' · aussi dans {autres}' if autres else ' · hors de toute collection' if not p.depuis else '')
                     + (f' · tag → {proposees[el.cle]}' if el.cle in proposees else ''))
    return '\n'.join(L) + '\n'


def resume(b: Bibliotheque, cfg: Config, cle: str) -> str:
    """Résumé d'une fiche douteuse (D121), jamais pour une fiche exclue par le filtre."""
    el = b.par_cle().get(cle)
    if el is None:
        raise SystemExit(f'Aucune fiche de clé {cle}.')
    if el.id in filtre.exclues(b, cfg):
        raise SystemExit(f'La fiche {cle} est exclue par le filtre de confidentialité, son résumé n\'est pas donné.')
    return f"{_ligne(el)}\n\n{el.champs.get('abstractNote') or '(pas de résumé)'}"
