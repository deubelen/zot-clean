"""Application d'un plan, socle commun de toutes les écritures (D34 à D36, D42, D46, D47, D56).

Garde-fous vérifiés ici, et non par les commandes, pour qu'aucune étape ne
puisse les contourner. Le plan doit viser le compte de la clé. Aucune clé
invalide ne doit bloquer la synchronisation. Au-delà de l'essai, un essai du
même plan doit avoir réussi et une sauvegarde récente exister. L'essai porte
toujours sur les premiers groupes du plan, si bien qu'un `--essai` relancé ne
reprend que ceux qui en restent, sans jamais avancer dans le plan (D179).

Les groupes sont traités par paquets d'environ 50 opérations, rang par rang.
Avant chaque lot, les éléments sont relus par l'API. Pour chaque champ, valeur
actuelle égale à l'après, rien à faire. Égale à l'avant, on écrit avec la
version relue. Autre valeur, conflit, et le groupe s'arrête (un plan
d'annulation laisse seulement ce champ, D39). Après un 412, l'élément est relu
et réécrit une fois. Les groupes déjà faits d'après les journaux du plan sont
sautés, ce qui rend toute relance sans danger.

Chaque écriture est inscrite au journal avant d'être envoyée (D178). Si sa
réponse se perd, ou si la commande s'interrompt, la relecture qui suit (nouvel
essai après un 412, reprise du plan) trouve les valeurs déjà écrites, et
l'intention restée sans confirmation devient alors une écriture journalisée,
donc annulable, au lieu de passer pour « rien à faire ».

Les collections (D114) suivent la même règle. Une collection à créer qui
n'existe pas encore est créée sous la clé du plan. Si elle existe déjà avec
les valeurs voulues, c'est qu'une exécution précédente l'a créée, et il n'y a
rien à faire.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from zot_clean import journal, lecture, sauvegarde
from zot_clean.config import Config
from zot_clean.ecriture import LOT, Client, Refus
from zot_clean.journal import Journal
from zot_clean.plans import DEFAUTS, Groupe, Operation, Plan, normaliser, valeur

ESSAI, TOUT = 'essai', 'tout'
GROUPES_SANS_PROGRESSION = 20


@dataclass
class Bilan:
    journal: Path | None = None
    faits: list[str] = field(default_factory=list)
    partiels: dict[str, str] = field(default_factory=dict)
    conflits: dict[str, str] = field(default_factory=dict)
    erreurs: dict[str, str] = field(default_factory=dict)
    # Groupes en conflit ou en erreur après une partie de leurs écritures, avec les clés écrites (D181)
    arretes: dict[str, list[str]] = field(default_factory=dict)
    elements_ecrits: int = 0
    restants: int = 0
    avertissements: list[str] = field(default_factory=list)


def comparer(op: Operation, data: dict, partiel: bool = False) -> tuple[dict, list[str]]:
    """Champs à écrire et champs en conflit, d'après les valeurs actuelles `data`."""
    a_ecrire, conflits = {}, []
    for champ, nouveau in op.apres.items():
        actuel = valeur(data, champ)
        if actuel == normaliser(champ, nouveau):
            continue
        if actuel == normaliser(champ, op.avant.get(champ, DEFAUTS.get(champ, ''))):
            a_ecrire[champ] = nouveau
        else:
            conflits.append(champ)
    return a_ecrire, conflits


def controler_synchronisation(cfg: Config) -> str | None:
    """Refuse si des clés invalides bloquent la synchronisation (D56), avertit s'il reste des éléments à envoyer."""
    invalides, non_sync, annotations = lecture.etat_synchronisation(cfg.base)
    if invalides:
        raise Refus(f"{len(invalides)} élément(s) à clé invalide bloquent la synchronisation de Zotero "
                    f"({', '.join(invalides[:5])}). Les réparer avant tout nettoyage (voir `zc audit`).")
    if non_sync:
        return (f'{non_sync} élément(s) ou collection(s) pas encore synchronisés. Laisser Zotero synchroniser '
                'avant de continuer, sinon ces changements locaux ne sont pas vus par le plan.')
    if annotations:
        return (f'{annotations} annotation(s) de PDF pas encore synchronisée(s), sans effet sur ce plan. Si ce nombre '
                'ne baisse pas après une synchronisation, Zotero n\'arrive pas à les envoyer (voir ses erreurs de '
                'synchronisation), et elles n\'existent que sur cet ordinateur.')
    return None


