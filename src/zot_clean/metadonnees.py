"""Métadonnées, étape 3 du nettoyage (D58 à D73). Identifiants et compléments.

`identifiants` corrige la forme des DOI, vérifie qu'ils existent et désignent
bien la fiche, et cherche le DOI manquant des articles, communications,
chapitres et prépublications. `completer` remplit les champs vides depuis le DOI
confirmé. Les cas sûrs vont directement au plan. Les autres sont écrits dans
`suivi/metadonnees.toml`, et y reviennent une fois jugés (`accepter` entre
dans le plan suivant de la même sous-étape, `refuser` n'est plus reproposé).

La détection se fait sur la copie de la base, les valeurs d'avant des plans
viennent de l'API, relue juste avant d'écrire le plan.
"""

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field

from zot_clean import filtre, plans
from zot_clean.audit import annee as annee_fiche, ecrire_toml, ligne, nom_type
from zot_clean.config import Config
from zot_clean.doublons import _toml
from zot_clean.ecriture import Client
from zot_clean.lecture import Bibliotheque, Element, Types
from zot_clean.plans import Groupe, Operation, Plan
from zot_clean.sources import Oeuvre, Services, isbns, norm, similarite, titres_concordants

FICHIER = 'metadonnees.toml'
IDENTIFIANTS, TYPES, COMPLETER = 'identifiants', 'types', 'completer'
ACCEPTER, REFUSER = 'accepter', 'refuser'
TYPES_CHERCHES = {'journalArticle', 'conferencePaper', 'bookSection', 'preprint'}
DOI_VALIDE = re.compile(r'^10\.\d{4,9}/\S+$')
CONTENEUR = {'journalArticle': 'publicationTitle', 'bookSection': 'bookTitle', 'conferencePaper': 'proceedingsTitle'}
AVEC_EDITEURS = {'book', 'bookSection'}
# Titres jamais rattachés avec certitude (D75).
GENERIQUES = {'introduction', 'conclusion', 'conclusions', 'preface', 'avant propos', 'foreword', 'afterword',
              'postface', 'editorial', 'compte rendu', 'review', 'book review', 'prologue', 'epilogue', 'index',
              'bibliography', 'bibliographie', 'introduction generale', 'general introduction'}
VIDES = {'the', 'a', 'an', 'of', 'and', 'in', 'on', 'to', 'for', 'le', 'la', 'les', 'l', 'de', 'des', 'du', 'd',
         'et', 'en', 'un', 'une', 'au', 'aux'}
MOTS_LANGUE = {
    'en': {'the', 'of', 'and', 'in', 'a', 'to', 'for', 'on', 'with', 'from', 'an', 'is', 'as', 'by', 'at', 'its',
           'their', 'how', 'what', 'why', 'between', 'toward', 'towards', 'into', 'new'},
    'fr': {'le', 'la', 'les', 'de', 'des', 'du', 'et', 'un', 'une', 'pour', 'sur', 'dans', 'au', 'aux', 'par', 'est',
           'que', 'qui', 'l', 'd', 'entre', 'vers', 'ou', 'son', 'sa', 'ses', 'leur', 'leurs', 'nouvelle'},
}


def titre_generique(titre: str) -> bool:
    n = norm(titre)
    return n in GENERIQUES or len([m for m in n.split() if m not in VIDES]) < 4


def langue_du_titre(titre: str) -> str:
    """« en » ou « fr » d'après les mots courants, vide si le titre ne tranche pas (D77)."""
    mots = norm(titre).split()
    scores = {code: sum(m in liste for m in mots) for code, liste in MOTS_LANGUE.items()}
    (premiere, a), (_, b) = sorted(scores.items(), key=lambda x: -x[1])
    return premiere if a >= 1 and a > b else ''

EN_TETE = """\
# Cas de métadonnées à juger, écrits par `zc metadonnees identifiants` et `zc metadonnees completer`.
# Ce fichier se relit et se modifie à la main ou avec l'agent. Les commandes le mettent à jour sans perdre
# les décisions, et le plan suivant de la même sous-étape reprend les cas acceptés. Les décisions s'écrivent
# aussi par `zc metadonnees accepter` (tous les évidents avec --evidents, ou des clés) et `zc metadonnees refuser`.
#
# decision : "accepter" (la proposition numéro `choix`, 1 pour la première), "refuser" (à ne plus proposer)
#            ou "" (à juger).
# forcer   : valeurs imposées à la fiche en plus de la proposition, par exemple { "date" = "1998" }.
# classe   : tri fait par zc. « évident » quand une seule proposition concorde en tout avec la fiche, son
#            numéro étant alors dans `choix`, ou quand un DOI introuvable n'a pas d'autre piste que son
#            retrait ; « douteux » sinon. L'avis de chaque proposition dit ce qui concorde ou diffère
#            (titre, auteur, année, type, revue ou ouvrage, éditeur…).
#
# Pour imposer une valeur hors de tout cas (revue fausse, ISBN d'un autre livre…), ajouter à la fin du
# fichier un cas complet comme celui-ci, avec la clé de la fiche, puis relancer `zc metadonnees completer`.
# Une valeur vide vide le champ, par exemple forcer = { "ISBN" = "" } pour un livre.
#
#   [[cas]]
#   cle = "ABCD1234"
#   sous_etape = "completer"
#   probleme = "forcer"
#   decision = "accepter"
#   forcer = { "publicationTitle" = "Journal of Experimental Psychology: General" }
"""


def normaliser_doi(v: str) -> str:
    # Adresse de résolution, y compris derrière le proxy d'une bibliothèque (dx.doi.org.ezproxy.exemple.org/10.…).
    v = re.sub(r'^\s*(https?://)?[^/\s]*doi\.org[^/\s]*/(?=10\.)', '', v.strip(), flags=re.I)
    v = re.sub(r'^doi:\s*', '', v, flags=re.I)
    return v.strip().rstrip('.,;')


@dataclass
class Proposition:
    champs: dict
    source: str = ''
    note: str = ''
    avis: str = ''  # « concorde » ou ce qui diffère de la fiche (D134), vide sans œuvre à comparer


@dataclass
class Cas:
    cle: str
    sous_etape: str
    probleme: str
    propositions: list[Proposition] = field(default_factory=list)
    decision: str = ''
    choix: int = 1
    forcer: dict = field(default_factory=dict)
    classe: str = ''  # « évident » ou « douteux » (D134), vide hors des identifiants

    @property
    def id(self) -> tuple[str, str, str]:
        return self.cle, self.sous_etape, self.probleme

    def retenus(self) -> dict:
        """Champs à écrire pour un cas accepté."""
        champs = dict(self.propositions[self.choix - 1].champs) if self.propositions else {}
        return champs | self.forcer


# --- Fichier de suivi -------------------------------------------------------------

