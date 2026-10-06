"""Noms des fichiers d'après les métadonnées de leur fiche (étape 8, D147 à D150).

Zotero fait foi (D148). Le modèle est le réglage synchronisé `attachmentRenameTemplate`
de la bibliothèque, à défaut le modèle par défaut de Zotero. Le calcul reproduit au
caractère près `Zotero.Attachments.getFileBaseNameFromItem` (Zotero 10.0.5,
`xpcom/attachments.js`), le moteur de `modules/templates.mjs`, le premier créateur
(`firstCreator`, calculé en SQL par `xpcom/data/items.js`) et le nettoyage du nom
(`Zotero.Utilities.cleanTags`, puis `Zotero.File.getValidFileName`). Les chaînes de
JavaScript comptent en unités UTF-16, d'où les troncatures faites ici sur cette mesure.

Le moteur couvre les variables (créateurs, `firstCreator`, `year`, `itemType`,
`attachmentTitle`, `accessDate`, tout champ de fiche) et les paramètres `truncate`,
`start`, `prefix`, `suffix`, `case`, `max`, `name`, `namePartSeparator`, `join`,
`initialize`, `initializeWith`. Un modèle avec conditions (`if`), expressions régulières
(`match`, `replaceFrom`), `case="title"`, `localize` ou `timeZone` lève
`ModeleNonPrisEnCharge` : `planifier` refuse alors et renvoie au renommage par Zotero lui-même.

Seule la pièce jointe principale d'une fiche est renommée, choisie comme
`Zotero.Item.getBestAttachments` (D150).

`planifier` prépare le plan de l'étape 8 : une opération `filename` par pièce
jointe principale en retard, que le serveur accepte pour un fichier importé et
que chaque Zotero applique au disque à sa synchronisation suivante (D147, D161).
`pour_le_tri` calcule la même opération pour le tri de l'Inbox, sur les
métadonnées d'après son plan (D149).
"""

import dataclasses
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from zot_clean import bbt, filtre
from zot_clean.lecture import (DATES_HORS_BASE, MODE_IMPORTE, MODE_IMPORTE_URL, MODE_LIE, MODE_LIEN, Bibliotheque,
                               Element, PieceJointe, date_multipart, multipart as _multipart)
from zot_clean.plans import Groupe, Operation, Plan

