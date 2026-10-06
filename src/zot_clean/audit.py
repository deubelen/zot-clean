"""Audit en lecture seule de la bibliothèque (D26).

Douze contrôles, chacun rendu comme une section du rapport Markdown
`rapports/audit-<date>.md`, avec ce que le nettoyage pourra y faire (D27).
Les onze premiers sont ici. Le douzième, sur le plan du fonds, et la
comparaison avec l'audit précédent sont dans `controle.py` (D139). Rien
n'est écrit dans Zotero.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from zot_clean import bbt, cles
from zot_clean.config import Config
from zot_clean.filtre import MASQUE
from zot_clean.lecture import MODE_IMPORTE, MODE_IMPORTE_URL, MODE_LIE, Bibliotheque, Element

OK, A_VOIR, INFO, NON_CONTROLE = 'OK', 'À voir', 'Info', 'Non contrôlé'
DETAILS_MAX = 100


@dataclass
class Section:
    titre: str
    statut: str
    resume: str
    details: list[str] = field(default_factory=list)
    remede: str = ''
    # Points relevés, par identifiant stable (clés, sans titres), pour comparer deux audits (D139).
    points: dict[str, str] = field(default_factory=dict)


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def annee(e: Element) -> str:
    m = re.search(r'\b(\d{4})\b', e.champs.get('date', ''))
    return m.group(1) if m else ''


def ligne(e: Element, masquees: set[str] = frozenset()) -> str:
    if e.cle in masquees:
        return f'{e.cle} · {MASQUE}'
    auteur = e.auteur or '?'
    return f"{e.cle} · {auteur} · {annee(e) or 's. d.'} · {e.titre[:80] or '(sans titre)'}"


CONTROLE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')


def ecrire_toml(chemin, lignes: list[str]) -> None:
    """Écrit un fichier de suivi. Un commentaire y recopie souvent un titre ou un nom venu de Zotero, dont un saut de
    ligne ferait de la suite une instruction TOML, voire une décision, et dont un caractère de contrôle rendrait le
    fichier illisible. Dans chaque commentaire, la suite d'un saut de ligne qui n'est pas elle-même un commentaire
    rejoint la ligne, et les caractères de contrôle deviennent des espaces (D194). Le texte est relu comme TOML,
    puis remplace l'ancien fichier d'un coup."""
    import os
    import tomllib
    propres = []
    for l in lignes:
        if not l.startswith('#'):
            propres.append(l)
            continue
        morceaux = CONTROLE.sub(' ', l).split('\n')
        propres.append(morceaux[0])
        for m in morceaux[1:]:
            if m.startswith('#') or not m.strip():
                propres.append(m)
            else:
                propres[-1] += ' ' + m.strip()
    texte = '\n'.join(propres)
    try:
        tomllib.loads(texte)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} : fichier de suivi mal formé ({e}). Signaler ce problème dans une issue.') from None
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + '.tmp')
    provisoire.write_text(texte, encoding='utf-8')
    os.replace(provisoire, chemin)


def pluriel(n: int, mot: str) -> str:
    """« 1 pièce jointe », « 2 pièces jointes », « 0 tag manuel » : chaque mot s'accorde, sauf les sigles (PDF)."""
    if n <= 1:
        return f'{n} {mot}'
    return f"{n} " + ' '.join(m if m.isupper() or m[-1] in 'sx' else m + 's' for m in mot.split())


# Noms des types de fiche tels que Zotero les affiche en français.
NOMS_TYPES = {
    'journalArticle': 'Article de revue', 'book': 'Livre', 'bookSection': 'Chapitre de livre',
    'conferencePaper': 'Article de colloque', 'document': 'Document', 'thesis': 'Thèse', 'report': 'Rapport',
    'webpage': 'Page web', 'magazineArticle': 'Article de magazine', 'newspaperArticle': 'Article de journal',
    'encyclopediaArticle': "Article d'encyclopédie", 'dictionaryEntry': 'Entrée de dictionnaire',
    'preprint': 'Prépublication', 'manuscript': 'Manuscrit', 'letter': 'Lettre', 'interview': 'Interview',
    'presentation': 'Présentation', 'blogPost': 'Billet de blog', 'forumPost': 'Message de forum',
    'film': 'Film', 'videoRecording': 'Enregistrement vidéo', 'audioRecording': 'Enregistrement audio',
    'podcast': 'Podcast', 'radioBroadcast': 'Émission de radio', 'tvBroadcast': 'Émission de télévision',
    'artwork': 'Illustration', 'map': 'Carte', 'computerProgram': 'Logiciel', 'dataset': 'Jeu de données',
    'standard': 'Norme', 'patent': 'Brevet', 'case': 'Affaire', 'statute': 'Acte juridique', 'bill': 'Projet de loi',
    'hearing': 'Audience', 'email': 'Courriel', 'instantMessage': 'Message instantané',
}


def nom_type(t: str) -> str:
    return NOMS_TYPES.get(t, t)


def est_pdf(p) -> bool:
    return p.type_contenu == 'application/pdf' or p.chemin.lower().endswith('.pdf')


def pdf_sur_disque(b: Bibliotheque):
    for p in b.pieces.values():
        if est_pdf(p) and p.fichier is not None and p.fichier.is_file():
            yield p