def charger_suivi(cfg: Config) -> list[Cas]:
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return []
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    cas = []
    for c in brut.get('cas', []):
        x = Cas(c['cle'], c['sous_etape'], c['probleme'],
                [Proposition(dict(p.get('champs', {})), p.get('source', ''), p.get('note', ''), p.get('avis', ''))
                 for p in c.get('propositions', [])],
                c.get('decision', ''), int(c.get('choix', 1)), dict(c.get('forcer', {})), c.get('classe', ''))
        if x.decision not in ('', ACCEPTER, REFUSER):
            raise SystemExit(f'{chemin} : décision inconnue « {x.decision} » pour {x.cle}.')
        if x.decision == ACCEPTER and x.propositions and not 1 <= x.choix <= len(x.propositions):
            raise SystemExit(f'{chemin} : choix {x.choix} hors des propositions pour {x.cle}.')
        cas.append(x)
    return cas


def ecrire_suivi(cfg: Config, cas: list[Cas], b: Bibliotheque) -> None:
    par_cle = b.par_cle()
    masquees = filtre.cles_masquees(b, cfg)
    lignes = [EN_TETE]
    for c in cas:
        f = par_cle.get(c.cle)
        cache = c.cle in masquees
        conteneur = next((f.champs[k] for k in ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                          if f and f.champs.get(k) and not cache), '')
        doi = f.champs.get('DOI', '') if f and not cache else ''
        description = (f'# {ligne(f, masquees)} ({nom_type(f.type)}' + (f', dans « {conteneur[:70]} »' if conteneur else '')
                       + (f', DOI {doi}' if doi else '') + ')') if f else f'# {c.cle}'
        lignes += ['[[cas]]', description,
                   f'cle = {_toml(c.cle)}', f'sous_etape = {_toml(c.sous_etape)}', f'probleme = {_toml(c.probleme)}',
                   f'decision = {_toml(c.decision)}', f'choix = {c.choix}', f'forcer = {_toml(c.forcer)}']
        if c.classe:
            lignes.append(f'classe = {_toml(c.classe)}')
        for i, p in enumerate(c.propositions, 1):
            # La note d'une source décrit l'œuvre trouvée, donc la fiche elle-même (D126).
            note = filtre.MASQUE if cache and p.source else p.note
            lignes += [f'[[cas.propositions]]  # {i}', f'champs = {_toml(p.champs)}', f'source = {_toml(p.source)}',
                       f'note = {_toml(note)}'] + ([f'avis = {_toml(p.avis)}'] if p.avis else [])
        lignes.append('')
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    ecrire_toml(cfg.suivi / FICHIER, lignes)


def decider(cas: list[Cas], evidents: bool = False, accepter: dict[str, int | None] | None = None,
            refuser: list[str] = (), sauf: set[str] = frozenset()) -> tuple[int, int]:
    """Décisions prises en bloc (D172), au lieu d'écrire le fichier à la main. `evidents` accepte tous les cas
    évidents encore à juger (hors `sauf`), avec le numéro retenu par zc. `accepter` donne, par clé de fiche, le numéro
    de la proposition à retenir (None pour celui qu'a retenu zc), `refuser` les fiches dont les cas sont refusés.
    Une clé suivie du problème (« ABCD1234:isbn_manquant ») vise un seul des cas de la fiche. Seuls les cas encore à
    juger changent. Renvoie le nombre de cas acceptés et refusés."""
    accepter = accepter or {}
    a_juger: dict[str, list[Cas]] = {}
    for c in cas:
        if not c.decision:
            a_juger.setdefault(c.cle, []).append(c)
            a_juger.setdefault(f'{c.cle}:{c.probleme}', []).append(c)
    inconnues = [k for k in [*accepter, *refuser] if k not in a_juger]
    if inconnues:
        raise SystemExit(f'Aucun cas à juger pour {", ".join(inconnues)} dans {FICHIER}. Vérifier la clé, ou relancer '
                         'la sous-étape si la fiche vient d\'être examinée.')
    acceptes = refuses = 0
    for cle, choix in accepter.items():
        if choix is not None and len(a_juger[cle]) > 1:
            problemes = ', '.join(f'{cle}:{c.probleme}' for c in a_juger[cle])
            raise SystemExit(f'{cle} a {len(a_juger[cle])} cas à juger, un numéro de proposition ne vaut que pour '
                             f'un seul. Viser le cas par son problème ({problemes}).')
        for c in a_juger[cle]:
            if choix is not None and not 1 <= choix <= len(c.propositions):
                raise SystemExit(f'{cle} : proposition {choix} inexistante ({len(c.propositions)} proposition(s)).')
            c.decision, c.choix = ACCEPTER, choix or c.choix
            acceptes += 1
    for cle in refuser:
        for c in a_juger[cle]:
            c.decision = REFUSER
            refuses += 1
    if evidents:
        for c in cas:
            if c.classe == 'évident' and not c.decision and c.cle not in sauf:
                c.decision = ACCEPTER
                acceptes += 1
    return acceptes, refuses


def fusionner_suivi(anciens: list[Cas], detectes: list[Cas], sous_etape: str,
                    portee: set[str] | None = None) -> list[Cas]:
    """Garde les décisions prises. Un cas refusé reste en mémoire, un cas résolu disparaît. Avec `portee`
    (tri de l'Inbox, D135), seules ces fiches ont été examinées, et les cas des autres restent tels quels.

    Un cas de DOI accepté puis résolu laisse les DOI qu'il a écartés en mémoire, sous la forme d'un cas
    `doi_manquant` refusé, pour qu'une fiche dont on a retiré un faux DOI ne se voie pas reproposer le candidat
    écarté (répétition du pilote)."""
    detectes_ids = {c.id for c in detectes}
    for c in anciens:
        ecartes = [p for i, p in enumerate(c.propositions, 1) if i != c.choix and p.champs.get('DOI')]
        memoire = Cas(c.cle, IDENTIFIANTS, 'doi_manquant', ecartes, REFUSER)
        if (c.decision == ACCEPTER and c.sous_etape == sous_etape == IDENTIFIANTS and c.probleme.startswith('doi_')
                and c.id not in detectes_ids and ecartes and (portee is None or c.cle in portee)
                and memoire.id not in {a.id for a in anciens}):
            dois = {p.champs['DOI'].lower() for p in ecartes}
            nouveau = next((d for d in detectes if d.id == memoire.id), None)
            if nouveau:
                nouveau.propositions = [p for p in nouveau.propositions if p.champs.get('DOI', '').lower() not in dois]
                if nouveau.propositions:
                    classer(nouveau)
                    continue
                detectes = [d for d in detectes if d is not nouveau]
            anciens = [*anciens, memoire]
    par_id = {c.id: c for c in anciens}
    vus, res = set(), []
    for c in detectes:
        ancien = par_id.get(c.id)
        if ancien and ancien.decision:
            res.append(ancien)
        else:
            if ancien:
                c.forcer = ancien.forcer
            res.append(c)
        vus.add(c.id)
    for c in anciens:
        if c.id in vus:
            continue
        if (c.sous_etape != sous_etape or c.decision == REFUSER or c.probleme == 'forcer'
                or (portee is not None and c.cle not in portee)):
            res.append(c)
    res.sort(key=lambda c: (c.sous_etape, c.decision != '', c.cle))
    return res


# --- Identifiants -----------------------------------------------------------------

