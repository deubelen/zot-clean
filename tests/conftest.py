"""Bibliothèque Zotero synthétique pour les tests (D29).

`zotero` fournit un dossier Zotero factice (base créée à partir du schéma réel,
dossier `storage/`) et des méthodes pour y ajouter collections, fiches, pièces
jointes et notes. Aucune donnée personnelle.
"""

import itertools
import shutil
import sqlite3
from pathlib import Path

import pytest

SCHEMA = Path(__file__).parent / 'donnees' / 'schema_zotero.sql'


@pytest.fixture(autouse=True)
def sans_time_machine(monkeypatch):
    """Les tests ne touchent jamais aux réglages de Time Machine de la machine (D159)."""
    from zot_clean import sauvegarde
    monkeypatch.setattr(sauvegarde, '_tmutil', lambda commande: None)
ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


class ZoteroFactice:
    def __init__(self, dossier: Path, modele: Path):
        self.dossier = dossier
        dossier.mkdir(parents=True)
        self.base = dossier / 'zotero.sqlite'
        # Copie d'une base vide construite une fois par session : recréer le schéma à chaque test coûte
        # plusieurs secondes sous Windows, qui synchronise le disque après chaque instruction.
        shutil.copyfile(modele, self.base)
        self.db = sqlite3.connect(self.base)
        self._ids = itertools.count(1)
        self.compte(4242)  # celui du faux serveur, `FauxServeur().utilisateur`

    def _cle(self, n: int) -> str:
        cle = ''
        for _ in range(8):
            n, r = divmod(n, len(ALPHABET))
            cle = ALPHABET[r] + cle
        return cle

    def _type(self, nom: str) -> int:
        return self.db.execute('select itemTypeID from itemTypes where typeName = ?', (nom,)).fetchone()[0]

    def _element(self, type_: str, cle: str | None = None, synced: bool = True, lib: int = 1,
                 ajout: str = '2026-01-01') -> tuple[int, str]:
        iid = next(self._ids)
        cle = cle or self._cle(iid)
        self.db.execute('insert into items (itemID, itemTypeID, libraryID, key, synced, dateAdded) '
                        'values (?, ?, ?, ?, ?, ?)', (iid, self._type(type_), lib, cle, int(synced), ajout))
        return iid, cle

    def _champs(self, iid: int, champs: dict[str, str]) -> None:
        for nom, valeur in champs.items():
            if valeur:
                fid = self.db.execute('select fieldID from fields where fieldName = ?', (nom,)).fetchone()[0]
                # Chaque valeur n'est stockée qu'une fois, partagée entre les fiches.
                ligne = self.db.execute('select valueID from itemDataValues where value = ?', (valeur,)).fetchone()
                vid = ligne[0] if ligne else next(self._ids)
                if not ligne:
                    self.db.execute('insert into itemDataValues (valueID, value) values (?, ?)', (vid, valeur))
                self.db.execute('insert into itemData values (?, ?, ?)', (iid, fid, vid))

    def collection(self, nom: str, parent: int | None = None, cle: str | None = None) -> int:
        cid = next(self._ids)
        self.db.execute('insert into collections (collectionID, collectionName, parentCollectionID, libraryID, key, synced) '
                        'values (?, ?, ?, 1, ?, 1)', (cid, nom, parent, cle or self._cle(cid)))
        return cid

    def fiche(self, titre: str, type_: str = 'journalArticle', auteurs: tuple[str, ...] = ('Durand',),
              date: str = '2020', collections: tuple[int, ...] = (), tags: tuple[tuple[str, int] | str, ...] = (),
              editeurs: tuple[str, ...] = (), createurs: tuple[tuple[str, str, str], ...] = (), **champs) -> int:
        """`date` est stockée telle quelle : une année seule devient une date multipart, comme dans Zotero.
        `createurs` : (nom, prénom, rôle) ajoutés après les directeurs et les auteurs."""
        iid, _ = self._element(type_, champs.pop('cle', None), champs.pop('synced', True), champs.pop('lib', 1),
                               champs.pop('ajout', '2026-01-01'))
        if date and len(date) == 4 and date.isdigit():
            date = f'{date}-00-00 {date}'
        self._champs(iid, dict(champs, title=titre, date=date))
        # Directeurs d'ouvrage saisis avant les auteurs, comme le fait souvent Zotero pour un chapitre.
        liste = [(n, 'A.', 'editor') for n in editeurs] + [(n, 'A.', 'author') for n in auteurs] + list(createurs)
        for i, (nom, prenom, role) in enumerate(liste):
            cid = next(self._ids)
            rid = self.db.execute('select creatorTypeID from creatorTypes where creatorType = ?', (role,)).fetchone()[0]
            self.db.execute('insert into creators (creatorID, firstName, lastName) values (?, ?, ?)', (cid, prenom, nom))
            self.db.execute('insert into itemCreators (itemID, creatorID, creatorTypeID, orderIndex) values (?, ?, ?, ?)',
                            (iid, cid, rid, i))
        for col in collections:
            self.db.execute('insert into collectionItems (collectionID, itemID) values (?, ?)', (col, iid))
        self.tags(iid, tags)
        return iid

    def tags(self, iid: int, tags) -> None:
        """Pose des tags, chacun un nom (manuel) ou un couple (nom, type), 1 pour automatique."""
        for tag in tags:
            nom, typ = (tag, 0) if isinstance(tag, str) else tag
            ligne = self.db.execute('select tagID from tags where name = ?', (nom,)).fetchone()
            tid = ligne[0] if ligne else next(self._ids)
            if not ligne:
                self.db.execute('insert into tags (tagID, name) values (?, ?)', (tid, nom))
            self.db.execute('insert into itemTags values (?, ?, ?)', (iid, tid, typ))

    def couleur(self, nom: str, couleur: str = '#990000') -> None:
        """Tag coloré, ajouté à la fin du réglage synchronisé `tagColors`."""
        import json
        ligne = self.db.execute("select value from syncedSettings where setting = 'tagColors' and libraryID = 1").fetchone()
        valeur = json.loads(ligne[0]) if ligne else []
        valeur.append({'name': nom, 'color': couleur})
        self.reglage('tagColors', valeur)

    def recherche(self, nom: str, tag: str, operateur: str = 'is') -> int:
        """Recherche enregistrée avec une condition sur un tag."""
        sid = next(self._ids)
        self.db.execute('insert into savedSearches (savedSearchID, savedSearchName, libraryID, key) values (?, ?, 1, ?)',
                        (sid, nom, self._cle(sid)))
        self.db.execute('insert into savedSearchConditions (savedSearchID, searchConditionID, condition, operator, value) '
                        "values (?, 0, 'tag', ?, ?)", (sid, operateur, tag))
        return sid

    def pdf(self, parent: int, nom: str, contenu: bytes | None = b'%PDF-1.4 factice', cle: str | None = None,
            ajout: str = '2026-01-01', type_contenu: str = 'application/pdf', mode: int = 0, url: str = '',
            titre: str = '', autres: tuple[str, ...] = (), tags=(), note: str = '') -> int:
        """Pièce jointe importée (`mode` 0), importée depuis une URL (1), liée (2) ou lien (3). `contenu=None` :
        fichier absent du disque. `autres` : autres fichiers posés dans son dossier `storage/<CLÉ>/`. `note` : note
        propre de la pièce jointe, que Zotero range dans `itemNotes` sans parent, enveloppée comme toute note."""
        iid, cle = self._element('attachment', cle, ajout=ajout)
        self.tags(iid, tags)
        self.db.execute('insert into itemNotes (itemID, parentItemID, note) values (?, null, ?)',
                        (iid, f'<div class="zotero-note znv1">{note}</div>'))
        chemin = f'/Documents/{nom}' if mode == 2 else ('' if mode == 3 else f'storage:{nom}')
        self.db.execute('insert into itemAttachments (itemID, parentItemID, linkMode, contentType, path) '
                        'values (?, ?, ?, ?, ?)', (iid, parent, mode, type_contenu, chemin))
        self._champs(iid, {'url': url, 'title': titre})
        if mode in (0, 1) and (contenu is not None or autres):
            (self.dossier / 'storage' / cle).mkdir(parents=True)
            if contenu is not None:
                (self.dossier / 'storage' / cle / nom).write_bytes(contenu)
            for autre in autres:
                (self.dossier / 'storage' / cle / autre).write_bytes(b'autre')
        return iid

    def reglage(self, nom: str, valeur) -> None:
        """Réglage synchronisé de la bibliothèque (`syncedSettings`), stocké en JSON comme le fait Zotero."""
        import json
        self.db.execute('insert or replace into syncedSettings (setting, libraryID, value, version, synced) '
                        'values (?, 1, ?, 0, 1)', (nom, json.dumps(valeur)))

    def annotation(self, piece: int, tags=(), cle: str | None = None) -> int:
        iid, _ = self._element('annotation', cle)
        self.tags(iid, tags)
        self.db.execute('insert into itemAnnotations (itemID, parentItemID, type, sortIndex, position, isExternal) '
                        "values (?, ?, 1, '0', '{}', 0)", (iid, piece))
        return iid

    def note(self, parent: int | None = None, tags=(), cle: str | None = None) -> int:
        iid, _ = self._element('note', cle)
        self.tags(iid, tags)
        self.db.execute('insert into itemNotes (itemID, parentItemID, note) values (?, ?, ?)', (iid, parent, 'Note'))
        return iid

    def corbeille(self, iid: int):
        self.db.execute('insert into deletedItems (itemID) values (?)', (iid,))

    def synchroniser(self, version: int) -> None:
        """Version de la bibliothèque reçue du serveur, comme après une synchronisation."""
        self.db.execute('insert or replace into libraries (libraryID, type, editable, filesEditable, version) '
                        "values (1, 'user', 1, 1, ?)", (version,))

    def compte(self, utilisateur: int | None, nom: str = 'durand') -> None:
        """Compte zotero.org synchronisé par la base, comme Zotero le retient à la première synchronisation
        (`settings`, `setting = 'account'`). None : base jamais synchronisée."""
        self.db.execute("delete from settings where setting = 'account' and key in ('userID', 'username')")
        if utilisateur is not None:
            self.db.executemany("insert into settings values ('account', ?, ?)",
                                [('userID', utilisateur), ('username', nom)])

    def enregistrer(self) -> Path:
        self.db.commit()
        return self.base


@pytest.fixture(scope='session')
def base_vide(tmp_path_factory) -> Path:
    chemin = tmp_path_factory.mktemp('modele') / 'zotero.sqlite'
    db = sqlite3.connect(chemin)
    db.executescript('begin;' + SCHEMA.read_text(encoding='utf-8') + 'commit;')
    db.close()
    return chemin


@pytest.fixture
def zotero(tmp_path, base_vide):
    z = ZoteroFactice(tmp_path / 'Zotero', base_vide)
    yield z
    z.db.close()


@pytest.fixture(autouse=True)
def sans_profil_reel(monkeypatch):
    """Aucun test ne lit le profil de Zotero de la machine. Better BibTeX est alors cherché dans le dossier de
    données (repli de D145), sauf quand un test fournit ses propres profils."""
    from zot_clean import bbt
    monkeypatch.setattr(bbt, 'dossiers_profils', lambda: [])
