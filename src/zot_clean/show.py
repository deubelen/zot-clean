"""Records shown in full to the agent (`zc show`, D127).

To judge a group of duplicates, identical PDFs or a metadata case, the agent
reads the complete fields of the records and the beginning of the text of their
PDFs, locally, before asking the user. An attachment key designates its record.
A confidential record (D126) is never shown, nor is the text of its PDFs if
`exclure_texte_integral` is set. The text of notes is never shown, only their
number.
"""

from pathlib import Path

from zot_clean import privacy
from zot_clean.audit import year, download_advice, is_pdf, type_name, norm
from zot_clean.config import Config
from zot_clean.lang import L, plural
from zot_clean.reader import Library

PAGES = 2
CHARACTERS = 1500


def roles() -> dict[str, str]:
    """Zotero roles other than author, shown to judge a chapter (chapter author or editor of the book?)."""
    return {'editor': L(en='editor', fr='directeur'),
            'seriesEditor': L(en='series editor', fr='directeur de collection'),
            'translator': L(en='translator', fr='traducteur'),
            'contributor': L(en='contributor', fr='contributeur'),
            'bookAuthor': L(en='book author', fr="auteur de l'ouvrage"),
            'reviewedAuthor': L(en='reviewed author', fr='auteur recensé')}


def pdf_text(path: Path, pages: int = PAGES, limit: int = CHARACTERS) -> str:
    """Beginning of the text of a PDF, or an explanation in parentheses when there is none."""
    import logging
    from pypdf import PdfReader
    # pypdf reports every irregularity of a PDF (fonts, misplaced objects): noise of no use for judging.
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    try:
        reader = PdfReader(path)
        text = ' '.join((page.extract_text() or '') for page in reader.pages[:pages])
    except Exception as e:  # damaged, encrypted or non-standard PDF: pypdf raises very varied errors
        return L(en=f'(unreadable text: {type(e).__name__})', fr=f'(texte illisible : {type(e).__name__})')
    # A line break is a word boundary: replaced by a space, not dropped like the other non-printable characters.
    text = ' '.join(''.join(c if c.isprintable() else ' ' for c in text).split())
    if not text:
        return L(en='(no text, PDF scanned without character recognition?)',
                 fr='(aucun texte, PDF scanné sans reconnaissance de caractères ?)')
    # Badly encoded fonts: pypdf returns a run of symbols. Real text is more than 75% letters.
    if sum(c.isalpha() or c.isspace() for c in text) < 0.75 * len(text):
        return L(en='(unreadable text, badly encoded fonts in the PDF)',
                 fr='(texte illisible, polices du PDF mal encodées)')
    return text[:limit] + (' […]' if len(text) > limit else '')


def describe(b: Library, cfg: Config, keys: list[str]) -> str:
    by_key = b.by_key()
    # An attachment or child note key designates its item.
    parents = {p.key: p.parent for p in b.attachments.values()}
    parents |= {b.all_items[n].key: parent for n, parent in b.notes.items() if n in b.all_items and parent is not None}
    hidden = privacy.hidden_keys(b, cfg)
    out, missing = [], []
    # Each item once, in the order of the keys, with the attachments and notes asked for under it.
    asked: dict[str, tuple] = {}
    for key in dict.fromkeys(keys):
        child = key in parents
        item = b.all_items.get(parents[key]) if child else by_key.get(key)
        if item is None:
            asked[key] = (None, set())
        else:
            asked.setdefault(item.key, (item, set()))[1].update({key} if child else set())
    for key, (item, designated) in asked.items():
        if item is None:
            out += [f'## {key}', '', L(en='No item or attachment with this key outside the Zotero trash. An item merged '
                                          'or sent to the trash by a plan is there, as expected.',
                                       fr='Aucune fiche ni pièce jointe de cette clé hors de la corbeille de Zotero. Une '
                                          'fiche fusionnée ou mise à la corbeille par un plan y est, comme prévu.'), '']
            continue
        if item.key in hidden or designated & hidden:
            out += [f'## {item.key} · {privacy.mask()}', '',
                    L(en='Excluded by the privacy filter. Ask the user to look at it in Zotero.',
                      fr="Exclue par le filtre de confidentialité. Demander à l'utilisateur de la regarder dans Zotero."), '']
            continue
        out += _item(b, cfg, item, designated, missing, hidden)
    if missing := list(dict.fromkeys(missing)):
        # D168: without the file, neither the text nor the fingerprint of the PDF can be used to judge.
        from zot_clean import bbt
        n = len(missing)
        pdfs = plural(n, en='PDF', fr='PDF')
        verb = L(en='are', fr='sont absents') if n > 1 else L(en='is', fr='est absent')
        keys_list = ', '.join(missing)
        out += [L(en=f"**Warning.** {pdfs} of these items {verb} missing from the disk ({keys_list}), "
                     f"so the text could not be read. ",
                  fr=f"**Attention.** {pdfs} de ces fiches {verb} du disque ({keys_list}), "
                     f"leur texte n'a pas pu être lu. ")
                + download_advice(bbt.file_storage(cfg.zotero_dir), L(en='read them', fr='les lire'),
                                  bbt.downloads_at_sync(cfg.zotero_dir)), '']
    return '\n'.join(out)