def _premier_auteur(e: Element) -> str:
    return e.auteur


def _auteur_ok(e: Element, o: Oeuvre) -> bool:
    a, b = norm(_premier_auteur(e)), norm(o.auteurs[0][0] if o.auteurs else '')
    return bool(a and b) and (a == b or a in b.split() or b in a.split())


def _annee_ok(e: Element, o: Oeuvre, ecart: int) -> bool:
    a = annee_fiche(e)
    return bool(a and o.annee) and abs(int(a) - int(o.annee)) <= ecart


def _premiere_page(pages: str) -> str:
    return re.split(r'\s*[-–]\s*', pages.strip(), maxsplit=1)[0] if pages else ''


def meme_publication(e: Element, o: Oeuvre, seuil: float) -> bool:
    """L'œuvre trouvée par l'identifiant de la fiche est-elle bien la fiche ? (D131)

    Titres concordants, ou, quand les titres diffèrent (titre traduit, titre de l'ouvrage saisi pour un
    chapitre), même premier auteur, année à un an près et un indice de plus (revue, volume, première page)."""
    if titres_concordants(e.titre, o.titre, seuil):
        return True
    if not (_auteur_ok(e, o) and _annee_ok(e, o, 1)):
        return False
    conteneur = next((e.champs[k] for k in ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                      if e.champs.get(k)), '')
    page = _premiere_page(e.champs.get('pages', ''))
    return any((bool(o.volume) and e.champs.get('volume', '').strip() == o.volume,
                bool(page) and page == _premiere_page(o.pages),
                bool(conteneur and o.conteneur) and similarite(conteneur, o.conteneur) >= seuil,
                bool(o.conteneur) and similarite(e.titre, o.conteneur) >= seuil))


def _ouvrage_ok(e: Element, o: Oeuvre, seuil: float) -> bool:
    """Pour un chapitre, le titre de l'ouvrage doit correspondre quand les deux sont connus (D75)."""
    ouvrage = e.champs.get('bookTitle', '')
    return e.type != 'bookSection' or not ouvrage or not o.conteneur or similarite(ouvrage, o.conteneur) >= seuil


def _decrire(o: Oeuvre, sim: float) -> str:
    """Tout ce qui aide à juger (D79) : auteur, année, type, revue ou ouvrage, volume, pages, éditeur."""
    auteur = o.auteurs[0][0] if o.auteurs else 's. a.'
    details = [x for x in (f'dans « {o.conteneur[:70]} »' if o.conteneur else '', f'vol. {o.volume}' if o.volume
                           else '', f'p. {o.pages}' if o.pages else '', o.editeur[:40], o.edition[:30],
                           f'coll. {o.collection[:40]}' if o.collection else '',
                           f'{o.nb_editions} éditions chez {o.source}' if o.nb_editions > 1 else '') if x]
    return (f'{o.source} : « {o.titre[:90]} », {auteur}, {o.annee or "s. d."}, {nom_type(o.type) if o.type else "type inconnu"}'
            + (', ' + ', '.join(details) if details else '') + f' (similarité {sim:.2f})')


SEUIL_EVIDENT = 0.9
COMPTES_RENDUS = ('review', 'compte rendu', 'erratum', 'corrigendum', 'reply', 'comment on')


def avis_oeuvre(e: Element, o: Oeuvre, livre: bool = False) -> str:
    """Ce qui distingue l'œuvre proposée de la fiche, ou « concorde » (D134, critères du skill `metadonnees`)."""
    pb = []
    if not titres_concordants(e.titre, o.titre, SEUIL_EVIDENT):
        pb.append(f'titre {similarite(e.titre, o.titre):.2f}')
    if not _auteur_ok(e, o):
        pb.append('auteur')
    if not _annee_ok(e, o, 1):
        pb.append('année')
    if o.type and o.type != e.type:
        pb.append('type')
    if livre:
        if not _editeur_ok(e, o):
            pb.append('éditeur')
        if o.nb_editions > 1:
            pb.append('plusieurs éditions')
    elif not _conteneur_ok(e, o):
        pb.append('revue ou ouvrage')
    if norm(e.titre) in GENERIQUES:
        pb.append('titre générique')
    if any(m in norm(o.titre) for m in COMPTES_RENDUS) and not any(m in norm(e.titre) for m in COMPTES_RENDUS):
        pb.append('compte rendu ?')
    return ', '.join(pb) or 'concorde'


def conteneurs_concordants(a: str, b: str) -> bool:
    """Même revue ou même ouvrage, à un sous-titre, une forme ou une abréviation près (« J. Exp. Psychol. » et
    « Journal of Experimental Psychology »). Deux revues dont un mot diffère ne concordent pas."""
    if titres_concordants(a, b, SEUIL_EVIDENT) or meme_forme('publicationTitle', a, b):
        return True
    x, y = ([m for m in norm(v).split() if m not in VIDES] for v in (a, b))
    return bool(x) and len(x) == len(y) and all(i.startswith(j) or j.startswith(i) for i, j in zip(x, y))


def _conteneur_ok(e: Element, o: Oeuvre) -> bool:
    """Revue, actes ou ouvrage de la fiche et de la source concordants quand les deux sont connus (D82)."""
    conteneur = next((e.champs[k] for k in ('publicationTitle', 'bookTitle', 'proceedingsTitle')
                      if e.champs.get(k)), '')
    return not conteneur or not o.conteneur or conteneurs_concordants(conteneur, o.conteneur)


def classer(c: Cas) -> Cas:
    """Évident quand une seule proposition concorde en tout, retenue d'avance dans `choix` (D134), ou quand un DOI
    introuvable n'a pas d'autre piste que son retrait (D169)."""
    if c.probleme == 'doi_inconnu' and len(c.propositions) == 1:
        c.classe, c.choix = 'évident', 1
        return c
    bonnes = [i for i, p in enumerate(c.propositions, 1) if p.avis == 'concorde']
    c.classe = 'évident' if len(bonnes) == 1 else 'douteux'
    if len(bonnes) == 1:
        c.choix = bonnes[0]
    return c


def chercher_doi(e: Element, services: Services, cfg: Config, exclu: str = '') -> tuple[Proposition | None, list[Proposition]]:
    """Candidat sûr (D62), ou candidats plausibles à juger, pour une fiche sans DOI fiable."""
    m = cfg.metadonnees
    plausibles, vus = [], {exclu.lower()}
    for resultats in services.recherches(e.titre, _premier_auteur(e), annee_fiche(e)):
        for o in resultats:
            # Même type exigé, ce qui écarte le DOI d'un livre pour un chapitre (D70).
            if not o.doi or o.doi.lower() in vus or o.type != e.type:
                continue
            vus.add(o.doi.lower())
            sim = similarite(e.titre, o.titre)
            prop = Proposition({'DOI': o.doi}, o.source, _decrire(o, sim), avis_oeuvre(e, o))
            # Une revue discordante laisse le cas au jugement (D82), même si le reste concorde.
            if (sim >= m.seuil_sur and _auteur_ok(e, o) and _annee_ok(e, o, m.ecart_annees)
                    and not titre_generique(e.titre) and _ouvrage_ok(e, o, m.seuil_discordance)
                    and (e.type == 'bookSection' or _conteneur_ok(e, o))):
                return prop, []
            if sim >= m.seuil_discordance:
                plausibles.append(prop)
    return None, plausibles[:3]


