"""Clés de citation, étape 7 du nettoyage (D143 à D146, D162).

Better BibTeX remplit les clés manquantes, `zc` ne fait que ce que BBT ne fait
pas. Ce module repère les clés en double, comparées sans tenir compte de la
casse sauf si BBT est réglé pour la distinguer, et les départage selon D144.
La fiche la plus ancienne (date d'ajout) garde la clé, les autres reçoivent le
premier suffixe libre (a, b… z, puis aa), comme le format `%(a)s` de BBT. Un
double dont deux fiches forment un groupe de doublons non jugé distinct est
renvoyé à l'étape 2, puisque la fusion réglera la clé.

`planifier` en tire un plan (D146), avec un groupe par clé en double et un
groupe par fiche dont Extra garde une ligne `Citation Key:`. La ligne passe
dans le champ natif s'il est vide, est retirée si elle répète la clé native,
et devient un cas à juger dans `suivi/cles.toml` si elle en diffère. Le reste
d'Extra est intact. Le plan compare l'état réel à l'état visé et ne planifie
que la différence (D119), les données d'avant venant de l'API.

Sans BBT actif, l'étape est sautée (D146), sauf le départage des doubles. Il
ne demande aucun calcul, BBT ne s'en charge pas même quand il est là (D162),
et une clé en double gêne toute exportation, celle de Zotero comprise. Les
lignes d'Extra, restes de BBT 7, attendent alors BBT.
"""

import re
import tomllib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date

from zot_clean import bbt, filtre
from zot_clean.config import Config
from zot_clean.ecriture import Client, Refus
from zot_clean.lecture import Bibliotheque, Element
from zot_clean.plans import Groupe, Operation, Plan

# Ligne `Citation Key: …` laissée dans Extra par BBT 7 ou par un import, que Zotero lit sans tenir compte de la casse.
LIGNE_EXTRA = re.compile(r'^[ \t]*citation[ \t]*key[ \t]*:[ \t]*(\S+)[ \t]*$', re.I | re.M)


def normaliser(cle: str, casse: bool = False) -> str:
    return cle.strip() if casse else cle.strip().lower()


def _anciennete(e: Element) -> tuple[str, str]:
    return e.ajout or '', e.cle


def doubles(b: Bibliotheque, casse: bool = False) -> dict[str, list[Element]]:
    """Clés portées par plusieurs fiches, par clé normalisée, chaque groupe trié de la fiche la plus ancienne à
    la plus récente."""
    par = defaultdict(list)
    for e in b.fiches:
        if cle := e.champs.get('citationKey', '').strip():
            par[normaliser(cle, casse)].append(e)
    return {k: sorted(v, key=_anciennete) for k, v in sorted(par.items()) if len(v) > 1}


def lettres(n: int) -> str:
    """1 → a, 26 → z, 27 → aa, 28 → ab."""
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord('a') + r) + s
    return s


def suffixe_libre(base: str, prises: Iterable[str], casse: bool = False) -> str:
    """Premier suffixe alphabétique qui, ajouté à `base`, ne donne aucune des clés `prises`."""
    prises = {normaliser(p, casse) for p in prises}
    n = 1
    while normaliser(base + lettres(n), casse) in prises:
        n += 1
    return lettres(n)


def base_de(cle: str) -> str:
    """Clé sans le suffixe que BBT ajoute après l'année en cas de collision (« durand2020a » → « durand2020 »), pour
    que le départage continue la série comme BBT (« durand2020b ») au lieu d'empiler les lettres."""
    m = re.fullmatch(r'(.*\d{4})[A-Za-z]{1,2}', cle)
    return m.group(1) if m else cle


@dataclass
class Changement:
    fiche: Element
    avant: str
    apres: str


@dataclass
class Double:
    cle: str  # clé normalisée
    garde: Element  # fiche qui garde sa clé
    changements: list[Changement] = field(default_factory=list)


@dataclass
class Departage:
    doubles: list[Double] = field(default_factory=list)
    # Doubles dont des fiches forment un groupe de doublons non jugé distinct, laissés à l'étape 2.
    renvoyes: dict[str, list[Element]] = field(default_factory=dict)
    # Doubles écartés par l'utilisateur dans `suivi/cles.toml`, laissés tels quels.
    ecartes: dict[str, list[Element]] = field(default_factory=dict)


