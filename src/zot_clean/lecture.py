"""Lecture de la bibliothèque sur une copie temporaire de `zotero.sqlite` (D12).

Seul module qui connaît le schéma interne de Zotero. La copie (base et `-wal`,
jamais les fichiers joints) est faite dans un dossier temporaire, effacé après
lecture. Avant toute requête, on vérifie que les tables et colonnes utilisées
existent, pour s'arrêter proprement si une version de Zotero a changé le schéma.
Si Zotero écrit dans la base pendant la copie, celle-ci est refaite (D185).
Dans le bloc `partager()`, que la ligne de commande ouvre pour chaque commande,
les lectures se partagent une seule copie tant que Zotero n'écrit pas dans la base.
Les éléments et collections de la corbeille sont ignorés, avec ce que Zotero y
cache avec eux, à savoir les pièces jointes et notes d'une fiche, les
annotations d'une pièce jointe et les sous-collections d'une collection (D186).
"""

import json
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

BIBLIOTHEQUE_PERSO = 1
COPIES = 3  # essais de copie quand Zotero écrit dans la base pendant qu'on la copie (D185)
PAUSE = 1.0

# Tables et colonnes lues ici. Toute absence arrête la lecture.
SCHEMA = {
    'items': {'itemID', 'itemTypeID', 'libraryID', 'key', 'synced', 'dateAdded', 'version'},
    'itemTypes': {'itemTypeID', 'typeName'},
    'fields': {'fieldID', 'fieldName'},
    'itemData': {'itemID', 'fieldID', 'valueID'},
    'itemDataValues': {'valueID', 'value'},
    'creators': {'creatorID', 'firstName', 'lastName'},
    'itemCreators': {'itemID', 'creatorID', 'creatorTypeID', 'orderIndex'},
    'collections': {'collectionID', 'collectionName', 'parentCollectionID', 'libraryID', 'key', 'synced'},
    'collectionItems': {'collectionID', 'itemID'},
    'tags': {'tagID', 'name'},
    'itemTags': {'itemID', 'tagID', 'type'},
    'itemAttachments': {'itemID', 'parentItemID', 'linkMode', 'contentType', 'path'},
    'itemNotes': {'itemID', 'parentItemID', 'note'},
    'deletedItems': {'itemID'},
    'deletedCollections': {'collectionID'},
    'version': {'schema', 'version'},
    'libraries': {'libraryID', 'version'},
    'itemAnnotations': {'itemID', 'parentItemID'},
    'itemTypeFields': {'itemTypeID', 'fieldID'},
    'baseFieldMappings': {'itemTypeID', 'baseFieldID', 'fieldID'},
    'itemTypeCreatorTypes': {'itemTypeID', 'creatorTypeID', 'primaryField'},
    'creatorTypes': {'creatorTypeID', 'creatorType'},
    'syncedSettings': {'setting', 'libraryID', 'value'},
    'savedSearches': {'savedSearchID', 'savedSearchName', 'libraryID', 'key'},
    'savedSearchConditions': {'savedSearchID', 'condition', 'operator', 'value'},
    'deletedSearches': {'savedSearchID'},
    'settings': {'setting', 'key', 'value'},
}

TYPES_NON_FICHES = {'note', 'attachment', 'annotation'}
MODE_IMPORTE, MODE_IMPORTE_URL, MODE_LIE, MODE_LIEN = 0, 1, 2, 3
CLE_VALIDE = re.compile(r'^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$')
DATES_HORS_BASE = {'date', 'filingDate'}  # champs de date rangés en base sous la forme « 2020-00-00 2020 »


class SchemaInconnu(Exception):
    pass


@dataclass
class Compte:
    """Compte zotero.org que synchronise la base locale. Zotero le retient à la première synchronisation
    (`Zotero.Users.setCurrentUserID`, table `settings`, `setting = 'account'`), le garde même si l'on délie le
    compte, et refuse ensuite d'en synchroniser un autre sans vider la base. `id` None : jamais synchronisée."""
    id: int | None = None
    nom: str = ''