def _editeur_ok(e: Element, o: Oeuvre) -> bool:
    mots = [m for m in norm(e.champs.get('publisher', '')).split() if m not in VIDES | {'editions', 'ed', 'press'}]
    return not mots or mots[0] in norm(o.editeur).split()


def chercher_isbn(e: Element, services: Services, cfg: Config) -> tuple[Proposition | None, list[Proposition]]:
    """Livre sûr (D92, une seule édition qui convient), ou éditions plausibles à juger (cinq au plus)."""
    m = cfg.metadonnees
    annee = annee_fiche(e)
    retenus, plausibles, vus = [], [], set()
    for resultats in services.recherches_livre(e.titre, _premier_auteur(e), annee):
        for o in resultats:
            brut = next((x for x in o.isbn for _, ok in isbns(x)[:1] if ok), '')
            if not brut or isbns(brut)[0][0] in vus:
                continue
            vus.add(isbns(brut)[0][0])
            sim = similarite(e.titre, o.titre)
            prop = Proposition({'ISBN': brut}, o.source, _decrire(o, sim), avis_oeuvre(e, o, livre=True))
            if (sim >= m.seuil_sur and _auteur_ok(e, o) and annee and o.annee == annee and _editeur_ok(e, o)
                    and not titre_generique(e.titre) and o.nb_editions <= 1):
                retenus.append(prop)
            elif sim >= m.seuil_discordance:
                plausibles.append(prop)
    if len(retenus) == 1:
        return retenus[0], []
    return None, (retenus + plausibles)[:5]


def analyser_isbn(e: Element, services: Services, cfg: Config, cherchable: bool):
    """ISBN à somme de contrôle fausse (cas à juger), ou ISBN manquant d'un livre (D94)."""
    valeurs = isbns(e.champs.get('ISBN', ''))
    if any(not ok for _, ok in valeurs):
        valides = [i for i, ok in valeurs if ok]
        garder = Proposition({'ISBN': ' '.join(valides)}, '', 'garder les ISBN valides' if valides
                             else "retirer l'ISBN")
        _, candidats = chercher_isbn(e, services, cfg) if cherchable and e.type == 'book' else (None, [])
        return Cas(e.cle, IDENTIFIANTS, 'isbn_invalide', [garder, *candidats])
    if valeurs and e.type in ('book', 'bookSection'):
        return isbn_discordant(e, valeurs[0][0], services, cfg, cherchable)
    if not valeurs and e.type == 'book' and cherchable and e.titre:
        sur, candidats = chercher_isbn(e, services, cfg)
        if sur:
            return sur
        if candidats:
            return Cas(e.cle, IDENTIFIANTS, 'isbn_manquant', candidats)
    return None


def isbn_discordant(e: Element, isbn: str, services: Services, cfg: Config, cherchable: bool) -> Cas | None:
    """ISBN valide qui désigne un autre livre (D131, comparaison des seuls titres). La notice lue ici est celle
    que `completer` lira ensuite, le cache servant les deux : aucune requête de plus, sauf la recherche par titre
    d'un livre dont l'ISBN est faux."""
    o = services.livre(isbn)
    reference = e.titre if e.type == 'book' else e.champs.get('bookTitle', '')
    if o is None or not reference or titres_concordants(reference, o.titre, cfg.metadonnees.seuil_discordance):
        return None
    retirer = Proposition({'ISBN': ''}, '', "retirer l'ISBN, qui désigne un autre livre")
    garder = Proposition({}, o.source, f"garder l'ISBN, il est juste ({_decrire(o, similarite(reference, o.titre))})",
                         avis_oeuvre(e, o, livre=True) if e.type == 'book' else '')
    sur, candidats = chercher_isbn(e, services, cfg) if cherchable and e.type == 'book' else (None, [])
    candidats = [p for p in ([sur] if sur else []) + candidats if isbns(p.champs['ISBN'])[0][0] != isbn]
    return Cas(e.cle, IDENTIFIANTS, 'isbn_discordant', [retirer, garder, *candidats])


def _isbn_confirme(cle: str, cas: list[Cas]) -> bool:
    """ISBN discordant jugé juste (« garder »). Le retirer ou en choisir un autre le change de toute façon."""
    return any(c.cle == cle and c.probleme == 'isbn_discordant' and c.decision == ACCEPTER
               and 'ISBN' not in c.retenus() for c in cas)


def analyser_identifiants(e: Element, services: Services, cfg: Config, cherchable: bool):
    """Proposition sûre, cas à juger, ou None."""
    brut = e.champs.get('DOI', '')
    retirer = Proposition({'DOI': ''}, '', 'retirer le DOI')
    if brut:
        doi = normaliser_doi(brut)
        forme = Proposition({'DOI': doi}, '', f'forme corrigée ({brut!r})') if doi != brut else None
        if not DOI_VALIDE.match(doi):
            sur, candidats = chercher_doi(e, services, cfg) if cherchable else (None, [])
            if sur:  # D128 : un DOI inutilisable cède la place à un candidat certain
                return Proposition(sur.champs, sur.source, f'DOI mal formé ({brut!r}) remplacé, {sur.note}')
            return Cas(e.cle, IDENTIFIANTS, 'doi_malforme', [retirer, *candidats])
        o = services.oeuvre(doi)
        if o is None:
            if services.existe(doi):
                return forme
            sur, candidats = chercher_doi(e, services, cfg, doi) if cherchable else (None, [])
            if sur:  # D128 : un DOI qui n'existe nulle part (identifiant JSTOR, faute de frappe) cède la place
                return Proposition(sur.champs, sur.source, f'DOI inexistant ({doi}) remplacé, {sur.note}')
            introuvable = Proposition({'DOI': ''}, '', 'retirer le DOI, que ni doi.org ni les sources ne connaissent')
            return Cas(e.cle, IDENTIFIANTS, 'doi_inconnu', [introuvable, *candidats])
        sim = similarite(e.titre, o.titre)
        if not meme_publication(e, o, cfg.metadonnees.seuil_discordance):
            sur, candidats = chercher_doi(e, services, cfg, doi) if cherchable else (None, [])
            garder = Proposition({'DOI': doi} if forme else {}, o.source,
                                 f'garder le DOI, il est juste ({_decrire(o, sim)})', avis_oeuvre(e, o))
            return Cas(e.cle, IDENTIFIANTS, 'doi_discordant', [retirer, garder, *([sur] if sur else []), *candidats])
        return forme
    if e.type in TYPES_CHERCHES and cherchable and e.titre:
        sur, candidats = chercher_doi(e, services, cfg)
        if sur:
            return sur
        if candidats:
            return Cas(e.cle, IDENTIFIANTS, 'doi_manquant', candidats)
    return None


def _progression(i: int, n: int, afficher, quoi: str = 'fiches examinées') -> None:
    if afficher and (i % 200 == 0 or i == n):
        afficher(f'{i}/{n} {quoi}')


