"""File names computed from the metadata of their item (step 8, D147 to D150).

Zotero is authoritative (D148). The template is the library's synced setting `attachmentRenameTemplate`,
failing that Zotero's default template. The computation reproduces to the letter
`Zotero.Attachments.getFileBaseNameFromItem` (Zotero 10.0.5, `xpcom/attachments.js`), the engine of
`modules/templates.mjs`, the first creator (`firstCreator`, computed in SQL by `xpcom/data/items.js`) and the
cleaning of the name (`Zotero.Utilities.cleanTags`, then `Zotero.File.getValidFileName`). JavaScript strings
count in UTF-16 units, hence the truncations done here on that measure.

The engine covers the variables (creators, `firstCreator`, `year`, `itemType`, `attachmentTitle`, `accessDate`,
any item field) and the parameters `truncate`, `start`, `prefix`, `suffix`, `case`, `max`, `name`,
`namePartSeparator`, `join`, `initialize`, `initializeWith`. A template with conditions (`if`), regular
expressions (`match`, `replaceFrom`), `case="title"`, `localize` or `timeZone` raises `UnsupportedTemplate`;
`make_plan` then refuses and refers to the renaming by Zotero itself.

Only the main attachment of an item is renamed, chosen like `Zotero.Item.getBestAttachments` (D150).

`make_plan` prepares the step 8 plan, with one `filename` operation per outdated main attachment, which the
server accepts for an imported file and which each Zotero applies on disk at its next sync (D147, D161).
`for_sorting` computes the same operation for the Inbox triage, on the metadata as of its plan (D149).
"""

import dataclasses
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from zot_clean import bbt, privacy
from zot_clean.lang import L, plural
from zot_clean.reader import (NON_BASE_DATES, MODE_IMPORTED, MODE_IMPORTED_URL, MODE_LINKED, MODE_LINK, Library,
                               Item, Attachment, date_multipart, multipart as _multipart)
from zot_clean.plans import Group, Operation, Plan