def departager(b: Bibliotheque, casse: bool = False, doublons_non_juges: Iterable[Iterable[str]] = (),
               gardes: dict[str, str] | None = None, ecartes: Iterable[str] = ()) -> Departage:
    """Départage des clés en double (D144).

    `doublons_non_juges` donne les groupes de doublons (clés de fiches) qui ne sont pas jugés distincts.
    `gardes` impose, par clé de citation, la clé de la fiche qui la garde (`suivi/cles.toml`). Une fiche
    imposée absente du groupe est ignorée, la plus ancienne garde alors la clé. Les suffixes sont calculés
    contre toutes les clés de la bibliothèque et contre ceux déjà attribués. `ecartes` donne les clés de
    citation des doubles à laisser tels quels."""
    gardes = {normaliser(k, casse): v for k, v in (gardes or {}).items()}
    ecartes = {normaliser(k, casse) for k in ecartes}
    groupes_doublons = [set(g) for g in doublons_non_juges]
    prises = {normaliser(e.champs['citationKey'], casse) for e in b.fiches if e.champs.get('citationKey', '').strip()}
    res = Departage()
    for k, fiches in doubles(b, casse).items():
        cles_fiches = {e.cle for e in fiches}
        if any(len(cles_fiches & g) > 1 for g in groupes_doublons):
            res.renvoyes[k] = fiches
            continue
        if k in ecartes:
            res.ecartes[k] = fiches
            continue
        garde = next((e for e in fiches if e.cle == gardes.get(k)), fiches[0])
        double = Double(k, garde)
        for e in fiches:
            if e is garde:
                continue
            avant = e.champs['citationKey']
            # Base tirée de la clé gardée : deux clés qui ne diffèrent que par la casse donnent la même série
            # (« dreyfus…1992 » et « dreyfus…1992a », non « Dreyfus…1992a »).
            base = base_de(garde.champs['citationKey'].strip())
            nouvelle = base + suffixe_libre(base, prises, casse)
            prises.add(normaliser(nouvelle, casse))
            double.changements.append(Changement(e, avant, nouvelle))
        res.doubles.append(double)
    return res


def restes_extra(b: Bibliotheque) -> list[tuple[Element, str]]:
    """Fiches dont Extra contient encore une ligne `Citation Key:`, avec la clé qu'elle porte."""
    trouves = []
    for e in b.fiches:
        if m := LIGNE_EXTRA.search(e.champs.get('extra', '')):
            trouves.append((e, m.group(1)))
    return trouves


# --- Plan de l'étape 7 (D146) -----------------------------------------------------

FICHIER = 'cles.toml'
ETAPE = 'cles'
ECARTER, NATIF, EXTRA = 'écarter', 'natif', 'extra'
# Sortes de changement, que les premiers groupes du plan (l'essai) couvrent toutes.
SUFFIXE, VERS_NATIF, RETIREE, REMPLACEE = ('suffixe', 'Extra vers le champ natif', "ligne d'Extra retirée",
                                           'clé native remplacée')

EN_TETE = """\
# Clés de citation, cas qui demandent un avis, écrits par `zc cles planifier` (étape 7).
# Ce fichier est facultatif. Il se relit et se modifie à la main ou avec l'agent. `zc cles planifier` le met à jour
# sans perdre les décisions prises, puis prépare le plan d'après elles. Un cas réglé dans Zotero en disparaît.
# Les décisions s'écrivent avec `zc cles decider FICHE=garder|écarter|natif|extra`.
#
# [[double]], une clé de citation portée par plusieurs fiches. La plus ancienne (date d'ajout) garde la clé, les
#   autres reçoivent un suffixe (a, b…).
#   fiches   : fiches qui partagent la clé, de la plus ancienne à la plus récente (renseigné par zc).
#   garde    : clé de la fiche qui garde la clé de citation, à la place de la plus ancienne (facultatif).
#   decision : "" (départager selon la règle) ou "écarter" (laisser tel quel, hors du plan).
#   Un double dont les fiches forment un groupe de doublons non jugé distinct est renvoyé à l'étape 2
#   (suivi/doublons.toml), la fusion réglant la clé.
#
# [[extra]], une fiche dont Extra garde une ligne « Citation Key: » qui diffère de sa clé native.
#   decision : "" (à juger), "natif" (garder la clé native, retirer la ligne), "extra" (la clé de la ligne remplace
#              la clé native, ligne retirée) ou "écarter" (ne rien changer, hors du plan).
#
# raison : note libre.
"""

# Ligne `Citation Key:` d'Extra, lue ligne à ligne pour pouvoir la retirer sans toucher au reste.
_LIGNE = re.compile(r'^[ \t]*citation[ \t]*key[ \t]*:[ \t]*(\S+)[ \t]*\r?$', re.I)


def cles_extra(extra: str) -> list[str]:
    """Clés des lignes `Citation Key:` d'Extra, dans l'ordre."""
    return [m.group(1) for ligne in (extra or '').split('\n') if (m := _LIGNE.match(ligne))]


def sans_lignes(extra: str) -> str:
    """Extra sans ses lignes `Citation Key:`, le reste intact."""
    return '\n'.join(ligne for ligne in (extra or '').split('\n') if not _LIGNE.match(ligne))