def _plan(etape: str, propositions: dict[str, tuple[dict, str]], client: Client, description: str,
          masquees: set[str] = frozenset()):
    """Plan d'un groupe par fiche, avec les valeurs d'avant relues par l'API. Renvoie aussi les écarts."""
    donnees = client.fiches(list(propositions))
    groupes, ecartes = [], []
    for cle, (champs, nature) in propositions.items():
        d = donnees.get(cle)
        if d is None or d.get('deleted'):
            ecartes.append((cle, 'fiche introuvable ou à la corbeille'))
            continue
        invalides = [f for f in champs if f not in d]
        if invalides:
            ecartes.append((cle, f"champ(s) absent(s) de ce type de fiche ({', '.join(invalides)})"))
            champs = {f: v for f, v in champs.items() if f in d}
        # Déjà fait sur le serveur, la copie locale n'étant pas encore synchronisée : rien à écrire.
        champs = {f: v for f, v in champs.items() if d.get(f) != v}
        if not champs:
            continue
        op = Operation(cle, {f: plans.brute(d, f) for f in champs}, champs, 0, nature)
        groupes.append(Groupe(cle, filtre.MASQUE if cle in masquees else d.get('title', '')[:80], [op]))
    return Plan(etape, client.utilisateur, groupes, description=description), ecartes


def _dans(cle: str, cles: set[str] | None) -> bool:
    return cles is None or cle in cles


def identifiants(b: Bibliotheque, cfg: Config, services: Services, client: Client, afficher=None,
                 cles: set[str] | None = None):
    """`cles` limite l'examen à ces fiches (tri de l'Inbox, D135)."""
    anciens = charger_suivi(cfg)
    exclues = filtre.exclues(b, cfg)
    surs, detectes, filtrees = {}, [], 0
    fiches = [e for e in b.fiches if _dans(e.cle, cles)]
    try:
        for i, e in enumerate(fiches, 1):
            _progression(i, len(fiches), afficher)
            cherchable = e.id not in exclues
            filtrees += not cherchable
            for r in (analyser_identifiants(e, services, cfg, cherchable),
                      analyser_isbn(e, services, cfg, cherchable)):
                if isinstance(r, Cas):
                    detectes.append(classer(r))
                elif r:
                    champs, nature = surs.get(e.cle, ({}, ''))
                    note = r.note or f'identifiant trouvé, {r.source}'
                    surs[e.cle] = (champs | r.champs, f'{nature} ; {note}' if nature else note)
    finally:
        services.sauver()
    cas = fusionner_suivi(anciens, detectes, IDENTIFIANTS, cles)
    ecrire_suivi(cfg, cas, b)
    acceptes = {c.cle: (c.retenus(), f'cas jugé ({c.probleme})') for c in cas
                if c.sous_etape == IDENTIFIANTS and c.decision == ACCEPTER and c.retenus() and _dans(c.cle, cles)}
    masquees = filtre.cles_masquees(b, cfg)
    plan, ecartes = _plan(IDENTIFIANTS, surs | acceptes, client, 'Identifiants (DOI, ISBN) corrigés ou ajoutés.',
                          masquees)
    a_juger = [c for c in cas if c.sous_etape == IDENTIFIANTS and not c.decision and _dans(c.cle, cles)]
    return plan, _avertir(services, _rapport_identifiants(plan, a_juger, ecartes, filtrees, masquees))


def _rapport_identifiants(plan: Plan, a_juger: list[Cas], ecartes: list, filtrees: int,
                          masquees: set[str] = frozenset()) -> str:
    r = ['# Identifiants', '', f'{len(plan.groupes)} fiche(s) modifiée(s) par ce plan (formes de DOI corrigées, '
         'DOI et ISBN trouvés avec certitude, cas jugés et acceptés).', '']
    if a_juger:
        par_probleme = {}
        for c in a_juger:
            par_probleme[c.probleme] = par_probleme.get(c.probleme, 0) + 1
        evidents = sum(c.classe == 'évident' for c in a_juger)
        r += [f'{len(a_juger)} cas à juger dans suivi/metadonnees.toml : ' +
              ', '.join(f'{n} {p}' for p, n in sorted(par_probleme.items())) +
              f'. Dont {evidents} évident(s), où une seule proposition concorde en tout avec la fiche.', '']
    if filtrees:
        r += [f'{filtrees} fiche(s) exclue(s) par le filtre de confidentialité, jamais cherchées par titre.', '']
    if ecartes:
        r += ['## Écartées', ''] + [f'- {c} : {raison}' for c, raison in ecartes] + ['']
    r += ['## Détail', '']
    for g in plan.groupes:
        op = g.operations[0]
        if g.id in masquees:
            r.append(f"- {g.id} « {g.titre} » : {', '.join(op.apres)}")
            continue
        r.append(f"- {g.id} « {g.titre} » : {', '.join(f'{k} {op.avant.get(k)!r} → {v!r}' for k, v in op.apres.items())}"
                 f' ({op.nature})')
    return '\n'.join(r) + '\n'


# --- Types ------------------------------------------------------------------------

# Transitions sûres quand l'auteur et l'année concordent (D86). « Document » vers tout type reconnu. Pas de
# communication vers chapitre (D130) : Crossref range en chapitres les actes publiés en collection (Lecture Notes).
TRANSITIONS_SURES = {('journalArticle', 'bookSection'), ('bookSection', 'journalArticle'),
                     ('journalArticle', 'conferencePaper'), ('bookSection', 'conferencePaper')}
TOUJOURS_A_JUGER = {'book', 'preprint', 'report', 'thesis', 'encyclopediaArticle'}
META = {'key', 'version', 'itemType', 'dateAdded', 'dateModified', 'collections', 'tags', 'relations', 'creators',
        'deleted', 'parentItem', 'extra'}


def transition_sure(de: str, vers: str) -> bool:
    if de in TOUJOURS_A_JUGER or vers in TOUJOURS_A_JUGER:
        return False
    return (de, vers) in TRANSITIONS_SURES or de == 'document'


def conversion(d: dict, vers: str, types: Types) -> tuple[dict, list[str], list[str]]:
    """Champs à écrire pour passer la fiche `d` au type `vers` (D85), champs transférés, valeurs recopiées."""
    de = d['itemType']
    apres, transferts, recopies = {'itemType': vers}, [], []
    for f, v in d.items():
        if f in META or not v or f in types.champs.get(vers, set()) or f not in types.champs.get(de, set()):
            continue
        cible = types.equivalent(f, de, vers)
        apres[f] = ''
        if cible and not d.get(cible) and cible not in apres:
            apres[cible] = v
            transferts.append(f'{f} → {cible}')
        else:
            recopies.append(f'{f} : {v}')
    if recopies:
        apres['extra'] = '\n'.join(([d['extra']] if d.get('extra') else []) + recopies)
    roles = types.roles.get(vers, set())
    createurs = d.get('creators') or []
    if any(c.get('creatorType') not in roles for c in createurs):
        apres['creators'] = [dict(c, creatorType=c['creatorType'] if c.get('creatorType') in roles else 'contributor')
                             for c in createurs]
    return apres, transferts, recopies


