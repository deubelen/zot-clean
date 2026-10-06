"""Plans d'écriture (D34, D46).

Une étape de nettoyage ne touche jamais Zotero, elle produit un plan. Un plan
est une liste de groupes, et chaque groupe une suite d'opérations sur des
éléments (clé, valeurs d'avant et d'après des champs touchés, rang dans le
groupe). Rattacher à une fiche, mettre à la corbeille ou en sortir sont des
changements de champs comme les autres (`parentItem`, `deleted`). `zc
appliquer` exécute le plan tel quel, et son empreinte relie le plan à ses
journaux.

Une opération porte sur une fiche (`genre = "items"`) ou sur une collection
(`genre = "collections"`, D114), dont le nom, le parent et la corbeille se
changent de la même façon (`name`, `parentCollection`, `deleted`). Une
opération de création (`creation`) fait naître une collection sous la clé
tirée par le plan, pour que les fiches du même plan puissent déjà y renvoyer.

L'empreinte porte sur tout ce qui agit à l'exécution ou dans le registre des
journaux, à savoir les groupes et, pour un plan d'annulation, les journaux
qu'il défait (format 2, D180). La description et la date de création n'y
entrent pas, pour qu'un plan recalculé à l'identique garde son empreinte
(D47). Un plan du format 1 garde l'empreinte calculée sans les journaux.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

FORMAT = 2
FORMATS = (1, 2)  # formats encore lus

# Valeur d'un champ absent des données renvoyées par l'API.
DEFAUTS = {'deleted': False, 'parentItem': False, 'parentCollection': False, 'collections': [], 'tags': [], 'relations': {}, 'creators': []}


def normaliser(champ: str, v):
    """Forme comparable d'une valeur, indépendante de l'ordre que renvoie l'API."""
    if champ == 'deleted':
        return bool(v)
    if champ in ('parentItem', 'parentCollection'):
        return v or False
    if champ == 'collections':
        return sorted(v or [])
    if champ == 'tags':
        return sorted([t['tag'], int(t.get('type', 0))] for t in v or [])
    if champ == 'relations':
        return {k: sorted([x] if isinstance(x, str) else x) for k, x in (v or {}).items() if x}
    return v


def valeur(data: dict, champ: str):
    return normaliser(champ, data.get(champ, DEFAUTS.get(champ, '')))


def brute(data: dict, champ: str):
    """Valeur telle que l'API l'attend en écriture, défaut compris."""
    return data.get(champ, DEFAUTS.get(champ, ''))


@dataclass
class Operation:
    cle: str
    avant: dict
    apres: dict
    rang: int = 0  # les rangs d'un groupe s'exécutent dans l'ordre, un rang en échec arrête le groupe
    nature: str = ''
    genre: str = 'items'  # ou 'collections', ou 'settings' (réglage synchronisé, `value`, D175)
    creation: bool = False  # collection à créer sous la clé `cle`, avec les champs de `apres`
    # Mise à la corbeille : enfants (pièces jointes, notes, annotations) d'une fiche, ou fiches et sous-collections
    # d'une collection, connus au plan. Un autre trouvé au moment d'écrire arrête le groupe (D182, D183).
    enfants: list[str] | None = None
    exige: dict | None = None  # champs qui doivent encore avoir ces valeurs, même dans un plan partiel (D183)


@dataclass
class Groupe:
    id: str
    titre: str
    operations: list[Operation]


@dataclass
class Plan:
    etape: str
    bibliotheque: int
    groupes: list[Groupe]
    description: str = ''
    # Annulation (D39) : un champ en conflit est laissé tel quel, les autres sont écrits.
    partiel: bool = False
    annule: list[str] = field(default_factory=list)
    cree: str = ''
    format: int = FORMAT

    @property
    def empreinte(self) -> str:
        contenu = {'etape': self.etape, 'bibliotheque': self.bibliotheque, 'partiel': self.partiel,
                   'groupes': [_sans_defauts(asdict(g)) for g in self.groupes]}
        if self.annule and self.format >= 2:  # absent sinon, pour que l'empreinte des autres plans ne change pas
            contenu['annule'] = self.annule
        return hashlib.sha256(json.dumps(contenu, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]

    @property
    def nb_operations(self) -> int:
        return sum(len(g.operations) for g in self.groupes)


def _sans_defauts(groupe: dict) -> dict:
    """Groupe sans les champs d'opération ajoutés pour les collections quand ils ont leur valeur par défaut,
    pour que l'empreinte des plans écrits avant eux ne change pas."""
    ops = [{k: v for k, v in o.items() if not (k == 'genre' and v == 'items' or k == 'creation' and not v
                                                or k in ('enfants', 'exige') and v is None)}
           for o in groupe['operations']]
    return dict(groupe, operations=ops)


def ecrire(plan: Plan, dossier: Path, rapport: str) -> Path:
    """Écrit le plan et son rapport lisible dans `dossier` (plans/ du dossier de travail)."""
    dossier.mkdir(parents=True, exist_ok=True)
    plan.cree = plan.cree or datetime.now().astimezone().isoformat(timespec='seconds')
    chemin = dossier / f'{datetime.now():%Y-%m-%d_%H%M%S}_{plan.etape}_{plan.empreinte}.json'
    d = asdict(plan)
    d = {'format': d.pop('format'), 'empreinte': plan.empreinte, **d}
    chemin.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    chemin.with_suffix('.md').write_text(rapport, encoding='utf-8')
    return chemin


def charger(chemin: Path) -> Plan:
    d = json.loads(chemin.read_text(encoding='utf-8'))
    if d.get('format') not in FORMATS:
        raise SystemExit(f'{chemin} : format de plan inconnu ({d.get("format")}). Mettre zot-clean à jour.')
    groupes = [Groupe(g['id'], g['titre'], [Operation(**o) for o in g['operations']]) for g in d['groupes']]
    plan = Plan(d['etape'], d['bibliotheque'], groupes, d.get('description', ''), d.get('partiel', False),
                d.get('annule', []), d.get('cree', ''), d['format'])
    if plan.empreinte != d.get('empreinte'):
        raise SystemExit(f'{chemin} : le plan a été modifié depuis sa création. Le régénérer.')
    return plan


def plus_recents(chemin: Path, plan: Plan) -> list[Path]:
    """Plans de la même étape préparés après `chemin`, dans le même dossier. Un plan regénéré ne remplace pas le
    fichier de l'ancien, qui reste à côté : `zc appliquer` le signale. Les plans d'annulation ne sont pas comparés."""
    if plan.etape == 'annulation':
        return []
    horodatage = chemin.name[:17]  # AAAA-MM-JJ_HHMMSS
    return sorted(p for p in chemin.parent.glob(f'*_{plan.etape}_*.json')
                  if p.name[:17] > horodatage and p.name.split('_')[2] == plan.etape)
