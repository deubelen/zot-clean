"""Privacy filter (D18, D65, D66).

Designates the records that must never be passed to the agent nor looked up by
title with an outside service. A record is excluded if it carries a tag from
`tags_exclus`, or if it is filed in a collection from `collections_exclues` or
in one of its subcollections. A collection is designated by its path
(« Fonds/Privé ») or by its name alone. An exclusion tag matches whatever its
capitalization and Unicode form (D190). An attachment or a note that carries
this tag is excluded together with its annotations, and an excluded record
together with its attachments, its notes and their annotations (D188).

An excluded record is still handled by the steps that do not need to read it
(duplicates, identifiers). Everything `zc` writes that the agent can read
(audit, tracking files, reports, plans) shows only its key (D126).
"""

import unicodedata

from zot_clean.config import Config
from zot_clean.lang import L
from zot_clean.reader import Library

def mask() -> str:
    """What is shown in place of a confidential item."""
    return L(en='(confidential item)', fr='(fiche confidentielle)')


def form(name: str) -> str:
    """Form of an exclusion tag, without capitals or Unicode variants (D190)."""
    return unicodedata.normalize('NFC', name).casefold()


def excluded_tags(cfg: Config) -> set[str]:
    return {form(t) for t in cfg.privacy.excluded_tags}


def excluded_tag(name: str, cfg: Config) -> bool:
    return form(name) in excluded_tags(cfg)


def excluded_items(b: Library, cfg: Config) -> set[int]:
    tags = excluded_tags(cfg)
    names = set(cfg.privacy.excluded_collections)
    cols = {c for c in b.collections if _excluded(b, c, names)}
    return {e.id for e in b.all_items.values()
            if any(form(n) in tags for n, _ in e.tags) or e.collections & cols}


def _excluded(b: Library, cid: int, names: set[str]) -> bool:
    while cid is not None:
        if b.collections[cid].name in names or b.path(cid) in names:
            return True
        cid = b.collections[cid].parent
    return False


def hidden_keys(b: Library, cfg: Config) -> set[str]:
    """Keys of the excluded items and their descendants (attachments, notes, annotations), of which nothing is
    written but the key (D126, D188)."""
    ids = excluded_items(b, cfg)
    attachments = {i for i, p in b.attachments.items() if i in ids or p.parent in ids}
    keys = {b.all_items[i].key for i in ids}
    keys |= {b.attachments[i].key for i in attachments}
    keys |= {b.all_items[n].key for n, parent in b.notes.items() if parent in ids and n in b.all_items}
    keys |= {b.all_items[a].key for a, p in b.annotation_of.items() if p in attachments and a in b.all_items}
    return keys