@dataclass
class Collection:
    id: int
    cle: str
    nom: str
    parent: int | None
    synced: bool


@dataclass
class PieceJointe:
    id: int
    cle: str
    parent: int | None
    mode: int
    type_contenu: str
    chemin: str
    fichier: Path | None  # emplacement sur le disque, None si on ne sait pas le résoudre
    version: int = 0  # version de l'élément reçue du serveur, 0 s'il n'a jamais été synchronisé
    note: bool = False  # la pièce jointe porte une note à elle, rangée par Zotero dans `itemNotes` (D206)


@dataclass
class Element:
    id: int
    cle: str
    type: str
    ajout: str
    synced: bool
    champs: dict[str, str] = field(default_factory=dict)
    createurs: list[tuple[str, str]] = field(default_factory=list)  # (nom, prénom)
    roles: list[str] = field(default_factory=list)  # rôle de chaque créateur (author, editor, translator…)
    collections: set[int] = field(default_factory=set)
    tags: list[tuple[str, int]] = field(default_factory=list)  # (nom, type), type 1 = automatique

    @property
    def titre(self) -> str:
        return self.champs.get('title', '')

    @property
    def auteur(self) -> str:
        """Nom du premier auteur. À défaut, celui du premier créateur (directeur d'un ouvrage collectif, par
        exemple). Le directeur d'un ouvrage est souvent saisi avant l'auteur du chapitre."""
        for (nom, _), role in zip(self.createurs, self.roles):
            if role == 'author':
                return nom
        return self.createurs[0][0] if self.createurs else ''

    @property
    def est_fiche(self) -> bool:
        return self.type not in TYPES_NON_FICHES


@dataclass
class Bibliotheque:
    version_schema: int
    elements: dict[int, Element]
    collections: dict[int, Collection]
    pieces: dict[int, PieceJointe]
    notes: dict[int, int | None]  # note -> parent
    cles_invalides: list[str]  # corbeille comprise, elles bloquent la synchronisation
    annotations: dict[int, int] = field(default_factory=dict)  # pièce jointe -> nombre d'annotations faites dans Zotero
    version: int = 0  # dernière version de la bibliothèque reçue du serveur par la synchronisation
    # Réglages synchronisés de la bibliothèque (modèle de renommage `attachmentRenameTemplate`, D148), décodés.
    reglages: dict[str, object] = field(default_factory=dict)
    # Rôle principal de chaque type de fiche (author, artist…), qui fait le premier créateur de Zotero.
    createur_principal: dict[str, str] = field(default_factory=dict)
    # Pour chaque type, champ propre de chaque champ de base (case : title -> caseName), comme getField de Zotero.
    champs_de_base: dict[str, dict[str, str]] = field(default_factory=dict)
    annotation_de: dict[int, int] = field(default_factory=dict)  # annotation -> pièce jointe
    couleurs: list[tuple[str, str]] = field(default_factory=list)  # tags colorés (nom, couleur), ordre du sélecteur
    # Conditions sur un tag des recherches enregistrées : (nom de la recherche, opérateur, valeur).
    recherches_tags: list[tuple[str, str, str]] = field(default_factory=list)
    recherches: dict[str, str] = field(default_factory=dict)  # clé -> nom des recherches enregistrées
    tags_corbeille: dict[str, int] = field(default_factory=dict)  # tag -> éléments de la corbeille qui le portent
    # Champs que connaît cette version de Zotero (`citationKey` n'existe que depuis Zotero 7, D145).
    champs_connus: set[str] = field(default_factory=set)
    compte: Compte = field(default_factory=Compte)  # compte zotero.org synchronisé, celui que la clé doit viser

    def par_cle(self) -> dict[str, Element]:
        return {e.cle: e for e in self.elements.values()}

    def enfants(self) -> dict[str, list[str]]:
        """Clés des pièces jointes et notes de chaque fiche, et des annotations de chaque pièce jointe (D182)."""
        res: dict[str, list[str]] = {}
        liens = [(p.cle, p.parent) for p in self.pieces.values()]
        liens += [(self.elements[n].cle, parent) for n, parent in self.notes.items() if n in self.elements]
        liens += [(self.elements[a].cle, piece) for a, piece in self.annotation_de.items() if a in self.elements]
        for cle, parent in liens:
            if parent in self.elements:
                res.setdefault(self.elements[parent].cle, []).append(cle)
        return res

    @property
    def fiches(self) -> list[Element]:
        """Références, sans les notes, pièces jointes et annotations."""
        return [e for e in self.elements.values() if e.est_fiche]

    def chemin(self, id_col: int) -> str:
        c = self.collections[id_col]
        return (self.chemin(c.parent) + '/' if c.parent else '') + c.nom

    def profondeur(self, id_col: int) -> int:
        c = self.collections[id_col]
        return 1 if not c.parent else 1 + self.profondeur(c.parent)

    def racine(self, id_col: int) -> int:
        c = self.collections[id_col]
        return id_col if not c.parent else self.racine(c.parent)