def pdf_absents(b: Bibliotheque, fiches: set[str] | None = None) -> list[str]:
    """Clés des PDF de fiches dont le fichier manque sur le disque, et que rien ne peut donc comparer (D168).
    `fiches` limite aux PDF de ces fiches (clés)."""
    return sorted(p.cle for p in b.pieces.values() if est_pdf(p) and p.parent in b.elements
                  and (fiches is None or b.elements[p.parent].cle in fiches)
                  and p.fichier is not None and not p.fichier.is_file())


def conseil_telechargement(stockage: str, but: str = 'les comparer') -> str:
    """Comment faire venir sur le disque les fichiers pas encore téléchargés, selon la synchronisation (D157, D168)."""
    if stockage == bbt.AUCUNE:
        return ('Zotero ne synchronise pas les fichiers et ne les téléchargera donc pas. Ces fichiers relèvent du '
                'point 5 de l\'audit (fichiers absents).')
    depuis = ' depuis le serveur WebDAV' if stockage == bbt.WEBDAV else ''
    return (f'Pour {but}, faire télécharger tous les fichiers par Zotero{depuis}, dans Réglages › '
            'Synchronisation, en réglant « Télécharger les fichiers » sur « au moment de la synchronisation », puis '
            'synchroniser et attendre la fin du téléchargement. Relancer ensuite la commande.')


def rappel_absents(b: Bibliotheque, stockage: str, suite: str = '', fiches: set[str] | None = None) -> str:
    """Avertissement des commandes qui comparent les PDF (D168), vide quand tous sont sur le disque. `suite`
    complète la phrase « non comparés »."""
    n = len(pdf_absents(b, fiches))
    if not n:
        return ''
    s = 's' if n > 1 else ''
    return (f"{pluriel(n, 'PDF')} absent{s} du disque (pas encore téléchargé{s} par Zotero ?), non comparé{s}"
            f"{suite}. " + conseil_telechargement(stockage))


# 1
def chiffres(b: Bibliotheque) -> Section:
    types = Counter(e.type for e in b.fiches)
    manuels = {n for e in b.elements.values() for n, t in e.tags if t == 0}
    autos = {n for e in b.elements.values() for n, t in e.tags if t == 1}
    details = [f'{nom_type(t)} : {n}' for t, n in types.most_common()]
    return Section('Chiffres d\'ensemble', INFO,
                   f"{pluriel(len(b.fiches), 'référence')}, {pluriel(len(b.pieces), 'pièce jointe')}, "
                   f"{pluriel(len(b.notes), 'note')}, {pluriel(len(b.collections), 'collection')}, "
                   f"{pluriel(len(manuels), 'tag manuel')} et {pluriel(len(autos), 'automatique')}.",
                   details)


# 2
def hors_collection(b: Bibliotheque, cfg: Config, masquees: set[str] = frozenset()) -> Section:
    sans = [e for e in b.fiches if not e.collections]
    inbox = [c.id for c in b.collections.values() if c.parent is None and c.nom == cfg.methode.inbox]
    n_inbox = sum(1 for e in b.fiches if inbox and inbox[0] in e.collections)
    texte = f"{pluriel(len(sans), 'référence')} dans aucune collection. "
    texte += f"{n_inbox} dans « {cfg.methode.inbox} »." if inbox else f"Pas de collection « {cfg.methode.inbox} » à la racine."
    points = {e.cle: ligne(e, masquees) for e in sans}
    return Section('Références sans collection', A_VOIR if sans else OK, texte, list(points.values()),
                   'Le rangement (étape 5) leur donnera une place dans le fonds. Ensuite, le tri des nouvelles références '
                   '(`zc inbox`) les traite au fil de l\'eau.', points)


# 3
def _doi(v: str) -> str:
    return re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', v.strip().lower())


def _isbns(v: str) -> set[str]:
    from zot_clean.sources import morceaux_isbn
    res = set()
    for c in morceaux_isbn(v):
        if len(c) == 10:
            c = '978' + c[:9]
            c += str((10 - sum(int(x) * (1 if i % 2 == 0 else 3) for i, x in enumerate(c)) % 10) % 10)
        if len(c) == 13:
            res.add(c)
    return res


def doublons(b: Bibliotheque, cfg: Config, masquees: set[str] = frozenset()) -> Section:
    from zot_clean import doublons as d
    distincts = d.distincts(d.charger_suivi(cfg))
    groupes = [g for g in d.candidats(b) if not d.deja_juge({e.cle for e in g}, distincts)]
    points = {}
    for g in sorted(groupes, key=lambda g: norm(g[0].titre)):
        # Les fiches d'un groupe se ressemblent : une seule fiche confidentielle masque tout le groupe (D126).
        cache = {e.cle for e in g} if any(e.cle in masquees for e in g) else set()
        points['/'.join(sorted(e.cle for e in g))] = ' / '.join(ligne(e, cache) for e in g)
    n = sum(len(g) for g in groupes)
    return Section('Doublons probables', A_VOIR if groupes else OK,
                   f"{pluriel(len(groupes), 'groupe')} de doublons probables ({pluriel(n, 'référence')}), "
                   f"repérés par DOI, ISBN ou titre, auteur et année (hors groupes déjà jugés distincts).",
                   list(points.values()),
                   'Le nettoyage (étape 2) les fusionnera à la manière de Zotero, en gardant notes, pièces jointes et collections.',
                   points)