@dataclass
class EntreeDouble:
    fiches: list[str]
    garde: str = ''
    decision: str = ''
    raison: str = ''


@dataclass
class EntreeExtra:
    fiche: str
    decision: str = ''
    raison: str = ''


@dataclass
class Suivi:
    doubles: list[EntreeDouble] = field(default_factory=list)
    extra: list[EntreeExtra] = field(default_factory=list)


def charger(cfg: Config) -> Suivi:
    """`suivi/cles.toml`, facultatif (D146)."""
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return Suivi()
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    s = Suivi()
    for g in brut.get('double', []):
        e = EntreeDouble([str(k) for k in g.get('fiches', [])], g.get('garde', ''), g.get('decision', ''),
                         g.get('raison', ''))
        if e.decision not in ('', ECARTER):
            raise SystemExit(f'{chemin} : décision inconnue « {e.decision} » pour {", ".join(e.fiches)}.')
        s.doubles.append(e)
    for g in brut.get('extra', []):
        if not g.get('fiche'):
            raise SystemExit(f"{chemin} : une entrée [[extra]] n'a pas de fiche.")
        e = EntreeExtra(g['fiche'], g.get('decision', ''), g.get('raison', ''))
        if e.decision not in ('', NATIF, EXTRA, ECARTER):
            raise SystemExit(f'{chemin} : décision inconnue « {e.decision} » pour {e.fiche}.')
        s.extra.append(e)
    return s


GARDER = 'garder'
DECISIONS = {'garder': GARDER, 'garde': GARDER, 'ecarter': ECARTER, 'écarter': ECARTER, 'natif': NATIF,
             'extra': EXTRA}


def decider(s: Suivi, decisions: dict[str, str], raison: str = '') -> int:
    """Décisions prises par commande (D177, sur le modèle de D172), au lieu d'écrire le fichier à la main. Par clé de
    fiche, « garder » (la fiche garde la clé de citation de son double), « écarter » (double ou cas d'Extra laissé
    tel quel), « natif » ou « extra » (cas d'Extra). Seuls les cas qui attendent changent, c'est-à-dire les doubles
    sans décision ni fiche imposée et les cas d'Extra sans décision. Renvoie le nombre de cas décidés."""
    extra = {e.fiche: e for e in s.extra if not e.decision}
    doubles = {k: d for d in s.doubles if not d.decision and not d.garde for k in d.fiches}
    connues = {e.fiche for e in s.extra} | {k for d in s.doubles for k in d.fiches}
    erreurs, vises = [], []
    for fiche, texte in decisions.items():
        decision = DECISIONS.get(texte.strip().lower())
        if decision is None:
            erreurs.append(f'{fiche} : décision inconnue « {texte} » (garder, écarter, natif ou extra).')
        elif fiche not in connues:
            erreurs.append(f'{fiche} ne figure dans aucun cas de {FICHIER}. Vérifier la clé, ou relancer '
                           '`zc cles planifier`.')
        elif decision in (NATIF, EXTRA) and fiche not in extra:
            erreurs.append(f'{fiche} n\'a pas de ligne d\'Extra à juger ([[extra]]), « {decision} » ne s\'y applique '
                           'pas, ou la décision est déjà prise.')
        elif decision == GARDER and fiche not in doubles:
            erreurs.append(f'{fiche} n\'est dans aucune clé en double à juger ([[double]]), ou la décision est déjà '
                           'prise.')
        elif decision == ECARTER and fiche in extra and fiche in doubles:
            erreurs.append(f'{fiche} a à la fois une clé en double et une ligne d\'Extra à juger. Écarter l\'un ou '
                           'l\'autre à la main dans le fichier.')
        elif decision == ECARTER and fiche not in extra and fiche not in doubles:
            erreurs.append(f'{fiche} : décision déjà prise. Une décision prise se change à la main dans le fichier.')
        else:
            vises.append((fiche, decision))
    touches = [id(doubles[f]) for f, d in vises if f in doubles and not (d == ECARTER and f in extra)]
    if len(set(touches)) < len(touches):
        erreurs.append('Une seule décision par clé en double (une seule fiche garde la clé).')
    if erreurs:
        raise SystemExit(' '.join(erreurs))
    for fiche, decision in vises:
        if decision in (NATIF, EXTRA) or (decision == ECARTER and fiche in extra):
            e = extra[fiche]
            e.decision, e.raison = decision, raison or e.raison
        else:
            d = doubles[fiche]
            if decision == GARDER:
                d.garde = fiche
            else:
                d.decision = ECARTER
            d.raison = raison or d.raison
    return len(vises)