def _type_refuse(cle: str, cas: list[Cas]) -> bool:
    return any(c.cle == cle and c.sous_etape == TYPES and c.decision == REFUSER for c in cas)


def types(b: Bibliotheque, cfg: Config, services: Services, client: Client, schema: Types, afficher=None,
          cles: set[str] | None = None):
    anciens = charger_suivi(cfg)
    m = cfg.metadonnees
    masquees = filtre.cles_masquees(b, cfg)
    surs, detectes = {}, []
    fiches = [e for e in b.fiches if DOI_VALIDE.match(normaliser_doi(e.champs.get('DOI', ''))) and _dans(e.cle, cles)]
    try:
        for i, e in enumerate(fiches, 1):
            _progression(i, len(fiches), afficher)
            o = services.oeuvre(normaliser_doi(e.champs['DOI']))
            if not o or not o.type or o.type == e.type or o.type not in schema.champs or _type_refuse(e.cle, anciens):
                continue
            if not meme_publication(e, o, m.seuil_discordance) and not _confirme(e.cle, anciens):
                continue
            local = dict(e.champs, itemType=e.type)
            _, transferts, recopies = conversion(local, o.type, schema)
            note = (f'{nom_type(e.type)} → {nom_type(o.type)} d\'après {o.source} ({_decrire(o, similarite(e.titre, o.titre))})'
                    + (f". Transférés : {', '.join(transferts)}" if transferts else '')
                    + (f". Recopiés dans extra : {', '.join(r.split(' : ')[0] for r in recopies)}" if recopies else ''))
            if e.cle in masquees:
                note = f'{nom_type(e.type)} → {nom_type(o.type)} d\'après {o.source}'
            if transition_sure(e.type, o.type) and _auteur_ok(e, o) and _annee_ok(e, o, m.ecart_annees):
                surs[e.cle] = (o.type, note)
            else:
                detectes.append(Cas(e.cle, TYPES, 'type_different', [Proposition({'itemType': o.type}, o.source, note)]))
        # Fiches « Document » sans identifiant, peut-être des livres : toujours à juger (D90).
        exclues = filtre.exclues(b, cfg)
        documents = []
        for e in b.fiches:
            if (e.type != 'document' or not _dans(e.cle, cles) or e.id in exclues or not e.titre or e.champs.get('DOI')
                    or e.champs.get('ISBN')):
                continue
            sur, candidats = chercher_isbn(e, services, cfg)
            props = [Proposition({'itemType': 'book', 'ISBN': p.champs['ISBN']}, p.source, f'livre : {p.note}')
                     for p in ([sur] if sur else []) + candidats]
            if props:
                detectes.append(Cas(e.cle, TYPES, 'livre_possible', props))
            else:
                documents.append(e.cle)
    finally:
        services.sauver()
    detectes += types_des_doublons(b, cfg, anciens, {c.cle for c in detectes} | set(surs), cles)
    cas = fusionner_suivi(anciens, detectes, TYPES, cles)
    ecrire_suivi(cfg, cas, b)
    vers = {cle: (t, note, {}) for cle, (t, note) in surs.items()}
    vers |= {c.cle: (c.retenus()['itemType'], f'cas jugé ({c.propositions[c.choix - 1].note})',
                     {k: v for k, v in c.retenus().items() if k != 'itemType'})
             for c in cas if c.sous_etape == TYPES and c.decision == ACCEPTER and c.retenus().get('itemType')
             and _dans(c.cle, cles)}
    groupes, ecartes = [], []
    for k in _doublons_en_conflit(cfg, cas):
        vers.pop(k, None)
        ecartes.append((k, 'une autre fiche du même groupe de doublons change aussi de type, n\'accepter qu\'un '
                           'des deux cas « type_doublon »'))
    donnees = client.fiches(list(vers))
    for cle, (nouveau, note, autres) in vers.items():
        d = donnees.get(cle)
        if d is None or d.get('deleted'):
            ecartes.append((cle, 'fiche introuvable ou à la corbeille'))
            continue
        if d['itemType'] == nouveau:
            continue
        apres, _, _ = conversion(d, nouveau, schema)
        apres |= {k: v for k, v in autres.items() if k in schema.champs.get(nouveau, set()) and not d.get(k)}
        op = Operation(cle, {f: plans.brute(d, f) for f in apres}, apres, 0, note)
        groupes.append(Groupe(cle, filtre.MASQUE if cle in masquees else d.get('title', '')[:80], [op]))
    plan = Plan(TYPES, client.utilisateur, groupes, description='Types de fiche corrigés d\'après la source du DOI.')
    a_juger = [c for c in cas if c.sous_etape == TYPES and not c.decision and _dans(c.cle, cles)]
    return plan, _avertir(services, _rapport_types(plan, a_juger, ecartes, documents))


def types_des_doublons(b: Bibliotheque, cfg: Config, anciens: list[Cas], deja: set[str],
                       cles: set[str] | None = None) -> list[Cas]:
    """Fiches d'un groupe de doublons à fusionner dont les types diffèrent, que la fusion refuse (D51). Chaque
    fiche reçoit un cas `type_doublon`, qui propose le type des autres. On en accepte un seul par groupe, celui
    de la fiche dont le type est faux, ce que `types` vérifie. Toujours à juger, rien ne dit quel type est bon."""
    from zot_clean import doublons
    par_cle = b.par_cle()
    res = []
    for g in doublons.charger_suivi(cfg):
        fiches = [par_cle[k] for k in g.cles if k in par_cle]
        if g.decision != doublons.FUSIONNER or len(fiches) != len(g.cles) or len({e.type for e in fiches}) < 2:
            continue
        for e in fiches:
            if not _dans(e.cle, cles) or e.cle in deja or _type_refuse(e.cle, anciens):
                continue
            autres = [x for x in fiches if x.cle != e.cle and x.type != e.type]
            props = [Proposition({'itemType': t}, '', f"{nom_type(e.type)} → {nom_type(t)}, le type de "
                                 f"{', '.join(x.cle for x in autres if x.type == t)}, doublon à fusionner. Accepter "
                                 "ce cas ou celui de l'autre fiche, pas les deux")
                     for t in dict.fromkeys(x.type for x in autres)]
            res.append(Cas(e.cle, TYPES, 'type_doublon', props))
    return res


def _doublons_en_conflit(cfg: Config, cas: list[Cas]) -> list[str]:
    """Fiches d'un même groupe de doublons dont plusieurs cas `type_doublon` sont acceptés : elles échangeraient
    leurs types au lieu d'en prendre un seul."""
    from zot_clean import doublons
    acceptes = {c.cle for c in cas if c.probleme == 'type_doublon' and c.decision == ACCEPTER}
    res = []
    for g in doublons.charger_suivi(cfg):
        if g.decision == doublons.FUSIONNER and len(communs := acceptes & set(g.cles)) > 1:
            res += sorted(communs)
    return res