# 4
def metadonnees(b: Bibliotheque, masquees: set[str] = frozenset()) -> Section:
    manques = defaultdict(list)
    for e in b.fiches:
        if not e.createurs:
            manques['sans auteur'].append(e)
        if not annee(e):
            manques['sans année'].append(e)
        if e.type == 'journalArticle' and not e.champs.get('DOI'):
            manques['article sans DOI'].append(e)
        if e.type == 'book' and not e.champs.get('ISBN'):
            manques['livre sans ISBN'].append(e)
        if e.type == 'document':
            manques['type « Document » par défaut'].append(e)
    resume = ', '.join(f'{k} {len(v)}' for k, v in manques.items()) or 'aucun manque relevé'
    points = {f'{k} · {e.cle}': f'{k} : {ligne(e, masquees)}' for k, v in manques.items() for e in v}
    graves = len(manques['sans auteur']) + len(manques['sans année']) + len(manques['type « Document » par défaut'])
    return Section('Métadonnées manquantes', A_VOIR if graves else (INFO if manques else OK), resume[0].upper() + resume[1:] + '.',
                   list(points.values()), 'Le nettoyage (étape 3) complétera ce qui peut l\'être par Crossref, '
                   'OpenAlex, BnF, Sudoc et Open Library, et listera le reste pour une correction à la main.', points)


# 5
def absents_importes(b: Bibliotheque) -> list[str]:
    """Clés des pièces jointes importées dont le fichier manque, les seules que zotero.org peut avoir (D133)."""
    return [p.cle for p in b.pieces.values() if p.mode in (MODE_IMPORTE, MODE_IMPORTE_URL)
            and p.fichier is not None and not p.fichier.is_file()]


# Phrase sur la synchronisation des fichiers et remède propre à chacune (D157).
STOCKAGES = {bbt.ZOTERO_ORG: 'Zotero synchronise les fichiers par zotero.org.',
             bbt.WEBDAV: 'Zotero synchronise les fichiers par WebDAV.',
             bbt.AUCUNE: 'La synchronisation des fichiers est désactivée dans Zotero.'}
_RETROUVER = ('Un fichier introuvable se retrouve parfois dans une ancienne sauvegarde ou sur un autre ordinateur. '
              'À défaut, la pièce jointe orpheline peut être supprimée.')
CONSEILS = {
    bbt.WEBDAV: 'Ouvrir la pièce jointe dans Zotero la retélécharge si elle est sur le serveur WebDAV. Un fichier '
                'encore sur zotero.org, reste d\'une ancienne synchronisation, se télécharge depuis la bibliothèque '
                'en ligne, Zotero ne l\'y cherche plus. ' + _RETROUVER,
    bbt.AUCUNE: 'Zotero ne synchronise pas les fichiers et ne retélécharge donc rien. Un fichier encore sur '
                'zotero.org, reste d\'une ancienne synchronisation, se télécharge depuis la bibliothèque en ligne. '
                + _RETROUVER}
CONSEIL_ZOTERO_ORG = 'Un fichier encore sur zotero.org revient quand on ouvre la pièce jointe dans Zotero, qui le ' \
                     'retélécharge. ' + _RETROUVER


def pieces_absentes(b: Bibliotheque, masquees: set[str] = frozenset(), en_ligne: dict[str, bool] | None = None,
                    motif: str = '', stockage: str = bbt.INCONNU) -> Section:
    """`en_ligne` dit, pour chaque fichier importé absent, s'il est encore sur zotero.org (D133). Sans lui
    (hors ligne, sans clé API), `motif` dit pourquoi la vérification n'a pas eu lieu. `stockage` (D157) dit où
    Zotero synchronise les fichiers, et donc ce que vaut une copie sur zotero.org."""
    ailleurs = stockage in (bbt.WEBDAV, bbt.AUCUNE)  # Zotero ne cherche plus les fichiers sur zotero.org
    recuperables, perdus, non_resolus, points = [], [], 0, {}
    for p in b.pieces.values():
        if p.mode not in (MODE_IMPORTE, MODE_IMPORTE_URL, MODE_LIE):
            continue
        if p.fichier is None:
            non_resolus += 1
        elif not p.fichier.is_file():
            parent = b.elements.get(p.parent)
            chemin = MASQUE if p.cle in masquees else p.chemin[:70]
            d = f"{p.cle} · {chemin}" + (f" (fiche {ligne(parent, masquees)})" if parent else '')
            if en_ligne is not None and en_ligne.get(p.cle):
                recuperables.append(d := d + ' · sur zotero.org')
            elif en_ligne is not None:
                perdus.append(d := d + (' · pas sur zotero.org' if stockage == bbt.WEBDAV else ' · introuvable'))
            else:
                perdus.append(d)
            points[p.cle] = d
    avec_piece = {p.parent for p in b.pieces.values()}
    sans_piece = [e for e in b.fiches if e.id not in avec_piece]
    n, r, x = len(recuperables) + len(perdus), len(recuperables), len(perdus)
    texte = f"{pluriel(n, 'fichier')} absent{'s' if n > 1 else ''} du disque"
    if en_ligne is not None and n:
        texte += (f", dont {r} encore sur zotero.org (à télécharger depuis la bibliothèque en ligne)" if ailleurs else
                  f", dont {r} encore sur zotero.org (récupérable{'s' if r > 1 else ''})")
        texte += (f" et {x} absent{'s' if x > 1 else ''} de zotero.org (peut-être sur le serveur WebDAV)"
                  if stockage == bbt.WEBDAV else f" et {x} introuvable{'s' if x > 1 else ''}")
    elif motif and n:
        texte += f" (non vérifiés sur zotero.org, {motif})"
    texte += f". {pluriel(len(sans_piece), 'référence')} sans aucune pièce jointe (information)."
    if non_resolus:
        texte += f" {non_resolus} fichiers liés relatifs au dossier de base de Zotero n'ont pas été vérifiés."
    if stockage in STOCKAGES:
        texte += ' ' + STOCKAGES[stockage]
    return Section('Fichiers absents', A_VOIR if n else OK, texte, recuperables + perdus,
                   CONSEILS.get(stockage, CONSEIL_ZOTERO_ORG), points)