DEFAULT_TEMPLATE = '{{ firstCreator suffix=" - " }}{{ year suffix=" - " }}{{ title truncate="100" }}'
# Zotero's default `autoRenameFiles.fileTypes` preference. Linked files are not renamed by default.
RENAMED_TYPES = ('application/pdf', 'application/epub+zip')
# `general.etAl`, the same in French, English and most of Zotero's languages.
ET_AL = 'et al.'
# Extension taken from the content type when the file name has none (`Zotero.MIME.getPrimaryExtension`).
EXTENSIONS = {'application/pdf': 'pdf', 'application/epub+zip': 'epub', 'text/html': 'html'}
# Zotero date fields other than the base field `date` (`globalSchemaMeta.fields`).
PATH_LENGTH_MAX = 250  # full path, under the historical Windows limit of 260 characters
NAME_BYTES_MAX = 255  # beyond that, Zotero shortens the name on download (`createShortened`)
RESERVED_NAMES = ({'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {f'COM{i}' for i in '123456789¹²³'}
                 | {f'LPT{i}' for i in '123456789¹²³'})

# Spaces removed by `String.prototype.trim` and matched by `\s` in JavaScript.
_JS_SPACES = '\t\n\x0b\x0c\r \xa0            ' \
              '    　﻿'
_JS_SPACE = f'[{_JS_SPACES}]'
_CONDITIONS = {'if', 'elseif', 'else', 'endif'}


def _rejected_parameters() -> dict[str, str]:
    return {'match': L(en='regular expression (match)', fr='expression régulière (match)'),
            'replaceFrom': L(en='replacement (replaceFrom)', fr='remplacement (replaceFrom)'),
            'replaceTo': L(en='replacement (replaceTo)', fr='remplacement (replaceTo)')}


class UnsupportedTemplate(Exception):
    """Zotero's template falls outside the subset that `zc` can compute."""


class NameNotComputable(Exception):
    """The name of an item cannot be computed (unknown conjunction, expression rejected by Zotero)."""


class UnknownConjunction(NameNotComputable):
    pass


# Template engine (`modules/templates.mjs`)

def _scanner(text: str, quotes_at_root: bool = False):
    """Port of `scanTemplateStructure`: (type, start, end, depth)."""
    depth, text_start, i = 0, 0, 0
    while i < len(text):
        c = text[i]
        if (quotes_at_root or depth > 0) and c in '"\'':
            if i > text_start:
                yield 'texte', text_start, i, depth
            end = text.find(c, i + 1)
            end = len(text) if end == -1 else end + 1
            yield 'chaine', i, end, depth
            i = text_start = end
        elif text.startswith('{{', i):
            if i > text_start:
                yield 'texte', text_start, i, depth
            yield 'ouvre', i, i + 2, depth
            depth += 1
            i = text_start = i + 2
        elif text.startswith('}}', i):
            if i > text_start:
                yield 'texte', text_start, i, depth
            depth -= 1
            yield 'ferme', i, i + 2, depth
            i = text_start = i + 2
        else:
            i += 1
    if len(text) > text_start:
        yield 'texte', text_start, len(text), depth


def _chunks(text: str) -> list[str]:
    """Port of `parseTemplateBrackets`: text and `{{ … }}` instructions in alternation."""
    res, start = [], 0
    for typ, d, f, nesting in _scanner(text):
        if typ == 'ouvre' and nesting == 0:
            res.append(text[start:d])
            start = d
        elif typ == 'ferme' and nesting == 0:
            res.append(text[start:f])
            start = f
    if start < len(text):
        res.append(text[start:])
    return res


def _literal(instruction: str) -> str | None:
    """Port of `parseStringLiteral`."""
    instruction = _trim(instruction)
    if not instruction or instruction[0] not in '"\'':
        return None
    q = instruction[0]
    m = re.fullmatch(f'{q}([^{q}]*){q}', instruction)
    return m.group(1) if m else None


def _camel(name: str) -> str:
    return re.sub(r'-(.)', lambda m: m.group(1).upper(), name)


def _attributes(chunk: str) -> dict[str, str]:
    """Port of `getAttributes`, on the whole instruction as Zotero does."""
    return {_camel(m.group(1)): m.group(2) if m.group(2) is not None else m.group(3)
            for m in re.finditer(r'([\w-]*) *=+ *(?:"([^"]*)"|\'([^\']*)\')', chunk, re.ASCII)}


def _operator(chunk: str) -> str:
    inner = _trim(chunk[2:-2])
    return re.split(_JS_SPACE + '+', inner, maxsplit=1)[0]


def valid_template(text: str) -> bool:
    """Port of `isTemplateValid`: matched braces and balanced conditions."""
    depth, start, levels = 0, 0, []
    for typ, d, _, _ in _scanner(text):
        if typ == 'ouvre':
            if depth == 0:
                start = d
            depth += 1
        elif typ == 'ferme':
            if depth == 0:
                return False
            depth -= 1
            if depth > 0:
                continue
            instruction = _trim(text[start + 2:d])
            op = re.split(_JS_SPACE + '+', instruction, maxsplit=1)[0]
            if op == 'if':
                levels.append(False)
            elif op in ('elseif', 'else'):
                if not levels or levels[-1]:
                    return False
                if op == 'else':
                    levels[-1] = True
            elif op == 'endif':
                if not levels:
                    return False
                levels.pop()
            elif instruction[:1] in ('"', "'") and _literal(instruction) is None:
                return False
    return depth == 0 and not levels


def normalize_template(text: str) -> str:
    """Port of `normalizeRenameTemplate`."""
    return _trim(re.sub(r'\r?\n|\r', '', text))


@dataclass(frozen=True)
class Template:
    text: str

    @classmethod
    def analyze(cls, text: str) -> 'Template':
        """Checks that the template stays within the subset computed here, otherwise raises `UnsupportedTemplate`."""
        text = normalize_template(text)
        if not valid_template(text):
            raise UnsupportedTemplate(L(en='malformed template, which Zotero replaces with its default template',
                                        fr='modèle mal formé, que Zotero remplace par son modèle par défaut'))
        for chunk in _chunks(text):
            if not chunk.startswith('{{'):
                continue
            if _literal(chunk[2:-2]) is not None:
                continue
            op = _operator(chunk)
            if op in _CONDITIONS:
                raise UnsupportedTemplate(L(en=f'condition "{op}"', fr=f'condition « {op} »'))
            attrs = _attributes(chunk)
            for name, cause in _rejected_parameters().items():
                if attrs.get(name):
                    raise UnsupportedTemplate(cause)
            if attrs.get('case') == 'title':
                raise UnsupportedTemplate(L(en='title case (case="title")', fr='casse de titre (case="title")'))
            if _camel(op) == 'itemType' and attrs.get('localize'):
                raise UnsupportedTemplate(L(en='translated item type (localize)',
                                            fr='type de fiche traduit (localize)'))
            if _camel(op) == 'accessDate' and attrs.get('timeZone'):
                raise UnsupportedTemplate(L(en='time zone (timeZone)', fr='fuseau horaire (timeZone)'))
        return cls(text)


def template_of(b: Library) -> str:
    """Template set in Zotero, like `getAttachmentRenameTemplate`: the default template if it is missing,
    empty or malformed."""
    text = b.settings.get('attachmentRenameTemplate')
    normal = normalize_template(text) if isinstance(text, str) else ''
    if not normal or not valid_template(normal):
        return DEFAULT_TEMPLATE
    return text


# Strings the JavaScript way

def _trim(s: str) -> str:
    return s.strip(_JS_SPACES)


def _substring(s: str, start: int, end: int | None = None) -> str:
    """`String.prototype.substring` in UTF-16 units. A character cut in two leaves a half pair, removed afterwards
    by the cleaning, as in Zotero."""
    units = s.encode('utf-16-le', 'surrogatepass')
    n = len(units) // 2
    start = max(0, min(start, n))
    end = n if end is None else max(0, min(end, n))
    start, end = min(start, end), max(start, end)
    return units[2 * start:2 * end].decode('utf-16-le', 'surrogatepass')


def _integer(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def clean(name: str) -> str:
    """Port of `cleanTags` then `getValidFileName` (without `skipXML`)."""
    name = re.sub(r'<br[^>]*>', '\n', name, flags=re.IGNORECASE)
    name = re.sub(r'</p>', '\n\n', name, flags=re.IGNORECASE)
    name = re.sub(r'<[^>]+>', '', name)
    name = re.sub(r'[/\\?*:|"<>]', '', name)
    name = re.sub(r'[\r\n\t]+', ' ', name)
    name = re.sub('[ - ]', ' ', name)
    name = re.sub('[​-‎]', '', name)
    name = re.sub('[  ]', ' ', name)
    # Without the u flag, Zotero's class [\ud800-\udfff] removes both halves of any character outside the
    # basic plane (emoji, rare ideograms): here, the half pairs and the characters beyond U+FFFF.
    name = re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿\U00010000-\U0010ffff]', '', name)
    name = unicodedata.normalize('NFC', name)
    name = re.sub('[⁨⁩]', '', name)
    name = re.sub(r'^\.', '', name)
    if name in ('', '.', '..'):
        name = '_'
    return name


def _casing(v: str, casing: str) -> str:
    if casing == 'upper':
        return v.upper()
    if casing == 'lower':
        return v.lower()
    if casing == 'sentence':
        return v[:1].upper() + v[1:]
    if casing == 'hyphen':
        v = re.sub(_JS_SPACE + '+-', '-', v)
        v = re.sub('-' + _JS_SPACE + '+', '-', v)
        return re.sub(_JS_SPACE + '+', '-', v.lower())
    if casing == 'snake':
        v = re.sub(_JS_SPACE + '+_', '_', v)
        v = re.sub('_' + _JS_SPACE + '+', '_', v)
        return re.sub(_JS_SPACE + '+', '_', v.lower())
    if casing in ('camel', 'pascal'):
        # [^\p{L}\d]+(.) with the u flag: a run of characters that are neither letters nor ASCII digits.
        v = re.sub(r'(?:(?![0-9])[\W\d_])+([^\n\r  ])', lambda m: m.group(1).upper(), v.lower())
        return v[:1].upper() + v[1:] if casing == 'pascal' else v
    return v


# Item as seen by the template

@dataclass
class Rules:
    """What the computation draws from Zotero's database and its language."""
    main_creator: dict[str, str]
    base_fields: dict[str, dict[str, str]]
    conjunction: str | None = None  # text between two names (« A et B »), None if unknown

    @classmethod
    def of(cls, b: Library, conjunction: str | None = None) -> 'Rules':
        return cls(b.main_creator, b.base_fields, conjunction)

    def field_name(self, item: Item, name: str, raw: bool = False) -> str:
        """`item.getField(name, raw, true)`: the type-specific field for a base field, readable multipart date."""
        specific = self.base_fields.get(item.type, {}).get(name, name)
        v = item.fields.get(specific, '')
        if not raw and v and (specific in NON_BASE_DATES or name == 'date'
                               or self.base_fields.get(item.type, {}).get('date') == specific):
            if _multipart(v):
                v = v[11:]
        return v

    def creators(self, item: Item, which_ones: str) -> list[tuple[str, str]]:
        """(last name, first name) of the creators of one kind, in the order of the item."""
        if which_ones == 'authors':
            roles = {self.main_creator.get(item.type)}
        elif which_ones == 'editors':
            roles = {'editor', 'seriesEditor'}
        else:
            return list(item.creators)
        return [c for c, r in zip(item.creators, item.roles) if r in roles]

    def first_creator(self, item: Item) -> str:
        """`firstCreator`: main role, failing that editors, directors, contributors."""
        for role in (self.main_creator.get(item.type), 'editor', 'director', 'contributor'):
            names = [c[0] for c, r in zip(item.creators, item.roles) if r == role]
            if len(names) == 1:
                return names[0]
            if len(names) == 2:
                if self.conjunction is None:
                    raise UnknownConjunction(L(en='conjunction of two authors unknown (`conjonction` setting)',
                                               fr='conjonction de deux auteurs inconnue (réglage `conjonction`)'))
                return names[0] + self.conjunction + names[1]
            if len(names) >= 3:
                return f'{names[0]} {ET_AL}'
        return ''

    def year(self, item: Item) -> str:
        v = self.field_name(item, 'date', raw=True)
        if not v:
            return ''
        sql = v[:10] if _multipart(v) else '0000-00-00'
        return '' if sql[:4] == '0000' else sql[:4]


def _creator_name(c: tuple[str, str], form: str, separator: str, initial: str, suffix_value: str) -> str:
    name, first_name = c

    def ini(v: str, yes: bool) -> str:
        return v[:1].upper() + suffix_value if yes else v

    if form in ('full', 'given-family', 'first-last'):
        return ini(first_name, initial in ('full', 'given', 'first')) + separator + ini(name, initial in ('full', 'family', 'last'))
    if form in ('full-reversed', 'family-given', 'last-first'):
        return ini(name, initial in ('full', 'family', 'last')) + separator + ini(first_name, initial in ('full', 'given', 'first'))
    if form in ('given', 'first'):
        return ini(first_name, initial in ('full', 'given', 'first'))
    return ini(name, initial in ('full', 'family', 'last'))


def _slice(listing: list, maximum) -> list:
    """`getSlicedCreatorsOfType`: `max` arrives as text, so "0" cuts nothing, a negative counts from the end."""
    if maximum is None:
        return listing
    n = _integer(maximum)
    if n is None or n == 0:
        return listing
    return listing[:n] if n > 0 else list(reversed(listing[n:]))


class _Render:
    """A name computation, with the state shared between the two passes of Zotero."""

    def __init__(self, item: Item, rules: Rules, attachment_title: str):
        self.item, self.rules, self.attachment_title = item, rules, attachment_title
        self.affix_chunks: list[tuple[str, str, str, str]] = []  # (value, raw, suffix, prefix)
        self.protected: list[str] = []

    def common(self, v: str, a: dict[str, str]) -> str:
        if not v:
            return ''
        prefix, suffix = a.get('prefix', ''), a.get('suffix', '')
        prefix = '' if prefix in ('\\', '/') else prefix
        suffix = '' if suffix in ('\\', '/') else suffix
        if self.protected:
            v = _sub_js('(' + '|'.join(self.protected) + ')', lambda m: '\\' + m.group(1) + '//', v)
        if (start := a.get('start')):
            v = _substring(v, _integer(start) or 0)
        if (length := a.get('truncate')):
            v = _substring(v, 0, _integer(length) or 0)
        v = _trim(v)
        raw_value, affix = v, False
        if prefix and not v.startswith(prefix):
            v, affix = prefix + v, True
        if suffix and not v.endswith(suffix):
            v, affix = v + suffix, True
        if affix:
            self.affix_chunks.append((v, raw_value, suffix, prefix))
        return _casing(v, a.get('case', ''))

    def variable(self, ident: str, a: dict[str, str]) -> str:
        f, r = self.item, self.rules
        ident = _camel(ident)
        families = ('authors', 'editors', 'creators')
        if ident in families:
            names = [_creator_name(c, a.get('name', 'family'), a.get('namePartSeparator', ' '),
                                  a.get('initialize', ''), a.get('initializeWith', '.'))
                    for c in _slice(r.creators(f, ident), a.get('max'))]
            return self.common(a.get('join', ', ').join(names), a)
        if ident.endswith('Count') and ident[:-5] in families:
            return self.common(str(len(r.creators(f, ident[:-5]))), a)
        if ident == 'firstCreator':
            return self.common(r.first_creator(f), a)
        if ident == 'year':
            return self.common(r.year(f), a)
        if ident == 'itemType':
            return self.common(f.type, a)
        if ident == 'attachmentTitle':
            return self.common(self.attachment_title, a)
        if ident == 'accessDate':
            return self.common(f.fields.get('accessDate', ''), a)
        # Any other name is an item field, empty if it does not exist for this type or at all.
        return self.common(r.field_name(f, ident), a)

    def generate(self, template: str) -> str:
        """Port of `generateHTMLFromTemplate`, without the conditions refused by `Template.analyze`."""
        html = ''
        for chunk in _chunks(template):
            if not chunk.startswith('{{'):
                html += chunk
                continue
            op = _operator(chunk)
            if op in _CONDITIONS:
                raise UnsupportedTemplate(L(en=f'condition "{op}"', fr=f'condition « {op} »'))
            literal = _literal(chunk[2:-2])
            if literal is not None:
                html += literal
            elif op:
                html += self.variable(op, _attributes(chunk))
        return html


def _sub_js(cause: str, replacement, text: str) -> str:
    """Expression built by Zotero without escaping: if JavaScript rejects it, Zotero fails too."""
    try:
        return re.sub(cause, replacement, text)
    except re.error as e:
        raise NameNotComputable(L(en=f'expression rejected ({e})', fr=f'expression rejetée ({e})')) from e


def base_name(item: Item, template: Template, rules: Rules, attachment_title: str = '') -> str:
    """Name without extension that Zotero gives the main file of `item` (`getFileBaseNameFromItem`)."""
    text = template.text
    renderer = _Render(item, rules, attachment_title)
    result = renderer.generate(text)
    # Second pass of Zotero: a suffix or prefix that would repeat is written only once.
    pairs: dict[str, str] = {}
    for _, raw_value, suffix, prefix in renderer.affix_chunks:
        if suffix and f'{raw_value}{suffix}{suffix}' in result:
            key = f'{raw_value}{suffix}{suffix}'
            if key not in renderer.protected:
                renderer.protected.append(key)
            pairs[key] = f'{raw_value}{suffix}'
        if prefix and f'{prefix}{prefix}{raw_value}' in result:
            key = f'{prefix}{prefix}{raw_value}'
            if key not in renderer.protected:
                renderer.protected.append(key)
            pairs[key] = f'{prefix}{raw_value}'
    if renderer.protected:
        text = _sub_js('(' + '|'.join(renderer.protected) + ')', lambda m: '\\' + m.group(1) + '//', text)
    result = renderer.generate(text)
    if pairs:
        cause = '(' + '|'.join(f'(?<!\\\\){p}(?!//)' for p in pairs) + ')'
        result = _sub_js(cause, lambda m: pairs.get(m.group(0), 'undefined'), result)
    return clean(result)


# Attachments

def current_name(p: Attachment) -> str:
    """`attachmentFilename`: the file name as the item carries it."""
    path = p.path
    for prefix in ('storage:', 'attachments:'):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    return re.split(r'[/\\]', path)[-1]


def present(p: Attachment) -> bool:
    return p.file is not None and p.file.is_file()


def extension(p: Attachment) -> str:
    """Like Zotero: the extension of the present file if it looks like one, otherwise that of the content type,
    and for a missing file the extension of the recorded name."""
    name = current_name(p)
    if present(p):
        ext = name.rsplit('.', 1)[1] if '.' in name else ''
        return ext if re.fullmatch(r'[A-Za-z0-9_]{1,10}', ext) else EXTENSIONS.get(p.content_type, '')
    m = re.search(r'\.([^.]+)$', name)
    return m.group(1) if m else ''


def expected_name(item: Item, p: Attachment, b: Library, template: Template, rules: Rules) -> str:
    """Full name, extension included, that Zotero would give the attachment `p` of `item`."""
    title = b.all_items[p.id].title if p.id in b.all_items else ''
    database = base_name(item, template, rules, title)
    ext = extension(p)
    return database + ('.' + ext if ext else '')


def attachments_of(b: Library, item: Item) -> list[Attachment]:
    """Attachments of the item in the order of `getBestAttachments`: PDF first, then the one whose URL is that
    of the item (then another URL, then none), then the oldest. Excluding links and trash."""
    return ordered(b, item, [p for p in b.attachments.values() if p.parent == item.id and p.mode != MODE_LINK
                               and p.id in b.all_items])


def ordered(b: Library, item: Item, attachments: list[Attachment]) -> list[Attachment]:
    """`attachments` in the order of `getBestAttachments` for `item`."""
    url = item.fields.get('url', '')

    def rank(p: Attachment):
        e = b.all_items[p.id]
        u = e.fields.get('url')
        url_rank = 2 if not u else (0 if u == url else 1)
        return (p.content_type != 'application/pdf', url_rank, e.date_added, p.id)

    return sorted(attachments, key=rank)


def main_attachment(b: Library, item: Item) -> Attachment | None:
    """The one Zotero opens on double-click and renames (`getBestAttachment`)."""
    attachments = attachments_of(b, item)
    return attachments[0] if attachments else None


def renamable(p: Attachment, linked: bool = False) -> bool:
    """`shouldAutoRenameAttachment` with the default settings: PDF or EPUB, imported (linked if `linked`),
    never a web page snapshot."""
    if p.mode == MODE_LINKED and not linked:
        return False
    if p.mode not in (MODE_IMPORTED, MODE_IMPORTED_URL, MODE_LINKED):
        return False
    if p.mode == MODE_IMPORTED_URL and p.content_type == 'text/html':
        return False
    return any(p.content_type.startswith(t) for t in RENAMED_TYPES)


def main_attachments(b: Library, linked: bool = False):
    """(item, main attachment) of the items whose main file Zotero would rename."""
    for item in b.items:
        p = main_attachment(b, item)
        if p is not None and renamable(p, linked):
            yield item, p


# Conjunction (D150)

def infer_conjunction(b: Library, template: Template) -> tuple[str | None, int]:
    """Most frequent conjunction in the names of the main files of two-creator items that Zotero named from
    `template`, and number of names that carry it."""
    rules = Rules.of(b)
    votes: Counter = Counter()
    for item, p in main_attachments(b):
        names = None
        for role in (rules.main_creator.get(item.type), 'editor', 'director', 'contributor'):
            found_list = [c[0] for c, r in zip(item.creators, item.roles) if r == role]
            if found_list:
                names = found_list
                break
        if not names or len(names) != 2 or not names[0] or not names[1]:
            continue
        current = unicodedata.normalize('NFC', current_name(p))
        a, z = (unicodedata.normalize('NFC', n) for n in names)
        i = current.find(z, len(a)) if current.startswith(a) else -1
        if i <= len(a) or i - len(a) > 12:
            continue
        candidate = current[len(a):i]
        rules.conjunction = candidate
        try:
            if expected_name(item, p, b, template, rules) == current_name(p):
                votes[candidate] += 1
        except NameNotComputable:
            pass
    if not votes:
        return None, 0
    return votes.most_common(1)[0]


# Zotero's word « et » (and) in common languages, for a library where no name reveals the conjunction.
CONJUNCTIONS = {'fr': ' et ', 'en': ' and ', 'de': ' und ', 'es': ' y ', 'it': ' e ', 'pt': ' e ', 'nl': ' en '}


def conjunction(b: Library, cfg, template: Template) -> str | None:
    """The `conjonction` setting of `config.toml` if filled in, otherwise deduced from the existing names (D150),
    otherwise from Zotero's language read in its profile (pilot rehearsal)."""
    word = getattr(cfg.method, 'conjunction', '') if cfg is not None else ''
    if word:
        return word if word != word.strip() else f' {word} '
    inferred = infer_conjunction(b, template)[0]
    if inferred is None and getattr(cfg, 'zotero_dir', None):
        return CONJUNCTIONS.get(bbt.zotero_language(cfg.zotero_dir))
    return inferred


# Cases set aside (D150)

def skip_cause(p: Attachment, new: str) -> str | None:
    """Reason not to give `new` to `p`, or None. Zotero does not fix these names, and `zc` does not fix them
    its own way: they are listed for a manual fix."""
    if p.file is not None:
        folder = p.file.parent
        old = unicodedata.normalize('NFC', current_name(p))
        target = unicodedata.normalize('NFC', new).casefold()
        if folder.is_dir():
            for f in folder.iterdir():
                n = unicodedata.normalize('NFC', f.name)
                if n != old and n.casefold() == target:
                    return L(en="name already taken in the attachment's folder",
                             fr='nom déjà pris dans le dossier de la pièce jointe')
    if new.endswith(('.', ' ')):
        return L(en='name ending with a dot or a space, refused by Windows',
                 fr='nom terminé par un point ou une espace, refusé par Windows')
    if new.split('.')[0].rstrip(' ').upper() in RESERVED_NAMES:
        return L(en='name reserved by Windows', fr='nom réservé de Windows')
    if len(new.encode('utf-8')) > NAME_BYTES_MAX:
        return L(en=f'name longer than {NAME_BYTES_MAX} bytes', fr=f'nom de plus de {NAME_BYTES_MAX} octets')
    if p.file is not None and len(str(p.file.parent / new)) > PATH_LENGTH_MAX:
        return L(en=f'path longer than {PATH_LENGTH_MAX} characters',
                 fr=f'chemin de plus de {PATH_LENGTH_MAX} caractères')
    return None


def other_file(p: Attachment) -> str | None:
    """For a missing imported file, the name of another file in its `storage/<KEY>/` folder (failed local
    rename, D150), Zotero's hidden files excluded."""
    if p.mode not in (MODE_IMPORTED, MODE_IMPORTED_URL) or p.file is None or p.file.is_file():
        return None
    folder: Path = p.file.parent
    if not folder.is_dir():
        return None
    others = sorted(f.name for f in folder.iterdir() if f.is_file() and not f.name.startswith('.'))
    return others[0] if others else None


# Step 8 plan (D147, D149, D150, D158)

STEP = 'noms'
API_MODES = ('imported_file', 'imported_url')  # files that the server renames, never a linked file
# Short title given by `setAutoAttachmentTitle` to the only file of its type on the item. That of an EPUB depends
# on Zotero's language, deduced from the conjunction (D150). Unknown language, an EPUB's title is left as is.
SHORT_TITLES = {'application/pdf': {None: 'PDF'},
                 'application/epub+zip': {' et ': 'Livre numérique', ' and ': 'Ebook'}}
NATURE = 'nom du fichier'


def renaming_by_zotero() -> str:
    return L(en='Have Zotero rename the files itself, in its settings (General, File Renaming, "Rename Files…" '
                'button), which applies its template to the whole library.',
             fr='Renommer les fichiers par Zotero lui-même, dans ses réglages (Général, renommage des '
                'fichiers, bouton « Renommer les fichiers… »), qui applique son modèle à toute la bibliothèque.')


class Computation:
    """Template and rules of the library, established once. Raises `UnsupportedTemplate`."""

    def __init__(self, b: Library, cfg):
        self.b = b
        self.template = Template.analyze(template_of(b))
        self.rules = Rules.of(b, conjunction(b, cfg, self.template))

    def name(self, item: Item, p: Attachment) -> str:
        return expected_name(item, p, self.b, self.template, self.rules)


def item_after(b: Library, item: Item, after: dict) -> Item:
    """Copy of `item` with the type, fields and creators that a plan writes (API values)."""
    type_ = after.get('itemType', item.type)
    dates = NON_BASE_DATES | {b.base_fields.get(type_, {}).get('date', 'date')}
    fields, creators, roles = dict(item.fields), list(item.creators), list(item.roles)
    for k, v in after.items():
        if k == 'creators':
            creators = [(c.get('lastName', c.get('name', '')), c.get('firstName', '')) for c in v or []]
            roles = [c.get('creatorType', '') for c in v or []]
        elif k != 'itemType' and isinstance(v, str):
            if v:
                fields[k] = date_multipart(v) if k in dates else v
            else:
                fields.pop(k, None)
    return dataclasses.replace(item, type=type_, fields=fields, creators=creators, roles=roles)


def new_title(d: dict, new: str, alone: bool, conj: str | None) -> str | None:
    """Title of the attachment after renaming, or None if it does not change. Like Zotero's
    `renameFilesFromParent` for a file renamed without being on disk: a title equal to the old name, with or
    without extension and ignoring case, becomes the short title of the type (« PDF ») if the attachment is the
    only file of that type on the item, otherwise the new name without extension (`setAutoAttachmentTitle`, D150)."""
    old, title = d.get('filename') or '', (d.get('title') or '').lower()
    if not old or title not in (old.lower(), re.sub(r'\.[^.]+$', '', old).lower()):
        return None
    short = SHORT_TITLES.get(d.get('contentType', ''))
    if alone and short is not None:
        return short.get(None) or short.get(conj)
    return re.sub(r'\.[^.]+$', '', new) or None


def _only_of_its_type(p: Attachment, attachments: list[Attachment]) -> bool:
    """`getFileAttachmentsWithContentType`: imported or linked files of the item, of the same type."""
    return all(q.key == p.key for q in attachments if q.mode != MODE_LINK and q.content_type == p.content_type)


def operation(computation: Computation, item: Item, p: Attachment, d: dict, attachments: list[Attachment],
              rank: int = 0) -> tuple[Operation | None, str]:
    """Operation that gives `p` (data `d` reread from the API) the name expected for `item`, or None and the reason
    for not renaming it (empty when the name is already right)."""
    if d.get('linkMode') not in API_MODES or d.get('deleted'):
        return None, L(en='not a file imported on the server, or in the trash',
                       fr='pas un fichier importé sur le serveur, ou à la corbeille')
    try:
        new = computation.name(item, p)
    except NameNotComputable as e:
        return None, L(en=f'name not computed ({e})', fr=f'nom non calculé ({e})')
    old = d.get('filename') or ''
    if new == old:
        return None, ''
    if cause := skip_cause(p, new):
        return None, cause
    before, after = {'filename': old}, {'filename': new}
    title = new_title(d, new, _only_of_its_type(p, attachments), computation.rules.conjunction)
    if title is not None and title != d.get('title', ''):
        before['title'], after['title'] = d.get('title', ''), title
    return Operation(p.key, before, after, rank, NATURE), ''


def missing_reason(p: Attachment, storage: str, online: dict[str, bool] | None) -> str:
    """Why a file missing from the disk is not renamed, empty if it is (D150, D158). Only a Zotero that syncs its
    files through zotero.org applies the new name by redownloading a file stored there."""
    if storage == bbt.WEBDAV:
        return L(en='missing from the disk, not renamed (files synced through WebDAV)',
                 fr='absent du disque, non renommé (fichiers synchronisés par WebDAV)')
    if storage == bbt.NONE:
        return L(en='missing from the disk, not renamed (file sync disabled in Zotero)',
                 fr='absent du disque, non renommé (synchronisation des fichiers désactivée dans Zotero)')
    if storage != bbt.ZOTERO_ORG:
        return L(en='missing from the disk, not renamed (file sync unknown, Zotero profile not found)',
                 fr='absent du disque, non renommé (synchronisation des fichiers inconnue, profil de Zotero '
                    'introuvable)')
    if online is None:
        return L(en='missing from the disk, not renamed for lack of having checked its presence on zotero.org',
                 fr="absent du disque, non renommé faute d'avoir vérifié sa présence sur zotero.org")
    if not online.get(p.key):
        return L(en="not found, neither on the disk nor on zotero.org (point 5 of the audit)",
                 fr="introuvable, ni sur le disque ni sur zotero.org (point 5 de l'audit)")
    return ''


def missing(b: Library) -> list[str]:
    """Keys of the renamable main attachments whose file is missing, to look for on zotero.org (D133)."""
    return [p.key for _, p in main_attachments(b) if not present(p)]


def make_plan(b: Library, cfg, client, online: dict[str, bool] | None = None,
              storage: str | None = None) -> tuple[Plan, str]:
    """Plan with one group per item whose main file carries a name outdated relative to its metadata. Plans only
    the difference between the current and expected names, and can therefore be rerun after each pass (D119).
    `online` says whether a missing file is on zotero.org, `storage` how Zotero syncs files (read from the
    profile if not given)."""
    try:
        computation = Computation(b, cfg)
    except UnsupportedTemplate as e:
        raise UnsupportedTemplate(
            L(en=f"The naming template set in Zotero goes beyond what zot-clean can compute ({e}). "
                 f"{renaming_by_zotero()}",
              fr=f'Le modèle de noms réglé dans Zotero sort de ce que zot-clean sait calculer '
                 f'({e}). {renaming_by_zotero()}')) from e
    if (server := client.server_version()) > b.version:
        from zot_clean.apply import stale_copy
        raise SystemExit(stale_copy(b.version, server))
    storage = bbt.file_storage(cfg.zotero_dir) if storage is None else storage
    hidden = privacy.hidden_keys(b, cfg)
    candidates, left_aside = [], []  # left_aside: (attachment, expected name or '', reason)
    for item, p in main_attachments(b):
        try:
            expected = computation.name(item, p)
        except NameNotComputable as e:
            left_aside.append((p, '', L(en=f'name not computed ({e})', fr=f'nom non calculé ({e})')))
            continue
        if expected == current_name(p):
            continue
        if not present(p) and (reason := missing_reason(p, storage, online)):
            left_aside.append((p, expected, reason))
            continue
        candidates.append((item, p, expected))
    data = client.items([p.key for _, p, _ in candidates])
    retained = []
    for item, p, expected in candidates:
        if (d := data.get(p.key)) is None:
            left_aside.append((p, expected, L(en='not found on the server', fr='introuvable sur le serveur')))
            continue
        op, reason = operation(computation, item, p, d, attachments_of(b, item))
        if op is not None:
            retained.append((item, p, op))
        elif reason:
            left_aside.append((p, expected, reason))
    # Present files first: the trial covers files the user can open right away.
    retained.sort(key=lambda x: (not present(x[1]), unicodedata.normalize('NFC', x[0].title).casefold(), x[0].key))
    groups = [Group(item.key, privacy.mask() if p.key in hidden else item.title[:80], [op])
               for item, p, op in retained]
    linked = sum(1 for item, p in main_attachments(b, linked=True) if p.mode == MODE_LINKED and _outdated(computation, item, p))
    files = plural(len(groups), en='file', fr='fichier')
    plan = Plan(STEP, client.user, groups,
                description=L(en=f'File names, {files} to rename.', fr=f'Noms des fichiers, {files} à renommer.'))
    return plan, _report(retained, left_aside, hidden, storage, linked, cfg.writing.trial, computation)


def _outdated(computation: Computation, item: Item, p: Attachment) -> bool:
    try:
        return computation.name(item, p) != current_name(p)
    except NameNotComputable:
        return False


def describe(op: Operation, mask: bool) -> str:
    """« old » → « new », and the title if it changes, showing nothing of a confidential item (D126)."""
    if mask:
        return L(en='file name', fr='nom du fichier') + (
            L(en=' and attachment title', fr=' et titre de la pièce jointe') if 'title' in op.after else '')
    old, new = op.before['filename'], op.after['filename']
    text = L(en=f'"{old}" → "{new}"', fr=f'« {old} » → « {new} »')
    if 'title' in op.after:
        old, new = op.before['title'], op.after['title']
        text += L(en=f', title "{old}" → "{new}"', fr=f', titre « {old} » → « {new} »')
    return text


def sync_notes() -> dict[str, str]:
    return {
        bbt.ZOTERO_ORG: L(en='Zotero syncs files through zotero.org.', fr='Zotero synchronise les fichiers par zotero.org.'),
        bbt.WEBDAV: L(en="Zotero syncs files through WebDAV. The new name goes through zotero.org with the "
                         "attachment's data, and Zotero renames the local file at sync. This case has not been "
                         "checked with a WebDAV server yet. Check the trial with particular care, on this computer "
                         "and, if there is one, on another machine or a tablet.",
                      fr="Zotero synchronise les fichiers par WebDAV. Le nouveau nom passe par zotero.org avec les "
                         "données de la pièce jointe, et Zotero renomme le fichier local à la synchronisation. Ce "
                         "cas n'a pas encore été vérifié avec un serveur WebDAV. Vérifier l'essai avec un soin "
                         "particulier, sur cet ordinateur et, s'il y en a, sur un autre poste ou une tablette."),
        bbt.NONE: L(en='File sync is disabled in Zotero. The files present on the disk are renamed all the same, '
                       'by the sync of the data.',
                    fr='La synchronisation des fichiers est désactivée dans Zotero. Les fichiers présents sur le '
                       'disque sont renommés quand même, par la synchronisation des données.'),
    }


def _report(retained: list, left_aside: list, hidden: set[str], storage: str, linked: int, trial: int,
             computation: Computation) -> str:
    titles = sum('title' in op.after for _, _, op in retained)
    missing_renamed = sum(not present(p) for _, p, _ in retained)
    n = len(retained)
    template = computation.template.text
    summary = (L(en=f"{n} main file(s) to rename according to Zotero's template (`{template}`)",
                 fr=f"{n} fichiers principaux à renommer d'après le modèle de Zotero (`{template}`)") if n > 1 else
               L(en=f"{n} main file(s) to rename according to Zotero's template (`{template}`)",
                 fr=f"{n} fichier principal à renommer d'après le modèle de Zotero (`{template}`)"))
    if titles:
        count = plural(titles, en='attachment', fr='pièce jointe')
        summary += L(en=f', {count} of them whose title, equal to the old name, also changes',
                     fr=f", dont {count} dont le titre, égal à l'ancien nom, change aussi")
    if missing_renamed:
        count = plural(missing_renamed, en='file', fr='fichier')
        summary += (L(en=f', and {count} missing from the disk but stored on zotero.org, which Zotero will name at '
                         'download',
                      fr=f', et {count} absents du disque mais stockés sur zotero.org, que Zotero nommera au '
                         'téléchargement') if missing_renamed > 1 else
                    L(en=f', and {count} missing from the disk but stored on zotero.org, which Zotero will name at '
                         'download',
                      fr=f', et {count} absent du disque mais stocké sur zotero.org, que Zotero nommera au '
                         'téléchargement'))
    lines = [L(en='# File names', fr='# Noms des fichiers'), '', summary + '.', '',
             L(en="The plan changes the name recorded in Zotero (`filename`), without touching the content of the "
                  "files. Each computer renames its files on the disk at its next sync, and `zc undo` puts the old "
                  "names back the same way.",
               fr="Le plan change le nom enregistré dans Zotero (`filename`), sans toucher au contenu des fichiers. "
                  "Chaque ordinateur renomme ses fichiers sur le disque à sa synchronisation suivante, et `zc undo` "
                  "remet les anciens noms de la même façon.")]
    if storage in sync_notes():
        lines += ['', sync_notes()[storage]]
    if retained:
        n = min(trial, len(retained))
        first = (L(en='the first file', fr='le premier fichier') if n == 1
                 else L(en=f'the first {n} files', fr=f'les {n} premiers fichiers'))
        lines += ['', L(en='## After the trial', fr="## Après l'essai"), '',
                  L(en=f'`zc apply <plan> --trial` renames {first} of the list (marked "trial"). Only Zotero renames '
                       'the file on the disk, during its sync. So start the Zotero sync (green arrow), then '
                       '`zc show` on the items of the trial. Each attachment must carry its new name, without '
                       '"file missing from the disk". Only then, `--all`.',
                    fr=f'`zc apply <plan> --trial` renomme {first} de la liste (marqués « essai »). Seul Zotero '
                       "renomme le fichier sur le disque, lors de sa synchronisation. Lancer donc la synchronisation "
                       "de Zotero (flèche verte), puis `zc show` sur les fiches de l'essai. Chaque pièce jointe doit "
                       "porter son nouveau nom, sans « fichier absent du disque ». Seulement ensuite, `--all`."),
                  '', L(en='## Renamings', fr='## Renommages'), '']
        for i, (item, p, op) in enumerate(retained):
            mask = p.key in hidden
            shown = privacy.mask() if mask else ''
            lines.append(L(en=f"- {p.key} (item {item.key}{', ' + shown if mask else ''}) · {describe(op, mask)}",
                           fr=f"- {p.key} (fiche {item.key}{', ' + shown if mask else ''}) · {describe(op, mask)}")
                         + ('' if present(p) else L(en=' · missing from the disk, stored on zotero.org',
                                                     fr=' · absent du disque, stocké sur zotero.org'))
                         + (L(en=' · trial', fr=' · essai') if i < trial else ''))
    if left_aside:
        lines += ['', L(en='## Left aside', fr='## Laissés de côté'), '',
                  L(en='These files are not renamed. A discarded name (already taken, refused by Windows, too long) '
                       'is settled by hand in Zotero, by fixing the item or renaming the attachment.',
                    fr='Ces fichiers ne sont pas renommés. Un nom écarté (déjà pris, refusé par Windows, trop long) '
                       'se règle à la main dans Zotero, en corrigeant la fiche ou en renommant la pièce jointe.'), '']
        for p, expected, reason in left_aside:
            if p.key in hidden:
                lines.append(f'- {p.key} · {privacy.mask()} · {reason}')
            else:
                current = current_name(p)
                lines.append(L(en=f'- {p.key} · "{current}"', fr=f'- {p.key} · « {current} »')
                             + (L(en=f' → "{expected}"', fr=f' → « {expected} »') if expected else '')
                             + f' · {reason}')
    if linked:
        count = plural(linked, en='main linked file', fr='fichier lié')
        lines += ['', (L(en=f'{count} outdated, left to the Zotero setting ("Rename linked files"), the '
                            'API not renaming linked files.',
                         fr=f'{count} principaux en retard, laissés au réglage de Zotero (« Renommer les fichiers '
                            "liés »), l'API ne renommant pas les fichiers liés.") if linked > 1 else
                       L(en=f'{count} outdated, left to the Zotero setting ("Rename linked files"), the '
                            'API not renaming linked files.',
                         fr=f'{count} principal en retard, laissé au réglage de Zotero (« Renommer les fichiers '
                            "liés »), l'API ne renommant pas les fichiers liés."))]
    return '\n'.join(lines) + '\n'


# Inbox triage (D149)

def for_sorting(b: Library, cfg, client, aimed: list[tuple[str, list[Operation], bool]],
                rank: int) -> tuple[dict[str, Operation], list[str]]:
    """`filename` operations of the Inbox triage. `aimed` gives, for each item, the operations of the triage plan
    that touch it and whether it absorbs a merge. The name is computed on the metadata as of the plan, and the
    main attachment chosen among those that remain on it, those from an absorbed item included. An item is
    retained when the plan changes its expected name (creators, date, title, type) or merges it. Returns the
    operations by item key and remarks for the report (names left outdated)."""
    try:
        computation = Computation(b, cfg)
    except UnsupportedTemplate as e:
        return {}, [L(en=f'File names left as they are, Zotero template not supported ({e}).',
                      fr=f'Noms des fichiers laissés tels quels, modèle de Zotero non pris en charge ({e}).')]
    by_key = b.by_key()
    candidates, remarks = [], []
    for key, ops, merge in aimed:
        item = by_key.get(key)
        if item is None:
            continue
        after: dict = {}
        for op in ops:
            if op.key == key:
                after |= op.after
        new = item_after(b, item, after)
        trash = {op.key for op in ops if op.after.get('deleted')}
        moved_in = {op.key for op in ops if op.after.get('parentItem') == key}
        attachments = ordered(b, new, [p for p in b.attachments.values() if (p.parent == item.id or p.key in moved_in)
                                        and p.id in b.all_items and p.mode != MODE_LINK and p.key not in trash])
        if not attachments or not renamable(attachments[0]):
            continue
        p = attachments[0]
        try:
            if not merge and computation.name(new, p) == computation.name(item, p):
                continue
        except NameNotComputable as e:
            remarks.append(L(en=f'{key}, file name not computed ({e}).', fr=f'{key}, nom du fichier non calculé ({e}).'))
            continue
        if not present(p):
            remarks.append(L(en=f'{key}, file missing from the disk, name left to `zc filenames plan`.',
                             fr=f'{key}, fichier absent du disque, nom laissé à `zc filenames plan`.'))
            continue
        candidates.append((key, new, p, attachments))
    data = client.items([p.key for _, _, p, _ in candidates]) if candidates else {}
    res = {}
    for key, new, p, attachments in candidates:
        if (d := data.get(p.key)) is None:
            continue
        op, reason = operation(computation, new, p, d, attachments, rank)
        if op is not None:
            res[key] = op
        elif reason:
            remarks.append(L(en=f'{key}, file name left as it is ({reason}).',
                             fr=f'{key}, nom du fichier laissé tel quel ({reason}).'))
    return res, remarks