def refus(b: Bibliotheque, cfg: Config, etat: bbt.Etat) -> str:
    """Pourquoi l'étape ne peut pas tourner, vide si elle le peut."""
    if not cfg.methode.cles_citation:
        return "L'étape des clés de citation est désactivée dans config.toml (`cles_citation = false`)."
    if 'citationKey' not in b.champs_connus:
        return ("Cette version de Zotero n'a pas de champ « Clé de citation », apparu avec Zotero 7. Mettre Zotero "
                'à jour avant cette étape.')
    if etat.present and etat.trop_ancien:
        return (f'Better BibTeX {etat.version} range les clés dans sa propre base et non dans le champ de Zotero. '
                f'Passer à Better BibTeX {bbt.VERSION_MIN} et Zotero 8 avant cette étape.')
    return ''


def avertissements(b: Bibliotheque, etat: bbt.Etat) -> list[str]:
    """Réglages de BBT à signaler avant d'écrire (D146)."""
    from zot_clean.audit import pluriel
    res = []
    if etat.present and etat.regenere:
        res.append(REGENERE)
    sans = sum(1 for e in b.fiches if not e.champs.get('citationKey', '').strip())
    if etat.present and etat.remplissage == 0 and sans:
        res.append(f"{pluriel(sans, 'référence')} sans clé, et Better BibTeX ne remplit pas seul les clés manquantes "
                   "(« Automatically fill citation key after » à 0). Les remplir par clic droit, Better BibTeX › "
                   "Fill, ou régler un délai.")
    return res


REGENERE = ("Better BibTeX refait la clé d'une fiche à chaque modification (« Regenerate citation key when item "
            "changes »). Chaque fiche modifiée par zc recevrait une nouvelle clé, et les suffixes des clés en double "
            "seraient recalculés. Décocher ce réglage dans Zotero › Réglages › Better BibTeX avant d'appliquer.")


def doublons_non_juges(b: Bibliotheque, cfg: Config) -> list[set[str]]:
    """Groupes de doublons repérés et non jugés distincts dans `suivi/doublons.toml` (D144)."""
    from zot_clean import doublons
    distincts = doublons.distincts(doublons.charger_suivi(cfg))
    return [c for g in doublons.candidats(b) if not doublons.deja_juge(c := {e.cle for e in g}, distincts)]


@dataclass
class CasExtra:
    fiche: Element
    natif: str
    lignes: list[str]  # clés distinctes des lignes d'Extra
    sorte: str = ''  # VERS_NATIF, RETIREE, REMPLACEE, vide pour un cas à juger ou écarté
    cible: str = ''  # clé native visée
    decision: str = ''


def _cas_extra(b: Bibliotheque, suivi: Suivi) -> list[CasExtra]:
    decisions = {e.fiche: e.decision for e in suivi.extra}
    res = []
    for e in b.fiches:
        lignes = list(dict.fromkeys(cles_extra(e.champs.get('extra', ''))))
        if not lignes:
            continue
        c = CasExtra(e, e.champs.get('citationKey', '').strip(), lignes, decision=decisions.get(e.cle, ''))
        if not c.natif and len(lignes) == 1:
            c.sorte, c.cible = VERS_NATIF, lignes[0]
        elif c.natif and lignes == [c.natif]:
            c.sorte, c.cible = RETIREE, c.natif
        elif c.decision == NATIF and c.natif:
            c.sorte, c.cible = RETIREE, c.natif
        elif c.decision == EXTRA:
            c.sorte, c.cible = (REMPLACEE if c.natif else VERS_NATIF), lignes[0]
        res.append(c)
    return res


def _simulee(b: Bibliotheque, cibles: dict[str, str]) -> Bibliotheque:
    """Les fiches avec la clé native qu'elles auront une fois les lignes d'Extra rangées, pour que le départage
    tienne compte des clés qui sortent d'Extra."""
    elements = {}
    for e in b.fiches:
        cle = cibles.get(e.cle, e.champs.get('citationKey', ''))
        elements[e.id] = replace(e, champs={'citationKey': cle} if cle else {})
    return Bibliotheque(b.version_schema, elements, {}, {}, {}, [])


def _entree(entrees: list[EntreeDouble], fiches: set[str]) -> EntreeDouble | None:
    """Entrée du suivi d'un double, celle qui partage le plus de fiches avec lui (deux au moins)."""
    meilleure, n = None, 1
    for x in entrees:
        if (k := len(set(x.fiches) & fiches)) > n:
            meilleure, n = x, k
    return meilleure


@dataclass
class Analyse:
    extra: list[CasExtra]
    departage: Departage
    entrees: dict[str, EntreeDouble]  # entrée du suivi de chaque double, par clé normalisée


