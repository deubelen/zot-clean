# The default method

`zot-clean` proposes a way of organizing a Zotero library. It comes from practice, that of a library reorganized and then kept in order over months. It is not imposed, since every convention can be renamed or turned off in `config.toml`. This page says what the method proposes, why, and how to change it. The names proposed here (`Subjects`, `Projects`, `1 to read`…) are those of a library declared English. A library declared French receives their French equivalents. The language is fixed at `zc init` (`--library-language`) and can be read with `zc config show`.

The general idea fits in one sentence. **Every reference has a stable place in a body of subjects classified by disciplines and themes, and everything else (current projects, archives, reading) is only a view of it.**

The sections and keys of `config.toml` keep their French names, whatever the language of the library (`[methode]`, `fonds`, `etats`…). They are given below as they must be written, with a gloss in parentheses.

## Four root collections

At the root of the library, only four collections.

| Root | Role |
|---|---|
| `Inbox` | References that have just arrived, waiting to be sorted. |
| `Projects` | One subcollection per current project (a course, an article, a book), possibly grouped by type. |
| `Subjects` | The permanent classification, by discipline then by theme. |
| `Archives` | Finished projects. |

**Why.** A library falls into disorder when the underlying classification and the work in progress get mixed. You create a collection for an article, then another for a course, and after a few years nobody knows where to look. Separating what lasts (the subjects) from what passes (the projects) settles the matter. The roots have no numbers (`00 Inbox`, `40 Subjects`…), which weigh down the names for a slim gain.

**Changing it.** In `config.toml`, section `[methode]`, the settings `inbox`, `projets` (projects), `fonds` (subjects) and `archives`. You can have several roots for projects, for example `projets = ["Courses", "Papers"]`, or do without a root by giving it an empty name (`archives = ""`).

## Every reference has its place in the subjects

A Zotero item can belong to several collections without being copied. The method makes use of this. Every reference is filed in a theme of the subjects, and can in addition appear in one or several projects.

**Why.** A reference that lives only in a project gets lost when the project ends. If it is also in the subjects, archiving the project loses nothing, and the reference is found by its theme years later. An item that is absent from the subjects therefore signals an oversight, which the filing step spots and offers to place.

## Subjects on two levels, sometimes three

The subjects have two levels, the discipline (Philosophy, Sociology…) then the theme (Philosophy of mind, Ethics…). A third level, the subtheme, is proposed only when a theme goes beyond 40 references.

**Why.** Creating subthemes in advance produces collections of three items, where you hesitate at every filing. The subjects are dug deeper where they grow. The audit flags a depth of more than three levels.

The list of disciplines and themes is not supplied. It is built during the cleanup (step 4), from your existing collections and tags. The agent proposes an outline, you discuss it, and once it is validated it is written in `plan.md`, with a definition for each theme (in the fields `Includes` and `Excludes`). These definitions are then used to file new references without hesitation.

**Changing it.** `seuil_sous_theme` (subtheme threshold, 40 by default) and `profondeur_max` (maximum depth, 3).

## `plan.md` follows Zotero

During the cleanup, `plan.md` is the validated outline that guides the filing. Afterwards, Zotero is the authority. You can create a theme directly in Zotero, `plan.md` only serves to keep the definitions and the filing instructions. The regular checkup, run with every audit, flags themes without a definition and definitions without a theme.

**Why.** If a file commanded Zotero, every gesture made in Zotero (creating a theme on the fly, moving a collection) would become an error to correct. The tool must follow your habits, not the other way around.

## Few tags, in families

The method uses only a few families of tags.

| Family | Examples | Use |
|---|---|---|
| Reading statuses | `1 to read`, `2 reading`, `3 read` | Where you stand with a text. The digits keep them in order. |
| Marks | `★ essential`, `printed` | Reference texts, printed copies. |
| Concepts | `#norm`, `#emotion` | Notions that cut across the themes of the subjects. |
| Technical | `_private`, `_to check` | Working marks, which you can filter on. |

Automatic tags, that is the keywords added by publishers and databases, are deleted during the cleanup (step 6).

**Why.** Automatic tags quickly number in the thousands, in several languages and in several forms, and make the tag selector unusable. Classification by theme is done by collections. Tags serve for what collections cannot do, namely the state of a reading and cross-cutting notions.

**Changing it.** `etats` (statuses), `autres_tags` (other tags), `prefixe_concept` (`#`) and `prefixe_technique` (`_`).

## Citation keys

If the [Better BibTeX](https://retorque.re/zotero-better-bibtex/) extension is installed, every reference receives a fixed citation key, of the type `durandMoraleAntique1938` (author, first words of the title, year), kept in Zotero's "Citation Key" field. It is used to cite from Markdown or LaTeX. Without Better BibTeX, this check is turned off by `zc init`.

**Why.** A key recomputed at every export changes when you correct an item, and breaks the citations already written. A key fixed in Zotero no longer moves.

**Changing it.** `cles_citation = false` (citation keys) to do without this check.

## File names

PDFs are named `Author - Year - Title`, by Zotero's automatic renaming (Settings › General › Customize Filename Format).

**Why.** A PDF named `1-s2.0-S0010027708.pdf` says nothing outside Zotero. A readable name makes it possible to find a file from the file explorer or a tablet.

**Changing it.** The template is set in Zotero (Settings › General › Customize Filename Format), and the audit reads it in the library. `Author - Year - Title` is Zotero's default template, which writes `Author - Title` for a reference without a date, `A and B` for two authors and `A et al.` beyond that. The conjunction ("and", "et") follows the language of Zotero. `zot-clean` deduces it from the existing names, and `conjonction` in `config.toml` fixes it if needed.

## What is not part of the method

`zot-clean` cleans only your personal library. Group libraries are never modified, since they contain other people's items.

It never modifies the content of the PDF files. Step 8 only changes their names, following the template set in Zotero, and `zc undo` can put them back. Only the items, the notes, the attachments (as Zotero elements) and the collections change, always through the Zotero API. An item or an attachment put in the trash stays there thirty days, as if you had deleted it in Zotero.