def verifier_schema(db: sqlite3.Connection) -> int:
    manques = []
    for table, colonnes in SCHEMA.items():
        presentes = {r[1] for r in db.execute(f'pragma table_info("{table}")')}
        if not presentes:
            manques.append(table)
        else:
            manques += [f'{table}.{c}' for c in sorted(colonnes - presentes)]
    if manques:
        raise SchemaInconnu('Schéma de Zotero non reconnu, éléments absents : ' + ', '.join(manques)
                            + '. Mettre zot-clean à jour, ou signaler la version de Zotero dans une issue.')
    ligne = db.execute("select version from version where schema = 'userdata'").fetchone()
    return int(ligne[0]) if ligne else 0


def _etat(*fichiers: Path) -> tuple:
    return tuple((s.st_size, s.st_mtime_ns) if (s := _stat(f)) else None for f in fichiers)


def _stat(f: Path):
    try:
        return f.stat()
    except FileNotFoundError:
        return None


def copier(base: Path, destination: Path) -> Path:
    """Copie la base et son journal `-wal`. Zotero ouvert peut écrire entre les deux copies, ou ranger le journal
    dans la base, et la copie perdrait alors les derniers changements sans erreur. Si l'un des deux fichiers a
    changé pendant la copie, elle est refaite (D185)."""
    return _copier(base, destination)[0]


def _copier(base: Path, destination: Path) -> tuple[Path, tuple]:
    """Comme `copier`, avec l'état des fichiers copiés (taille et date de la base et du journal)."""
    if not base.is_file():
        raise FileNotFoundError(f'Base Zotero introuvable : {base}')
    copie = destination / base.name
    wal, copie_wal = base.with_name(base.name + '-wal'), copie.with_name(copie.name + '-wal')
    for essai in range(COPIES):
        if essai:
            time.sleep(PAUSE)
        avant = _etat(base, wal)
        shutil.copy2(base, copie)
        copie_wal.unlink(missing_ok=True)
        if wal.is_file():
            shutil.copy2(wal, copie_wal)
        if _etat(base, wal) == avant:
            return copie, avant
    raise SystemExit('Zotero écrit dans sa base pendant la lecture (synchronisation en cours ?). Attendre la fin '
                     'de la synchronisation, puis relancer la commande.')


# Copies partagées pendant un bloc `partager()` : dossier temporaire, et pour chaque base, sa copie et l'état des
# fichiers copiés. None hors d'un tel bloc.
_partage: dict | None = None


@contextmanager
def partager():
    """Les lectures faites dans ce bloc (`lire`, `lire_types`, `etat_synchronisation`, `compte_synchronise`) se
    partagent une seule copie de la base, au lieu d'en faire une chacune. Une base de 1 à 2 Go était copiée trois
    ou quatre fois par commande. La copie est refaite dès que la base ou son journal ont changé depuis, comme si
    chaque lecture copiait la base, et effacée à la fin du bloc."""
    global _partage
    if _partage is not None:  # bloc déjà ouvert plus haut
        yield
        return
    with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
        _partage = {'dossier': Path(tmp), 'copies': {}}
        try:
            yield
        finally:
            _partage = None