# 6
def md5(chemin: Path) -> str:
    h = hashlib.md5()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(1 << 20), b''):
            h.update(bloc)
    return h.hexdigest()


def pdf_identiques(b: Bibliotheque, cfg: Config | None = None, masquees: set[str] = frozenset(),
                   stockage: str = bbt.INCONNU) -> Section:
    """Copies d'un même PDF, hors celles d'une fiche à la corbeille et les groupes jugés voulus (D125). Un PDF
    absent du disque n'est pas comparé, et sans aucun groupe trouvé le contrôle est « non contrôlé » (D168)."""
    from zot_clean import pieces as pc
    voulus = [set(e.copies) for e in pc.charger(cfg) if e.decision == pc.GARDER] if cfg else []
    parent = {p.cle: p.parent for p in b.pieces.values()}
    points, meme_fiche = {}, 0
    for copies in pc.groupes_identiques(b):
        if any(set(copies) <= v for v in voulus):
            continue
        parents = list(dict.fromkeys(parent[k] for k in copies))
        meme_fiche += len(copies) - len(parents)
        if len(parents) > 1:
            fiches = [b.elements[x] for x in parents]
            cache = {f.cle for f in fiches} if masquees & set(copies) else set()
            points['/'.join(sorted(f.cle for f in fiches))] = ' / '.join(ligne(f, cache) for f in fiches)
    differentes = list(points.values())
    absents = len(pdf_absents(b))
    texte = (f"{pluriel(len(differentes), 'PDF')} rattaché{'s' if len(differentes) > 1 else ''} à des fiches "
             f"différentes (doublons de fiches probables), {meme_fiche} copie{'s' if meme_fiche > 1 else ''} "
             f"en trop sur une même fiche.")
    remede = ('Des fiches qui partagent le même PDF sont souvent des doublons, ou l\'une porte le PDF de l\'autre. '
              'Les traiter à l\'étape 2 (`zc doublons chercher`, puis `zc pieces chercher`).')
    if absents:
        s = 's' if absents > 1 else ''
        texte += f" {pluriel(absents, 'PDF')} absent{s} du disque, non comparé{s}."
        remede = conseil_telechargement(stockage) + ' ' + remede
    statut = A_VOIR if differentes or meme_fiche else (NON_CONTROLE if absents else OK)
    return Section('PDF identiques', statut, texte, differentes, remede, points)