def _item(b: Library, cfg: Config, item, designated: set[str], missing: list[str] | None = None,
           hidden: frozenset[str] | set[str] = frozenset()) -> list[str]:
    out = [f'## {item.key} · {type_name(item.type)}', '']
    fields = dict(item.fields)
    if 'date' in fields:  # Zotero stores « 2018-00-00 2018 »: the sortable date, then the date as entered
        fields['date'] = fields['date'].split(' ', 1)[-1]
    colon = L(en=': ', fr=' : ')
    if 'title' in fields:
        out.append(f"- title{colon}{fields.pop('title')}")
    out += [f'- {k}{colon}{v}' for k, v in sorted(fields.items()) if v]
    if item.creators:
        role_names = roles()
        out.append(L(en='- creators: ', fr='- créateurs : ') + ' ; '.join(
            (f'{n}, {p}' if p else n) + (f' ({role_names.get(r, r)})' if r and r != 'author' else '')
            for (n, p), r in zip(item.creators, item.roles)))
    if item.collections:
        out.append(L(en='- collections: ', fr='- collections : ') + ' ; '.join(sorted(b.path(c) for c in item.collections)))
    if item.tags:
        out.append(L(en='- tags: ', fr='- tags : ') + ', '.join(n + (L(en=' (automatic)', fr=' (auto)') if t == 1 else '') for n, t in item.tags))
    notes = [b.all_items[n].key for n, parent in b.notes.items() if parent == item.id and n in b.all_items]
    if notes:
        asked = ', '.join(sorted(k for k in notes if k in designated))
        out.append(L(en=f'- notes: {len(notes)}', fr=f'- notes : {len(notes)}')
                   + (L(en=f' ({asked}, requested key, text never shown)',
                        fr=f' ({asked}, clé demandée, texte jamais montré)') if asked else ''))
    if item.type == 'note':
        out.append(L(en='The text of a note is never shown.', fr="Le texte d'une note n'est jamais montré."))
    for i, p in sorted(b.attachments.items(), key=lambda x: x[1].key):
        if p.parent != item.id:
            continue
        if p.key in hidden:  # excluded attachment under a public item (D188)
            out += ['', L(en=f'### Attachment {p.key} · {privacy.mask()}', fr=f'### Pièce jointe {p.key} · {privacy.mask()}')]
            continue
        name = p.file.name if p.file else p.path or L(en='web link', fr='lien web')
        absent = p.file is not None and not p.file.is_file()
        details = [x for x in (f'{b.annotations[i]} annotation(s)' if b.annotations.get(i) else '',
                               L(en='requested key', fr='clé demandée') if p.key in designated else '',
                               L(en='file missing from the disk', fr='fichier absent du disque') if absent else '')
                   if x]
        out += ['', L(en=f'### Attachment {p.key} · {name}', fr=f'### Pièce jointe {p.key} · {name}')
                + (f" ({', '.join(details)})" if details else '')]
        if not is_pdf(p):
            continue
        if absent and missing is not None:
            missing.append(p.key)
        if cfg.privacy.exclude_full_text:
            out.append(L(en='(PDF text excluded by the configuration)', fr='(texte des PDF exclu par la configuration)'))
        elif p.file is None or absent:
            out.append(L(en='(file missing from the disk, text not read)', fr='(fichier absent du disque, texte non lu)'))
        else:
            out.append(pdf_text(p.file))
    return out + ['']