def _rapport_types(plan: Plan, a_juger: list[Cas], ecartes: list, documents: list[str] = ()) -> str:
    r = ['# Types', '', f'{len(plan.groupes)} fiche(s) changent de type. Les champs qui ont un équivalent dans le '
         'nouveau type y sont transférés, les autres valeurs sont recopiées dans le champ extra, rien n\'est perdu.',
         '', 'Lancer ensuite `zc metadonnees completer`, qui remplira les champs du nouveau type.', '']
    if a_juger:
        r += [f'{len(a_juger)} changement(s) de type à juger dans suivi/metadonnees.toml.', '']
    if documents:
        r += [f"{len(documents)} fiche(s) « Document » sans livre trouvé par leur titre "
              f"({', '.join(documents[:20])}{'…' if len(documents) > 20 else ''}). `zc` ne propose un type qu'aux "
              "fiches qui ont un DOI, qui ressemblent à un livre connu ou qui doublent une fiche d'un autre type. "
              "Pour les autres, le bon type se choisit à la main dans Zotero, menu « Type de document » de la "
              "fiche.", '']
    if ecartes:
        r += ['## Écartées', ''] + [f'- {c} : {raison}' for c, raison in ecartes] + ['']
    r += ['## Détail', '']
    r += [f'- {g.id} « {g.titre} » : {g.operations[0].nature}' for g in plan.groupes]
    return '\n'.join(r) + '\n'


# --- Compléments ------------------------------------------------------------------

def _personnes(liste, role: str) -> list[dict]:
    return [{'creatorType': role, 'lastName': n, 'firstName': p} if p else {'creatorType': role, 'name': n}
            for n, p in liste if n]


def champs_oeuvre(o: Oeuvre, type_: str, champs: list[str], exclus: dict[str, list[str]] | None = None) -> dict:
    d = {'ISBN': ', '.join(o.isbn), 'ISSN': ', '.join(o.issn), 'date': o.date, 'volume': o.volume, 'issue': o.numero,
         'pages': o.pages, 'publisher': o.editeur, 'place': o.lieu, 'language': o.langue,
         'abstractNote': re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', o.resume)).strip(),
         'numPages': o.nb_pages, 'edition': o.edition, 'series': o.collection, 'seriesNumber': o.numero_collection}
    if type_ in CONTENEUR:
        d[CONTENEUR[type_]] = o.conteneur
    retires = set((exclus or {}).get(type_, []))
    d = {k: v for k, v in d.items() if k in champs and k not in retires and v}
    if 'creators' in champs and 'creators' not in retires:
        createurs = _personnes(o.auteurs, 'author')
        if type_ in AVEC_EDITEURS:
            createurs += _personnes(o.editeurs_scientifiques, 'editor') + _personnes(o.traducteurs, 'translator')
        if createurs:
            d['creators'] = createurs
    return d


def _confirme(cle: str, cas: list[Cas]) -> bool:
    """DOI discordant jugé. Retirer le DOI ou en choisir un autre le change de toute façon, reste « garder »."""
    return any(c.cle == cle and c.probleme == 'doi_discordant' and c.decision == ACCEPTER for c in cas)


def _a_remplir(e: Element, valeurs: dict, o: Oeuvre, differences: list) -> dict:
    """Champs vides à remplir (D60), langue vérifiée sur le titre (D77). Les écarts vont dans `differences`."""
    res = {}
    for f, v in valeurs.items():
        if f == 'language':
            if not e.champs.get(f) and v[:2].lower() == langue_du_titre(e.titre) != '':
                res[f] = v[:2].lower()
        elif f == 'creators':
            if not e.createurs:
                res[f] = v
        elif not e.champs.get(f):
            res[f] = v
        elif not meme_forme(f, e.champs[f], str(v)):
            differences.append((e.cle, f, e.champs[f], v, o.source))
    return res


def _date_triable(v: str) -> list[str]:
    """[année, mois, jour], « 00 » pour ce qui manque. Zotero range « 1991-00-00 1991 »."""
    m = re.match(r'(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?', v.strip())
    return [m.group(1), (m.group(2) or '0').zfill(2), (m.group(3) or '0').zfill(2)] if m else []


def _pages_completes(v: str) -> str:
    """« 422-31 » devient « 422-431 »."""
    debut, _, fin = re.sub(r'\s*[–—-]+\s*', '-', v.strip()).partition('-')
    if fin.isdigit() and debut.isdigit() and len(fin) < len(debut):
        fin = debut[:len(debut) - len(fin)] + fin
    return f'{debut}-{fin}' if fin else debut


def meme_forme(champ: str, a: str, b: str) -> bool:
    """Deux valeurs qui ne diffèrent que par leur écriture (D132) : date plus ou moins précise, ISSN ou ISBN
    sans tirets ou en partie, pages abrégées, article initial d'un nom de revue, accents et casse."""
    if champ == 'date':
        x, y = _date_triable(a), _date_triable(b)
        return bool(x and y) and all(i == j or '00' in (i, j) for i, j in zip(x, y))
    if champ in ('ISSN', 'ISBN'):
        x, y = ({re.sub(r'[^0-9X]', '', s.upper()) for s in re.split(r'[,;\s]+', v) if s} for v in (a, b))
        return bool(x and y) and (x <= y or y <= x)
    if champ == 'pages':
        x, y = _pages_completes(a), _pages_completes(b)
        return x == y or ('-' not in x or '-' not in y) and x.split('-')[0] == y.split('-')[0]
    # Tirets longs, « & » pour « and » ou « et », article initial : mots vides écartés.
    x, y = ([m for m in norm(re.sub(r'[–—]', '-', v)).split() if m not in VIDES | {'et'}] for v in (a, b))
    return x == y