@contextmanager
def _ouvrir(base: Path):
    """Connexion à une copie de `base`, partagée dans un bloc `partager()`, propre à cette lecture sinon."""
    if _partage is None:
        with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
            db = sqlite3.connect(copier(base, Path(tmp)))
            try:
                yield db
            finally:
                db.close()
        return
    copies = _partage['copies']
    cle = base.resolve()
    if cle not in copies:
        (dossier := _partage['dossier'] / str(len(copies))).mkdir()
        copies[cle] = _copier(base, dossier)
    elif copies[cle][1] != _etat(base, base.with_name(base.name + '-wal')):  # Zotero a écrit depuis la copie
        copies[cle] = _copier(base, copies[cle][0].parent)
    db = sqlite3.connect(copies[cle][0])
    try:
        yield db
    finally:
        db.close()


def lire(base: Path, bibliotheque: int = BIBLIOTHEQUE_PERSO) -> Bibliotheque:
    """Lit une bibliothèque (la personnelle par défaut) depuis une copie temporaire de `base`."""
    with _ouvrir(base) as db:
        return _lire(db, bibliotheque, base.parent / 'storage')


def _lire(db: sqlite3.Connection, lib: int, stockage: Path) -> Bibliotheque:
    version = verifier_schema(db)
    elements, versions = {}, {}
    for iid, cle, typ, ajout, synced, v in db.execute(
            'select i.itemID, i.key, t.typeName, i.dateAdded, i.synced, i.version from items i join itemTypes t '
            'using(itemTypeID) where i.libraryID = ? and i.itemID not in (select itemID from deletedItems)', (lib,)):
        elements[iid] = Element(iid, cle, typ, ajout, bool(synced))
        versions[iid] = int(v or 0)
    for iid, nom, val in db.execute(
            'select d.itemID, f.fieldName, v.value from itemData d join fields f using(fieldID) '
            'join itemDataValues v using(valueID)'):
        if iid in elements:
            elements[iid].champs[nom] = str(val)
    for iid, nom, prenom, role in db.execute(
            'select ic.itemID, c.lastName, c.firstName, ct.creatorType from itemCreators ic join creators c '
            'using(creatorID) left join creatorTypes ct using(creatorTypeID) order by ic.itemID, ic.orderIndex'):
        if iid in elements:
            elements[iid].createurs.append((nom or '', prenom or ''))
            elements[iid].roles.append(role or '')
    for iid, nom, typ in db.execute('select it.itemID, t.name, it.type from itemTags it join tags t using(tagID)'):
        if iid in elements:
            elements[iid].tags.append((nom, typ))
    collections = {cid: Collection(cid, cle, nom, parent, bool(synced)) for cid, cle, nom, parent, synced in db.execute(
        'select collectionID, key, collectionName, parentCollectionID, synced from collections where libraryID = ? '
        'and collectionID not in (select collectionID from deletedCollections)',
        (lib,))}
    for cid, iid in db.execute('select collectionID, itemID from collectionItems'):
        if cid in collections and iid in elements:
            elements[iid].collections.add(cid)
    pieces = {}
    for iid, parent, mode, typ, chemin in db.execute(
            'select itemID, parentItemID, linkMode, contentType, path from itemAttachments'):
        if iid in elements:
            pieces[iid] = PieceJointe(iid, elements[iid].cle, parent, mode, typ or '', chemin or '',
                                      _fichier(elements[iid].cle, mode, chemin or '', stockage), versions[iid])
    # Zotero range aussi dans `itemNotes`, sans parent, la note propre d'une pièce jointe (D206). Seules les vraies
    # notes vont dans `notes`, et une pièce jointe notée le retient.
    notes = {}
    for iid, parent, texte in db.execute('select itemID, parentItemID, note from itemNotes'):
        if iid in pieces:
            pieces[iid].note = note_non_vide(texte)
        elif iid in elements and elements[iid].type == 'note':
            notes[iid] = parent
    invalides = [k for (k,) in db.execute('select key from items where libraryID = ?', (lib,))
                 if not CLE_VALIDE.match(k)]
    annotations: dict[int, int] = {}
    annotation_de: dict[int, int] = {}
    for iid, parent in db.execute('select itemID, parentItemID from itemAnnotations'):
        if parent in pieces:
            annotations[parent] = annotations.get(parent, 0) + 1
            if iid in elements:
                annotation_de[iid] = parent
    ligne = db.execute('select version from libraries where libraryID = ?', (lib,)).fetchone()
    reglages = {}
    for nom, valeur in db.execute('select setting, value from syncedSettings where libraryID = ?', (lib,)):
        try:
            reglages[nom] = json.loads(valeur)
        except (TypeError, ValueError):
            reglages[nom] = valeur
    principal = dict(db.execute(
        'select t.typeName, c.creatorType from itemTypeCreatorTypes i join itemTypes t using(itemTypeID) '
        'join creatorTypes c using(creatorTypeID) where i.primaryField = 1'))
    de_base: dict[str, dict[str, str]] = {}
    for typ, base, propre in db.execute(
            'select t.typeName, fb.fieldName, fp.fieldName from baseFieldMappings m join itemTypes t '
            'using(itemTypeID) join fields fb on fb.fieldID = m.baseFieldID join fields fp on fp.fieldID = m.fieldID'):
        de_base.setdefault(typ, {})[base] = propre
    b = Bibliotheque(version, elements, collections, pieces, notes, invalides, annotations,
                     int(ligne[0]) if ligne else 0, reglages, principal, de_base, annotation_de)
    b.couleurs = _couleurs(reglages.get('tagColors'))
    b.recherches_tags = [(nom, op or '', val or '') for nom, op, val in db.execute(
        "select s.savedSearchName, c.operator, c.value from savedSearchConditions c join savedSearches s "
        "using(savedSearchID) where s.libraryID = ? and c.condition = 'tag' "
        "and s.savedSearchID not in (select savedSearchID from deletedSearches) order by s.savedSearchName", (lib,))]
    for nom, n in db.execute(
            'select t.name, count(distinct it.itemID) from itemTags it join tags t using(tagID) join items i '
            'using(itemID) where i.libraryID = ? and it.itemID in (select itemID from deletedItems) group by t.name',
            (lib,)):
        b.tags_corbeille[nom] = n
    b.recherches = dict(db.execute('select key, savedSearchName from savedSearches where libraryID = ? and '
                                   'savedSearchID not in (select savedSearchID from deletedSearches)', (lib,)))
    b.champs_connus = {nom for (nom,) in db.execute('select fieldName from fields')}
    b.compte = _compte(db)
    cacher_avec_la_corbeille(b)
    return b