MODELE_PAR_DEFAUT = '{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}'
# Préférence `autoRenameFiles.fileTypes` par défaut de Zotero. Les fichiers liés ne sont pas renommés par défaut.
TYPES_RENOMMES = ('application/pdf', 'application/epub+zip')
# `general.etAl`, identique en français, en anglais et dans la plupart des langues de Zotero.
ET_AL = 'et al.'
# Extension tirée du type de contenu quand le nom du fichier n'en a pas (`Zotero.MIME.getPrimaryExtension`).
EXTENSIONS = {'application/pdf': 'pdf', 'application/epub+zip': 'epub', 'text/html': 'html'}
# Champs de date propres à Zotero hors champs de base `date` (`globalSchemaMeta.fields`).
LONGUEUR_CHEMIN_MAX = 250  # chemin complet, sous la limite historique de 260 caractères de Windows
OCTETS_NOM_MAX = 255  # au-delà, Zotero raccourcit le nom au téléchargement (`createShortened`)
NOMS_RESERVES = ({'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {f'COM{i}' for i in '123456789¹²³'}
                 | {f'LPT{i}' for i in '123456789¹²³'})

# Espaces retirés par `String.prototype.trim` et reconnus par `\s` en JavaScript.
_ESPACES_JS = '\t\n\x0b\x0c\r \xa0            ' \
              '    　﻿'
_ESPACE_JS = f'[{_ESPACES_JS}]'
_CONDITIONS = {'if', 'elseif', 'else', 'endif'}
_PARAMETRES_REFUSES = {'match': 'expression régulière (match)', 'replaceFrom': 'remplacement (replaceFrom)',
                       'replaceTo': 'remplacement (replaceTo)'}


class ModeleNonPrisEnCharge(Exception):
    """Le modèle de Zotero sort du sous-ensemble que `zc` sait calculer."""


class NomIncalculable(Exception):
    """Le nom d'une fiche ne peut pas être calculé (conjonction inconnue, expression rejetée par Zotero)."""


class ConjonctionInconnue(NomIncalculable):
    pass


# Moteur de modèles (`modules/templates.mjs`)

def _scanner(texte: str, guillemets_racine: bool = False):
    """Port de `scanTemplateStructure` : (type, début, fin, profondeur)."""
    profondeur, debut_texte, i = 0, 0, 0
    while i < len(texte):
        c = texte[i]
        if (guillemets_racine or profondeur > 0) and c in '"\'':
            if i > debut_texte:
                yield 'texte', debut_texte, i, profondeur
            fin = texte.find(c, i + 1)
            fin = len(texte) if fin == -1 else fin + 1
            yield 'chaine', i, fin, profondeur
            i = debut_texte = fin
        elif texte.startswith('{{', i):
            if i > debut_texte:
                yield 'texte', debut_texte, i, profondeur
            yield 'ouvre', i, i + 2, profondeur
            profondeur += 1
            i = debut_texte = i + 2
        elif texte.startswith('}}', i):
            if i > debut_texte:
                yield 'texte', debut_texte, i, profondeur
            profondeur -= 1
            yield 'ferme', i, i + 2, profondeur
            i = debut_texte = i + 2
        else:
            i += 1
    if len(texte) > debut_texte:
        yield 'texte', debut_texte, len(texte), profondeur


def _morceaux(texte: str) -> list[str]:
    """Port de `parseTemplateBrackets` : texte et instructions `{{ … }}` en alternance."""
    res, debut = [], 0
    for typ, d, f, prof in _scanner(texte):
        if typ == 'ouvre' and prof == 0:
            res.append(texte[debut:d])
            debut = d
        elif typ == 'ferme' and prof == 0:
            res.append(texte[debut:f])
            debut = f
    if debut < len(texte):
        res.append(texte[debut:])
    return res


def _litteral(instruction: str) -> str | None:
    """Port de `parseStringLiteral`."""
    instruction = _trim(instruction)
    if not instruction or instruction[0] not in '"\'':
        return None
    q = instruction[0]
    m = re.fullmatch(f'{q}([^{q}]*){q}', instruction)
    return m.group(1) if m else None


def _camel(nom: str) -> str:
    return re.sub(r'-(.)', lambda m: m.group(1).upper(), nom)


def _attributs(morceau: str) -> dict[str, str]:
    """Port de `getAttributes`, sur l'instruction entière comme le fait Zotero."""
    return {_camel(m.group(1)): m.group(2) if m.group(2) is not None else m.group(3)
            for m in re.finditer(r'([\w-]*) *=+ *(?:"([^"]*)"|\'([^\']*)\')', morceau, re.ASCII)}


def _operateur(morceau: str) -> str:
    interieur = _trim(morceau[2:-2])
    return re.split(_ESPACE_JS + '+', interieur, maxsplit=1)[0]


def modele_valide(texte: str) -> bool:
    """Port de `isTemplateValid` : accolades appariées et conditions équilibrées."""
    profondeur, debut, niveaux = 0, 0, []
    for typ, d, _, _ in _scanner(texte):
        if typ == 'ouvre':
            if profondeur == 0:
                debut = d
            profondeur += 1
        elif typ == 'ferme':
            if profondeur == 0:
                return False
            profondeur -= 1
            if profondeur > 0:
                continue
            instruction = _trim(texte[debut + 2:d])
            op = re.split(_ESPACE_JS + '+', instruction, maxsplit=1)[0]
            if op == 'if':
                niveaux.append(False)
            elif op in ('elseif', 'else'):
                if not niveaux or niveaux[-1]:
                    return False
                if op == 'else':
                    niveaux[-1] = True
            elif op == 'endif':
                if not niveaux:
                    return False
                niveaux.pop()
            elif instruction[:1] in ('"', "'") and _litteral(instruction) is None:
                return False
    return profondeur == 0 and not niveaux


def normaliser_modele(texte: str) -> str:
    """Port de `normalizeRenameTemplate`."""
    return _trim(re.sub(r'\r?\n|\r', '', texte))


@dataclass(frozen=True)
class Modele:
    texte: str

    @classmethod
    def analyser(cls, texte: str) -> 'Modele':
        """Vérifie que le modèle reste dans le sous-ensemble calculé ici, sinon lève `ModeleNonPrisEnCharge`."""
        texte = normaliser_modele(texte)
        if not modele_valide(texte):
            raise ModeleNonPrisEnCharge('modèle mal formé, que Zotero remplace par son modèle par défaut')
        for morceau in _morceaux(texte):
            if not morceau.startswith('{{'):
                continue
            if _litteral(morceau[2:-2]) is not None:
                continue
            op = _operateur(morceau)
            if op in _CONDITIONS:
                raise ModeleNonPrisEnCharge(f'condition « {op} »')
            attrs = _attributs(morceau)
            for nom, motif in _PARAMETRES_REFUSES.items():
                if attrs.get(nom):
                    raise ModeleNonPrisEnCharge(motif)
            if attrs.get('case') == 'title':
                raise ModeleNonPrisEnCharge('casse de titre (case="title")')
            if _camel(op) == 'itemType' and attrs.get('localize'):
                raise ModeleNonPrisEnCharge('type de fiche traduit (localize)')
            if _camel(op) == 'accessDate' and attrs.get('timeZone'):
                raise ModeleNonPrisEnCharge('fuseau horaire (timeZone)')
        return cls(texte)


def modele_de(b: Bibliotheque) -> str:
    """Modèle réglé dans Zotero, comme `getAttachmentRenameTemplate` : le modèle par défaut s'il manque,
    s'il est vide ou mal formé."""
    texte = b.reglages.get('attachmentRenameTemplate')
    normal = normaliser_modele(texte) if isinstance(texte, str) else ''
    if not normal or not modele_valide(normal):
        return MODELE_PAR_DEFAUT
    return texte


# Chaînes à la manière de JavaScript

def _trim(s: str) -> str:
    return s.strip(_ESPACES_JS)


def _sous_chaine(s: str, debut: int, fin: int | None = None) -> str:
    """`String.prototype.substring` en unités UTF-16. Un caractère coupé en deux laisse une demi-paire,
    retirée ensuite par le nettoyage, comme dans Zotero."""
    unites = s.encode('utf-16-le', 'surrogatepass')
    n = len(unites) // 2
    debut = max(0, min(debut, n))
    fin = n if fin is None else max(0, min(fin, n))
    debut, fin = min(debut, fin), max(debut, fin)
    return unites[2 * debut:2 * fin].decode('utf-16-le', 'surrogatepass')


def _entier(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def nettoyer(nom: str) -> str:
    """Port de `cleanTags` puis `getValidFileName` (sans `skipXML`)."""
    nom = re.sub(r'<br[^>]*>', '\n', nom, flags=re.IGNORECASE)
    nom = re.sub(r'</p>', '\n\n', nom, flags=re.IGNORECASE)
    nom = re.sub(r'<[^>]+>', '', nom)
    nom = re.sub(r'[/\\?*:|"<>]', '', nom)
    nom = re.sub(r'[\r\n\t]+', ' ', nom)
    nom = re.sub('[ - ]', ' ', nom)
    nom = re.sub('[​-‎]', '', nom)
    nom = re.sub('[  ]', ' ', nom)
    # Sans le drapeau u, la classe [\ud800-\udfff] de Zotero retire les deux moitiés de tout caractère hors du
    # plan de base (emoji, idéogrammes rares) : ici, les demi-paires et les caractères au-delà de U+FFFF.
    nom = re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿\U00010000-\U0010ffff]', '', nom)
    nom = unicodedata.normalize('NFC', nom)
    nom = re.sub('[⁨⁩]', '', nom)
    nom = re.sub(r'^\.', '', nom)
    if nom in ('', '.', '..'):
        nom = '_'
    return nom


def _casse(v: str, casse: str) -> str:
    if casse == 'upper':
        return v.upper()
    if casse == 'lower':
        return v.lower()
    if casse == 'sentence':
        return v[:1].upper() + v[1:]
    if casse == 'hyphen':
        v = re.sub(_ESPACE_JS + '+-', '-', v)
        v = re.sub('-' + _ESPACE_JS + '+', '-', v)
        return re.sub(_ESPACE_JS + '+', '-', v.lower())
    if casse == 'snake':
        v = re.sub(_ESPACE_JS + '+_', '_', v)
        v = re.sub('_' + _ESPACE_JS + '+', '_', v)
        return re.sub(_ESPACE_JS + '+', '_', v.lower())
    if casse in ('camel', 'pascal'):
        # [^\p{L}\d]+(.) avec le drapeau u : une suite de caractères qui ne sont ni lettres ni chiffres ASCII.
        v = re.sub(r'(?:(?![0-9])[\W\d_])+([^\n\r  ])', lambda m: m.group(1).upper(), v.lower())
        return v[:1].upper() + v[1:] if casse == 'pascal' else v
    return v


# Fiche vue par le modèle

@dataclass
class Regles:
    """Ce que le calcul tire de la base de Zotero et de sa langue."""
    createur_principal: dict[str, str]
    champs_de_base: dict[str, dict[str, str]]
    conjonction: str | None = None  # texte entre deux noms (« A et B »), None si inconnu

    @classmethod
    def de(cls, b: Bibliotheque, conjonction: str | None = None) -> 'Regles':
        return cls(b.createur_principal, b.champs_de_base, conjonction)

    def champ(self, fiche: Element, nom: str, brut: bool = False) -> str:
        """`item.getField(nom, brut, true)` : champ propre du type pour un champ de base, date multipart lisible."""
        propre = self.champs_de_base.get(fiche.type, {}).get(nom, nom)
        v = fiche.champs.get(propre, '')
        if not brut and v and (propre in DATES_HORS_BASE or nom == 'date'
                               or self.champs_de_base.get(fiche.type, {}).get('date') == propre):
            if _multipart(v):
                v = v[11:]
        return v

    def createurs(self, fiche: Element, quels: str) -> list[tuple[str, str]]:
        """(nom, prénom) des créateurs d'une famille, dans l'ordre de la fiche."""
        if quels == 'authors':
            roles = {self.createur_principal.get(fiche.type)}
        elif quels == 'editors':
            roles = {'editor', 'seriesEditor'}
        else:
            return list(fiche.createurs)
        return [c for c, r in zip(fiche.createurs, fiche.roles) if r in roles]

    def premier_createur(self, fiche: Element) -> str:
        """`firstCreator` : rôle principal, à défaut directeurs d'ouvrage, réalisateurs, contributeurs."""
        for role in (self.createur_principal.get(fiche.type), 'editor', 'director', 'contributor'):
            noms = [c[0] for c, r in zip(fiche.createurs, fiche.roles) if r == role]
            if len(noms) == 1:
                return noms[0]
            if len(noms) == 2:
                if self.conjonction is None:
                    raise ConjonctionInconnue('conjonction de deux auteurs inconnue (réglage `conjonction`)')
                return noms[0] + self.conjonction + noms[1]
            if len(noms) >= 3:
                return f'{noms[0]} {ET_AL}'
        return ''

    def annee(self, fiche: Element) -> str:
        v = self.champ(fiche, 'date', brut=True)
        if not v:
            return ''
        sql = v[:10] if _multipart(v) else '0000-00-00'
        return '' if sql[:4] == '0000' else sql[:4]


def _nom_createur(c: tuple[str, str], forme: str, separateur: str, initiale: str, avec: str) -> str:
    nom, prenom = c

    def ini(v: str, oui: bool) -> str:
        return v[:1].upper() + avec if oui else v

    if forme in ('full', 'given-family', 'first-last'):
        return ini(prenom, initiale in ('full', 'given', 'first')) + separateur + ini(nom, initiale in ('full', 'family', 'last'))
    if forme in ('full-reversed', 'family-given', 'last-first'):
        return ini(nom, initiale in ('full', 'family', 'last')) + separateur + ini(prenom, initiale in ('full', 'given', 'first'))
    if forme in ('given', 'first'):
        return ini(prenom, initiale in ('full', 'given', 'first'))
    return ini(nom, initiale in ('full', 'family', 'last'))


def _tranche(liste: list, maximum) -> list:
    """`getSlicedCreatorsOfType` : `max` arrive en texte, "0" ne coupe donc rien, un négatif part de la fin."""
    if maximum is None:
        return liste
    n = _entier(maximum)
    if n is None or n == 0:
        return liste
    return liste[:n] if n > 0 else list(reversed(liste[n:]))


class _Rendu:
    """Un calcul de nom, avec l'état partagé entre les deux passes de Zotero."""

    def __init__(self, fiche: Element, regles: Regles, titre_piece: str):
        self.fiche, self.regles, self.titre_piece = fiche, regles, titre_piece
        self.morceaux_affixes: list[tuple[str, str, str, str]] = []  # (valeur, brute, suffixe, préfixe)
        self.proteges: list[str] = []

    def commun(self, v: str, a: dict[str, str]) -> str:
        if not v:
            return ''
        prefixe, suffixe = a.get('prefix', ''), a.get('suffix', '')
        prefixe = '' if prefixe in ('\\', '/') else prefixe
        suffixe = '' if suffixe in ('\\', '/') else suffixe
        if self.proteges:
            v = _sub_js('(' + '|'.join(self.proteges) + ')', lambda m: '\\' + m.group(1) + '//', v)
        if (debut := a.get('start')):
            v = _sous_chaine(v, _entier(debut) or 0)
        if (longueur := a.get('truncate')):
            v = _sous_chaine(v, 0, _entier(longueur) or 0)
        v = _trim(v)
        brute, affixe = v, False
        if prefixe and not v.startswith(prefixe):
            v, affixe = prefixe + v, True
        if suffixe and not v.endswith(suffixe):
            v, affixe = v + suffixe, True
        if affixe:
            self.morceaux_affixes.append((v, brute, suffixe, prefixe))
        return _casse(v, a.get('case', ''))

    def variable(self, ident: str, a: dict[str, str]) -> str:
        f, r = self.fiche, self.regles
        ident = _camel(ident)
        familles = ('authors', 'editors', 'creators')
        if ident in familles:
            noms = [_nom_createur(c, a.get('name', 'family'), a.get('namePartSeparator', ' '),
                                  a.get('initialize', ''), a.get('initializeWith', '.'))
                    for c in _tranche(r.createurs(f, ident), a.get('max'))]
            return self.commun(a.get('join', ', ').join(noms), a)
        if ident.endswith('Count') and ident[:-5] in familles:
            return self.commun(str(len(r.createurs(f, ident[:-5]))), a)
        if ident == 'firstCreator':
            return self.commun(r.premier_createur(f), a)
        if ident == 'year':
            return self.commun(r.annee(f), a)
        if ident == 'itemType':
            return self.commun(f.type, a)
        if ident == 'attachmentTitle':
            return self.commun(self.titre_piece, a)
        if ident == 'accessDate':
            return self.commun(f.champs.get('accessDate', ''), a)
        # Tout autre nom est un champ de fiche, vide s'il n'existe pas pour ce type ou pas du tout.
        return self.commun(r.champ(f, ident), a)

    def generer(self, modele: str) -> str:
        """Port de `generateHTMLFromTemplate`, sans les conditions refusées par `Modele.analyser`."""
        html = ''
        for morceau in _morceaux(modele):
            if not morceau.startswith('{{'):
                html += morceau
                continue
            op = _operateur(morceau)
            if op in _CONDITIONS:
                raise ModeleNonPrisEnCharge(f'condition « {op} »')
            litteral = _litteral(morceau[2:-2])
            if litteral is not None:
                html += litteral
            elif op:
                html += self.variable(op, _attributs(morceau))
        return html


def _sub_js(motif: str, remplacement, texte: str) -> str:
    """Expression bâtie par Zotero sans échappement : si JavaScript la refuse, Zotero échoue aussi."""
    try:
        return re.sub(motif, remplacement, texte)
    except re.error as e:
        raise NomIncalculable(f'expression rejetée ({e})') from e


def nom_de_base(fiche: Element, modele: Modele, regles: Regles, titre_piece: str = '') -> str:
    """Nom sans extension que Zotero donne au fichier principal de `fiche` (`getFileBaseNameFromItem`)."""
    texte = modele.texte
    rendu = _Rendu(fiche, regles, titre_piece)
    resultat = rendu.generer(texte)
    # Seconde passe de Zotero : un suffixe ou un préfixe qui se répéterait n'est écrit qu'une fois.
    paires: dict[str, str] = {}
    for _, brute, suffixe, prefixe in rendu.morceaux_affixes:
        if suffixe and f'{brute}{suffixe}{suffixe}' in resultat:
            cle = f'{brute}{suffixe}{suffixe}'
            if cle not in rendu.proteges:
                rendu.proteges.append(cle)
            paires[cle] = f'{brute}{suffixe}'
        if prefixe and f'{prefixe}{prefixe}{brute}' in resultat:
            cle = f'{prefixe}{prefixe}{brute}'
            if cle not in rendu.proteges:
                rendu.proteges.append(cle)
            paires[cle] = f'{prefixe}{brute}'
    if rendu.proteges:
        texte = _sub_js('(' + '|'.join(rendu.proteges) + ')', lambda m: '\\' + m.group(1) + '//', texte)
    resultat = rendu.generer(texte)
    if paires:
        motif = '(' + '|'.join(f'(?<!\\\\){p}(?!//)' for p in paires) + ')'
        resultat = _sub_js(motif, lambda m: paires.get(m.group(0), 'undefined'), resultat)
    return nettoyer(resultat)


# Pièces jointes

def nom_actuel(p: PieceJointe) -> str:
    """`attachmentFilename` : le nom du fichier tel que la fiche le porte."""
    chemin = p.chemin
    for prefixe in ('storage:', 'attachments:'):
        if chemin.startswith(prefixe):
            chemin = chemin[len(prefixe):]
            break
    return re.split(r'[/\\]', chemin)[-1]


def present(p: PieceJointe) -> bool:
    return p.fichier is not None and p.fichier.is_file()


def extension(p: PieceJointe) -> str:
    """Comme Zotero : l'extension du fichier présent si elle en a l'air, sinon celle du type de contenu,
    et pour un fichier absent l'extension du nom enregistré."""
    nom = nom_actuel(p)
    if present(p):
        ext = nom.rsplit('.', 1)[1] if '.' in nom else ''
        return ext if re.fullmatch(r'[A-Za-z0-9_]{1,10}', ext) else EXTENSIONS.get(p.type_contenu, '')
    m = re.search(r'\.([^.]+)$', nom)
    return m.group(1) if m else ''


def nom_attendu(fiche: Element, p: PieceJointe, b: Bibliotheque, modele: Modele, regles: Regles) -> str:
    """Nom complet, extension comprise, que Zotero donnerait à la pièce jointe `p` de `fiche`."""
    titre = b.elements[p.id].titre if p.id in b.elements else ''
    base = nom_de_base(fiche, modele, regles, titre)
    ext = extension(p)
    return base + ('.' + ext if ext else '')


def pieces_de(b: Bibliotheque, fiche: Element) -> list[PieceJointe]:
    """Pièces jointes de la fiche dans l'ordre de `getBestAttachments` : PDF d'abord, puis celle dont l'URL est
    celle de la fiche (puis une autre URL, puis aucune), puis la plus ancienne. Hors liens et hors corbeille."""
    return ordonner(b, fiche, [p for p in b.pieces.values() if p.parent == fiche.id and p.mode != MODE_LIEN
                               and p.id in b.elements])


def ordonner(b: Bibliotheque, fiche: Element, pieces: list[PieceJointe]) -> list[PieceJointe]:
    """`pieces` dans l'ordre de `getBestAttachments` pour `fiche`."""
    url = fiche.champs.get('url', '')

    def rang(p: PieceJointe):
        e = b.elements[p.id]
        u = e.champs.get('url')
        rang_url = 2 if not u else (0 if u == url else 1)
        return (p.type_contenu != 'application/pdf', rang_url, e.ajout, p.id)

    return sorted(pieces, key=rang)


def piece_principale(b: Bibliotheque, fiche: Element) -> PieceJointe | None:
    """Celle que Zotero ouvre d'un double clic et renomme (`getBestAttachment`)."""
    pieces = pieces_de(b, fiche)
    return pieces[0] if pieces else None


def renommable(p: PieceJointe, lies: bool = False) -> bool:
    """`shouldAutoRenameAttachment` avec les réglages par défaut : PDF ou EPUB, importé (lié si `lies`),
    jamais un instantané de page web."""
    if p.mode == MODE_LIE and not lies:
        return False
    if p.mode not in (MODE_IMPORTE, MODE_IMPORTE_URL, MODE_LIE):
        return False
    if p.mode == MODE_IMPORTE_URL and p.type_contenu == 'text/html':
        return False
    return any(p.type_contenu.startswith(t) for t in TYPES_RENOMMES)


def principales(b: Bibliotheque, lies: bool = False):
    """(fiche, pièce principale) des fiches dont Zotero renommerait le fichier principal."""
    for fiche in b.fiches:
        p = piece_principale(b, fiche)
        if p is not None and renommable(p, lies):
            yield fiche, p


# Conjonction (D150)

def deduire_conjonction(b: Bibliotheque, modele: Modele) -> tuple[str | None, int]:
    """Conjonction la plus fréquente dans les noms des fichiers principaux de fiches à deux créateurs que Zotero
    a nommés d'après `modele`, et nombre de noms qui la portent."""
    regles = Regles.de(b)
    votes: Counter = Counter()
    for fiche, p in principales(b):
        noms = None
        for role in (regles.createur_principal.get(fiche.type), 'editor', 'director', 'contributor'):
            trouves = [c[0] for c, r in zip(fiche.createurs, fiche.roles) if r == role]
            if trouves:
                noms = trouves
                break
        if not noms or len(noms) != 2 or not noms[0] or not noms[1]:
            continue
        actuel = unicodedata.normalize('NFC', nom_actuel(p))
        a, z = (unicodedata.normalize('NFC', n) for n in noms)
        i = actuel.find(z, len(a)) if actuel.startswith(a) else -1
        if i <= len(a) or i - len(a) > 12:
            continue
        candidate = actuel[len(a):i]
        regles.conjonction = candidate
        try:
            if nom_attendu(fiche, p, b, modele, regles) == nom_actuel(p):
                votes[candidate] += 1
        except NomIncalculable:
            pass
    if not votes:
        return None, 0
    return votes.most_common(1)[0]


# Mot « et » de Zotero dans les langues courantes, pour une bibliothèque dont aucun nom ne trahit la conjonction.
CONJONCTIONS = {'fr': ' et ', 'en': ' and ', 'de': ' und ', 'es': ' y ', 'it': ' e ', 'pt': ' e ', 'nl': ' en '}


def conjonction(b: Bibliotheque, cfg, modele: Modele) -> str | None:
    """Réglage `conjonction` de `config.toml` s'il est rempli, sinon déduite des noms existants (D150), sinon de la
    langue de Zotero lue dans son profil (répétition du pilote)."""
    mot = getattr(cfg.methode, 'conjonction', '') if cfg is not None else ''
    if mot:
        return mot if mot != mot.strip() else f' {mot} '
    deduite = deduire_conjonction(b, modele)[0]
    if deduite is None and getattr(cfg, 'dossier_zotero', None):
        return CONJONCTIONS.get(bbt.langue_zotero(cfg.dossier_zotero))
    return deduite


# Cas écartés (D150)

def motif_ecarte(p: PieceJointe, nouveau: str) -> str | None:
    """Raison de ne pas donner `nouveau` à `p`, ou None. Zotero ne corrige pas ces noms, et `zc` ne les
    corrige pas à sa manière : ils sont listés pour un réglage à la main."""
    if p.fichier is not None:
        dossier = p.fichier.parent
        ancien = unicodedata.normalize('NFC', nom_actuel(p))
        cible = unicodedata.normalize('NFC', nouveau).casefold()
        if dossier.is_dir():
            for f in dossier.iterdir():
                n = unicodedata.normalize('NFC', f.name)
                if n != ancien and n.casefold() == cible:
                    return 'nom déjà pris dans le dossier de la pièce jointe'
    if nouveau.endswith(('.', ' ')):
        return 'nom terminé par un point ou une espace, refusé par Windows'
    if nouveau.split('.')[0].rstrip(' ').upper() in NOMS_RESERVES:
        return 'nom réservé de Windows'
    if len(nouveau.encode('utf-8')) > OCTETS_NOM_MAX:
        return f'nom de plus de {OCTETS_NOM_MAX} octets'
    if p.fichier is not None and len(str(p.fichier.parent / nouveau)) > LONGUEUR_CHEMIN_MAX:
        return f'chemin de plus de {LONGUEUR_CHEMIN_MAX} caractères'
    return None


def autre_fichier(p: PieceJointe) -> str | None:
    """Pour un fichier importé absent, le nom d'un autre fichier de son dossier `storage/<CLÉ>/` (renommage
    local échoué, D150), fichiers cachés de Zotero exclus."""
    if p.mode not in (MODE_IMPORTE, MODE_IMPORTE_URL) or p.fichier is None or p.fichier.is_file():
        return None
    dossier: Path = p.fichier.parent
    if not dossier.is_dir():
        return None
    autres = sorted(f.name for f in dossier.iterdir() if f.is_file() and not f.name.startswith('.'))
    return autres[0] if autres else None


# Plan de l'étape 8 (D147, D149, D150, D158)

ETAPE = 'noms'
MODES_API = ('imported_file', 'imported_url')  # fichiers que le serveur renomme, jamais un fichier lié
# Titre court donné par `setAutoAttachmentTitle` au seul fichier de son type sur la fiche. Celui d'un EPUB dépend
# de la langue de Zotero, déduite de la conjonction (D150). Langue inconnue, le titre d'un EPUB reste tel quel.
TITRES_COURTS = {'application/pdf': {None: 'PDF'},
                 'application/epub+zip': {' et ': 'Livre numérique', ' and ': 'Ebook'}}
NATURE = 'nom du fichier'
RENOMMAGE_PAR_ZOTERO = ('Renommer les fichiers par Zotero lui-même, dans ses réglages (Général, renommage des '
                        'fichiers, bouton « Renommer les fichiers… »), qui applique son modèle à toute la bibliothèque.')


class Calcul:
    """Modèle et règles de la bibliothèque, établis une fois. Lève `ModeleNonPrisEnCharge`."""

    def __init__(self, b: Bibliotheque, cfg):
        self.b = b
        self.modele = Modele.analyser(modele_de(b))
        self.regles = Regles.de(b, conjonction(b, cfg, self.modele))

    def nom(self, fiche: Element, p: PieceJointe) -> str:
        return nom_attendu(fiche, p, self.b, self.modele, self.regles)


def fiche_apres(b: Bibliotheque, fiche: Element, apres: dict) -> Element:
    """Copie de `fiche` avec le type, les champs et les créateurs qu'un plan écrit (valeurs de l'API)."""
    type_ = apres.get('itemType', fiche.type)
    dates = DATES_HORS_BASE | {b.champs_de_base.get(type_, {}).get('date', 'date')}
    champs, createurs, roles = dict(fiche.champs), list(fiche.createurs), list(fiche.roles)
    for k, v in apres.items():
        if k == 'creators':
            createurs = [(c.get('lastName', c.get('name', '')), c.get('firstName', '')) for c in v or []]
            roles = [c.get('creatorType', '') for c in v or []]
        elif k != 'itemType' and isinstance(v, str):
            if v:
                champs[k] = date_multipart(v) if k in dates else v
            else:
                champs.pop(k, None)
    return dataclasses.replace(fiche, type=type_, champs=champs, createurs=createurs, roles=roles)


def nouveau_titre(d: dict, nouveau: str, seul: bool, conj: str | None) -> str | None:
    """Titre de la pièce jointe après renommage, ou None s'il ne change pas. Comme `renameFilesFromParent` de Zotero
    pour un fichier renommé sans être sur le disque : un titre égal à l'ancien nom, avec ou sans extension et sans
    tenir compte de la casse, devient le titre court du type (« PDF ») si la pièce jointe est le seul fichier de ce
    type sur la fiche, sinon le nouveau nom sans extension (`setAutoAttachmentTitle`, D150)."""
    ancien, titre = d.get('filename') or '', (d.get('title') or '').lower()
    if not ancien or titre not in (ancien.lower(), re.sub(r'\.[^.]+$', '', ancien).lower()):
        return None
    courts = TITRES_COURTS.get(d.get('contentType', ''))
    if seul and courts is not None:
        return courts.get(None) or courts.get(conj)
    return re.sub(r'\.[^.]+$', '', nouveau) or None


def _seul_de_son_type(p: PieceJointe, pieces: list[PieceJointe]) -> bool:
    """`getFileAttachmentsWithContentType` : fichiers importés ou liés de la fiche, du même type."""
    return all(q.cle == p.cle for q in pieces if q.mode != MODE_LIEN and q.type_contenu == p.type_contenu)


def operation(calcul: Calcul, fiche: Element, p: PieceJointe, d: dict, pieces: list[PieceJointe],
              rang: int = 0) -> tuple[Operation | None, str]:
    """Opération qui donne à `p` (données `d` relues par l'API) le nom attendu pour `fiche`, ou None et la raison
    de ne pas la renommer (vide quand le nom est déjà le bon)."""
    if d.get('linkMode') not in MODES_API or d.get('deleted'):
        return None, 'pas un fichier importé sur le serveur, ou à la corbeille'
    try:
        nouveau = calcul.nom(fiche, p)
    except NomIncalculable as e:
        return None, f'nom non calculé ({e})'
    ancien = d.get('filename') or ''
    if nouveau == ancien:
        return None, ''
    if motif := motif_ecarte(p, nouveau):
        return None, motif
    avant, apres = {'filename': ancien}, {'filename': nouveau}
    titre = nouveau_titre(d, nouveau, _seul_de_son_type(p, pieces), calcul.regles.conjonction)
    if titre is not None and titre != d.get('title', ''):
        avant['title'], apres['title'] = d.get('title', ''), titre
    return Operation(p.cle, avant, apres, rang, NATURE), ''


def raison_absent(p: PieceJointe, stockage: str, en_ligne: dict[str, bool] | None) -> str:
    """Pourquoi un fichier absent du disque n'est pas renommé, vide s'il l'est (D150, D158). Seul un Zotero qui
    synchronise ses fichiers par zotero.org applique le nouveau nom en retéléchargeant un fichier qui y est stocké."""
    if stockage == bbt.WEBDAV:
        return 'absent du disque, non renommé (fichiers synchronisés par WebDAV)'
    if stockage == bbt.AUCUNE:
        return 'absent du disque, non renommé (synchronisation des fichiers désactivée dans Zotero)'
    if stockage != bbt.ZOTERO_ORG:
        return 'absent du disque, non renommé (synchronisation des fichiers inconnue, profil de Zotero introuvable)'
    if en_ligne is None:
        return 'absent du disque, non renommé faute d\'avoir vérifié sa présence sur zotero.org'
    if not en_ligne.get(p.cle):
        return 'introuvable, ni sur le disque ni sur zotero.org (point 5 de l\'audit)'
    return ''


def absents(b: Bibliotheque) -> list[str]:
    """Clés des pièces jointes principales renommables dont le fichier manque, à chercher sur zotero.org (D133)."""
    return [p.cle for _, p in principales(b) if not present(p)]


def planifier(b: Bibliotheque, cfg, client, en_ligne: dict[str, bool] | None = None,
              stockage: str | None = None) -> tuple[Plan, str]:
    """Plan d'un groupe par fiche dont le fichier principal porte un nom en retard sur ses métadonnées. Ne planifie
    que la différence entre les noms actuels et les noms attendus, et se relance donc après chaque passe (D119).
    `en_ligne` dit si un fichier absent est sur zotero.org, `stockage` comment Zotero synchronise les fichiers
    (lu dans le profil s'il n'est pas donné)."""
    from zot_clean.audit import pluriel
    try:
        calcul = Calcul(b, cfg)
    except ModeleNonPrisEnCharge as e:
        raise ModeleNonPrisEnCharge(f'Le modèle de noms réglé dans Zotero sort de ce que zot-clean sait calculer '
                                    f'({e}). {RENOMMAGE_PAR_ZOTERO}') from e
    if (serveur := client.version_serveur()) > b.version:
        from zot_clean.appliquer import copie_en_retard
        raise SystemExit(copie_en_retard(b.version, serveur))
    stockage = bbt.stockage_fichiers(cfg.dossier_zotero) if stockage is None else stockage
    masquees = filtre.cles_masquees(b, cfg)
    candidats, laisses = [], []  # laisses : (pièce jointe, nom attendu ou '', raison)
    for fiche, p in principales(b):
        try:
            attendu = calcul.nom(fiche, p)
        except NomIncalculable as e:
            laisses.append((p, '', f'nom non calculé ({e})'))
            continue
        if attendu == nom_actuel(p):
            continue
        if not present(p) and (raison := raison_absent(p, stockage, en_ligne)):
            laisses.append((p, attendu, raison))
            continue
        candidats.append((fiche, p, attendu))
    donnees = client.fiches([p.cle for _, p, _ in candidats])
    retenus = []
    for fiche, p, attendu in candidats:
        if (d := donnees.get(p.cle)) is None:
            laisses.append((p, attendu, 'introuvable sur le serveur'))
            continue
        op, raison = operation(calcul, fiche, p, d, pieces_de(b, fiche))
        if op is not None:
            retenus.append((fiche, p, op))
        elif raison:
            laisses.append((p, attendu, raison))
    # Les fichiers présents d'abord : l'essai porte sur des fichiers que l'utilisateur peut ouvrir aussitôt.
    retenus.sort(key=lambda x: (not present(x[1]), unicodedata.normalize('NFC', x[0].titre).casefold(), x[0].cle))
    groupes = [Groupe(fiche.cle, filtre.MASQUE if p.cle in masquees else fiche.titre[:80], [op])
               for fiche, p, op in retenus]
    lies = sum(1 for fiche, p in principales(b, lies=True) if p.mode == MODE_LIE and _en_retard(calcul, fiche, p))
    plan = Plan(ETAPE, client.utilisateur, groupes,
                description=f"Noms des fichiers, {pluriel(len(groupes), 'fichier')} à renommer.")
    return plan, _rapport(retenus, laisses, masquees, stockage, lies, cfg.ecriture.essai, calcul)


def _en_retard(calcul: Calcul, fiche: Element, p: PieceJointe) -> bool:
    try:
        return calcul.nom(fiche, p) != nom_actuel(p)
    except NomIncalculable:
        return False


def decrire(op: Operation, masque: bool) -> str:
    """« ancien » → « nouveau », et le titre s'il change, sans rien montrer d'une fiche confidentielle (D126)."""
    if masque:
        return 'nom du fichier' + (' et titre de la pièce jointe' if 'title' in op.apres else '')
    texte = f"« {op.avant['filename']} » → « {op.apres['filename']} »"
    if 'title' in op.apres:
        texte += f", titre « {op.avant['title']} » → « {op.apres['title']} »"
    return texte


SYNCHRONISATIONS = {
    bbt.ZOTERO_ORG: 'Zotero synchronise les fichiers par zotero.org.',
    bbt.WEBDAV: 'Zotero synchronise les fichiers par WebDAV. Le nouveau nom passe par zotero.org avec les données de '
                'la pièce jointe, et Zotero renomme le fichier local à la synchronisation. Ce cas n\'a pas encore été '
                'vérifié avec un serveur WebDAV. Vérifier l\'essai avec un soin particulier, sur cet ordinateur '
                'et, s\'il y en a, sur un autre poste ou une tablette.',
    bbt.AUCUNE: 'La synchronisation des fichiers est désactivée dans Zotero. Les fichiers présents sur le disque sont '
                'renommés quand même, par la synchronisation des données.',
}


def _rapport(retenus: list, laisses: list, masquees: set[str], stockage: str, lies: int, essai: int,
             calcul: Calcul) -> str:
    from zot_clean.audit import pluriel
    titres = sum('title' in op.apres for _, _, op in retenus)
    absents_renommes = sum(not present(p) for _, p, _ in retenus)
    n = len(retenus)
    resume = (f"{n} fichier{'s' if n > 1 else ''} principa{'ux' if n > 1 else 'l'} à renommer d'après le modèle de "
              f"Zotero (`{calcul.modele.texte}`)")
    if titres:
        resume += f", dont {pluriel(titres, 'pièce jointe')} dont le titre, égal à l'ancien nom, change aussi"
    if absents_renommes:
        resume += (f", et {pluriel(absents_renommes, 'fichier')} absent{'s' if absents_renommes > 1 else ''} du "
                   'disque mais stocké' + ('s' if absents_renommes > 1 else '') + ' sur zotero.org, que Zotero '
                   'nommera au téléchargement')
    L = ['# Noms des fichiers', '', resume + '.', '',
         'Le plan change le nom enregistré dans Zotero (`filename`), sans toucher au contenu des fichiers. Chaque '
         'ordinateur renomme ses fichiers sur le disque à sa synchronisation suivante, et `zc annuler` remet les '
         'anciens noms de la même façon.']
    if stockage in SYNCHRONISATIONS:
        L += ['', SYNCHRONISATIONS[stockage]]
    if retenus:
        n = min(essai, len(retenus))
        L += ['', '## Après l\'essai', '',
              f'`zc appliquer <plan> --essai` renomme {"le premier fichier" if n == 1 else f"les {n} premiers fichiers"} '
              'de la liste (marqués « essai »). Seul Zotero renomme le fichier sur le disque, lors de sa synchronisation. '
              'Lancer donc la synchronisation de Zotero (flèche verte), puis `zc voir` sur les fiches de l\'essai. '
              'Chaque pièce jointe doit porter son nouveau nom, sans « fichier absent du disque ». Seulement ensuite, '
              '`--tout`.',
              '', '## Renommages', '']
        for i, (fiche, p, op) in enumerate(retenus):
            masque = p.cle in masquees
            L.append(f"- {p.cle} (fiche {fiche.cle}{', ' + filtre.MASQUE if masque else ''}) · {decrire(op, masque)}"
                     + ('' if present(p) else ' · absent du disque, stocké sur zotero.org')
                     + (' · essai' if i < essai else ''))
    if laisses:
        L += ['', '## Laissés de côté', '',
              'Ces fichiers ne sont pas renommés. Un nom écarté (déjà pris, refusé par Windows, trop long) se règle à '
              'la main dans Zotero, en corrigeant la fiche ou en renommant la pièce jointe.', '']
        for p, attendu, raison in laisses:
            if p.cle in masquees:
                L.append(f'- {p.cle} · {filtre.MASQUE} · {raison}')
            else:
                L.append(f'- {p.cle} · « {nom_actuel(p)} »' + (f' → « {attendu} »' if attendu else '') + f' · {raison}')
    if lies:
        L += ['', f"{pluriel(lies, 'fichier lié')} principa{'ux' if lies > 1 else 'l'} en retard, laissé"
                  f"{'s' if lies > 1 else ''} au réglage de Zotero (« Renommer les fichiers liés »), l'API ne "
                  'renommant pas les fichiers liés.']
    return '\n'.join(L) + '\n'


# Tri de l'Inbox (D149)

def pour_le_tri(b: Bibliotheque, cfg, client, vises: list[tuple[str, list[Operation], bool]],
                rang: int) -> tuple[dict[str, Operation], list[str]]:
    """Opérations `filename` du tri de l'Inbox. `vises` donne, pour chaque fiche, les opérations du plan de tri qui
    la touchent et si elle absorbe une fusion. Le nom est calculé sur les métadonnées d'après le plan, et la pièce
    jointe principale choisie parmi celles qui lui restent, venues d'une fiche absorbée comprises. Une fiche est
    retenue quand le plan change son nom attendu (créateurs, date, titre, type) ou la fusionne. Renvoie les opérations
    par clé de fiche et des remarques pour le rapport (noms laissés en retard)."""
    try:
        calcul = Calcul(b, cfg)
    except ModeleNonPrisEnCharge as e:
        return {}, [f'Noms des fichiers laissés tels quels, modèle de Zotero non pris en charge ({e}).']
    par_cle = b.par_cle()
    candidats, remarques = [], []
    for cle, ops, fusion in vises:
        fiche = par_cle.get(cle)
        if fiche is None:
            continue
        apres: dict = {}
        for op in ops:
            if op.cle == cle:
                apres |= op.apres
        nouvelle = fiche_apres(b, fiche, apres)
        corbeille = {op.cle for op in ops if op.apres.get('deleted')}
        venues = {op.cle for op in ops if op.apres.get('parentItem') == cle}
        pieces = ordonner(b, nouvelle, [p for p in b.pieces.values() if (p.parent == fiche.id or p.cle in venues)
                                        and p.id in b.elements and p.mode != MODE_LIEN and p.cle not in corbeille])
        if not pieces or not renommable(pieces[0]):
            continue
        p = pieces[0]
        try:
            if not fusion and calcul.nom(nouvelle, p) == calcul.nom(fiche, p):
                continue
        except NomIncalculable as e:
            remarques.append(f'{cle}, nom du fichier non calculé ({e}).')
            continue
        if not present(p):
            remarques.append(f'{cle}, fichier absent du disque, nom laissé à `zc noms planifier`.')
            continue
        candidats.append((cle, nouvelle, p, pieces))
    donnees = client.fiches([p.cle for _, _, p, _ in candidats]) if candidats else {}
    res = {}
    for cle, nouvelle, p, pieces in candidats:
        if (d := donnees.get(p.cle)) is None:
            continue
        op, raison = operation(calcul, nouvelle, p, d, pieces, rang)
        if op is not None:
            res[cle] = op
        elif raison:
            remarques.append(f'{cle}, nom du fichier laissé tel quel ({raison}).')
    return res, remarques