def analyser(b: Bibliotheque, cfg: Config, etat: bbt.Etat, suivi: Suivi, avec_extra: bool = True) -> Analyse:
    cas = _cas_extra(b, suivi) if avec_extra else []
    sim = _simulee(b, {c.fiche.cle: c.cible for c in cas if c.sorte})
    entrees = {}
    for k, fiches in doubles(sim, etat.casse).items():
        if x := _entree(suivi.doubles, {e.cle for e in fiches}):
            entrees[k] = x
    gardes = {k: x.garde for k, x in entrees.items() if x.garde}
    ecartes = [k for k, x in entrees.items() if x.decision == ECARTER]
    d = departager(sim, etat.casse, doublons_non_juges(b, cfg), gardes, ecartes)
    return Analyse(cas, d, entrees)


@dataclass
class _Vise:
    fiche: Element  # telle que la copie locale la donne
    cle: str | None = None  # nouvelle clé native, None si elle ne change pas
    extra: bool = False  # retirer les lignes `Citation Key:` d'Extra
    sortes: set[str] = field(default_factory=set)


def _operations(vises: dict[str, _Vise], client: Client) -> tuple[dict[str, Operation], list[str]]:
    """Opérations par fiche, l'avant relu par l'API. Une fiche qui a changé depuis la copie locale est laissée."""
    if not vises:
        return {}, []
    api = client.fiches(sorted(vises))
    ops, problemes = {}, []
    for cle, v in vises.items():
        d = api.get(cle)
        if d is None or d.get('deleted'):
            problemes.append(f"La fiche {cle} n'existe plus dans Zotero ou est à la corbeille, laissée de côté.")
            continue
        natif, extra = d.get('citationKey') or '', d.get('extra') or ''
        if (natif.strip() != v.fiche.champs.get('citationKey', '').strip()
                or cles_extra(extra) != cles_extra(v.fiche.champs.get('extra', ''))):
            problemes.append(f'La fiche {cle} a changé depuis la copie locale, laissée de côté. Relancer après la '
                             'synchronisation de Zotero.')
            continue
        avant, apres = {}, {}
        if v.cle is not None and v.cle != natif:
            avant['citationKey'], apres['citationKey'] = natif, v.cle
        if v.extra and (nouveau := sans_lignes(extra)) != extra:
            avant['extra'], apres['extra'] = extra, nouveau
        if apres:
            ops[cle] = Operation(cle, avant, apres, nature=', '.join(sorted(v.sortes)))
    return ops, problemes


@dataclass
class _Retenu:
    groupe: Groupe
    sortes: set[str]
    cache: bool
    double: Double | None = None
    cas: CasExtra | None = None


def _fiches(fiches: Iterable[Element]) -> set[str]:
    return {e.cle for e in fiches}


def planifier(b: Bibliotheque, cfg: Config, client: Client, etat: bbt.Etat | None = None,
              jour: date | None = None) -> tuple[Plan, str]:
    """Plan de l'étape 7 (D146), un groupe par clé en double et un groupe par fiche pour une ligne d'Extra. Écrit
    aussi `suivi/cles.toml` quand des cas demandent un avis."""
    etat = etat or bbt.detecter(cfg.dossier_zotero)
    if motif := refus(b, cfg, etat):
        raise Refus(motif)
    if (serveur := client.version_serveur()) > b.version:
        raise Refus(f"Zotero n'a pas encore reçu les derniers changements de la bibliothèque (version locale "
                    f'{b.version}, version du serveur {serveur}). Vérifier que Zotero est ouvert et synchronise, '
                    'puis relancer.')
    a = analyser(b, cfg, etat, charger(cfg), avec_extra=etat.present)
    masquees = filtre.cles_masquees(b, cfg)
    ecrire(cfg, b, a, masquees)

    par_cle = b.par_cle()
    vises: dict[str, _Vise] = {}
    for c in a.extra:
        if c.sorte:
            vises[c.fiche.cle] = _Vise(c.fiche, c.cible if c.cible != c.natif else None, True, {c.sorte})
    for dbl in a.departage.doubles:
        for ch in dbl.changements:
            v = vises.setdefault(ch.fiche.cle, _Vise(par_cle[ch.fiche.cle]))
            v.cle = ch.apres
            v.sortes.add(SUFFIXE)
    ops, problemes = _operations(vises, client)

    retenus: list[_Retenu] = []
    for dbl in a.departage.doubles:
        g_ops = [ops[ch.fiche.cle] for ch in dbl.changements if ch.fiche.cle in ops]
        if g_ops:
            cache = bool(masquees & _fiches([dbl.garde, *(ch.fiche for ch in dbl.changements)]))
            titre = filtre.MASQUE if cache else dbl.garde.champs['citationKey'].strip()
            sortes = set().union(*(vises[op.cle].sortes for op in g_ops))
            retenus.append(_Retenu(Groupe(f'double-{dbl.garde.cle}', titre, g_ops), sortes, cache, double=dbl))
    for c in a.extra:
        op = ops.get(c.fiche.cle)
        if c.sorte and op and SUFFIXE not in vises[c.fiche.cle].sortes:
            cache = c.fiche.cle in masquees
            retenus.append(_Retenu(Groupe(c.fiche.cle, filtre.MASQUE if cache else _titre(c.fiche), [op]),
                                   {c.sorte}, cache, cas=c))
    retenus = _ordonner(retenus, cfg.ecriture.essai)
    plan = Plan(ETAPE, client.utilisateur, [r.groupe for r in retenus],
                description=f'Clés de citation, {len(retenus)} groupe(s).')
    return plan, _rapport(b, a, etat, retenus, problemes, masquees, cfg.ecriture.essai, jour or date.today())


