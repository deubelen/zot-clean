"""Doublons, étape 2 du nettoyage (D27, D49 à D51).

`chercher` repère les groupes candidats sur la copie de la base (DOI, ISBN,
titre, premier auteur et année), les classe en « sûrs » et « à juger » et les
écrit dans `suivi/doublons.toml`, en gardant les décisions déjà prises. Un
groupe jugé distinct n'est plus proposé, ni signalé par l'audit.

`planifier` construit, pour chaque groupe à fusionner, un plan qui fait ce
que fait la fusion de Zotero. Les enfants des fiches absorbées sont rattachés
à la fiche conservée (rang 0), la fiche conservée est complétée et les fiches
liées aux absorbées pointent vers elle (rang 1), les fiches absorbées vont à
la corbeille (rang 2). Les données viennent de l'API, les empreintes des
pièces jointes des fichiers locaux, puisque le `md5` de l'API est vide quand
les fichiers sont synchronisés par WebDAV.

Les relations suivent `moveRelations` de Zotero (`chrome/content/zotero/
mergeItems.mjs`). Celles d'une absorbée passent sur la fiche conservée, sauf
un lien vers une fiche du groupe, l'absorbée perd ses `dc:replaces`, la fiche
conservée gagne un `dc:replaces` vers elle, et une fiche liée qui pointait
vers l'absorbée pointe vers la fiche conservée. Les groupes d'un même plan
s'enchaînent comme des fusions successives, chacun partant des relations
laissées par les précédents.
"""

import json
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field

from zot_clean import filtre, plans
from zot_clean.cles import base_de
from zot_clean.audit import _doi, _isbns, annee, ecrire_toml, ligne, md5, nom_type, norm
from zot_clean.config import Config
from zot_clean.ecriture import Client
from zot_clean.lecture import Bibliotheque, Element, note_non_vide
from zot_clean.plans import Groupe, Operation, Plan
from zot_clean.sources import titres_concordants

FICHIER = 'doublons.toml'
FUSIONNER, DISTINCT = 'fusionner', 'distinct'
SUR, A_JUGER = 'sûr', 'à juger'
# Un même DOI ne fait un groupe sûr qu'avec des titres concordants, au seuil des correspondances évidentes de
# l'étape 3 (`metadonnees.SEUIL_EVIDENT`). À 0,8, un erratum (« Erratum to: <titre> ») passerait encore.
SEUIL_TITRES = 0.9
ENFANTS = {'attachment': 'la pièce jointe', 'note': 'la note'}
REMPLACE = 'dc:replaces'  # prédicat de Zotero qui garde la trace d'une fusion
COMPLETER = 'compléter la fiche conservée'
NE_PAS_COPIER = {'key', 'version', 'itemType', 'dateAdded', 'dateModified', 'collections', 'tags', 'relations',
                 'creators', 'deleted', 'parentItem'}

EN_TETE = """\
# Doublons repérés par `zc doublons chercher`, avec les décisions prises.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc doublons chercher` le met à jour
# sans perdre les décisions, `zc doublons planifier` prépare la fusion des groupes à fusionner.
# Les décisions s'écrivent avec `zc doublons accepter` (fusionner, --conserver) et `zc doublons refuser` (distinct).
#
# decision  : "fusionner", "distinct" (éditions ou textes différents, à ne plus signaler) ou "" (à juger).
# conserver : clé de la fiche à garder (facultatif, sinon celle qui a le plus de pièces jointes, puis la plus ancienne).
# forcer    : valeurs imposées à la fiche gardée, par exemple { "date" = "1938" } (facultatif).
# raison    : note libre, utile pour les groupes jugés distincts.
#
# Un groupe que `zc doublons chercher` n'a pas repéré s'ajoute à la fin du fichier, par exemple
#   [[groupe]]
#   cles = ["ABCD1234", "EFGH5678"]
#   decision = "fusionner"
# Il est gardé tant que ses fiches existent.
"""