def copie_en_retard(locale: int, serveur: int) -> str:
    """Refus commun aux commandes qui lisent l'état réel sur la copie locale (D119, D123). Zotero, même ouvert, ne va
    pas toujours chercher seul les changements de collections faits par l'API, d'où la synchronisation manuelle."""
    return (f"Zotero n'a pas encore reçu les derniers changements de la bibliothèque (version locale {locale}, "
            f"serveur {serveur}). Lancer à la main la synchronisation de Zotero (flèche verte en haut à droite), "
            "attendre qu'elle se termine, puis relancer la commande.")



def lire_a_jour(cfg: Config, client: Client, signaler=lambda m: None, lire=None,
                facultatif: bool = False) -> lecture.Bibliotheque:
    """Bibliothèque à jour pour préparer un plan (D171). Lue sur la copie locale (D119) ; si Zotero n'a pas encore
    reçu les derniers changements du serveur (ceux de la passe précédente, en général), ils sont lus sur zotero.org
    et reportés, au lieu d'attendre la synchronisation. Le socle relit de toute façon chaque élément avant d'écrire.
    `facultatif` : zotero.org injoignable, la copie locale seule suffit (commandes qui ne font que lire)."""
    from zot_clean.ecriture import ErreurAPI
    b = (lire or (lambda: lecture.lire(cfg.base)))()
    try:
        en_retard = client.version_serveur() > b.version
        ch = client.changements(b.version) if en_retard else None
    except ErreurAPI:
        if not facultatif:
            raise
        signaler('zotero.org injoignable, lecture de la seule copie locale, qui peut ne pas avoir reçu les derniers '
                 'changements.')
        return b
    if ch:
        lecture.reporter(b, ch, cfg.base.parent / 'storage')
        signaler(f'{ch.nombre} changement(s) pas encore reçus par Zotero, lus sur zotero.org.')
    return b

ETAPES_GESTION = {'inbox'}


def a_traiter(plan: Plan, cfg: Config, mode: str, maintenant: datetime | None = None) -> list[Groupe]:
    faits = journal.groupes_faits(cfg.journal, plan.empreinte)
    restants = [g for g in plan.groupes if g.id not in faits]
    if mode == ESSAI or len(plan.groupes) <= cfg.ecriture.essai:
        essai = {g.id for g in plan.groupes[:cfg.ecriture.essai]}
        return [g for g in restants if g.id in essai]
    petit = _petit_plan_de_gestion(plan, cfg)
    if not petit and not journal.essai_fait(cfg.journal, plan.empreinte):
        raise Refus("Aucun essai de ce plan n'a réussi. Lancer d'abord `zc appliquer <plan> --essai`, "
                    'puis vérifier le résultat dans Zotero.')
    if restants and not petit and not sauvegarde.recente(cfg, maintenant):
        raise Refus(f'Aucune sauvegarde de moins de {cfg.sauvegarde.delai_heures:g} heures. '
                    'Fermer Zotero, lancer `zc sauvegarder`, puis relancer.')
    return restants


def _petit_plan_de_gestion(plan: Plan, cfg: Config) -> bool:
    """Tri de l'Inbox touchant moins de `petit_plan_de_gestion` fiches, appliqué sans essai ni sauvegarde
    récente (D136, D138) : il ne fait que ranger et corriger peu de fiches, et `zc annuler` le défait."""
    fiches = {op.cle for g in plan.groupes for op in g.operations if op.genre == 'items'}
    return plan.etape in ETAPES_GESTION and len(fiches) < cfg.ecriture.petit_plan_de_gestion