# 7
def tags(b: Bibliotheque, cfg: Config, automatiques: bool | None | str = '') -> Section:
    """Jeu de tags vu comme l'étape 6 le traitera (D151 à D155). Un tag porté seulement par des fiches
    confidentielles est désigné par son identifiant. `automatiques` est le réglage de Zotero qui crée les tags
    automatiques, lu dans le profil quand il n'est pas donné (None, profil introuvable)."""
    from zot_clean import tags as t
    a = t._Analyse(b, cfg)
    if automatiques == '':
        automatiques = bbt.tags_automatiques(cfg.dossier_zotero)

    def nom(n: str) -> str:
        return t.identifiant(n) if a.u[n].confidentiel else n

    autos = sorted(n for n, u in a.u.items() if 1 in u.types)
    occ_autos = sum(a.u[n].occurrences[1] for n in autos)
    manuels = {n for n, u in a.u.items() if 0 in u.types}
    formes_manuelles = {t.forme(n, cfg) for n in manuels}
    doublent = [n for n in autos if 0 not in a.u[n].types and t.forme(n, cfg) in formes_manuelles]
    variantes, _ = a.groupes()
    hors = sorted(n for n in manuels if a.hors_familles(n) and n not in a.importes)
    enfants = sorted(n for n, u in a.u.items() if u.enfants == len(u.elements))
    part = f" ({100 * len(autos) // max(1, len(a.u))} % des tags)" if autos else ''
    texte = (f"{pluriel(len(autos), 'tag automatique')}{part}, posé{'s' if len(autos) > 1 else ''} {occ_autos} fois"
             + (f", dont {len(doublent)} de même forme qu'un tag manuel" if doublent else '') + '. '
             f"{pluriel(len(variantes), 'groupe')} de variantes (casse, accents, pluriel). ")
    if a.importes:
        texte += (f"{pluriel(len(a.importes), 'tag manuel')} qui {'ont' if len(a.importes) > 1 else 'a'} l'air de "
                  f"mots-clés importés, sur {pluriel(len(a.lot), 'fiche')}. ")
    texte += f"{pluriel(len(hors), 'tag manuel')} hors des familles de la méthode (états, concepts, techniques)."
    if b.couleurs:
        texte += f" {pluriel(len(b.couleurs), 'tag coloré')} sur 9 possibles."
    if enfants:
        texte += f" {pluriel(len(enfants), 'tag')} porté{'s' if len(enfants) > 1 else ''} seulement par des pièces " \
                 'jointes, notes ou annotations.'
    if automatiques:
        texte += ' Zotero crée encore des tags automatiques à chaque ajout (réglage actif).'
    points = ({f'automatique · {nom(n)}': f'automatique : {nom(n)}' for n in autos}
              | {f'variantes · {" / ".join(v.noms)}': f'variantes : {" / ".join(v.noms)} → {v.cible}' for v in variantes}
              | {f'importé · {nom(n)}': f'mot-clé importé : {nom(n)}' for n in sorted(a.importes)}
              | {f'hors familles · {nom(n)}': f"hors familles : {nom(n)} ({len(a.u[n].fiches)})" for n in hors})
    if automatiques:
        points['réglage'] = 'réglage de Zotero « Ajouter automatiquement des tags » actif'
    details = [d for k, d in points.items() if not k.startswith(('automatique', 'importé'))]
    remede = ('L\'étape 6 du nettoyage (`zc tags inventaire`, skill `tags`) supprime les tags automatiques et les '
              'mots-clés importés par une règle globale, regroupe les variantes, ramène les états à ceux de la méthode '
              'et propose comme concepts les tags répartis sur plusieurs thèmes.')
    if automatiques:
        remede += (' Décocher dans Zotero, Réglages › Général, « Ajouter automatiquement des tags à partir des mots-clés '
                   'et des vedettes-matières », et le même réglage dans le connecteur de Zotero du navigateur.')
    statut = A_VOIR if autos or variantes or a.importes else (INFO if hors or automatiques else OK)
    return Section('Tags', statut, texte, details, remede, points)


# 8
def cles_citation(b: Bibliotheque, cfg: Config, masquees: set[str] = frozenset(),
                  etat: bbt.Etat | None = None) -> Section:
    """Clés absentes, en double (comparées comme Better BibTeX les compare) et restées dans Extra, réglages de
    Better BibTeX lus dans le profil de Zotero (D144 à D146)."""
    if not cfg.methode.cles_citation:
        return Section('Clés de citation', INFO, 'Contrôle désactivé dans la configuration.')
    etat = etat or bbt.detecter(cfg.dossier_zotero)
    reglages = etat.present and etat.source == bbt.PROFIL
    sans = [e for e in b.fiches if not e.champs.get('citationKey', '').strip()]
    doubles = cles.doubles(b, etat.casse)
    restes = cles.restes_extra(b)
    texte = (f"{bbt.decrire(etat)} {pluriel(len(sans), 'référence')} sans clé de citation, "
             f"{pluriel(len(doubles), 'clé')} en double "
             f"({'casse distinguée, comme le règle Better BibTeX' if etat.casse else 'sans tenir compte de la casse'}), "
             f"{pluriel(len(restes), 'référence')} dont Extra contient encore une ligne « Citation Key: ».")
    if reglages and not etat.formule_methode:
        texte += (f" La formule de Better BibTeX diffère de celle de la méthode (`{bbt.FORMULE_METHODE}`), ce qui "
                  "n'est pas un problème, les clés existantes ne sont jamais changées.")
    alertes = {}
    if etat.present and etat.trop_ancien:
        alertes['réglage · version'] = (f'Better BibTeX {etat.version} trop ancien, passer à Better BibTeX '
                                        f'{bbt.VERSION_MIN} et Zotero 8')
    if reglages and etat.regenere:
        alertes['réglage · resetKeyOnChange'] = (
            "Better BibTeX refait la clé d'une fiche à chaque modification (« Regenerate citation key when item "
            "changes »). Chaque étape de zc qui modifie des fiches changerait alors leur clé. Décocher ce réglage "
            "dans Zotero › Réglages › Better BibTeX")
    if reglages and etat.remplissage == 0 and sans:
        alertes['réglage · fillKeyAfter'] = (
            "Better BibTeX ne remplit pas seul les clés manquantes (« Automatically fill citation key after » à 0). "
            "Les remplir par clic droit, Better BibTeX › Fill, ou régler un délai")
    points = {f'sans clé · {e.cle}': f'sans clé : {e.cle}' for e in sans}
    for k, fiches in doubles.items():
        cles_fiches = sorted(e.cle for e in fiches)
        if masquees & set(cles_fiches):
            # La clé de citation contient le nom de l'auteur et le début du titre (D126).
            points[f"en double · {'+'.join(cles_fiches)}"] = f"en double : {MASQUE} ({', '.join(cles_fiches)})"
        else:
            points[f'en double · {k}'] = (f"en double : {fiches[0].champs['citationKey'].strip()} "
                                          f"({', '.join(e.cle for e in fiches)})")
    for e, _ in restes:
        points[f'Extra · {e.cle}'] = f'ligne « Citation Key: » dans Extra : {e.cle}'
    details = list(alertes.values()) + [d for k, d in points.items() if not k.startswith('sans clé')]
    points |= alertes
    statut = A_VOIR if doubles or restes or alertes or (etat.present and sans) else INFO if sans else OK
    if etat.present:
        remede = ("L'étape 7 du nettoyage (`zc cles planifier`, skill `cles`) départage les clés en double, la fiche "
                  "la plus ancienne gardant la sienne et les autres recevant un suffixe (a, b…), et range les lignes "
                  "« Citation Key: » d'Extra dans le champ natif. Les clés manquantes sont l'affaire de Better "
                  "BibTeX, qui les remplit seul, ou sur demande par clic droit, Better BibTeX › Fill.")
    else:
        remede = ("Sans Better BibTeX actif, l'étape 7 est sautée, sauf le départage des clés en double "
                  "(`zc cles planifier`), qui ne demande aucun calcul. Les clés ne sont utiles que pour écrire en "
                  "Markdown ou en LaTeX. Installer ou activer Better BibTeX, ou désactiver ce contrôle "
                  "(`cles_citation = false`).")
    return Section('Clés de citation', statut, texte, details, remede, points)