def candidats(b: Bibliotheque) -> list[list[Element]]:
    parent = {e.id: e.id for e in b.fiches}

    def racine(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    index = defaultdict(list)
    for e in b.fiches:
        # Les chapitres portent souvent le DOI ou l'ISBN de l'ouvrage, qui ne les distingue pas.
        if e.champs.get('DOI') and e.type != 'bookSection':
            index['doi', _doi(e.champs['DOI'])].append(e.id)
        if e.type == 'book':
            for i in _isbns(e.champs.get('ISBN', '')):
                index['isbn', i].append(e.id)
        titre = norm(e.titre)
        if len(titre) >= 10:
            auteur = norm(e.auteur)
            index['sig', titre[:60], annee(e), auteur, e.type].append(e.id)
    # Des fiches qui portent le même PDF sont souvent des doublons, ou l'une a reçu le PDF de l'autre (D125).
    from zot_clean.pieces import groupes_identiques
    pieces = {pj.cle: pj.parent for pj in b.pieces.values()}
    fiches = {e.id for e in b.fiches}
    for copies in groupes_identiques(b):
        index['pdf', copies[0]] = list(dict.fromkeys(pieces[k] for k in copies if pieces.get(k) in fiches))
    for ids in index.values():
        for x in ids[1:]:
            parent[racine(x)] = racine(ids[0])
    groupes = defaultdict(list)
    for e in b.fiches:
        groupes[racine(e.id)].append(e)
    return sorted((g for g in groupes.values() if len(g) > 1), key=lambda g: norm(g[0].titre))


def classer(g: list[Element]) -> str:
    """Sûr, un groupe de même type qui partage le DOI et des titres concordants, ou le titre, les créateurs et
    l'année (D49). Un chapitre importé avec le DOI de l'ouvrage, ou un erratum saisi avec celui de l'article,
    partage le DOI sans être un doublon : sans titres concordants, le groupe est à juger."""
    if len({e.type for e in g}) > 1:
        return A_JUGER
    dois = {_doi(e.champs.get('DOI', '')) for e in g}
    if (len(dois) == 1 and '' not in dois and g[0].type != 'bookSection'
            and all(titres_concordants(g[0].titre, e.titre, SEUIL_TITRES) for e in g[1:])):
        return SUR
    signatures = {(norm(e.titre), tuple(norm(n) for n, _ in e.createurs), annee(e)) for e in g}
    return SUR if len(signatures) == 1 and next(iter(signatures))[0] else A_JUGER


@dataclass
class Entree:
    cles: list[str]
    classe: str
    decision: str = ''
    conserver: str = ''
    raison: str = ''
    forcer: dict = field(default_factory=dict)


def charger_suivi(cfg: Config) -> list[Entree]:
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return []
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    entrees = []
    for g in brut.get('groupe', []):
        e = Entree(list(g['cles']), g.get('classe', A_JUGER), g.get('decision', ''), g.get('conserver', ''),
                   g.get('raison', ''), dict(g.get('forcer', {})))
        if e.decision not in ('', FUSIONNER, DISTINCT):
            raise SystemExit(f'{chemin} : décision inconnue « {e.decision} » pour {", ".join(e.cles)}.')
        entrees.append(e)
    return entrees


def distincts(entrees: list[Entree]) -> list[set[str]]:
    return [set(e.cles) for e in entrees if e.decision == DISTINCT]


def deja_juge(cles: set[str], distincts_: list[set[str]]) -> bool:
    return any(cles <= d for d in distincts_)


def _toml(v) -> str:
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return '[' + ', '.join(_toml(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{ ' + ', '.join(f'{json.dumps(k, ensure_ascii=False)} = {_toml(x)}' for k, x in v.items()) + ' }'
    return json.dumps(v)


def ecrire_suivi(cfg: Config, entrees: list[Entree], b: Bibliotheque) -> None:
    par_cle = b.par_cle()
    masquees = filtre.cles_masquees(b, cfg)
    nb_pj = defaultdict(int)
    for p in b.pieces.values():
        nb_pj[p.parent] += 1
    lignes = [EN_TETE]
    for e in entrees:
        lignes += ['[[groupe]]']
        # Les fiches d'un groupe se ressemblent : une seule fiche confidentielle masque tout le groupe (D126).
        cache = set(e.cles) if masquees & set(e.cles) else set()
        for cle in e.cles:
            f = par_cle.get(cle)
            lignes.append(f'# {ligne(f, cache)} ({nom_type(f.type)}, {nb_pj[f.id]} pièce(s) jointe(s))' if f
                          else f'# {cle} (absente de la bibliothèque)')
        lignes += [f'cles = {_toml(e.cles)}', f'classe = {_toml(e.classe)}', f'decision = {_toml(e.decision)}',
                   f'conserver = {_toml(e.conserver)}', f'raison = {_toml(e.raison)}', f'forcer = {_toml(e.forcer)}',
                   '']
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    ecrire_toml(cfg.suivi / FICHIER, lignes)


def decider(entrees: list[Entree], surs: bool = False, fusionner=(), distinct=(), conserver=(), sauf=(),
            raison: str = '') -> tuple[int, int]:
    """Décisions prises par commande (D177, sur le modèle de D172), au lieu d'écrire le fichier à la main. Chaque
    groupe se désigne par la clé de l'une de ses fiches. `fusionner` et `conserver` (la fiche à garder) donnent les
    groupes à fusionner, `distinct` ceux qui n'en sont pas, avec `raison`. `surs` fusionne tous les groupes sûrs
    encore à juger, sauf ceux qui contiennent une fiche de `sauf`. Seuls les groupes encore à juger changent.
    Renvoie le nombre de groupes à fusionner et distincts."""
    a_juger: dict[str, list[Entree]] = defaultdict(list)
    for e in entrees:
        if not e.decision:
            for k in e.cles:
                a_juger[k].append(e)
    connues = {k for e in entrees for k in e.cles}
    demandes = [*fusionner, *conserver, *distinct]
    inconnues = [k for k in demandes if k not in a_juger]
    if inconnues:
        absentes = [k for k in inconnues if k not in connues]
        decidees = [k for k in inconnues if k in connues]
        morceaux = []
        if absentes:
            morceaux.append(f'Aucun groupe de {FICHIER} ne contient {", ".join(absentes)}. Vérifier la clé, ou '
                            'relancer `zc doublons chercher`. Deux fiches que zc n\'a pas réunies s\'ajoutent à la '
                            'main en fin de fichier, comme le montre son en-tête.')
        if decidees:
            morceaux.append(f'Le groupe de {", ".join(decidees)} est déjà décidé. Une décision prise se change à la '
                            'main dans le fichier.')
        raise SystemExit(' '.join(morceaux))
    if (ambigues := [k for k in demandes if len(a_juger[k]) > 1]):
        raise SystemExit(f'{", ".join(ambigues)} figure dans plusieurs groupes à juger. Les départager à la main '
                         f'dans {FICHIER}.')
    if (hors := [k for k in sauf if k not in connues]):
        raise SystemExit(f'Aucun groupe de {FICHIER} ne contient {", ".join(hors)}.')
    gardees = [a_juger[k][0] for k in conserver]
    if len({id(e) for e in gardees}) < len(gardees):
        raise SystemExit('Une seule fiche conservée par groupe.')
    fusion = {id(a_juger[k][0]): a_juger[k][0] for k in [*fusionner, *conserver]}
    distincts_ = {id(a_juger[k][0]): a_juger[k][0] for k in distinct}
    if fusion.keys() & distincts_.keys():
        raise SystemExit('Un même groupe ne peut pas être à la fois fusionné et distinct.')
    for k in conserver:
        a_juger[k][0].conserver = k
    for e in fusion.values():
        e.decision = FUSIONNER
    for e in distincts_.values():
        e.decision, e.raison = DISTINCT, raison or e.raison
    n = len(fusion)
    if surs:
        ecartees = set(sauf)
        for e in entrees:
            if e.classe == SUR and not e.decision and not ecartees & set(e.cles):
                e.decision = FUSIONNER
                n += 1
    return n, len(distincts_)


def chercher(b: Bibliotheque, cfg: Config) -> list[Entree]:
    anciennes = charger_suivi(cfg)
    par_cles = {frozenset(e.cles): e for e in anciennes}
    dist = distincts(anciennes)
    actuelles, vues = [], set()
    for g in candidats(b):
        cles = frozenset(e.cle for e in g)
        if deja_juge(set(cles), dist):
            continue
        e = par_cles.get(cles) or Entree(sorted(cles), '')
        e.classe = classer(g)
        actuelles.append(e)
        vues.add(cles)
    # Les groupes jugés distincts restent en mémoire, même quand ils ne sont plus repérés. Un groupe à fusionner
    # que zc ne repère pas (ajouté à la main, DOI retiré entre-temps) reste tant que ses fiches existent.
    presentes = {e.cle for e in b.fiches}
    gardees = [e for e in anciennes if frozenset(e.cles) not in vues and
               (e.decision == DISTINCT or e.decision == FUSIONNER and len(e.cles) > 1 and set(e.cles) <= presentes)]
    actuelles.sort(key=lambda e: (e.decision != '', e.classe != SUR))
    entrees = actuelles + gardees
    ecrire_suivi(cfg, entrees, b)
    return entrees


# --- Plan de fusion -------------------------------------------------------------

class _Fichiers:
    """Empreintes et attaches des pièces jointes, d'après la base locale."""

    def __init__(self, b: Bibliotheque):
        self.b = b
        self.par_cle = b.par_cle()
        self.parents_de_notes = {p for p in b.notes.values() if p}

    def empreinte(self, cle: str) -> str:
        e = self.par_cle.get(cle)
        p = self.b.pieces.get(e.id) if e else None
        return md5(p.fichier) if p and p.fichier and p.fichier.is_file() else ''

    def annotee(self, cle: str) -> bool:
        e = self.par_cle.get(cle)
        return bool(e and (self.b.annotations.get(e.id) or e.id in self.parents_de_notes
                           or (e.id in self.b.pieces and self.b.pieces[e.id].note)))  # note propre (D206)


def _nb_pj(enfants: list[dict]) -> int:
    return sum(1 for k in enfants if k['itemType'] == 'attachment')


def _choisir(items: list[dict], enfants: dict[str, list[dict]], conserver: str) -> dict:
    if conserver:
        return next(d for d in items if d['key'] == conserver)
    return sorted(items, key=lambda d: (-_nb_pj(enfants[d['key']]), d.get('dateAdded', '')))[0]


def _liste(v) -> list[str]:
    return [v] if isinstance(v, str) else list(v or [])


def _relations(d: dict) -> dict[str, list[str]]:
    """Relations d'un élément, une liste d'adresses par prédicat (l'API donne une chaîne pour une seule)."""
    return {p: _liste(v) for p, v in (d.get('relations') or {}).items() if _liste(v)}


def _ajouter(relations: dict, p: str, o: str) -> None:
    if o not in relations.setdefault(p, []):
        relations[p].append(o)


class _Liens:
    """Relations prévues par les groupes déjà planifiés, pour que chaque groupe parte de l'état laissé par les
    précédents, comme des fusions successives dans Zotero, et que `avant` corresponde à ce que le socle relira."""

    def __init__(self, client: Client, masquees: set[str]):
        self.client, self.masquees = client, masquees
        self.prevues: dict[str, dict] = {}
        self.absorbees: set[str] = set()
        self.lues: dict[str, dict | None] = {}
        self.prefixe = client.uri('')  # adresse des fiches de cette bibliothèque, à la clé près

    def de(self, d: dict) -> dict[str, list[str]]:
        return json.loads(json.dumps(self.prevues.get(d['key'], _relations(d))))

    def gardee(self, m: dict, autres: list[dict]) -> dict:
        """Relations de la fiche conservée. Celles des absorbées y passent, sauf un lien vers une fiche du groupe
        (Zotero écarte le lien vers la fiche conservée, zc aussi vers une autre absorbée, elle aussi à la
        corbeille), puis un `dc:replaces` vers chaque absorbée. Les liens qu'elle avait déjà restent."""
        relations, groupe = self.de(m), {self.client.uri(d['key']) for d in [m, *autres]}
        for d in autres:
            for p, objets in self.de(d).items():
                for o in objets:
                    if o not in groupe:
                        _ajouter(relations, p, o)
            _ajouter(relations, REMPLACE, self.client.uri(d['key']))
        return relations

    def liees(self, m: dict, autres: list[dict]) -> list[Operation]:
        """Fiches hors du groupe qui pointent vers une absorbée : leur lien passe à la fiche conservée (rang 1).
        Elles se trouvent par les liens de l'absorbée, que Zotero pose des deux côtés (« Connexe »), et parmi les
        relations déjà prévues par le plan. Une fiche absorbée par un groupe précédent n'est pas touchée."""
        cles_groupe = {d['key'] for d in [m, *autres]}
        uris = {self.client.uri(d['key']): d['key'] for d in autres}
        candidates = {o[len(self.prefixe):] for d in autres for p, objets in self.de(d).items() if p != REMPLACE
                      for o in objets if o.startswith(self.prefixe)}
        candidates |= {k for k, r in self.prevues.items()
                       if any(o in uris for p, objets in r.items() if p != REMPLACE for o in objets)}
        candidates -= cles_groupe | self.absorbees
        if (a_lire := sorted(k for k in candidates if k not in self.lues)):
            lues = self.client.fiches(a_lire)
            self.lues.update({k: lues.get(k) for k in a_lire})
        ops, vers = [], self.client.uri(m['key'])
        for k in sorted(candidates):
            if self.lues.get(k) is None:  # supprimée pour de bon, ou adresse d'une autre bibliothèque
                continue
            avant = self.de(self.lues[k])
            apres, sources = json.loads(json.dumps(avant)), []
            for p, objets in apres.items():
                if p == REMPLACE:
                    continue
                for o in [o for o in objets if o in uris]:
                    objets.remove(o)
                    if vers not in objets:
                        objets.append(vers)
                    sources.append(uris[o])
            if not sources:
                continue
            self.prevues[k] = apres
            masque = f' {filtre.MASQUE}' if k in self.masquees else ''
            ops.append(Operation(k, {'relations': avant}, {'relations': apres}, 1,
                                 f"fiche liée {k}{masque} : son lien vers {', '.join(dict.fromkeys(sources))} "
                                 f"passe à {m['key']}"))
        return ops

    def corbeille(self, d: dict) -> tuple[dict, dict]:
        """Avant et après de la mise à la corbeille d'une absorbée, qui perd ses `dc:replaces`, passés sur la fiche
        conservée, pour qu'un élément remplacé n'ait pas deux remplaçants (Zotero)."""
        self.absorbees.add(d['key'])
        relations = self.de(d)
        if REMPLACE not in relations:
            return {'deleted': False}, {'deleted': True}
        sans = {p: o for p, o in relations.items() if p != REMPLACE}
        self.prevues[d['key']] = sans
        return {'deleted': False, 'relations': relations}, {'deleted': True, 'relations': sans}


def _fusion(m: dict, autres: list[dict], enfants: dict[str, list[dict]], forcer: dict, liens: _Liens,
            fichiers: _Fichiers, cache: bool = False):
    """Opérations de la fusion et valeurs différentes. Avec `cache`, les natures ne citent aucun titre (D126)."""
    valides = set(m) - NE_PAS_COPIER
    maj = {}
    for d in autres:
        for f in sorted(valides):
            if not m.get(f) and d.get(f) and f not in maj:
                maj[f] = d[f]
    if not m.get('creators'):
        maj['creators'] = next((d['creators'] for d in autres if d.get('creators')), [])
        if not maj['creators']:
            del maj['creators']
    differences = [(f, m[f], d[f]) for d in autres for f in sorted(valides)
                   if m.get(f) and d.get(f) and d[f] != m[f] and f not in forcer]
    # La fiche conservée porte la clé suffixée par Better BibTeX (« ozgen2002a ») et une absorbée la clé de base
    # (« ozgen2002 »), la plus ancienne et la plus citée : la fiche conservée prend celle-ci (répétition du pilote).
    garde = str(m.get('citationKey') or '').strip()
    base = next((k for d in autres if (k := str(d.get('citationKey') or '').strip())
                 and k != garde and base_de(garde).lower() == k.lower()), None)
    if garde and base and 'citationKey' not in forcer:
        maj['citationKey'] = base
    maj.update(forcer)

    collections = list(dict.fromkeys(m.get('collections', []) + [c for d in autres for c in d.get('collections', [])]))
    if collections != m.get('collections', []):
        maj['collections'] = collections
    tags, vus = list(m.get('tags', [])), {(t['tag'], t.get('type', 0)) for t in m.get('tags', [])}
    for d in autres:
        for t in d.get('tags', []):
            if (t['tag'], t.get('type', 0)) not in vus:
                vus.add((t['tag'], t.get('type', 0)))
                tags.append(t)
    if len(tags) != len(m.get('tags', [])):
        maj['tags'] = tags
    maj['relations'] = liens.gardee(m, autres)

    ops = []
    empreintes = {fichiers.empreinte(k['key']) for k in enfants[m['key']] if k['itemType'] == 'attachment'} - {''}
    for d in autres:
        for k in enfants[d['key']]:
            h = fichiers.empreinte(k['key']) if k['itemType'] == 'attachment' else ''
            annotee = fichiers.annotee(k['key'])
            # Note de la pièce jointe elle-même (champ `note` de l'élément), que Zotero reporte en fusionnant.
            notee = k['itemType'] == 'attachment' and note_non_vide(k.get('note'))  # vide, Zotero l'enveloppe
            if h and h in empreintes and not k.get('tags') and not annotee and not notee:
                ops.append(Operation(k['key'], {'deleted': False}, {'deleted': True}, 0,
                                     'pièce jointe identique à la corbeille'
                                     + ('' if cache else f" : {k.get('title', '')}"), enfants=[]))
            else:
                # Une copie identique mais annotée, notée ou taguée n'est jamais mise à la corbeille (D51, D125).
                garde = ('sa note de pièce jointe' if notee else 'ses annotations ou notes' if annotee
                         else 'ses tags')
                pourquoi = (f' (identique à une copie déjà présente, gardée pour {garde})'
                            if h and h in empreintes else '')

                # Le texte d'une note ne sort jamais du journal (D191).
                ops.append(Operation(k['key'], {'parentItem': d['key']}, {'parentItem': m['key']}, 0,
                                     f"rattacher {ENFANTS.get(k['itemType'], k['itemType'])}"
                                     + ('' if cache or not k.get('title') else f" : {k['title']}") + pourquoi))
                if h:
                    empreintes.add(h)
    avant = {f: plans.brute(m, f) for f in maj} | {'relations': liens.de(m)}
    ops.append(Operation(m['key'], avant, maj, 1, COMPLETER))
    liens.prevues[m['key']] = maj['relations']
    ops += liens.liees(m, autres)
    for d in autres:
        avant, apres = liens.corbeille(d)
        ops.append(Operation(d['key'], avant, apres, 2, 'fiche absorbée à la corbeille',
                             enfants=[k['key'] for k in enfants[d['key']]]))
    return ops, differences


def _court(v) -> str:
    return repr(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))[:70]


def planifier(cfg: Config, client: Client, b: Bibliotheque) -> tuple[Plan, str]:
    """Plan de fusion des seuls groupes décidés « fusionner ». Un groupe sûr sans décision n'y entre pas, il s'accepte
    d'abord par `zc doublons accepter --surs` (D49)."""
    entrees = charger_suivi(cfg)
    choisies = [e for e in entrees if e.decision == FUSIONNER]
    donnees = client.fiches([k for e in choisies for k in e.cles])
    fichiers = _Fichiers(b)
    masquees = filtre.cles_masquees(b, cfg)
    liens = _Liens(client, masquees)
    groupes, refus, details = [], [], []
    for e in choisies:
        items = [donnees.get(k) for k in e.cles]
        manquantes = [k for k, d in zip(e.cles, items) if d is None]
        if manquantes:
            refus.append((e, f"introuvable(s) : {', '.join(manquantes)}"))
            continue
        if any(d.get('deleted') for d in items):
            refus.append((e, 'une fiche est déjà à la corbeille'))
            continue
        types = sorted({d['itemType'] for d in items})
        if len(types) > 1:
            refus.append((e, f"types différents ({', '.join(nom_type(t) for t in types)}), changer d'abord le type "
                             "(étape 3)"))
            continue
        if e.conserver and e.conserver not in e.cles:
            refus.append((e, f'conserver = « {e.conserver} » ne fait pas partie du groupe'))
            continue
        enfants = {d['key']: [k for k in client.enfants(d['key']) if not k.get('deleted')] for d in items}
        m = _choisir(items, enfants, e.conserver)
        autres = [d for d in items if d['key'] != m['key']]
        cache = any(k in masquees for k in e.cles)
        ops, differences = _fusion(m, autres, enfants, e.forcer, liens, fichiers, cache)
        gid = str(len(groupes) + 1)
        groupes.append(Groupe(gid, filtre.MASQUE if cache else m.get('title', '')[:80], ops))
        details.append(_detail(gid, m, autres, enfants, ops, differences, cache))
    plan = Plan('doublons', client.utilisateur, groupes,
                description=f'Fusion de {len(groupes)} groupe(s) de doublons.')
    a_juger = sum(1 for e in entrees if not e.decision)
    return plan, _rapport(plan, refus, details, a_juger, avertissement(b, cfg, plan))


def avertissement(b: Bibliotheque, cfg: Config, plan: Plan) -> str:
    """PDF des fiches du plan absents du disque (D168). Sans le fichier, zc ne peut pas reconnaître une copie
    identique, qui est alors rattachée à la fiche conservée au lieu d'aller à la corbeille."""
    from zot_clean import bbt
    from zot_clean.audit import rappel_absents
    fiches = {op.cle for g in plan.groupes for op in g.operations if op.rang == 2 or op.nature == COMPLETER}
    suite = ('. Une copie identique est alors rattachée à la fiche conservée au lieu d\'aller à la corbeille, '
             'et la fiche garde deux fois le même fichier')
    return rappel_absents(b, bbt.stockage_fichiers(cfg.dossier_zotero), suite, fiches) if fiches else ''


def _detail(gid, m, autres, enfants, ops, differences, cache: bool = False) -> list[str]:
    """Détail d'un groupe. Avec `cache`, ni titre ni valeur, seulement les clés et les noms des champs (D126)."""
    r = [f"### Groupe {gid}. {filtre.MASQUE if cache else m.get('title', '')[:90]}", '',
         f"- conserver {m['key']} ({nom_type(m['itemType'])}, {m.get('date', '') or 's. d.'}, "
         f"{_nb_pj(enfants[m['key']])} pièce(s) jointe(s), ajoutée le {m.get('dateAdded', '')[:10]})"]
    r += [f"- absorber {d['key']} ({nom_type(d['itemType'])}, {d.get('date', '') or 's. d.'}, "
          f"{_nb_pj(enfants[d['key']])} pièce(s) jointe(s), ajoutée le {d.get('dateAdded', '')[:10]})" for d in autres]
    op_m = next(op for op in ops if op.cle == m['key'])
    maj = op_m.apres
    champs = {k: v for k, v in maj.items() if k not in ('relations', 'collections', 'tags')}
    if champs:
        r.append('- champs complétés : ' + ', '.join(k if cache else f'{k} = {_court(v)}' for k, v in champs.items()))
    if 'collections' in maj:
        r.append(f"- collections : {len(m.get('collections', []))} → {len(maj['collections'])}")
    if 'tags' in maj:
        r.append(f"- tags : {len(m.get('tags', []))} → {len(maj['tags'])}")
    repris = sum(len(set(o) - set(op_m.avant['relations'].get(p, []))) for p, o in maj['relations'].items()
                 if p != REMPLACE)
    if repris:
        r.append(f'- liens « Connexe » ou autres relations repris des fiches absorbées : {repris}')
    r += [f'- {op.nature}' for op in ops if op.rang == 0 or op.rang == 1 and op.cle != m['key']]
    # Clé de citation d'une fiche absorbée qui disparaît avec elle (D146), signalée à part des autres différences.
    gardee = str(maj.get('citationKey') or m.get('citationKey') or '').strip()
    if (ancienne := str(m.get('citationKey') or '').strip()) and ancienne != gardee:
        r.append(f"- clé de citation de {m['key']} remplacée par celle, sans suffixe, d'une fiche absorbée" if cache
                 else f"- clé de citation « {ancienne} » de {m['key']} remplacée par « {gardee} », sans suffixe, "
                      "d'une fiche absorbée. Un texte qui cite l'ancienne est à mettre à jour")
    for d in autres:
        if (cle := str(d.get('citationKey') or '').strip()) and cle != gardee:
            r.append(f"- clé de citation de {d['key']} qui disparaît, la fiche conservée gardant la sienne"
                     if cache else f"- clé de citation « {cle} » de {d['key']} qui disparaît, la fiche conservée "
                                   f"gardant « {gardee} ». Un texte qui la cite est à mettre à jour")
    differences = [x for x in differences if x[0] != 'citationKey']
    if differences:
        r.append('- valeurs différentes, celle de la fiche conservée est gardée (imposer une valeur avec `forcer`) :')
        r += [f'  - {f}' if cache else f'  - {f} : {_court(a)} gardé, {_court(b)} écarté' for f, a, b in differences]
    return r + ['']


def _rapport(plan: Plan, refus: list, details: list[list[str]], a_juger: int, avert: str = '') -> str:
    r = ['# Fusion de doublons', '', *([f'**Attention.** {avert}', ''] if avert else []),
         f"{len(plan.groupes)} groupe(s) à fusionner, {plan.nb_operations} opération(s). Comme dans Zotero, les "
         "notes et pièces jointes passent sur la fiche conservée, les champs vides sont complétés, collections et "
         "tags réunis, les liens « Connexe » des fiches absorbées passent à la fiche conservée, de leur côté comme "
         "de celui des fiches liées, et les fiches absorbées vont à la corbeille avec un lien vers la fiche conservée.", '',
         "Zotero vide la corbeille automatiquement (après 30 jours par défaut). Passé ce délai, une fusion n'est "
         "plus annulable par `zc annuler`.", '']
    if a_juger:
        r += [f'{a_juger} groupe(s) restent à juger dans suivi/doublons.toml.', '']
    if refus:
        r += ['## Groupes écartés', '']
        r += [f"- {', '.join(e.cles)} : {raison}" for e, raison in refus] + ['']
    r += ['## Détail', '']
    for d in details:
        r += d
    return '\n'.join(r)