def _titre(e: Element) -> str:
    from zot_clean.audit import annee
    return f"{e.auteur or '?'}, {annee(e) or 's. d.'}, {e.titre[:60] or '(sans titre)'}"


def _ordonner(retenus: list[_Retenu], essai: int) -> list[_Retenu]:
    """Les premiers groupes, appliqués par l'essai, couvrent chaque sorte de changement présente (D146)."""
    restants = list(retenus)
    reste = set().union(*(r.sortes for r in restants))
    premiers = []
    while reste and len(premiers) < essai:
        _, r = max(enumerate(restants), key=lambda ir: (len(ir[1].sortes & reste), not ir[1].cache, -ir[0]))
        premiers.append(r)
        restants.remove(r)
        reste -= r.sortes
    return premiers + restants


def ecrire(cfg: Config, b: Bibliotheque, a: Analyse, masquees: set[str], suivi: Suivi | None = None) -> None:
    """`suivi/cles.toml`, écrit seulement quand des cas demandent un avis ou que le fichier existe déjà (D146).
    La clé de citation d'un double qui touche une fiche confidentielle n'y figure pas (D126). `suivi` donne les
    raisons des cas d'Extra, celles du fichier par défaut. Un cas d'Extra décidé y reste jusqu'à ce qu'il soit réglé
    dans Zotero (D177)."""
    from zot_clean.audit import ligne
    from zot_clean.doublons import _toml
    d = a.departage
    par_cle = b.par_cle()  # les fiches du départage ne portent que leur clé de citation
    nouvelles = {ch.fiche.cle: ch.apres for dbl in d.doubles for ch in dbl.changements}
    tous = ([(dbl.cle, [dbl.garde, *(ch.fiche for ch in dbl.changements)], '') for dbl in d.doubles]
            + [(k, f, 'écarté') for k, f in d.ecartes.items()] + [(k, f, 'renvoyé') for k, f in d.renvoyes.items()])
    blocs = []
    for k, fiches, etat in sorted(tous, key=lambda t: t[0]):
        x = a.entrees.get(k) or EntreeDouble([])
        fiches = sorted(fiches, key=_anciennete)
        caches = _fiches(fiches) if masquees & _fiches(fiches) else set()
        blocs.append('[[double]]')
        if etat == 'renvoyé':
            blocs.append("# renvoyé à l'étape 2, ces fiches forment un groupe de doublons non jugé distinct "
                         '(suivi/doublons.toml)')
        blocs.append(f"# clé {filtre.MASQUE if caches else '« ' + fiches[0].champs['citationKey'].strip() + ' »'}")
        for e in fiches:
            if e.cle in nouvelles:
                quoi = 'reçoit un suffixe' if caches else f'→ {nouvelles[e.cle]}'
            else:
                quoi = 'inchangée' if etat else 'garde la clé'
            blocs.append(f"# {ligne(par_cle[e.cle], caches)}, ajoutée le {(e.ajout or '')[:10]}, {quoi}")
        blocs += [f'fiches = {_toml([e.cle for e in fiches])}', f'garde = {_toml(x.garde)}',
                  f'decision = {_toml(x.decision)}', f'raison = {_toml(x.raison)}', '']
    chemin = cfg.suivi / FICHIER
    raisons = {e.fiche: e.raison for e in (suivi or charger(cfg)).extra}
    for c in a.extra:
        if c.sorte and not c.decision:
            continue
        blocs.append('[[extra]]')
        if c.fiche.cle in masquees:
            blocs.append(f'# {c.fiche.cle} · {filtre.MASQUE}')
        else:
            blocs += [f'# {ligne(c.fiche)}', f"# clé native « {c.natif} », ligne{'s' if len(c.lignes) > 1 else ''} "
                                              "d'Extra « " + ' », « '.join(c.lignes) + ' »']
        if c.decision == NATIF and not c.natif:
            blocs.append('# "natif" impossible, la fiche n\'a pas de clé native')
        blocs += [f'fiche = {_toml(c.fiche.cle)}', f'decision = {_toml(c.decision)}',
                  f"raison = {_toml(raisons.get(c.fiche.cle, ''))}", '']
    if not blocs and not chemin.is_file():
        return
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    from zot_clean.audit import ecrire_toml
    ecrire_toml(chemin, [EN_TETE, *blocs])