def note_non_vide(texte) -> bool:
    """Une note sans texte reste enveloppée par Zotero dans `<div class="zotero-note znv1"></div>`."""
    return bool(re.sub(r'<[^>]*>|&nbsp;|\s', '', texte or ''))


def cacher_avec_la_corbeille(b: Bibliotheque) -> None:
    """Retire ce que Zotero cache avec un parent à la corbeille (D186) : pièces jointes et notes d'une fiche,
    annotations d'une pièce jointe, sous-collections d'une collection. Leurs tags comptent avec ceux de la corbeille,
    puisque supprimer un tag par l'API l'y retire aussi."""
    def retirer(iid: int) -> None:
        e = b.elements.pop(iid)
        for nom, _ in e.tags:
            b.tags_corbeille[nom] = b.tags_corbeille.get(nom, 0) + 1
        b.pieces.pop(iid, None)
        b.notes.pop(iid, None)
        b.annotations.pop(iid, None)
        if (piece := b.annotation_de.pop(iid, None)) is not None and b.annotations.get(piece):
            b.annotations[piece] -= 1

    for iid in [i for i, p in b.pieces.items() if p.parent is not None and p.parent not in b.elements]:
        retirer(iid)
    for iid in [i for i, parent in b.notes.items() if parent is not None and parent not in b.elements]:
        retirer(iid)
    for iid in [a for a, piece in b.annotation_de.items() if piece not in b.pieces]:
        retirer(iid)
    for piece in [p for p in b.annotations if p not in b.pieces]:
        del b.annotations[piece]
    while orphelines := [c for c, col in b.collections.items()
                         if col.parent is not None and col.parent not in b.collections]:
        for c in orphelines:
            del b.collections[c]
            for e in b.elements.values():
                e.collections.discard(c)