# 9
# Repli quand le modèle de Zotero sort du sous-ensemble calculé par `noms` : « Auteur - Année - Titre », année
# facultative puisque Zotero écrit « Auteur - Titre » pour une fiche sans date (D150).
MODELE_REPLI = re.compile(r'^.+( - \d{4})? - .+$')
REMEDE_NOMS = ('`zc noms planifier` (étape 8 du nettoyage) prépare le renommage de ces fichiers par l\'API de Zotero, '
               'chaque ordinateur renommant les siens à la synchronisation suivante. Un fichier introuvable relève du '
               'point 5. Un nom écarté (déjà pris, refusé par Windows, trop long) se règle à la main dans Zotero.')
REMEDE_NOMS_REPLI = ('`zc noms planifier` ne sait pas renommer d\'après ce modèle. Renommer les fichiers par Zotero '
                     'lui-même, dans ses réglages (Général, renommage des fichiers, bouton « Renommer les fichiers… »).')


def noms_fichiers(b: Bibliotheque, cfg: Config, masquees: set[str] = frozenset(),
                  en_ligne: dict[str, bool] | None = None, stockage: str = '') -> Section:
    """Noms attendus des fichiers principaux d'après le modèle de Zotero (D148, D150), ou expression régulière
    de repli si le modèle n'est pas pris en charge. `en_ligne` dit si un fichier absent est sur zotero.org (D133).
    Sous WebDAV ou sans synchronisation des fichiers (`stockage`, D157), un fichier absent n'est pas renommé,
    il est seulement listé (D158)."""
    from zot_clean import noms
    try:
        modele = noms.Modele.analyser(noms.modele_de(b))
    except noms.ModeleNonPrisEnCharge as e:
        return _noms_repli(b, masquees, str(e))
    regles = noms.Regles.de(b, noms.conjonction(b, cfg, modele))

    def montrer(p, nom: str) -> str:
        return MASQUE if p.cle in masquees else nom[:90]

    justes, incalculables, retards, points, principales = 0, 0, Counter(), {}, set()
    for fiche, p in noms.principales(b, lies=True):
        principales.add(p.id)
        if p.mode == MODE_LIE:
            continue
        try:
            attendu = noms.nom_attendu(fiche, p, b, modele, regles)
        except noms.NomIncalculable:
            incalculables += 1
            continue
        actuel = noms.nom_actuel(p)
        if attendu == actuel:
            justes += 1
            continue
        if noms.present(p):
            etat = 'présent'
        elif stockage in (bbt.WEBDAV, bbt.AUCUNE):
            etat = 'absent, non renommé'
        elif en_ligne is None:
            etat = 'absent du disque'
        else:
            etat = 'sur zotero.org' if en_ligne.get(p.cle) else 'introuvable'
        ecarte = noms.motif_ecarte(p, attendu) if etat not in ('introuvable', 'absent, non renommé') else None
        retards['écarté' if ecarte else etat] += 1
        points[p.cle] = (f"{p.cle} · {montrer(p, actuel)} → {montrer(p, attendu)} · {etat}"
                         + (f', écarté ({ecarte})' if ecarte else ''))
    lies = sum(1 for i in principales if b.pieces[i].mode == MODE_LIE)
    fiches = {e.id: e for e in b.fiches}
    secondaires = 0
    for p in b.pieces.values():
        fiche = fiches.get(p.parent)
        if (fiche is None or p.id in principales or p.mode not in (MODE_IMPORTE, MODE_IMPORTE_URL)
                or p.type_contenu != 'application/pdf'):
            continue
        try:
            secondaires += noms.nom_attendu(fiche, p, b, modele, regles) != noms.nom_actuel(p)
        except noms.NomIncalculable:
            pass
    echecs = {f'renommage échoué · {p.cle}': f"{p.cle} · {montrer(p, noms.nom_actuel(p))} absent, son dossier "
                                              f"contient {montrer(p, autre)}"
              for p in b.pieces.values() if (autre := noms.autre_fichier(p)) is not None}
    points |= echecs
    n, total = sum(retards.values()), justes + sum(retards.values())
    texte = (f"{justes} fichier{'s' if justes > 1 else ''} principa{'ux' if justes > 1 else 'l'} sur {total} "
             f"{'portent' if justes > 1 else 'porte'} le nom attendu d'après le modèle de Zotero")
    if n:
        pluriels = {'présent': 'présents', 'absent du disque': 'absents du disque', 'introuvable': 'introuvables',
                    'écarté': 'écartés', 'absent, non renommé': 'absents, non renommés'}
        texte += f", {n} {'sont en retard sur leur' if n > 1 else 'est en retard sur sa'} fiche (" + ', '.join(
            f'{v} {pluriels.get(k, k) if v > 1 else k}' for k, v in retards.items()) + ')'
    texte += '.'
    if echecs:
        texte += (f" {pluriel(len(echecs), 'pièce jointe')} {'pointent' if len(echecs) > 1 else 'pointe'} vers un "
                  f"fichier absent alors que son dossier en contient un autre (renommage local échoué).")
    if incalculables:
        texte += (f" {pluriel(incalculables, 'nom')} non calculé{'s' if incalculables > 1 else ''}, faute de "
                  f"connaître la conjonction de deux auteurs (réglage `conjonction` de config.toml).")
    if secondaires:
        texte += f" {pluriel(secondaires, 'PDF secondaire')} sous un autre nom, que Zotero ne renomme pas (information)."
    if lies:
        texte += (f" {pluriel(lies, 'fichier lié')} principa{'ux' if lies > 1 else 'l'}, que Zotero ne renomme pas "
                  f"par défaut (information).")
    statut = A_VOIR if n or echecs else (INFO if incalculables or secondaires or lies else OK)
    remede = REMEDE_NOMS + (' Après un renommage échoué, redonner au fichier le nom que porte la pièce jointe, '
                            'Zotero fermé.' if echecs else '')
    return Section('Noms des fichiers', statut, texte, list(points.values()), remede, points)