def _rapport(b: Bibliotheque, a: Analyse, etat: bbt.Etat, retenus: list[_Retenu], problemes: list[str],
             masquees: set[str], essai: int, jour: date) -> str:
    from zot_clean.audit import ligne, pluriel
    d = a.departage
    par_cle = b.par_cle()
    doubles_ = [r for r in retenus if r.double]
    extras = [r for r in retenus if r.cas]
    suffixes = sum(len(r.groupe.operations) for r in doubles_)
    def s(n: int) -> str:
        return 's' if n > 1 else ''

    L = [f'# Clés de citation, plan du {jour:%d/%m/%Y}', '', bbt.decrire(etat), '',
         f"{pluriel(len(retenus), 'groupe')}. {pluriel(len(doubles_), 'clé')} en double départagée{s(len(doubles_))}, "
         f"la plus ancienne fiche gardant la clé et {pluriel(suffixes, 'autre')} recevant un suffixe. "
         f"{pluriel(len(extras), 'ligne')} « Citation Key: » d'Extra rangée{s(len(extras))}, le reste d'Extra "
         "intact. Une clé unique n'est jamais touchée."]
    if doubles_:
        L += ['', "Une fiche qui reçoit un suffixe change de clé. Un texte qui la citait sous l'ancienne clé, ambiguë "
                  'jusqu\'ici, est à mettre à jour.']
    if avert := avertissements(b, etat):
        L += ['', '## Attention', ''] + [f'- {x}' for x in avert]
    if not etat.present:
        restes = len(restes_extra(b))
        L += ['', "Better BibTeX n'est pas actif. L'étape est sautée, sauf le départage des clés en double, qui "
                  'ne demande aucun calcul.'
              + (f" {pluriel(restes, 'fiche')} dont Extra garde une ligne « Citation Key: » "
                 f"{'attendent' if restes > 1 else 'attend'} Better BibTeX." if restes else '')]
    premiers = retenus[:essai]
    if premiers and len(retenus) > essai:
        L += ['', '## Essai', '', f'Les {len(premiers)} premiers groupes, appliqués par `zc appliquer <plan> --essai`, '
              'couvrent chaque sorte de changement. À vérifier avec `zc voir` :', '']
        L += [f"- {r.groupe.id} · {r.groupe.titre} ({', '.join(sorted(r.sortes))})" for r in premiers]
    if doubles_:
        from zot_clean.audit import norm
        L += ['', '## Clés en double', '']
        autre_titre = 0
        for r in doubles_:
            changees = {op.cle: op.apres.get('citationKey', '') for op in r.groupe.operations}
            if r.cache:
                L.append(f'- {filtre.MASQUE}, {r.double.garde.cle} garde la clé, '
                         + ', '.join(f'{k} reçoit un suffixe' for k in changees))
            else:
                garde = par_cle[r.double.garde.cle]
                L.append(f'- « {r.groupe.titre} », {ligne(garde)} garde la clé')
                for k, n in changees.items():
                    # La clé suffixée reprend le titre de la fiche qui garde la clé (D144). Quand les titres
                    # diffèrent, elle parle d'un autre texte : le signaler, sans changer la règle.
                    autre = etat.present and norm(par_cle[k].titre) != norm(garde.titre)
                    autre_titre += autre
                    L.append(f'  - {ligne(par_cle[k])} → {n}' + (" (clé tirée du titre d'une autre fiche)" if autre
                                                                  else ''))
        if autre_titre:
            L += ['', f"{pluriel(autre_titre, 'fiche')} {'reçoivent' if autre_titre > 1 else 'reçoit'} une clé tirée "
                  "du titre d'une autre fiche. Pour lui donner une clé tirée de son propre titre, régénérer la clé de "
                  'cette fiche seule dans Zotero une fois le plan appliqué et synchronisé (clic droit sur la fiche, '
                  'Better BibTeX › Refresh). Sa clé venant de changer, aucun texte ne la cite encore sous ce nom.']
    if extras:
        L += ['', "## Lignes « Citation Key: » d'Extra", '']
        for r in extras:
            c = r.cas
            if r.cache:
                L.append(f'- {c.fiche.cle} · {filtre.MASQUE}, {c.sorte}')
            elif c.sorte == VERS_NATIF:
                L.append(f'- {ligne(c.fiche)}, « {c.cible} » passe dans le champ natif')
            elif c.sorte == RETIREE:
                L.append(f'- {ligne(c.fiche)}, ligne retirée, la clé native « {c.natif} » reste')
            else:
                L.append(f'- {ligne(c.fiche)}, clé native « {c.natif} » remplacée par « {c.cible} »')
    if d.renvoyes:
        L += ['', "## Renvoyés à l'étape 2", '',
              'Ces fiches forment un groupe de doublons non jugé distinct dans `suivi/doublons.toml`. La fusion '
              'réglera la clé. Si elles sont distinctes, le noter dans `suivi/doublons.toml`, puis relancer.', '']
        for fiches in d.renvoyes.values():
            cache = masquees & _fiches(fiches)
            L.append(f"- {filtre.MASQUE if cache else '« ' + fiches[0].champs['citationKey'].strip() + ' »'}, "
                     + ', '.join(e.cle for e in fiches))
    a_juger = [c for c in a.extra if not c.sorte and c.decision != ECARTER]
    if a_juger:
        L += ['', '## À juger dans suivi/cles.toml', '',
              f"{pluriel(len(a_juger), 'fiche')} dont la ligne « Citation Key: » d'Extra diffère de la clé native, "
              f'laissée{s(len(a_juger))} hors du plan.', '']
        L += [f'- {c.fiche.cle} · {filtre.MASQUE}' if c.fiche.cle in masquees else
              f"- {ligne(c.fiche)}, native « {c.natif} », Extra « {' », « '.join(c.lignes)} »" for c in a_juger]
    ecartes = len(d.ecartes) + sum(1 for c in a.extra if not c.sorte and c.decision == ECARTER)
    if ecartes:
        L += ['', f"{pluriel(ecartes, 'cas')} écarté{s(ecartes)} dans suivi/cles.toml, laissé{s(ecartes)} "
                  f"tel{s(ecartes)} quel{s(ecartes)}."]
    sans = sum(1 for e in b.fiches if not e.champs.get('citationKey', '').strip())
    if sans:
        L += ['', f"{pluriel(sans, 'référence')} sans clé de citation. "
              + ('Better BibTeX les remplit seul quelques secondes après leur arrivée, ou sur demande par clic droit, '
                 'Better BibTeX › Fill.' if etat.present else 'Sans Better BibTeX, elles restent vides.')]
    if problemes:
        L += ['', '## À regarder', ''] + [f'- {p}' for p in problemes]
    return '\n'.join(L) + '\n'


