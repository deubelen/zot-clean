"""Read-only audit of the library (D26).

Twelve checks, each rendered as a section of the Markdown report
`rapports/audit-<date>.md`, with what the cleanup can do about it (D27).
The first eleven are here. The twelfth, on the subjects outline, and the
comparison with the previous audit are in `checkup.py` (D139). Nothing
is written to Zotero.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from zot_clean import bbt, citation_keys
from zot_clean.config import Config
from zot_clean.lang import L, current as lang_current, plural as lang_plural
from zot_clean.privacy import mask
from zot_clean.reader import MODE_IMPORTED, MODE_IMPORTED_URL, MODE_LINKED, Library, Item

# Internal codes of the status of a section, in French like the stored words (D209). `status_label` shows them.
OK, TO_REVIEW, INFO, NOT_CHECKED = 'OK', 'À voir', 'Info', 'Non contrôlé'
MAX_DETAILS = 100


def status_label(status: str) -> str:
    """Status of a section as shown in the report."""
    return {TO_REVIEW: L(en='To review', fr='À voir'), NOT_CHECKED: L(en='Not checked', fr='Non contrôlé')
            }.get(status, status)


@dataclass
class Section:
    title: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)
    remedy: str = ''
    # Points found, by stable identifier (keys, no titles), to compare two audits (D139).
    points: dict[str, str] = field(default_factory=dict)


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def year(e: Item) -> str:
    m = re.search(r'\b(\d{4})\b', e.fields.get('date', ''))
    return m.group(1) if m else ''


def line(e: Item, hidden: set[str] = frozenset()) -> str:
    if e.key in hidden:
        return f'{e.key} · {mask()}'
    author = e.author or '?'
    return (f"{e.key} · {author} · {year(e) or L(en='n.d.', fr='s. d.')} · "
            f"{e.title[:80] or L(en='(untitled)', fr='(sans titre)')}")


CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')


def write_toml(path, lines: list[str]) -> None:
    """Writes a tracking file. A comment there often copies a title or a name from Zotero, where a line break
    would turn the rest into a TOML statement, even a decision, and a control character would make the file
    unreadable. In each comment, whatever follows a line break and is not itself a comment joins the line, and
    control characters become spaces (D194). The text is read back as TOML, then replaces the old file in one
    go."""
    import os
    import tomllib
    clean = []
    for l in lines:
        if not l.startswith('#'):
            clean.append(l)
            continue
        chunks = CONTROL_CHARS.sub(' ', l).split('\n')
        clean.append(chunks[0])
        for m in chunks[1:]:
            if m.startswith('#') or not m.strip():
                clean.append(m)
            else:
                clean[-1] += ' ' + m.strip()
    text = '\n'.join(clean)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(L(en=f'{path}: malformed tracking file ({e}). Report this problem in an issue.',
                           fr=f'{path} : fichier de suivi mal formé ({e}). Signaler ce problème dans une issue.')
                         ) from None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


def plural(n: int, word: str) -> str:
    """« 1 pièce jointe », « 2 pièces jointes », « 0 tag manuel »: every word agrees, except acronyms (PDF)."""
    if n <= 1:
        return f'{n} {word}'
    return f"{n} " + ' '.join(m if m.isupper() or m[-1] in 'sx' else m + 's' for m in word.split())


def type_names() -> dict[str, str]:
    """Item type names as Zotero displays them in the language of the library."""
    return {
        'journalArticle': L(en='Journal Article', fr='Article de revue'), 'book': L(en='Book', fr='Livre'),
        'bookSection': L(en='Book Section', fr='Chapitre de livre'),
        'conferencePaper': L(en='Conference Paper', fr='Article de colloque'),
        'document': L(en='Document', fr='Document'), 'thesis': L(en='Thesis', fr='Thèse'),
        'report': L(en='Report', fr='Rapport'), 'webpage': L(en='Web Page', fr='Page web'),
        'magazineArticle': L(en='Magazine Article', fr='Article de magazine'),
        'newspaperArticle': L(en='Newspaper Article', fr='Article de journal'),
        'encyclopediaArticle': L(en='Encyclopedia Article', fr="Article d'encyclopédie"),
        'dictionaryEntry': L(en='Dictionary Entry', fr='Entrée de dictionnaire'),
        'preprint': L(en='Preprint', fr='Prépublication'), 'manuscript': L(en='Manuscript', fr='Manuscrit'),
        'letter': L(en='Letter', fr='Lettre'), 'interview': L(en='Interview', fr='Interview'),
        'presentation': L(en='Presentation', fr='Présentation'), 'blogPost': L(en='Blog Post', fr='Billet de blog'),
        'forumPost': L(en='Forum Post', fr='Message de forum'), 'film': L(en='Film', fr='Film'),
        'videoRecording': L(en='Video Recording', fr='Enregistrement vidéo'),
        'audioRecording': L(en='Audio Recording', fr='Enregistrement audio'),
        'podcast': L(en='Podcast', fr='Podcast'),
        'radioBroadcast': L(en='Radio Broadcast', fr='Émission de radio'),
        'tvBroadcast': L(en='TV Broadcast', fr='Émission de télévision'),
        'artwork': L(en='Artwork', fr='Illustration'), 'map': L(en='Map', fr='Carte'),
        'computerProgram': L(en='Software', fr='Logiciel'), 'dataset': L(en='Dataset', fr='Jeu de données'),
        'standard': L(en='Standard', fr='Norme'), 'patent': L(en='Patent', fr='Brevet'),
        'case': L(en='Case', fr='Affaire'), 'statute': L(en='Statute', fr='Acte juridique'),
        'bill': L(en='Bill', fr='Projet de loi'), 'hearing': L(en='Hearing', fr='Audience'),
        'email': L(en='Email', fr='Courriel'),
        'instantMessage': L(en='Instant Message', fr='Message instantané'),
    }


def type_name(t: str) -> str:
    return type_names().get(t, t)


def is_pdf(p) -> bool:
    return p.content_type == 'application/pdf' or p.path.lower().endswith('.pdf')


def pdfs_on_disk(b: Library):
    for p in b.attachments.values():
        if is_pdf(p) and p.file is not None and p.file.is_file():
            yield p


def missing_pdfs(b: Library, items: set[str] | None = None) -> list[str]:
    """Keys of the item PDFs whose file is missing from disk, which nothing can therefore compare (D168).
    `items` restricts to the PDFs of these items (keys)."""
    return sorted(p.key for p in b.attachments.values() if is_pdf(p) and p.parent in b.all_items
                  and (items is None or b.all_items[p.parent].key in items)
                  and p.file is not None and not p.file.is_file())


def download_advice(storage: str, goal: str | None = None, at_sync: bool = False) -> str:
    """How to bring to disk the files not downloaded yet, depending on the sync setup (D157, D168). `goal` is the
    verb phrase that completes « Pour … » (compare them by default). `at_sync`: Zotero already downloads at sync time
    (`bbt.downloads_at_sync`), the advice to set it would be repeated in vain (D242)."""
    if goal is None:
        goal = L(en='compare them', fr='les comparer')
    if at_sync and storage != bbt.NONE:
        return L(en='Zotero already downloads the files at sync time. If they are still missing after a sync, they are '
                    'not on the server either: point 5 of the audit lists them (missing files).',
                 fr='Zotero télécharge déjà les fichiers au moment de la synchronisation. S\'ils manquent encore après '
                    'une synchronisation, ils ne sont pas non plus sur le serveur : le point 5 de l\'audit les recense '
                    '(fichiers absents).')
    if storage == bbt.NONE:
        return L(en="Zotero does not sync files, so it will not download them. These files fall under point 5 of "
                    "the audit (missing files).",
                 fr='Zotero ne synchronise pas les fichiers et ne les téléchargera donc pas. Ces fichiers relèvent du '
                    'point 5 de l\'audit (fichiers absents).')
    origin = (L(en=' from the WebDAV server', fr=' depuis le serveur WebDAV') if storage == bbt.WEBDAV else '')
    return L(en=f'To {goal}, have Zotero download all the files{origin}, in Settings › Sync, by setting "Download '
                f'files" to "at sync time", then sync and wait for the download to finish. Then run the command '
                f'again.',
             fr=f'Pour {goal}, faire télécharger tous les fichiers par Zotero{origin}, dans Réglages › '
                'Synchronisation, en réglant « Télécharger les fichiers » sur « au moment de la synchronisation », puis '
                'synchroniser et attendre la fin du téléchargement. Relancer ensuite la commande.')


def missing_reminder(b: Library, storage: str, follow_up: str = '', items: set[str] | None = None,
                     at_sync: bool = False) -> str:
    """Warning of the commands that compare PDFs (D168), empty when all are on disk. `follow_up` completes the
    sentence « non comparés »."""
    n = len(missing_pdfs(b, items))
    if not n:
        return ''
    pdfs = lang_plural(n, en='PDF', fr='PDF')
    if n > 1:
        head = L(en=f'{pdfs} missing from the disk (not downloaded by Zotero yet?), not compared{follow_up}. ',
                 fr=f'{pdfs} absents du disque (pas encore téléchargés par Zotero ?), non comparés{follow_up}. ')
    else:
        head = L(en=f'{pdfs} missing from the disk (not downloaded by Zotero yet?), not compared{follow_up}. ',
                 fr=f'{pdfs} absent du disque (pas encore téléchargé par Zotero ?), non comparé{follow_up}. ')
    return head + download_advice(storage, at_sync=at_sync)


# 1
def figures(b: Library) -> Section:
    types = Counter(e.type for e in b.items)
    manual_tags = {n for e in b.all_items.values() for n, t in e.tags if t == 0}
    autos = {n for e in b.all_items.values() for n, t in e.tags if t == 1}
    details = [f'{type_name(t)} : {n}' for t, n in types.most_common()]
    refs = lang_plural(len(b.items), en='item', fr='référence')
    attachments = lang_plural(len(b.attachments), en='attachment', fr='pièce jointe')
    notes = lang_plural(len(b.notes), en='note', fr='note')
    collections = lang_plural(len(b.collections), en='collection', fr='collection')
    manual = lang_plural(len(manual_tags), en='manual tag', fr='tag manuel')
    n_auto = len(autos)
    if n_auto > 1:
        automatic = L(en=f'{n_auto} automatic', fr=f'{n_auto} automatiques')
    else:
        automatic = L(en=f'{n_auto} automatic', fr=f'{n_auto} automatique')
    return Section(L(en='Overview', fr="Chiffres d'ensemble"), INFO,
                   L(en=f'{refs}, {attachments}, {notes}, {collections}, {manual} and {automatic}.',
                     fr=f'{refs}, {attachments}, {notes}, {collections}, {manual} et {automatic}.'),
                   details)


# 2
def without_collection(b: Library, cfg: Config, hidden: set[str] = frozenset()) -> Section:
    without = [e for e in b.items if not e.collections]
    inbox = [c.id for c in b.collections.values() if c.parent is None and c.name == cfg.method.inbox]
    n_inbox = sum(1 for e in b.items if inbox and inbox[0] in e.collections)
    refs = lang_plural(len(without), en='item', fr='référence')
    name = cfg.method.inbox
    text = L(en=f'{refs} in no collection. ', fr=f'{refs} dans aucune collection. ')
    text += (L(en=f'{n_inbox} in “{name}”.', fr=f'{n_inbox} dans « {name} ».') if inbox else
             L(en=f'No “{name}” collection at the root.', fr=f'Pas de collection « {name} » à la racine.'))
    points = {e.key: line(e, hidden) for e in without}
    return Section(L(en='Items without a collection', fr='Références sans collection'),
                   TO_REVIEW if without else OK, text, list(points.values()),
                   L(en='Filing (step 5) will give them a place in the subjects. Then the sorting of new items '
                        '(`zc inbox`) handles them as they come in.',
                     fr='Le rangement (étape 5) leur donnera une place dans le fonds. Ensuite, le tri des nouvelles '
                        'références (`zc inbox`) les traite au fil de l\'eau.'), points)


# 3
def _doi(v: str) -> str:
    return re.sub(r'^(https?://(dx\.)?doi\.org/|doi:\s*)', '', v.strip().lower())


def _isbns(v: str) -> set[str]:
    from zot_clean.sources import isbn_chunks
    res = set()
    for c in isbn_chunks(v):
        if len(c) == 10:
            c = '978' + c[:9]
            c += str((10 - sum(int(x) * (1 if i % 2 == 0 else 3) for i, x in enumerate(c)) % 10) % 10)
        if len(c) == 13:
            res.add(c)
    return res


def duplicates(b: Library, cfg: Config, hidden: set[str] = frozenset()) -> Section:
    from zot_clean import duplicates as d
    distinct_sets = d.distinct_sets(d.load_tracking(cfg))
    groups = [g for g in d.candidates(b) if not d.already_judged({e.key for e in g}, distinct_sets)]
    points = {}
    for g in sorted(groups, key=lambda g: norm(g[0].title)):
        # The items of a group look alike: a single confidential item hides the whole group (D126).
        cache = {e.key for e in g} if any(e.key in hidden for e in g) else set()
        points['/'.join(sorted(e.key for e in g))] = ' / '.join(line(e, cache) for e in g)
    n = sum(len(g) for g in groups)
    n_groups = lang_plural(len(groups), en='group', fr='groupe')
    refs = lang_plural(n, en='item', fr='référence')
    return Section(L(en='Probable duplicates', fr='Doublons probables'), TO_REVIEW if groups else OK,
                   L(en=f'{n_groups} of probable duplicates ({refs}), found by DOI, ISBN, or title, author and '
                        f'year (excluding groups already judged distinct).',
                     fr=f"{n_groups} de doublons probables ({refs}), repérés par DOI, ISBN ou titre, auteur et "
                        f"année (hors groupes déjà jugés distincts)."),
                   list(points.values()),
                   L(en='Cleanup (step 2) will merge them the way Zotero does, keeping notes, attachments and '
                        'collections.',
                     fr='Le nettoyage (étape 2) les fusionnera à la manière de Zotero, en gardant notes, pièces '
                        'jointes et collections.'),
                   points)


# 4
def metadata(b: Library, hidden: set[str] = frozenset()) -> Section:
    gaps = defaultdict(list)
    for e in b.items:
        if not e.creators:
            gaps['sans auteur'].append(e)
        if not year(e):
            gaps['sans année'].append(e)
        if e.type == 'journalArticle' and not e.fields.get('DOI'):
            gaps['article sans DOI'].append(e)
        if e.type == 'book' and not e.fields.get('ISBN'):
            gaps['livre sans ISBN'].append(e)
        if e.type == 'document':
            gaps['type « Document » par défaut'].append(e)
    # The keys of `gaps` are stable identifiers (they go into the points), the labels are what is shown.
    labels = {'sans auteur': L(en='no author', fr='sans auteur'), 'sans année': L(en='no year', fr='sans année'),
              'article sans DOI': L(en='article without DOI', fr='article sans DOI'),
              'livre sans ISBN': L(en='book without ISBN', fr='livre sans ISBN'),
              'type « Document » par défaut': L(en='default “Document” type',
                                                 fr='type « Document » par défaut')}
    summary = ', '.join(f'{labels[k]} {len(v)}' for k, v in gaps.items()) or L(en='no gap found',
                                                                                  fr='aucun manque relevé')
    points = {f'{k} · {e.key}': L(en=f'{labels[k]}: {line(e, hidden)}', fr=f'{labels[k]} : {line(e, hidden)}')
              for k, v in gaps.items() for e in v}
    serious = len(gaps['sans auteur']) + len(gaps['sans année']) + len(gaps['type « Document » par défaut'])
    return Section(L(en='Missing metadata', fr='Métadonnées manquantes'),
                   TO_REVIEW if serious else (INFO if gaps else OK), summary[0].upper() + summary[1:] + '.',
                   list(points.values()),
                   L(en='Cleanup (step 3) will complete what can be completed through Crossref, OpenAlex, BnF, '
                        'Sudoc and Open Library, and list the rest for a correction by hand.',
                     fr='Le nettoyage (étape 3) complétera ce qui peut l\'être par Crossref, '
                        'OpenAlex, BnF, Sudoc et Open Library, et listera le reste pour une correction à la main.'),
                   points)


# 5
def missing_imported(b: Library) -> list[str]:
    """Keys of the imported attachments whose file is missing, the only ones zotero.org may have (D133)."""
    return [p.key for p in b.attachments.values() if p.mode in (MODE_IMPORTED, MODE_IMPORTED_URL)
            and p.file is not None and not p.file.is_file()]


def storage_sentence(storage: str) -> str:
    """Sentence on each file sync setup (D157), empty for an unknown one."""
    return {bbt.ZOTERO_ORG: L(en='Zotero syncs files through zotero.org.',
                              fr='Zotero synchronise les fichiers par zotero.org.'),
            bbt.WEBDAV: L(en='Zotero syncs files through WebDAV.', fr='Zotero synchronise les fichiers par WebDAV.'),
            bbt.NONE: L(en='File sync is disabled in Zotero.',
                        fr='La synchronisation des fichiers est désactivée dans Zotero.')}.get(storage, '')


def storage_advice(storage: str) -> str:
    """Remedy for the missing files, specific to the file sync setup (D157)."""
    recover = L(en='A file that cannot be found can sometimes be recovered from an old backup or from another '
                   'computer. Failing that, the orphan attachment can be deleted.',
                fr='Un fichier introuvable se retrouve parfois dans une ancienne sauvegarde ou sur un autre '
                   'ordinateur. À défaut, la pièce jointe orpheline peut être supprimée.')
    if storage == bbt.WEBDAV:
        return L(en='Opening the attachment in Zotero downloads it again if it is on the WebDAV server. A file still '
                    'on zotero.org, left over from an old sync, can be downloaded from the online library, since '
                    'Zotero no longer looks for it there. ',
                 fr='Ouvrir la pièce jointe dans Zotero la retélécharge si elle est sur le serveur WebDAV. Un '
                    'fichier encore sur zotero.org, reste d\'une ancienne synchronisation, se télécharge depuis la '
                    'bibliothèque en ligne, Zotero ne l\'y cherche plus. ') + recover
    if storage == bbt.NONE:
        return L(en='Zotero does not sync files and so downloads nothing again. A file still on zotero.org, left '
                    'over from an old sync, can be downloaded from the online library. ',
                 fr='Zotero ne synchronise pas les fichiers et ne retélécharge donc rien. Un fichier encore sur '
                    'zotero.org, reste d\'une ancienne synchronisation, se télécharge depuis la bibliothèque en '
                    'ligne. ') + recover
    return L(en='A file still on zotero.org comes back when the attachment is opened in Zotero, which downloads it '
                'again. ',
             fr='Un fichier encore sur zotero.org revient quand on ouvre la pièce jointe dans Zotero, qui le '
                'retélécharge. ') + recover


def missing_attachments(b: Library, hidden: set[str] = frozenset(), online: dict[str, bool] | None = None,
                    cause: str = '', storage: str = bbt.UNKNOWN) -> Section:
    """`online` says, for each missing imported file, whether it is still on zotero.org (D133). Without it
    (offline, no API key), `cause` says why the check did not happen. `storage` (D157) says where Zotero syncs
    the files, and so what a copy on zotero.org is worth."""
    elsewhere = storage in (bbt.WEBDAV, bbt.NONE)  # Zotero no longer looks for the files on zotero.org
    recoverable, lost, unresolved, points = [], [], 0, {}
    for p in b.attachments.values():
        if p.mode not in (MODE_IMPORTED, MODE_IMPORTED_URL, MODE_LINKED):
            continue
        if p.file is None:
            unresolved += 1
        elif not p.file.is_file():
            parent = b.all_items.get(p.parent)
            path = mask() if p.key in hidden else p.path[:70]
            d = f"{p.key} · {path}" + (L(en=f' (item {line(parent, hidden)})', fr=f' (fiche {line(parent, hidden)})')
                                       if parent else '')
            if online is not None and online.get(p.key):
                recoverable.append(d := d + L(en=' · on zotero.org', fr=' · sur zotero.org'))
            elif online is not None:
                lost.append(d := d + (L(en=' · not on zotero.org', fr=' · pas sur zotero.org')
                                      if storage == bbt.WEBDAV else L(en=' · not found', fr=' · introuvable')))
            else:
                lost.append(d)
            points[p.key] = d
    with_attachment = {p.parent for p in b.attachments.values()}
    no_attachment = [e for e in b.items if e.id not in with_attachment]
    n, r, x = len(recoverable) + len(lost), len(recoverable), len(lost)
    files = lang_plural(n, en='file', fr='fichier')
    absent = L(en='missing', fr='absents') if n > 1 else L(en='missing', fr='absent')
    text = L(en=f'{files} {absent} from the disk', fr=f'{files} {absent} du disque')
    if online is not None and n:
        if elsewhere:
            text += L(en=f', of which {r} still on zotero.org (to download from the online library)',
                      fr=f', dont {r} encore sur zotero.org (à télécharger depuis la bibliothèque en ligne)')
        else:
            recoverable_word = L(en='recoverable', fr='récupérables') if r > 1 else L(en='recoverable',
                                                                                          fr='récupérable')
            text += L(en=f', of which {r} still on zotero.org ({recoverable_word})',
                      fr=f', dont {r} encore sur zotero.org ({recoverable_word})')
        if storage == bbt.WEBDAV:
            gone = L(en='not on', fr='absents de') if x > 1 else L(en='not on', fr='absent de')
            text += L(en=f' and {x} {gone} zotero.org (maybe on the WebDAV server)',
                      fr=f' et {x} {gone} zotero.org (peut-être sur le serveur WebDAV)')
        else:
            lost_word = L(en='not found', fr='introuvables') if x > 1 else L(en='not found', fr='introuvable')
            text += L(en=f' and {x} {lost_word}', fr=f' et {x} {lost_word}')
    elif cause and n:
        text += L(en=f' (not checked on zotero.org, {cause})', fr=f' (non vérifiés sur zotero.org, {cause})')
    refs = lang_plural(len(no_attachment), en='item', fr='référence')
    text += L(en=f'. {refs} with no attachment at all (information).',
              fr=f'. {refs} sans aucune pièce jointe (information).')
    if unresolved:
        text += L(en=f" {unresolved} linked files relative to Zotero's base folder were not checked.",
                  fr=f" {unresolved} fichiers liés relatifs au dossier de base de Zotero n'ont pas été vérifiés.")
    if storage_sentence(storage):
        text += ' ' + storage_sentence(storage)
    return Section(L(en='Missing files', fr='Fichiers absents'), TO_REVIEW if n else OK, text, recoverable + lost,
                   storage_advice(storage), points)


# 6
def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def identical_pdfs(b: Library, cfg: Config | None = None, hidden: set[str] = frozenset(),
                   storage: str = bbt.UNKNOWN) -> Section:
    """Copies of the same PDF, except those of a trashed item and the groups judged intended (D125). A PDF
    missing from disk is not compared, and with no group found the check is « non contrôlé » (D168)."""
    from zot_clean import attachments as pc
    intended = [set(e.copies) for e in pc.load(cfg) if e.decision == pc.KEEP] if cfg else []
    parent = {p.key: p.parent for p in b.attachments.values()}
    points, same_item = {}, 0
    for copies in pc.identical_groups(b):
        if any(set(copies) <= v for v in intended):
            continue
        parents = list(dict.fromkeys(parent[k] for k in copies))
        same_item += len(copies) - len(parents)
        if len(parents) > 1:
            items = [b.all_items[x] for x in parents]
            cache = {f.key for f in items} if hidden & set(copies) else set()
            points['/'.join(sorted(f.key for f in items))] = ' / '.join(line(f, cache) for f in items)
    different = list(points.values())
    missing = len(missing_pdfs(b))
    pdfs = lang_plural(len(different), en='PDF', fr='PDF')
    attached = L(en='attached', fr='rattachés') if len(different) > 1 else L(en='attached', fr='rattaché')
    copies = L(en='copies', fr='copies') if same_item > 1 else L(en='copy', fr='copie')
    text = L(en=f'{pdfs} {attached} to different items (probable duplicate items), {same_item} extra {copies} on '
                f'a single item.',
             fr=f'{pdfs} {attached} à des fiches différentes (doublons de fiches probables), {same_item} {copies} '
                f'en trop sur une même fiche.')
    remedy = L(en='Items that share the same PDF are often duplicates, or one carries the PDF of the other. Handle '
                  'them in step 2 (`zc duplicates find`, then `zc attachments find`).',
               fr='Des fiches qui partagent le même PDF sont souvent des doublons, ou l\'une porte le PDF de '
                  'l\'autre. Les traiter à l\'étape 2 (`zc duplicates find`, puis `zc attachments find`).')
    if missing:
        n_missing = lang_plural(missing, en='PDF', fr='PDF')
        text += (L(en=f' {n_missing} missing from the disk, not compared.',
                   fr=f' {n_missing} absents du disque, non comparés.') if missing > 1 else
                 L(en=f' {n_missing} missing from the disk, not compared.',
                   fr=f' {n_missing} absent du disque, non comparé.'))
        remedy = download_advice(storage, at_sync=bool(cfg) and bbt.downloads_at_sync(cfg.zotero_dir)) + ' ' + remedy
    status = TO_REVIEW if different or same_item else (NOT_CHECKED if missing else OK)
    return Section(L(en='Identical PDFs', fr='PDF identiques'), status, text, different, remedy, points)


# 7
def tags(b: Library, cfg: Config, automatic: bool | None | str = '') -> Section:
    """Tag set as step 6 will handle it (D151 to D155). A tag carried only by confidential items is designated
    by its identifier. `automatic` is the Zotero setting that creates automatic tags, read from the profile when
    not given (None, profile not found)."""
    from zot_clean import tags as t
    a = t._Analysis(b, cfg)
    if automatic == '':
        automatic = bbt.automatic_tags(cfg.zotero_dir)

    def name(n: str) -> str:
        return t.identifier(n) if a.u[n].confidential else n

    autos = sorted(n for n, u in a.u.items() if 1 in u.types)
    auto_occurrences = sum(a.u[n].occurrences[1] for n in autos)
    manual_tags = {n for n, u in a.u.items() if 0 in u.types}
    manual_forms = {t.form(n, cfg) for n in manual_tags}
    doubling = [n for n in autos if 0 not in a.u[n].types and t.form(n, cfg) in manual_forms]
    variants, _ = a.groups()
    outside = sorted(n for n in manual_tags if a.outside_families(n) and n not in a.imported)
    children = sorted(n for n, u in a.u.items() if u.children == len(u.all_items))
    pct = 100 * len(autos) // max(1, len(a.u))
    part = L(en=f' ({pct}% of tags)', fr=f' ({pct} % des tags)') if autos else ''
    auto_tags = lang_plural(len(autos), en='automatic tag', fr='tag automatique')
    placed = L(en='applied', fr='posés') if len(autos) > 1 else L(en='applied', fr='posé')
    text = L(en=f'{auto_tags}{part}, {placed} {auto_occurrences} times', fr=f'{auto_tags}{part}, {placed} {auto_occurrences} fois')
    if doubling:
        n_doubling = len(doubling)
        text += L(en=f', of which {n_doubling} of the same form as a manual tag',
                  fr=f", dont {n_doubling} de même forme qu'un tag manuel")
    groups = lang_plural(len(variants), en='group', fr='groupe')
    text += L(en=f'. {groups} of variants (case, accents, plural). ', fr=f'. {groups} de variantes (casse, accents, pluriel). ')
    if a.imported:
        imported = lang_plural(len(a.imported), en='manual tag', fr='tag manuel')
        have = L(en='look like', fr='ont') if len(a.imported) > 1 else L(en='looks like', fr='a')
        batch = lang_plural(len(a.batch), en='item', fr='fiche')
        text += L(en=f'{imported} that {have} imported keywords, on {batch}. ',
                  fr=f"{imported} qui {have} l'air de mots-clés importés, sur {batch}. ")
    outside_tags = lang_plural(len(outside), en='manual tag', fr='tag manuel')
    text += L(en=f"{outside_tags} outside the method's families (statuses, concepts, techniques).",
              fr=f'{outside_tags} hors des familles de la méthode (états, concepts, techniques).')
    if b.colors:
        colored = lang_plural(len(b.colors), en='colored tag', fr='tag coloré')
        text += L(en=f' {colored} out of 9 possible.', fr=f' {colored} sur 9 possibles.')
    if children:
        n_children = lang_plural(len(children), en='tag', fr='tag')
        carried = L(en='carried', fr='portés') if len(children) > 1 else L(en='carried', fr='porté')
        text += L(en=f' {n_children} {carried} only by attachments, notes or annotations.',
                  fr=f' {n_children} {carried} seulement par des pièces jointes, notes ou annotations.')
    if automatic:
        text += L(en=' Zotero still creates automatic tags on every addition (setting enabled).',
                  fr=' Zotero crée encore des tags automatiques à chaque ajout (réglage actif).')
    points = ({f'automatique · {name(n)}': L(en=f'automatic: {name(n)}', fr=f'automatique : {name(n)}')
               for n in autos}
              | {f'variantes · {" / ".join(v.names)}': L(en=f'variants: {" / ".join(v.names)} → {v.target}',
                                                           fr=f'variantes : {" / ".join(v.names)} → {v.target}')
                 for v in variants}
              | {f'importé · {name(n)}': L(en=f'imported keyword: {name(n)}', fr=f'mot-clé importé : {name(n)}')
                 for n in sorted(a.imported)}
              | {f'hors familles · {name(n)}': L(en=f'outside families: {name(n)} ({len(a.u[n].items)})',
                                                  fr=f'hors familles : {name(n)} ({len(a.u[n].items)})')
                 for n in outside})
    if automatic:
        points['réglage'] = L(en='Zotero setting "Automatically tag items with keywords and subject headings" '
                                 'enabled',
                              fr='réglage de Zotero « Ajouter automatiquement des tags » actif')
    details = [d for k, d in points.items() if not k.startswith(('automatique', 'importé'))]
    remedy = L(en='Cleanup step 6 (`zc tags inventory`, skill `tags`) deletes the automatic tags and the imported '
                  'keywords through a global rule, groups the variants, brings the statuses back to those of the '
                  'method and proposes as concepts the tags spread over several themes.',
               fr='L\'étape 6 du nettoyage (`zc tags inventory`, skill `tags`) supprime les tags automatiques et '
                  'les mots-clés importés par une règle globale, regroupe les variantes, ramène les états à ceux '
                  'de la méthode et propose comme concepts les tags répartis sur plusieurs thèmes.')
    if automatic:
        remedy += L(en=' Uncheck, in Zotero, Settings › General, "Automatically tag items with keywords and subject '
                       'headings", and the same setting in the Zotero Connector of the browser.',
                    fr=' Décocher dans Zotero, Réglages › Général, « Ajouter automatiquement des tags à partir des '
                       'mots-clés et des vedettes-matières », et le même réglage dans le connecteur de Zotero du '
                       'navigateur.')
    status = TO_REVIEW if autos or variants or a.imported else (INFO if outside or automatic else OK)
    return Section('Tags', status, text, details, remedy, points)


# 8
def use_citation_keys(b: Library, cfg: Config, hidden: set[str] = frozenset(),
                  state: bbt.State | None = None) -> Section:
    """Missing keys, duplicate keys (compared as Better BibTeX compares them) and keys left in Extra, Better
    BibTeX settings read from the Zotero profile (D144 to D146)."""
    title = L(en='Citation keys', fr='Clés de citation')
    if not cfg.method.use_citation_keys:
        return Section(title, INFO, L(en='Check disabled in the configuration.',
                                      fr='Contrôle désactivé dans la configuration.'))
    state = state or bbt.detect(cfg.zotero_dir)
    settings = state.present and state.source == bbt.PROFILE
    without = [e for e in b.items if not e.fields.get('citationKey', '').strip()]
    doubles = citation_keys.doubles(b, state.casing)
    leftovers = citation_keys.extra_leftovers(b)
    described = bbt.describe(state)
    n_without = lang_plural(len(without), en='item', fr='référence')
    dups = lang_plural(len(doubles), en='duplicate key', fr='clé')
    n_left = lang_plural(len(leftovers), en='item', fr='référence')
    casing = (L(en='case-sensitive, as Better BibTeX sets it', fr='casse distinguée, comme le règle Better BibTeX')
              if state.casing else L(en='ignoring case', fr='sans tenir compte de la casse'))
    text = L(en=f'{described} {n_without} without a citation key, {dups} ({casing}), {n_left} whose Extra still '
                f'contains a "Citation Key:" line.',
             fr=f'{described} {n_without} sans clé de citation, {dups} en double ({casing}), '
                f'{n_left} dont Extra contient encore une ligne « Citation Key: ».')
    if settings and not state.method_formula:
        text += L(en=f" The Better BibTeX formula differs from the method's (`{bbt.METHOD_FORMULA}`), which is not a "
                     f"problem, since existing keys are never changed.",
                  fr=f" La formule de Better BibTeX diffère de celle de la méthode (`{bbt.METHOD_FORMULA}`), ce qui "
                     "n'est pas un problème, les clés existantes ne sont jamais changées.")
    alerts = {}
    if state.present and state.too_old:
        alerts['réglage · version'] = L(
            en=f'Better BibTeX {state.version} is too old, upgrade to Better BibTeX {bbt.VERSION_MIN} and Zotero 8',
            fr=f'Better BibTeX {state.version} trop ancien, passer à Better BibTeX {bbt.VERSION_MIN} et Zotero 8')
    if settings and state.regenerates:
        alerts['réglage · resetKeyOnChange'] = L(
            en="Better BibTeX regenerates the key of an item on every change (\"Regenerate citation key when item "
               "changes\"). Every zc step that modifies items would then change their key. Uncheck this setting in "
               "Zotero › Settings › Better BibTeX",
            fr="Better BibTeX refait la clé d'une fiche à chaque modification (« Regenerate citation key when item "
               "changes »). Chaque étape de zc qui modifie des fiches changerait alors leur clé. Décocher ce réglage "
               "dans Zotero › Réglages › Better BibTeX")
    if settings and state.fill_after == 0 and without:
        alerts['réglage · fillKeyAfter'] = L(
            en="Better BibTeX does not fill missing keys by itself (\"Automatically fill citation key after\" at "
               "0). Fill them with a right click, Better BibTeX › Fill, or set a delay",
            fr="Better BibTeX ne remplit pas seul les clés manquantes (« Automatically fill citation key after » à 0). "
               "Les remplir par clic droit, Better BibTeX › Fill, ou régler un délai")
    points = {f'sans clé · {e.key}': L(en=f'no key: {e.key}', fr=f'sans clé : {e.key}') for e in without}
    for k, items in doubles.items():
        item_keys = sorted(e.key for e in items)
        if hidden & set(item_keys):
            # The citation key contains the author name and the start of the title (D126).
            shown = f"{mask()} ({', '.join(item_keys)})"
            points[f"en double · {'+'.join(item_keys)}"] = L(en=f'duplicate: {shown}', fr=f'en double : {shown}')
        else:
            shown = f"{items[0].fields['citationKey'].strip()} ({', '.join(e.key for e in items)})"
            points[f'en double · {k}'] = L(en=f'duplicate: {shown}', fr=f'en double : {shown}')
    for e, _ in leftovers:
        points[f'Extra · {e.key}'] = L(en=f'"Citation Key:" line in Extra: {e.key}',
                                       fr=f'ligne « Citation Key: » dans Extra : {e.key}')
    details = list(alerts.values()) + [d for k, d in points.items() if not k.startswith('sans clé')]
    points |= alerts
    status = TO_REVIEW if doubles or leftovers or alerts or (state.present and without) else INFO if without else OK
    if state.present:
        remedy = L(en="Cleanup step 7 (`zc citation-keys plan`, skill `citation-keys`) separates the duplicate keys, the "
                      "oldest item keeping its own and the others getting a suffix (a, b…), and moves the "
                      "\"Citation Key:\" lines of Extra into the native field. Missing keys are the business of "
                      "Better BibTeX, which fills them by itself, or on request by right click, Better BibTeX › "
                      "Fill.",
                   fr="L'étape 7 du nettoyage (`zc citation-keys plan`, skill `citation-keys`) départage les clés en double, "
                      "la fiche la plus ancienne gardant la sienne et les autres recevant un suffixe (a, b…), et "
                      "range les lignes « Citation Key: » d'Extra dans le champ natif. Les clés manquantes sont "
                      "l'affaire de Better BibTeX, qui les remplit seul, ou sur demande par clic droit, Better "
                      "BibTeX › Fill.")
    else:
        remedy = L(en="Without an active Better BibTeX, step 7 is skipped, except for the separation of duplicate "
                      "keys (`zc citation-keys plan`), which needs no computation. Keys are only useful for writing "
                      "in Markdown or LaTeX. Install or enable Better BibTeX, or disable this check "
                      "(`cles_citation = false`).",
                   fr="Sans Better BibTeX actif, l'étape 7 est sautée, sauf le départage des clés en double "
                      "(`zc citation-keys plan`), qui ne demande aucun calcul. Les clés ne sont utiles que pour "
                      "écrire en Markdown ou en LaTeX. Installer ou activer Better BibTeX, ou désactiver ce contrôle "
                      "(`cles_citation = false`).")
    return Section(title, status, text, details, remedy, points)


# 9
# Fallback when the Zotero template is outside the subset computed by `filenames`: « Auteur - Année - Titre »,
# year optional since Zotero writes « Auteur - Titre » for an item without a date (D150).
FALLBACK_TEMPLATE = re.compile(r'^.+( - \d{4})? - .+$')
def filenames_remedy() -> str:
    return L(en="`zc filenames plan` (cleanup step 8) prepares the renaming of these files through the Zotero API, "
                "each computer renaming its own at the next sync. A file that cannot be found falls under point 5. "
                "A skipped name (already taken, refused by Windows, too long) is fixed by hand in Zotero.",
             fr="`zc filenames plan` (étape 8 du nettoyage) prépare le renommage de ces fichiers par l'API de "
                "Zotero, chaque ordinateur renommant les siens à la synchronisation suivante. Un fichier "
                "introuvable relève du point 5. Un nom écarté (déjà pris, refusé par Windows, trop long) se règle "
                "à la main dans Zotero.")


def filenames_fallback_remedy() -> str:
    return L(en='`zc filenames plan` cannot rename from this template. Rename the files with Zotero itself, in its '
                'settings (General, File Renaming, "Rename Files…" button).',
             fr="`zc filenames plan` ne sait pas renommer d'après ce modèle. Renommer les fichiers par Zotero "
                "lui-même, dans ses réglages (Général, renommage des fichiers, bouton « Renommer les fichiers… »).")


def file_names(b: Library, cfg: Config, hidden: set[str] = frozenset(),
                  online: dict[str, bool] | None = None, storage: str = '') -> Section:
    """Expected names of the main files from the Zotero template (D148, D150), or a fallback regular expression
    if the template is not supported. `online` says whether a missing file is on zotero.org (D133). Under WebDAV
    or without file sync (`storage`, D157), a missing file is not renamed, only listed (D158)."""
    from zot_clean import filenames
    try:
        template = filenames.Template.analyze(filenames.template_of(b))
    except filenames.UnsupportedTemplate as e:
        return _fallback_names(b, hidden, str(e))
    rules = filenames.Rules.of(b, filenames.conjunction(b, cfg, template))

    def display(p, name: str) -> str:
        return mask() if p.key in hidden else name[:90]

    correct, uncomputable, stale, points, main_attachments = 0, 0, Counter(), {}, set()
    for item, p in filenames.main_attachments(b, linked=True):
        main_attachments.add(p.id)
        if p.mode == MODE_LINKED:
            continue
        try:
            expected = filenames.expected_name(item, p, b, template, rules)
        except filenames.NameNotComputable:
            uncomputable += 1
            continue
        current = filenames.current_name(p)
        if expected == current:
            correct += 1
            continue
        # The states are internal words (they key the counts); `state_label` shows them.
        if filenames.present(p):
            state = 'présent'
        elif storage in (bbt.WEBDAV, bbt.NONE):
            state = 'absent, non renommé'
        elif online is None:
            state = 'absent du disque'
        else:
            state = 'sur zotero.org' if online.get(p.key) else 'introuvable'
        skipped = filenames.skip_cause(p, expected) if state not in ('introuvable', 'absent, non renommé') else None
        stale['écarté' if skipped else state] += 1
        points[p.key] = (f"{p.key} · {display(p, current)} → {display(p, expected)} · {state_label(state)}"
                         + (L(en=f', skipped ({skipped})', fr=f', écarté ({skipped})') if skipped else ''))
    linked = sum(1 for i in main_attachments if b.attachments[i].mode == MODE_LINKED)
    items = {e.id: e for e in b.items}
    secondary = 0
    for p in b.attachments.values():
        item = items.get(p.parent)
        if (item is None or p.id in main_attachments or p.mode not in (MODE_IMPORTED, MODE_IMPORTED_URL)
                or p.content_type != 'application/pdf'):
            continue
        try:
            secondary += filenames.expected_name(item, p, b, template, rules) != filenames.current_name(p)
        except filenames.NameNotComputable:
            pass
    failures = {f'renommage échoué · {p.key}': L(
                    en=f"{p.key} · {display(p, filenames.current_name(p))} missing, its folder contains "
                       f"{display(p, other)}",
                    fr=f"{p.key} · {display(p, filenames.current_name(p))} absent, son dossier "
                       f"contient {display(p, other)}")
              for p in b.attachments.values() if (other := filenames.other_file(p)) is not None}
    points |= failures
    n, total = sum(stale.values()), correct + sum(stale.values())
    main = L(en='main files', fr='fichiers principaux') if correct > 1 else L(en='main file', fr='fichier principal')
    carry = L(en='have', fr='portent') if correct > 1 else L(en='has', fr='porte')
    text = L(en=f'{correct} {main} out of {total} {carry} the name expected from the Zotero template',
             fr=f"{correct} {main} sur {total} {carry} le nom attendu d'après le modèle de Zotero")
    if n:
        lag = (L(en='are behind their item', fr='sont en retard sur leur fiche') if n > 1 else
               L(en='is behind its item', fr='est en retard sur sa fiche'))
        breakdown = ', '.join(f'{v} {state_label(k, v)}' for k, v in stale.items())
        text += L(en=f', {n} {lag} ({breakdown})', fr=f', {n} {lag} ({breakdown})')
    text += '.'
    if failures:
        atts = lang_plural(len(failures), en='attachment', fr='pièce jointe')
        point = L(en='point', fr='pointent') if len(failures) > 1 else L(en='points', fr='pointe')
        text += L(en=f' {atts} {point} to a missing file while its folder contains another one (local renaming '
                     f'failed).',
                  fr=f' {atts} {point} vers un fichier absent alors que son dossier en contient un autre '
                     f'(renommage local échoué).')
    if uncomputable:
        names = lang_plural(uncomputable, en='name', fr='nom')
        not_computed = (L(en='not computed', fr='non calculés') if uncomputable > 1 else
                        L(en='not computed', fr='non calculé'))
        text += L(en=f' {names} {not_computed}, since the conjunction between two authors is unknown '
                     f'(`conjonction` setting of config.toml).',
                  fr=f' {names} {not_computed}, faute de connaître la conjonction de deux auteurs '
                     f'(réglage `conjonction` de config.toml).')
    if secondary:
        n_secondary = lang_plural(secondary, en='secondary PDF', fr='PDF secondaire')
        text += L(en=f' {n_secondary} under another name, which Zotero does not rename (information).',
                  fr=f' {n_secondary} sous un autre nom, que Zotero ne renomme pas (information).')
    if linked:
        n_linked = lang_plural(linked, en='main linked file', fr='fichier lié')
        if linked > 1:
            text += L(en=f' {n_linked}, which Zotero does not rename by default (information).',
                      fr=f' {n_linked} principaux, que Zotero ne renomme pas par défaut (information).')
        else:
            text += L(en=f' {n_linked}, which Zotero does not rename by default (information).',
                      fr=f' {n_linked} principal, que Zotero ne renomme pas par défaut (information).')
    status = TO_REVIEW if n or failures else (INFO if uncomputable or secondary or linked else OK)
    remedy = filenames_remedy()
    if failures:
        remedy += L(en=' After a failed renaming, give the file back the name the attachment carries, with Zotero '
                       'closed.',
                    fr=' Après un renommage échoué, redonner au fichier le nom que porte la pièce jointe, '
                       'Zotero fermé.')
    return Section(L(en='File names', fr='Noms des fichiers'), status, text, list(points.values()), remedy, points)


def state_label(state: str, count: int = 1) -> str:
    """Internal state of a file name as shown (in the plural for a count above 1, in French)."""
    labels = {'présent': L(en='present', fr='présent'), 'absent du disque': L(en='missing from the disk',
                                                                              fr='absent du disque'),
              'introuvable': L(en='not found', fr='introuvable'), 'écarté': L(en='skipped', fr='écarté'),
              'absent, non renommé': L(en='missing, not renamed', fr='absent, non renommé'),
              'sur zotero.org': L(en='on zotero.org', fr='sur zotero.org')}
    plurals = {'présent': 'présents', 'absent du disque': 'absents du disque', 'introuvable': 'introuvables',
               'écarté': 'écartés', 'absent, non renommé': 'absents, non renommés'}
    if count > 1 and lang_current() == 'fr':
        return plurals.get(state, state)
    return labels.get(state, state)


def _fallback_names(b: Library, hidden: set[str], cause: str) -> Section:
    outside = [p for p in b.attachments.values() if p.mode in (MODE_IMPORTED, MODE_IMPORTED_URL)
            and p.content_type == 'application/pdf' and p.path.startswith('storage:')
            and not FALLBACK_TEMPLATE.match(Path(p.path[len('storage:'):]).stem)]
    points = {p.key: f"{p.key} · {mask() if p.key in hidden else p.path[len('storage:'):][:90]}" for p in outside}
    pdfs = lang_plural(len(outside), en='PDF', fr='PDF')
    return Section(L(en='File names', fr='Noms des fichiers'), TO_REVIEW if outside else OK,
                   L(en=f'Zotero template that zot-clean cannot compute ({cause}). {pdfs} not in the form '
                        f'"Author - Year - Title" or "Author - Title".',
                     fr=f"Modèle de Zotero que zot-clean ne sait pas calculer ({cause}). {pdfs} "
                        f"hors de la forme « Auteur - Année - Titre » ou « Auteur - Titre »."),
                   list(points.values()), filenames_fallback_remedy(), points)


# 10
def structure(b: Library, cfg: Config) -> Section:
    m = cfg.method
    roots = sorted(c.name for c in b.collections.values() if c.parent is None)
    missing = [r for r in m.roots if r not in roots]
    surplus = [r for r in roots if r not in m.roots]
    # Depth measured under the subjects root if it exists (archives keep the old classification).
    subjects = [c.id for c in b.collections.values() if c.parent is None and c.name == m.subjects]
    measured = [c for c in b.collections if not subjects or b.root(c) == subjects[0]]
    depth = max((b.depth(c) for c in measured), default=0)
    children = {c.parent for c in b.collections.values()}
    occupied = {c for e in b.all_items.values() for c in e.collections}
    # An empty Inbox is the goal after sorting, not a collection to delete.
    empties = [b.path(c) for c, x in b.collections.items() if c not in children and c not in occupied
             and not (x.parent is None and x.name == m.inbox)]
    multiple = sum(1 for e in b.items if len(e.collections) > 1)
    n_roots = lang_plural(len(roots), en='collection', fr='collection')
    n_empties = lang_plural(len(empties), en='collection', fr='collection')
    n_multiple = lang_plural(multiple, en='item', fr='référence')
    under = L(en=f' under “{m.subjects}”', fr=f' sous « {m.subjects} »') if subjects else ''
    empty = L(en='empty', fr='vides') if len(empties) > 1 else L(en='empty', fr='vide')
    filed = L(en='filed', fr='rangées') if multiple > 1 else L(en='filed', fr='rangée')
    text = L(en=f'{n_roots} at the root, maximum depth {depth}{under}, {n_empties} {empty}, {n_multiple} {filed} in '
                f'several places.',
             fr=f'{n_roots} à la racine, profondeur maximale {depth}{under}, {n_empties} {empty}, '
                f'{n_multiple} {filed} à plusieurs endroits.')
    if missing:
        names = ', '.join(missing)
        text += L(en=f' Method roots missing: {names}.', fr=f' Racines de la méthode absentes : {names}.')
    points = {f'racine · {r}': L(en=f'root outside the method: {r}', fr=f'racine hors méthode : {r}')
              for r in surplus} | {
        f'vide · {v}': L(en=f'empty: {v}', fr=f'vide : {v}') for v in sorted(empties)}
    details = list(points.values())
    compliant = not missing and not surplus and depth <= m.max_depth + 1 and not empties
    remedy = L(en='The subjects outline (step 4) will propose a structure from the existing collections, then filing '
                  '(step 5) will move the items into it and archive the old classification.',
               fr='Le plan du fonds (étape 4) proposera une structure à partir des collections existantes, '
                  'puis le rangement (étape 5) y déplacera les références et archivera l\'ancien classement.')
    without, remaining = [], [p for p in m.projects if p not in missing]
    for r in missing:
        without += ([f'projets = {json.dumps(remaining, ensure_ascii=False)}'] if r in m.projects else
                 [f'{n} = ""' for n, a in (('inbox', 'inbox'), ('fonds', 'subjects'), ('archives', 'archives'))
                  if getattr(m, a) == r])
    if without:
        forms = ', '.join(f'`{x}`' for x in dict.fromkeys(without))
        remedy += L(en=f' A missing root can be created in Zotero if needed. If it is of no use (no projects, no '
                       f'archives), write it in config.toml, section [methode], in the form {forms}, so that the '
                       f'audit stops asking for it.',
                    fr=f" Une racine absente se crée dans Zotero au besoin. Sans usage pour elle (pas de projets, "
                       f"pas d'archives), l'écrire dans config.toml, section [methode], sous la forme {forms}, "
                       f"pour que l'audit ne la réclame plus.")
    return Section(L(en='Collection structure', fr='Structure des collections'), OK if compliant else TO_REVIEW,
                   text, details, remedy, points)


# 11
def sync_check(b: Library) -> Section:
    unsynced = Counter(e.type for e in b.all_items.values() if not e.synced)
    cols = sum(1 for c in b.collections.values() if not c.synced)
    n_unsynced = lang_plural(sum(unsynced.values()), en='item', fr='élément')
    n_cols = lang_plural(cols, en='collection', fr='collection')
    n_invalid = lang_plural(len(b.invalid_keys), en='item', fr='élément')
    text = L(en=f'{n_unsynced} and {n_cols} not synced yet, {n_invalid} with an invalid key.',
             fr=f'{n_unsynced} et {n_cols} pas encore synchronisés, {n_invalid} à clé invalide.')
    details = [L(en=f'invalid key: {k}', fr=f'clé invalide : {k}') for k in b.invalid_keys] + [
        L(en=f'not synced: {t} ({n})', fr=f'non synchronisé : {t} ({n})') for t, n in unsynced.most_common()]
    remedy = L(en='A few unsynced items are normal (recent changes). An invalid key blocks sync and must be '
                  'repaired before any cleanup.',
               fr='Quelques éléments non synchronisés sont normaux (modifications récentes). Une clé invalide '
                  'bloque la synchronisation et doit être réparée avant tout nettoyage.')
    points = {k: L(en=f'invalid key: {k}', fr=f'clé invalide : {k}') for k in b.invalid_keys}
    if b.account.id is None:  # cleanup writes through zotero.org, so all its commands refuse
        text = L(en='Zotero has never synced this library with a zotero.org account. ',
                 fr="Zotero n'a jamais synchronisé cette bibliothèque avec un compte zotero.org. ") + text
        remedy = L(en="Cleanup modifies the library through zotero.org, so it requires sync. In Zotero, open "
                      "Settings › Sync, sign in to your zotero.org account (create one if needed), sync and wait "
                      "for it to finish, then, if not done yet, save the API key with `zc init`. ",
                   fr="Le nettoyage modifie la bibliothèque en passant par zotero.org, il demande la "
                      "synchronisation. Dans Zotero, ouvrir Réglages › Synchronisation, se connecter à son compte "
                      "zotero.org (le créer au besoin), synchroniser et attendre la fin, puis, si ce n'est fait, "
                      "enregistrer la clé API avec `zc init`. ") + remedy
        points['compte'] = L(en='library never synced', fr='bibliothèque jamais synchronisée')
    return Section(L(en='Sync', fr='Synchronisation'), TO_REVIEW if b.invalid_keys or b.account.id is None
                   else (INFO if unsynced or cols else OK), text, details, remedy, points)


def run_audit(b: Library, cfg: Config, fingerprints: bool = True, online: dict[str, bool] | None = None,
            cause: str = '', storage: str | None = None, automatic: bool | None | str = '') -> list[Section]:
    from zot_clean.privacy import hidden_keys
    m = hidden_keys(b, cfg)
    storage = bbt.file_storage(cfg.zotero_dir) if storage is None else storage
    sections = [figures(b), without_collection(b, cfg, m), duplicates(b, cfg, m), metadata(b, m),
                missing_attachments(b, m, online, cause, storage)]
    sections.append(identical_pdfs(b, cfg, m, storage) if fingerprints else
                    Section(L(en='Identical PDFs', fr='PDF identiques'), INFO,
                            L(en='Check skipped (option --no-hashes).', fr='Contrôle sauté (option --no-hashes).')))
    sections += [tags(b, cfg, automatic), use_citation_keys(b, cfg, m), file_names(b, cfg, m, online, storage),
                 structure(b, cfg),
                 sync_check(b)]
    return sections


def report(sections: list[Section], b: Library, day: date | None = None, evolution: list[str] = ()) -> str:
    day = day or date.today()
    to_review = sum(1 for s in sections if s.status == TO_REVIEW)
    not_checked = sum(1 for s in sections if s.status == NOT_CHECKED)
    n_review = lang_plural(to_review, en='point', fr='point')
    n_total = len(sections)
    version = b.schema_version
    out = [L(en=f'# Audit of the Zotero library of {day:%d/%m/%Y}', fr=f'# Audit de la bibliothèque Zotero du {day:%d/%m/%Y}'),
           '',
           L(en=f'Read-only, nothing was modified. {n_review} out of {n_total} to review', fr=f"Lecture seule, rien n'a été modifié. {n_review} sur {n_total} à voir")
           + ((L(en=f', {not_checked} not checked for lack of files on the disk',
                 fr=f', {not_checked} non contrôlés faute de fichiers sur le disque') if not_checked > 1 else
               L(en=f', {not_checked} not checked for lack of files on the disk',
                 fr=f', {not_checked} non contrôlé faute de fichiers sur le disque')) if not_checked else '')
           + L(en=f'. Zotero database schema, version {version}.', fr=f'. Schéma de la base Zotero, version {version}.'),
           '', L(en='| | Check | Result |', fr='| | Contrôle | Résultat |'), '|---|---|---|']
    for i, s in enumerate(sections, 1):
        out.append(f'| {status_label(s.status)} | {i}. {s.title} | {s.summary.replace("|", "/")} |')
    if evolution:
        out += [''] + list(evolution)
    for i, s in enumerate(sections, 1):
        out += ['', f'## {i}. {s.title}', '', s.summary]
        if s.remedy and s.status != OK:
            out += ['', L(en='*What cleanup can do about it.* ', fr='*Ce que le nettoyage pourra faire.* ') + s.remedy]
        if s.details:
            out.append('')
            out += [f'- {d}' for d in s.details[:MAX_DETAILS]]
            if len(s.details) > MAX_DETAILS:
                more = len(s.details) - MAX_DETAILS
                out.append(L(en=f'- … and {more} more', fr=f'- … et {more} autres'))
    return '\n'.join(out) + '\n'