def appliquer(plan: Plan, chemin_plan: Path, client: Client, cfg: Config, mode: str,
              maintenant: datetime | None = None) -> Bilan:
    if plan.bibliotheque != client.utilisateur:
        raise Refus(f'Ce plan a été préparé pour le compte {plan.bibliotheque}, la clé est celle du compte '
                    f'{client.utilisateur}.')
    bilan = Bilan()
    if avert := controler_synchronisation(cfg):
        bilan.avertissements.append(avert)
    deja = journal.groupes_faits(cfg.journal, plan.empreinte)
    groupes = a_traiter(plan, cfg, mode, maintenant)
    bilan.restants = len(plan.groupes) - len(deja) - len(groupes)
    if not groupes:
        return bilan
    suspens = journal.en_suspens([r.chemin for r in journal.du_plan(cfg.journal, plan.empreinte)])
    j = Journal(cfg.journal, plan.etape)
    bilan.journal = j.chemin
    j.en_tete(plan=chemin_plan.name, empreinte=plan.empreinte, etape=plan.etape, mode=mode,
              bibliotheque=plan.bibliotheque, reprise=bool(deja), annule=plan.annule)
    traites = 0
    try:
        for n, paquet in enumerate(_paquets(groupes), 1):
            _Execution(paquet, client, j, bilan, plan.partiel, suspens).lancer()
            traites += len(paquet)
            # Progression sur la sortie d'erreur pour un long plan, tous les cinq paquets d'une cinquantaine d'opérations.
            if len(groupes) > GROUPES_SANS_PROGRESSION and (traites == len(groupes) or n % 5 == 0):
                client.signaler(f'{traites}/{len(groupes)} groupes traités')
    except BaseException:
        j.fermer()
        raise
    bilan.restants += len(bilan.conflits) + len(bilan.erreurs)
    j.fin(faits=len(bilan.faits), partiels=len(bilan.partiels), conflits=len(bilan.conflits),
          erreurs=len(bilan.erreurs), elements=bilan.elements_ecrits)
    return bilan


def _paquets(groupes: list[Groupe]):
    paquet, n = [], 0
    for g in groupes:
        paquet.append(g)
        n += len(g.operations)
        if n >= LOT:
            yield paquet
            paquet, n = [], 0
    if paquet:
        yield paquet


def _lots(ops: list[tuple[Groupe, Operation]]):
    """Lots de 50 opérations au plus, d'un seul genre (fiches ou collections), sans deux fois le même élément."""
    lots: list[list] = []
    for g, op in ops:
        for lot in lots:
            if len(lot) < LOT and lot[0][1].genre == op.genre and all(o.cle != op.cle for _, o in lot):
                lot.append((g, op))
                break
        else:
            lots.append([(g, op)])
    return lots