def _noms_repli(b: Bibliotheque, masquees: set[str], motif: str) -> Section:
    hors = [p for p in b.pieces.values() if p.mode in (MODE_IMPORTE, MODE_IMPORTE_URL)
            and p.type_contenu == 'application/pdf' and p.chemin.startswith('storage:')
            and not MODELE_REPLI.match(Path(p.chemin[len('storage:'):]).stem)]
    points = {p.cle: f"{p.cle} · {MASQUE if p.cle in masquees else p.chemin[len('storage:'):][:90]}" for p in hors}
    return Section('Noms des fichiers', A_VOIR if hors else OK,
                   f"Modèle de Zotero que zot-clean ne sait pas calculer ({motif}). {pluriel(len(hors), 'PDF')} "
                   f"hors de la forme « Auteur - Année - Titre » ou « Auteur - Titre ».", list(points.values()),
                   REMEDE_NOMS_REPLI, points)


# 10
def structure(b: Bibliotheque, cfg: Config) -> Section:
    m = cfg.methode
    racines = sorted(c.nom for c in b.collections.values() if c.parent is None)
    manquantes = [r for r in m.racines if r not in racines]
    en_trop = [r for r in racines if r not in m.racines]
    # Profondeur mesurée sous le fonds s'il existe (les archives gardent l'ancien classement).
    fonds = [c.id for c in b.collections.values() if c.parent is None and c.nom == m.fonds]
    mesurees = [c for c in b.collections if not fonds or b.racine(c) == fonds[0]]
    profondeur = max((b.profondeur(c) for c in mesurees), default=0)
    enfants = {c.parent for c in b.collections.values()}
    occupees = {c for e in b.elements.values() for c in e.collections}
    # Une Inbox vide est l'état visé après le tri, pas une collection à supprimer.
    vides = [b.chemin(c) for c, x in b.collections.items() if c not in enfants and c not in occupees
             and not (x.parent is None and x.nom == m.inbox)]
    multiples = sum(1 for e in b.fiches if len(e.collections) > 1)
    texte = (f"{pluriel(len(racines), 'collection')} à la racine, profondeur maximale {profondeur}"
             f"{f' sous « {m.fonds} »' if fonds else ''}, "
             f"{pluriel(len(vides), 'collection')} vide{'s' if len(vides) > 1 else ''}, "
             f"{pluriel(multiples, 'référence')} rangée{'s' if multiples > 1 else ''} à plusieurs endroits.")
    if manquantes:
        texte += f" Racines de la méthode absentes : {', '.join(manquantes)}."
    points = {f'racine · {r}': f'racine hors méthode : {r}' for r in en_trop} | {
        f'vide · {v}': f'vide : {v}' for v in sorted(vides)}
    details = list(points.values())
    conforme = not manquantes and not en_trop and profondeur <= m.profondeur_max + 1 and not vides
    remede = ('Le plan du fonds (étape 4) proposera une structure à partir des collections existantes, '
              'puis le rangement (étape 5) y déplacera les références et archivera l\'ancien classement.')
    sans, restants = [], [p for p in m.projets if p not in manquantes]
    for r in manquantes:
        sans += ([f'projets = {json.dumps(restants, ensure_ascii=False)}'] if r in m.projets else
                 [f'{n} = ""' for n in ('inbox', 'fonds', 'archives') if getattr(m, n) == r])
    if sans:
        remede += (' Une racine absente se crée dans Zotero au besoin. Sans usage pour elle (pas de projets, pas '
                   'd\'archives), l\'écrire dans config.toml, section [methode], sous la forme '
                   + ', '.join(f'`{s}`' for s in dict.fromkeys(sans)) + ', pour que l\'audit ne la réclame plus.')
    return Section('Structure des collections', OK if conforme else A_VOIR, texte, details, remede, points)