def multipart(v: str) -> bool:
    """Date sous la forme de la base de Zotero (« 2020-00-00 2020 »), et non une date et heure SQL."""
    if re.fullmatch(r'-?[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01]) ([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?', v):
        return False
    return bool(re.match(r'[0-9]{4}-(0[0-9]|1[0-2])-(0[0-9]|[12][0-9]|3[01]) ', v))


def date_multipart(v: str) -> str:
    """Date écrite par l'API mise sous la forme de la base de Zotero (« 2020-00-00 2020 »), pour l'année."""
    if not v or multipart(v):
        return v
    if m := re.match(r'(\d{4})-(\d{1,2})(?:-(\d{1,2}))?\b', v):
        return f'{m.group(1)}-{m.group(2).zfill(2)}-{(m.group(3) or "0").zfill(2)} {v}'
    if m := re.search(r'(?<!\d)(\d{4})(?!\d)', v):
        return f'{m.group(1)}-00-00 {v}'
    return v


MODES_API = {'imported_file': MODE_IMPORTE, 'imported_url': MODE_IMPORTE_URL, 'linked_file': MODE_LIE,
             'linked_url': MODE_LIEN, 'embedded_image': 4}


def reporter(b: Bibliotheque, ch, stockage: Path) -> None:
    """Reporte sur `b`, lue sur une copie locale en retard, les changements que le serveur a reçus depuis (D171),
    tels que `ecriture.Client.changements` les rend. `b` devient l'état du serveur, comme si Zotero avait
    synchronisé. Un objet nouveau reçoit un identifiant négatif, inconnu de la base locale."""
    ids_col = {c.cle: cid for cid, c in b.collections.items()}
    ids = {e.cle: iid for iid, e in b.elements.items()}
    nouveaux = (-n for n in range(1, 10 ** 9))

    def retirer_collection(cle: str) -> None:
        """Avec ses sous-collections, que Zotero met à la corbeille avec elle."""
        if (cid := ids_col.pop(cle, None)) is None:
            return
        del b.collections[cid]
        for e in b.elements.values():
            e.collections.discard(cid)
        for sous in [c.cle for c in b.collections.values() if c.parent == cid]:
            retirer_collection(sous)

    def retirer_element(cle: str) -> None:
        if (iid := ids.pop(cle, None)) is None:
            return
        e = b.elements.pop(iid)
        b.pieces.pop(iid, None)
        b.notes.pop(iid, None)
        if (piece := b.annotation_de.pop(iid, None)) is not None and b.annotations.get(piece):
            b.annotations[piece] -= 1
        return e

    for cle in ch.collections_supprimees:
        retirer_collection(cle)
    parents = {}
    for d in ch.collections:
        if d.get('deleted'):
            retirer_collection(d['key'])
            continue
        cid = ids_col.setdefault(d['key'], next(nouveaux))
        b.collections[cid] = Collection(cid, d['key'], d.get('name', ''), None, True)
        parents[cid] = d.get('parentCollection') or None
    for cid, parent in parents.items():
        b.collections[cid].parent = ids_col.get(parent, 0) if parent else None  # 0 : parent à la corbeille

    for cle in ch.elements_supprimes:
        retirer_element(cle)
    recus = []
    for d in ch.elements:
        if d.get('deleted'):
            if e := retirer_element(d['key']):
                for nom, _ in e.tags:
                    b.tags_corbeille[nom] = b.tags_corbeille.get(nom, 0) + 1
            continue
        iid = ids.setdefault(d['key'], next(nouveaux))
        ancien = b.elements.get(iid)
        e = Element(iid, d['key'], d['itemType'], ancien.ajout if ancien else
                    str(d.get('dateAdded', '')).replace('T', ' ').rstrip('Z'), True)
        dates = DATES_HORS_BASE | {b.champs_de_base.get(e.type, {}).get('date', 'date')}
        e.champs = {k: date_multipart(str(v)) if k in dates else str(v) for k, v in d.items()
                    if k in b.champs_connus and v not in ('', None)}
        for c in d.get('creators') or []:
            e.createurs.append((c.get('lastName', c.get('name', '')), c.get('firstName', '')))
            e.roles.append(c.get('creatorType', ''))
        e.tags = [(t['tag'], int(t.get('type', 0))) for t in d.get('tags') or []]
        e.collections = {ids_col[k] for k in d.get('collections') or [] if k in ids_col}
        b.elements[iid] = e
        recus.append((iid, d))
    for iid, d in recus:
        parent = ids.get(d.get('parentItem') or '')
        if d.get('parentItem') and parent is None:  # parent à la corbeille ou supprimé : caché avec lui (D186)
            for nom, _ in retirer_element(d['key']).tags:
                b.tags_corbeille[nom] = b.tags_corbeille.get(nom, 0) + 1
            continue
        if d['itemType'] == 'attachment':
            mode = MODES_API.get(d.get('linkMode', ''), -1)
            if mode in (MODE_IMPORTE, MODE_IMPORTE_URL):
                chemin = f"storage:{d['filename']}" if d.get('filename') else ''
            else:
                chemin = d.get('path') or ''
            b.pieces[iid] = PieceJointe(iid, d['key'], parent, mode, d.get('contentType') or '', chemin,
                                        _fichier(d['key'], mode, chemin, stockage), int(d.get('version') or 0),
                                        note_non_vide(d.get('note')))
        elif d['itemType'] == 'note':
            b.notes[iid] = parent
        elif d['itemType'] == 'annotation' and parent is not None and b.annotation_de.get(iid) != parent:
            if (ancienne := b.annotation_de.get(iid)) is not None and b.annotations.get(ancienne):
                b.annotations[ancienne] -= 1
            b.annotation_de[iid] = parent
            b.annotations[parent] = b.annotations.get(parent, 0) + 1

    for nom in ch.reglages_supprimes:
        b.reglages.pop(nom, None)
    for nom, valeur in ch.reglages.items():
        b.reglages[nom] = valeur
    b.couleurs = _couleurs(b.reglages.get('tagColors'))
    for cle in ch.recherches_supprimees:
        _retirer_recherche(b, cle)
    for d in ch.recherches:
        _retirer_recherche(b, d['key'])
        if not d.get('deleted'):
            b.recherches[d['key']] = d.get('name', '')
            b.recherches_tags += [(d.get('name', ''), c.get('operator', ''), c.get('value', ''))
                                  for c in d.get('conditions') or [] if c.get('condition') == 'tag']
    b.recherches_tags.sort(key=lambda r: r[0])
    cacher_avec_la_corbeille(b)
    b.version = max(b.version, ch.version)