class _Execution:
    def __init__(self, paquet: list[Groupe], client: Client, j: Journal, bilan: Bilan, partiel: bool,
                 suspens: dict[tuple[str, str], dict]):
        self.paquet, self.client, self.j, self.bilan, self.partiel = paquet, client, j, bilan, partiel
        self.suspens = suspens  # (groupe, clé) -> intention sans confirmation, de ce journal ou d'un précédent
        self.echec: dict[str, tuple[str, str]] = {}  # groupe -> (statut, détail)
        self.laisses: dict[str, list[str]] = {g.id: [] for g in paquet}
        self.ecrits: dict[str, list[str]] = {g.id: [] for g in paquet}

    def lancer(self):
        for rang in sorted({op.rang for g in self.paquet for op in g.operations}):
            ops = [(g, op) for g in self.paquet if g.id not in self.echec for op in g.operations if op.rang == rang]
            for lot in _lots(ops):
                self._lot(lot)
        for g in self.paquet:
            if g.id in self.echec:
                statut, detail = self.echec[g.id]
                if self.ecrits[g.id]:  # un rang déjà écrit : le groupe n'est pas intact (D181)
                    self.bilan.arretes[g.id] = self.ecrits[g.id]
                    detail += f", après l'écriture de {', '.join(self.ecrits[g.id])}"
                (self.bilan.conflits if statut == 'conflit' else self.bilan.erreurs)[g.id] = detail
            elif self.laisses[g.id]:
                statut, detail = 'partiel', 'champs laissés en l\'état : ' + ', '.join(self.laisses[g.id])
                self.bilan.partiels[g.id] = detail
            else:
                statut, detail = 'fait', ''
                self.bilan.faits.append(g.id)
            self.j.groupe(g.id, statut, detail)

    def _lot(self, lot: list[tuple[Groupe, Operation]], second: bool = False):
        genre = lot[0][1].genre
        courant = self.client.lire([op.cle for _, op in lot], genre)
        objets, attente = [], {}
        for g, op in lot:
            if g.id in self.echec:
                continue
            d = courant.get(op.cle)
            if op.creation:
                if d is None:
                    objets.append({'key': op.cle, 'version': 0, **op.apres})
                    attente[op.cle] = (g, op, {'key': op.cle}, op.apres)
                elif any(valeur(d, c) != normaliser(c, v) for c, v in op.apres.items()):
                    self.echec[g.id] = ('conflit', f'{op.cle} existe déjà, avec d\'autres valeurs')
                else:
                    self._confirmer(g, op, d['version'], genre)
                continue
            if d is None:
                self.echec[g.id] = ('conflit', f"{op.cle} n'existe plus (supprimé définitivement ?)")
                continue
            if motif := self._precondition(op, d, genre):
                self.echec[g.id] = ('conflit', motif)
                continue
            a_ecrire, conflits = comparer(op, d, self.partiel)
            if conflits and not self.partiel:
                self.echec[g.id] = ('conflit', f"{op.cle} modifié depuis le plan ({', '.join(conflits)})")
                continue
            self.laisses[g.id] += [f'{op.cle}.{c}' for c in conflits]
            if not a_ecrire and not conflits:
                self._confirmer(g, op, d['version'], genre)
            if a_ecrire:
                objets.append({'key': op.cle, 'version': d['version'], **a_ecrire})
                attente[op.cle] = (g, op, d, a_ecrire)
        for g, op, d, a_ecrire in attente.values():
            self.suspens[g.id, op.cle] = self.j.intention(g.id, op.rang, d, a_ecrire, genre, op.creation)
        res = self.client.ecrire(objets, genre)
        a_refaire = []
        for cle, (g, op, d, a_ecrire) in attente.items():
            if cle in res.reussis:
                self._journaliser(g, op.rang, d, a_ecrire, res.reussis[cle]['version'], genre, op.creation)
            elif cle in res.inchanges:
                continue
            elif cle in res.echecs and res.echecs[cle][0] == 412 and not second:
                a_refaire.append((g, op))
            elif cle in res.echecs:
                code, message = res.echecs[cle]
                self.echec[g.id] = ('conflit' if code == 412 else 'erreur', f'{cle} : {code} {message}')
            else:
                self.echec[g.id] = ('erreur', f'{cle} : réponse de Zotero sans nouvelle de cet élément')
        if a_refaire:
            self._lot(a_refaire, second=True)

    def _precondition(self, op: Operation, d: dict, genre: str) -> str:
        """Ce que le plan exige encore au moment d'écrire. Les champs de `exige` ont gardé leur valeur, et un
        élément qui part à la corbeille ne contient rien que le plan ne connaissait pas (D182, D183). La relecture
        se fait juste avant l'écriture, il reste seulement l'instant qui les sépare."""
        ecarts = [c for c, v in (op.exige or {}).items() if valeur(d, c) != normaliser(c, v)]
        if ecarts:
            return f"{op.cle} modifié depuis ({', '.join(ecarts)}), laissé tel quel"
        if op.enfants is None or op.apres.get('deleted') is not True or valeur(d, 'deleted'):
            return ''
        nouveaux = [k for k in self.client.contenu(op.cle, genre) if k not in op.enfants]
        if not nouveaux:
            return ''
        quoi = ('fiche(s) ou sous-collection(s)' if genre == 'collections'
                else 'pièce(s) jointe(s), note(s) ou annotation(s)')
        return (f"{op.cle} contient {len(nouveaux)} {quoi} ajoutée(s) depuis le plan ({', '.join(nouveaux[:5])}), "
                'laissé hors de la corbeille')

    def _journaliser(self, g: Groupe, rang: int, avant: dict, ecrit: dict, version: int, genre: str, cree: bool):
        self.j.element(g.id, rang, avant, ecrit, version, genre, cree)
        self.suspens.pop((g.id, avant['key']), None)
        self.ecrits[g.id].append(avant['key'])
        self.bilan.elements_ecrits += 1

    def _confirmer(self, g: Groupe, op: Operation, version: int, genre: str):
        """Valeurs déjà écrites : si une intention de ce plan les attendait, c'est cette écriture-là, faite par
        zotero.org sans que sa réponse arrive (D178). Sans intention, rien n'est attribué à `zc`."""
        if i := self.suspens.get((g.id, op.cle)):
            self._journaliser(g, op.rang, i['avant'], i['ecrit'], version, genre, bool(i.get('cree')))