def describe_tag(b: Library, cfg: Config, name: str, limit: int = 50) -> str:
    """Items that carry a tag (`zc show --tag`, D156), to judge its fate: title, author, year and
    collections of the records, with the type of the tag. A confidential identifier name designates its tag."""
    from zot_clean import tags as t
    u = t.usages(b, cfg)
    name = next((n for n in u if u[n].confidential and t.identifier(n) == name), name)
    if name not in u:
        similar = sorted(n for n in u if t.form(n, cfg) == t.form(name, cfg) and not u[n].confidential)
        same = ', '.join(similar)
        return L(en=f'No item carries the tag “{name}”.', fr=f'Aucun élément ne porte le tag « {name} ».') + (
            L(en=f' Names of the same form: {same}.', fr=f' Noms de même forme : {same}.') if similar else '')
    x = u[name]
    shown = t.identifier(name) if x.confidential else name
    hidden = privacy.hidden_keys(b, cfg)
    n_all, n_items = len(x.all_items), len(x.items)
    out = [f'# Tag « {shown} »', '',
           L(en=f"{t.type_shown(x.readable_type)}, carried by {n_all} element(s), that is {n_items} item(s) directly "
                f"or through a child, in {x.dispersion} theme(s) of the subjects",
             fr=f"{t.type_shown(x.readable_type)}, porté par {n_all} élément(s), soit {n_items} fiche(s) directement "
                f"ou par un enfant, dans {x.dispersion} thème(s) du fonds")
           + (f" ({', '.join(th for th, _ in x.themes.most_common())})" if x.themes else '') + '.']
    if x.color:
        out.append(L(en=f'Colored tag ({x.color_rank}, {x.color}).', fr=f'Tag coloré ({x.color_rank}, {x.color}).'))
    if x.searches:
        out.append(L(en='Cited by the saved searches ', fr='Cité par les recherches enregistrées ')
                   + ', '.join(L(en=f'“{r}”', fr=f'« {r} »') for r in x.searches) + '.')
    out.append('')
    all_items = sorted((b.all_items[i] for i in x.all_items),
                      key=lambda e: (e.key in hidden, not e.is_item, norm(e.title), e.key))
    for el in all_items[:limit]:
        typ = dict(el.tags).get(name, 0)
        auto = L(en=' (automatic)', fr=' (automatique)') if typ == 1 else ''
        if el.key in hidden:
            out.append(f'- {el.key} · {privacy.mask()}{auto}')
            continue
        item = el if el.is_item else b.all_items.get(t.item_of(b, el) or -1)
        child = {'attachment': L(en='attachment', fr='pièce jointe'), 'note': 'note',
                 'annotation': 'annotation'}.get(el.type, el.type)
        what = '' if el.is_item else L(en=f'{child} of ', fr=f'{child} de ')
        cols = ' ; '.join(sorted(b.path(c) for c in item.collections)) if item else ''
        if item is None:
            out.append(L(en=f'- {el.key} · orphan {child}{auto}', fr=f'- {el.key} · {child} isolée{auto}'))
        else:
            out.append(f'- {el.key} · {what}{item.author or "?"}, {year(item) or L(en="n.d.", fr="s. d.")}, '
                       f'{item.title[:100] or L(en="(untitled)", fr="(sans titre)")}{auto}'
                       + (f' · {cols}' if cols else L(en=' · no collection', fr=' · aucune collection')))
    if len(all_items) > limit:
        out.append(L(en=f'- … and {len(all_items) - limit} other(s)', fr=f'- … et {len(all_items) - limit} autre(s)'))
    return '\n'.join(out) + '\n'