def completer(b: Bibliotheque, cfg: Config, services: Services, client: Client, afficher=None,
              cles: set[str] | None = None):
    cas = charger_suivi(cfg)
    m = cfg.metadonnees
    propositions, differences, discordants, types_en_attente, isbn_discordants = {}, [], [], [], []
    fiches = [e for e in b.fiches if DOI_VALIDE.match(normaliser_doi(e.champs.get('DOI', ''))) and _dans(e.cle, cles)]
    try:
        for i, e in enumerate(fiches, 1):
            _progression(i, len(fiches), afficher)
            o = services.oeuvre(normaliser_doi(e.champs['DOI']))
            if o is None:
                continue
            if not meme_publication(e, o, m.seuil_discordance) and not _confirme(e.cle, cas):
                discordants.append((e.cle, e.titre, o.titre, o.source))
                continue
            if o.type and o.type != e.type and not _type_refuse(e.cle, cas):
                types_en_attente.append(e.cle)  # D87 : le type d'abord
                continue
            valeurs = champs_oeuvre(o, e.type, m.champs, m.exclus_par_type)
            if a_remplir := _a_remplir(e, valeurs, o, differences):
                propositions[e.cle] = (a_remplir, f'complété depuis {o.source}')
        # Livres et chapitres par leur ISBN (D90, D93). Les valeurs venues du DOI passent en premier.
        livres = [e for e in b.fiches if e.type in ('book', 'bookSection') and _dans(e.cle, cles)
                  and any(ok for _, ok in isbns(e.champs.get('ISBN', '')))]
        for n, e in enumerate(livres, 1):
            _progression(n, len(livres), afficher, 'livres et chapitres examinés par leur ISBN')
            isbn = next(i for i, ok in isbns(e.champs['ISBN']) if ok)
            o = services.livre(isbn)
            if o is None:
                continue
            reference = e.titre if e.type == 'book' else e.champs.get('bookTitle', '')
            if (reference and not titres_concordants(reference, o.titre, m.seuil_discordance)
                    and not _isbn_confirme(e.cle, cas)):
                isbn_discordants.append((e.cle, reference, o.titre, o.source))
                continue
            valeurs = champs_oeuvre(o, 'book', m.champs, m.exclus_par_type)
            if e.type == 'bookSection':  # notice de l'ouvrage : ni ses créateurs ni son nombre de pages
                valeurs = {k: v for k, v in valeurs.items() if k not in ('creators', 'numPages')}
                if 'bookTitle' in m.champs:
                    valeurs['bookTitle'] = o.titre
            champs, nature = propositions.get(e.cle, ({}, ''))
            valeurs = {k: v for k, v in valeurs.items() if k not in champs}
            if a_remplir := _a_remplir(e, valeurs, o, differences):
                propositions[e.cle] = (champs | a_remplir, ' ; '.join(filter(None, (nature, f'complété depuis {o.source}'))))
    finally:
        services.sauver()
    imposes = {}
    for c in cas:
        if c.sous_etape == COMPLETER and c.decision == ACCEPTER and c.forcer and _dans(c.cle, cles):
            champs, _ = propositions.get(c.cle, ({}, ''))
            propositions[c.cle] = (champs | c.forcer, 'valeurs imposées dans suivi/metadonnees.toml')
            imposes[c.cle] = c.forcer
    # Ce qu'un cas `forcer` règle n'est plus signalé comme sauté ni comme différent.
    discordants = [x for x in discordants if 'DOI' not in imposes.get(x[0], {})]
    isbn_discordants = [x for x in isbn_discordants if 'ISBN' not in imposes.get(x[0], {})]
    differences = [x for x in differences if x[1] not in imposes.get(x[0], {})]
    donnees = client.fiches(list(propositions))
    # Un champ rempli dans Zotero depuis la copie de la base n'est pas écrasé.
    for cle, (champs, nature) in list(propositions.items()):
        d = donnees.get(cle, {})
        forces = next((c.forcer for c in cas if c.cle == cle and c.sous_etape == COMPLETER
                       and c.decision == ACCEPTER), {})
        garde = {f: v for f, v in champs.items() if f in forces or not d.get(f)}
        propositions[cle] = (garde, nature)
    masquees = filtre.cles_masquees(b, cfg)
    plan, ecartes = _plan(COMPLETER, {k: v for k, v in propositions.items() if v[0]}, client,
                          'Champs vides complétés depuis les sources de métadonnées.', masquees)
    return plan, _avertir(services, _rapport_completer(plan, differences, discordants, ecartes, types_en_attente,
                                                       isbn_discordants, masquees, imposes))


def _court(v) -> str:
    return (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))[:70]


def _rapport_completer(plan: Plan, differences: list, discordants: list, ecartes: list,
                       types_en_attente: list | None = None, isbn_discordants: list | None = None,
                       masquees: set[str] = frozenset(), imposes: dict[str, dict] | None = None) -> str:
    """Rapport des compléments. Pour une fiche confidentielle, les noms des champs sans leurs valeurs (D126).
    Les valeurs imposées par un cas `forcer` sont comptées à part des champs remplis depuis les sources."""
    imposes = imposes or {}
    comptes, forces = {}, {}
    for g in plan.groupes:
        for f, v in g.operations[0].apres.items():
            if f in imposes.get(g.id, {}):
                quoi = f'{f} vidé' if v in ('', [], None) else f
                forces[quoi] = forces.get(quoi, 0) + 1
            else:
                comptes[f] = comptes.get(f, 0) + 1
    r = ['# Compléments', '', f'{len(plan.groupes)} fiche(s) complétée(s). Seuls les champs vides sont remplis, '
         'une valeur déjà présente n\'est jamais remplacée, sauf par un cas `forcer` de suivi/metadonnees.toml.', '']
    if comptes:
        r += ['Champs remplis : ' + ', '.join(f'{f} ({n})' for f, n in sorted(comptes.items())) + '.', '']
    if forces:
        r += ['Valeurs imposées par un cas `forcer` : ' + ', '.join(f'{f} ({n})' for f, n in sorted(forces.items()))
              + '.', '']
    if discordants:
        r += [f'{len(discordants)} fiche(s) sautée(s), leur DOI semble désigner une autre publication. Les juger '
              'd\'abord avec `zc metadonnees identifiants`.', '']
    if isbn_discordants:
        r += [f'{len(isbn_discordants)} livre(s) ou chapitre(s) sauté(s), leur ISBN semble désigner un autre livre. '
              'Les juger d\'abord avec `zc metadonnees identifiants` (cas `isbn_discordant`).', '']
    if types_en_attente:
        r += [f'{len(types_en_attente)} fiche(s) sautée(s), leur type diffère de celui de la source. Passer d\'abord '
              'par `zc metadonnees types`.', '']
    if discordants or isbn_discordants:
        r += ['## Sautées, titre différent de la source', '']
        r += [f'- {c} ({quoi}) : {filtre.MASQUE}' if c in masquees else
              f'- {c} ({quoi}) : {_court(a)!r} dans Zotero, {_court(v)!r} chez {s}'
              for quoi, liste in (('DOI', discordants), ('ISBN', isbn_discordants or [])) for c, a, v, s in liste]
        r.append('')
    if ecartes:
        r += ['## Écartées', ''] + [f'- {c} : {raison}' for c, raison in ecartes] + ['']
    if differences:
        r += ['## Valeurs différentes, laissées telles quelles', '',
              'Pour imposer la valeur de la source, ajouter un cas `forcer` dans suivi/metadonnees.toml.', '']
        r += [f'- {c} {f} : valeurs masquées' if c in masquees else
              f'- {c} {f} : {_court(a)!r} dans Zotero, {_court(v)!r} chez {s}' for c, f, a, v, s in differences[:300]]
        if len(differences) > 300:
            r.append(f'- … et {len(differences) - 300} autres')
        r.append('')
    r += ['## Détail', '']
    for g in plan.groupes:
        op = g.operations[0]
        r.append(f"- {g.id} « {g.titre} » : " + ', '.join(k if g.id in masquees else f'{k} = {_court(v)!r}'
                                                          for k, v in op.apres.items()))
    return '\n'.join(r) + '\n'


def _avertir(services: Services, rapport: str) -> str:
    avert = services.avertissements()
    if not avert:
        return rapport
    titre, _, reste = rapport.partition('\n\n')
    return f'{titre}\n\n' + ''.join(f'**Attention.** {a}\n\n' for a in avert) + reste


def afficher_progression(message: str) -> None:
    print(message, file=sys.stderr)