def _retirer_recherche(b: Bibliotheque, cle: str) -> None:
    if (nom := b.recherches.pop(cle, None)) is not None:
        b.recherches_tags = [r for r in b.recherches_tags if r[0] != nom]


def _couleurs(valeur) -> list[tuple[str, str]]:
    """Tags colorés, réglage synchronisé `tagColors` (liste ordonnée de {name, color}, 9 au plus)."""
    if not isinstance(valeur, list):
        return []
    return [(str(c['name']), str(c.get('color', ''))) for c in valeur if isinstance(c, dict) and c.get('name')]


@dataclass
class Types:
    """Champs et rôles admis par chaque type de fiche, et champs de base (D85)."""
    champs: dict[str, set[str]]
    base: dict[str, dict[str, str]]  # type -> {champ propre : champ de base}, par exemple bookTitle -> publicationTitle
    roles: dict[str, set[str]]

    def equivalent(self, champ: str, de: str, vers: str) -> str | None:
        """Champ du type `vers` qui correspond à `champ` du type `de`, ou None."""
        commun = self.base.get(de, {}).get(champ, champ)
        if commun in self.champs.get(vers, set()):
            return commun
        return next((propre for propre, b in self.base.get(vers, {}).items() if b == commun), None)


def lire_types(base: Path) -> Types:
    with _ouvrir(base) as db:
        verifier_schema(db)
        champs: dict[str, set[str]] = {}
        for typ, champ in db.execute('select t.typeName, f.fieldName from itemTypeFields i '
                                     'join itemTypes t using(itemTypeID) join fields f using(fieldID)'):
            champs.setdefault(typ, set()).add(champ)
        bases: dict[str, dict[str, str]] = {}
        for typ, b, propre in db.execute(
                'select t.typeName, fb.fieldName, fp.fieldName from baseFieldMappings m join itemTypes t '
                'using(itemTypeID) join fields fb on fb.fieldID = m.baseFieldID '
                'join fields fp on fp.fieldID = m.fieldID'):
            bases.setdefault(typ, {})[propre] = b
        roles: dict[str, set[str]] = {}
        for typ, role in db.execute('select t.typeName, c.creatorType from itemTypeCreatorTypes i '
                                    'join itemTypes t using(itemTypeID) join creatorTypes c using(creatorTypeID)'):
            roles.setdefault(typ, set()).add(role)
        return Types(champs, bases, roles)