# 11
def synchronisation(b: Bibliotheque) -> Section:
    non_sync = Counter(e.type for e in b.elements.values() if not e.synced)
    cols = sum(1 for c in b.collections.values() if not c.synced)
    texte = (f"{pluriel(sum(non_sync.values()), 'élément')} et {pluriel(cols, 'collection')} pas encore synchronisés, "
             f"{pluriel(len(b.cles_invalides), 'élément')} à clé invalide.")
    details = [f'clé invalide : {k}' for k in b.cles_invalides] + [f'non synchronisé : {t} ({n})'
                                                                   for t, n in non_sync.most_common()]
    remede = ('Quelques éléments non synchronisés sont normaux (modifications récentes). Une clé invalide bloque la '
              'synchronisation et doit être réparée avant tout nettoyage.')
    points = {k: f'clé invalide : {k}' for k in b.cles_invalides}
    if b.compte.id is None:  # le nettoyage écrit par zotero.org, toutes ses commandes refusent alors
        texte = "Zotero n'a jamais synchronisé cette bibliothèque avec un compte zotero.org. " + texte
        remede = ("Le nettoyage modifie la bibliothèque en passant par zotero.org, il demande la synchronisation. "
                  "Dans Zotero, ouvrir Réglages › Synchronisation, se connecter à son compte zotero.org (le créer au "
                  "besoin), synchroniser et attendre la fin, puis, si ce n'est fait, enregistrer la clé API avec "
                  "`zc init`. " + remede)
        points['compte'] = 'bibliothèque jamais synchronisée'
    return Section('Synchronisation', A_VOIR if b.cles_invalides or b.compte.id is None
                   else (INFO if non_sync or cols else OK), texte, details, remede, points)


def auditer(b: Bibliotheque, cfg: Config, empreintes: bool = True, en_ligne: dict[str, bool] | None = None,
            motif: str = '', stockage: str | None = None, automatiques: bool | None | str = '') -> list[Section]:
    from zot_clean.filtre import cles_masquees
    m = cles_masquees(b, cfg)
    stockage = bbt.stockage_fichiers(cfg.dossier_zotero) if stockage is None else stockage
    sections = [chiffres(b), hors_collection(b, cfg, m), doublons(b, cfg, m), metadonnees(b, m),
                pieces_absentes(b, m, en_ligne, motif, stockage)]
    sections.append(pdf_identiques(b, cfg, m, stockage) if empreintes else
                    Section('PDF identiques', INFO, 'Contrôle sauté (option --sans-empreintes).'))
    sections += [tags(b, cfg, automatiques), cles_citation(b, cfg, m), noms_fichiers(b, cfg, m, en_ligne, stockage),
                 structure(b, cfg),
                 synchronisation(b)]
    return sections


def rapport(sections: list[Section], b: Bibliotheque, jour: date | None = None, evolution: list[str] = ()) -> str:
    jour = jour or date.today()
    a_voir = sum(1 for s in sections if s.statut == A_VOIR)
    non = sum(1 for s in sections if s.statut == NON_CONTROLE)
    L = [f'# Audit de la bibliothèque Zotero du {jour:%d/%m/%Y}', '',
         f'Lecture seule, rien n\'a été modifié. {a_voir} point{"s" if a_voir > 1 else ""} sur {len(sections)} '
         f'à voir' + (f', {non} non contrôlé{"s" if non > 1 else ""} faute de fichiers sur le disque' if non else '')
         + f'. Schéma de la base Zotero, version {b.version_schema}.', '',
         '| | Contrôle | Résultat |', '|---|---|---|']
    for i, s in enumerate(sections, 1):
        L.append(f'| {s.statut} | {i}. {s.titre} | {s.resume.replace("|", "/")} |')
    if evolution:
        L += [''] + list(evolution)
    for i, s in enumerate(sections, 1):
        L += ['', f'## {i}. {s.titre}', '', s.resume]
        if s.remede and s.statut != OK:
            L += ['', f'*Ce que le nettoyage pourra faire.* {s.remede}']
        if s.details:
            L.append('')
            L += [f'- {d}' for d in s.details[:DETAILS_MAX]]
            if len(s.details) > DETAILS_MAX:
                L.append(f'- … et {len(s.details) - DETAILS_MAX} autres')
    return '\n'.join(L) + '\n'