# --- Tri de l'Inbox (D146) ----------------------------------------------------------

def signaler_sans_cle(b: Bibliotheque, cfg: Config, etat: bbt.Etat | None = None) -> bool:
    """Le tri signale une référence sans clé quand Better BibTeX, actif, aurait dû la remplir à son arrivée."""
    etat = etat or bbt.detecter(cfg.dossier_zotero)
    return etat.present and not refus(b, cfg, etat)


def departage_inbox(b: Bibliotheque, cfg: Config, client: Client, triees: set[str], exclues: set[str] = frozenset(),
                    etat: bbt.Etat | None = None) -> tuple[list[tuple[str, Operation]], set[str]]:
    """Départage (D144) des clés en double qui touchent une référence triée, pour le tri de l'Inbox (D146).

    Chaque opération, au rang 1, est rendue avec la référence triée dont le groupe la reçoit, la sienne si elle
    reçoit le suffixe. Un double qui touche une fiche de `exclues` (fusionnée par le même plan) est laissé. Rend
    aussi les références dont le groupe touche une fiche confidentielle, à montrer sans valeurs (D126)."""
    etat = etat or bbt.detecter(cfg.dossier_zotero)
    if refus(b, cfg, etat):
        return [], set()
    a = analyser(b, cfg, etat, charger(cfg), avec_extra=False)
    masquees = filtre.cles_masquees(b, cfg)
    par_cle = b.par_cle()
    retenus = []
    for dbl in a.departage.doubles:
        fiches = _fiches([dbl.garde, *(ch.fiche for ch in dbl.changements)])
        if fiches & triees and not fiches & exclues:
            retenus.append((dbl, fiches, next(k for k in [dbl.garde.cle, *(ch.fiche.cle for ch in dbl.changements)]
                                              if k in triees)))
    vises = {ch.fiche.cle: _Vise(par_cle[ch.fiche.cle], ch.apres, False, {SUFFIXE})
             for dbl, _, _ in retenus for ch in dbl.changements}
    ops, _ = _operations(vises, client)
    res, caches = [], set()
    for dbl, fiches, premiere in retenus:
        for ch in dbl.changements:
            if op := ops.get(ch.fiche.cle):
                op.rang = 1
                groupe = ch.fiche.cle if ch.fiche.cle in triees else premiere
                res.append((groupe, op))
                if masquees & fiches:
                    caches.add(groupe)
    return res, caches