def etat_synchronisation(base: Path, bibliotheque: int = BIBLIOTHEQUE_PERSO) -> tuple[list[str], int, int]:
    """Clés invalides (corbeille comprise), nombre d'éléments et collections pas encore synchronisés hors
    annotations, et nombre d'annotations pas encore synchronisées (souvent bloquées, sans effet sur les fiches)."""
    with _ouvrir(base) as db:
        verifier_schema(db)
        invalides = [k for (k,) in db.execute('select key from items where libraryID = ?', (bibliotheque,))
                     if not CLE_VALIDE.match(k)]
        annotations = db.execute(
            "select count(*) from items i join itemTypes t using(itemTypeID) where i.libraryID = ? "
            "and i.synced = 0 and t.typeName = 'annotation'", (bibliotheque,)).fetchone()[0]
        non_sync = sum(db.execute(f'select count(*) from {t} where libraryID = ? and synced = 0',
                                  (bibliotheque,)).fetchone()[0] for t in ('items', 'collections'))
        return invalides, non_sync - annotations, annotations


def compte_synchronise(base: Path) -> Compte:
    """Compte zotero.org que synchronise la base, pour une commande qui ne lit pas toute la bibliothèque."""
    with _ouvrir(base) as db:
        verifier_schema(db)
        return _compte(db)


def _compte(db: sqlite3.Connection) -> Compte:
    reglages = dict(db.execute("select key, value from settings where setting = 'account'"))
    try:
        ident = int(reglages.get('userID') or 0)
    except (TypeError, ValueError):
        ident = 0
    return Compte(ident or None, str(reglages.get('username') or ''))


def version_bibliotheque(base: Path, bibliotheque: int = BIBLIOTHEQUE_PERSO) -> int:
    """Version de synchronisation de la bibliothèque, lue sur `base` ouverte en lecture seule.

    À n'appeler que sur une copie (sauvegarde), jamais sur la base de Zotero."""
    db = sqlite3.connect(f'{base.as_uri()}?mode=ro', uri=True)
    try:
        ligne = db.execute('select version from libraries where libraryID = ?', (bibliotheque,)).fetchone()
        return int(ligne[0]) if ligne else 0
    finally:
        db.close()


def _fichier(cle: str, mode: int, chemin: str, stockage: Path) -> Path | None:
    if mode in (MODE_IMPORTE, MODE_IMPORTE_URL) and chemin.startswith('storage:'):
        return stockage / cle / chemin[len('storage:'):]
    if mode == MODE_LIE and chemin and not chemin.startswith('attachments:'):
        return Path(chemin)
    # Fichiers liés relatifs au dossier de base des pièces jointes : réglage de Zotero non lu ici.
    return None
