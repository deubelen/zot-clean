"""`zc` command line."""

import argparse
import contextlib
import json
import os
import re
import shlex
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from zot_clean import __version__, lang, registry
from zot_clean.lang import L, plural

# Commands not yet available, with their milestone (D31), listed in the help. `trier`, planned for v0.3, became
# `zc inbox` (D135) and no longer appears there.
UPCOMING: dict[str, tuple[str, str]] = {}


_secret_rejected = False


def _read_up_to_date(cfg):
    """Up-to-date library for a command that only reads (D171, D174). Local copy alone if zotero.org is
    unreachable."""
    from zot_clean import apply as a, api, reader
    try:
        client = api.from_config(cfg)
    except SystemExit:  # no API key: the local copy alone
        return reader.read(cfg.database)
    return a.read_up_to_date(cfg, client, _progress, optional=True)


def _warn(message: str) -> None:
    print(L(en=f'Warning. {message}', fr=f'Attention. {message}'))


def _error(message: str) -> None:
    print(L(en=f'Error. {message}', fr=f'Erreur. {message}'))


def _groups_line(plan) -> str:
    return L(en=f'{len(plan.groups)} group(s), {plan.n_operations} operation(s).',
             fr=f'{len(plan.groups)} groupe(s), {plan.n_operations} opération(s).')


def _plan_paths(path) -> str:
    return L(en=f"Plan: {path}\nReport: {path.with_suffix('.md')}",
             fr=f"Plan : {path}\nRapport : {path.with_suffix('.md')}")


def _read_then_trial(path) -> str:
    return L(en=f'Read the report, then `zc apply {path} --trial`.',
             fr=f'Relire le rapport, puis `zc apply {path} --trial`.')


def _progress(message: str) -> None:
    """Progress line of a long command, on the error output so as not to mix with the result."""
    print(message, file=sys.stderr)


def _secret_outside_terminal(_prompt: str) -> str:
    """Outside a terminal, no key is asked for. The message is shown only once per launch."""
    global _secret_rejected
    if not _secret_rejected:
        _secret_rejected = True
        print(L(en='No interactive terminal (zc init run by an agent or a script?). Keys must not go through an '
                  'agent. Run `zc init` yourself in a terminal to enter them.',
                fr="Pas de terminal interactif (zc init lancé par un agent ou un script ?). Les clés ne doivent pas "
                   "passer par un agent. Relancer `zc init` soi-même dans un terminal pour les saisir."))
    return ''


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:  # input closed (agent, script): end the question's line before what follows
        print()
        return ''


def init(args) -> int:
    import getpass
    from zot_clean import init as i, lang
    folder = args.folder.resolve()
    interactive = sys.stdin.isatty()
    language = i.choose_language(folder, args.library_language, args.update, _ask if interactive else None, print)
    if language is None:
        return 1
    secret = getpass.getpass if interactive else _secret_outside_terminal
    with lang.language(language):
        return i.initialize(folder, args.zotero_dir, args.update, _ask, secret, print, language)


def audit(args) -> int:
    from zot_clean import audit as a, config, reader
    cfg = config.load(args.workspace)
    try:
        b = reader.read(cfg.database)
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    client = _account_client(cfg, b, args.offline)
    lag = _local_copy_behind(client, b) if client and not args.offline else ''
    online, cause = (_online_files(cfg, b, a.missing_imported(b), client) if not args.offline
                       else (None, L(en='option --offline', fr='option --offline')))
    sections = a.run_audit(b, cfg, fingerprints=not args.no_hashes, online=online, cause=cause)
    from zot_clean import checkup as k, privacy
    section, memory = k.outline_check(b, cfg, privacy.hidden_keys(b, cfg))
    sections.append(section)
    day = date.today()
    snap = k.snapshot(sections, b)
    before = k.previous(cfg, day)
    evolution = k.evolution(sections, snap, before[1], before[0]) if before else k.no_comparison()
    cfg.reports.mkdir(parents=True, exist_ok=True)
    output = cfg.reports / f'audit-{day:%Y-%m-%d}.md'
    text = a.report(sections, b, day, evolution)
    if lag:  # at the top of the report too, which the agent summarizes
        title, _, rest = text.partition('\n')
        text = f'{title}\n\n> {lag}\n{rest}'
    output.write_text(text, encoding='utf-8')
    k.save_snapshot(cfg, snap, day)
    if memory is not None:
        k.write_memory(cfg, memory)
    if lag:
        print(lag + '\n')
    width = max((len(a.status_label(s.status)) for s in sections), default=0)
    for i, s in enumerate(sections, 1):
        label = a.status_label(s.status).ljust(width)
        print(L(en=f'{label} {i:2}. {s.title}: {s.summary}', fr=f'{label} {i:2}. {s.title} : {s.summary}'))
    if before:
        changed = [l for l in evolution if l.startswith('- ')]
        print(L(en=f"\nSince the audit of {before[0]:%d/%m/%Y}: ", fr=f"\nDepuis l'audit du {before[0]:%d/%m/%Y} : ")
              + (L(en=f'{len(changed)} check(s) with something new or settled, details at the top of the report.',
                   fr=f'{len(changed)} contrôle(s) avec du nouveau ou du réglé, détail en tête du rapport.')
                 if changed else L(en='nothing new or settled.', fr='aucun point nouveau ni réglé.')))
    else:
        print(L(en='\nNo audit from a previous day, nothing is compared.',
                fr="\nAucun audit d'un jour précédent, rien n'est comparé."))
    print(L(en=f'\nFull report: {output}', fr=f'\nRapport complet : {output}'))
    return 0


def _local_copy_behind(client, b) -> str:
    """Warning when zotero.org holds changes that Zotero has not received yet, for example those of a plan just
    applied. The audit reads the local copy alone (D171), its figures are then those of before (pilot bench, D242).
    Empty when up to date or when zotero.org cannot be reached."""
    from zot_clean import api
    try:
        behind = client.server_version() > b.version
    except (api.APIError, api.Refusal, OSError):
        return ''
    return L(en='**Warning.** Zotero has not yet received the latest changes made on zotero.org (a plan just applied, '
                'for instance). This audit reads the copy of this computer, so its figures are those of before. '
                'Synchronize Zotero (green arrow), then run `zc audit` again.',
             fr="**Attention.** Zotero n'a pas encore reçu les derniers changements faits sur zotero.org (un plan qui "
                "vient d'être appliqué, par exemple). Cet audit lit la copie de cet ordinateur, ses chiffres sont donc "
                "ceux d'avant. Synchroniser Zotero (flèche verte), puis relancer `zc audit`.") if behind else ''


def _account_client(cfg, b, offline: bool):
    """Client for the key for the audit, None without a key (audit of the local copy alone, as before). Refusal if the
    key is not that of the synced account, as for any command that uses the key. The audit is
    the first command of a session, and the refusal comes there before a complete report on which work would be
    prepared that all the following commands would refuse. Missing files would also be looked for
    in another library there, and all reported as lost. `--offline` does not use the key, the audit of the
    local copy is done, with the refusal as a warning."""
    from zot_clean import apply as a, api
    try:
        client = api.from_config(cfg)
    except SystemExit:
        return None
    try:
        a.check_account(client.user, b.account)
    except api.Refusal as e:
        if offline:
            print(L(en=f'Warning. {e}\n', fr=f'Attention. {e}\n'))
            return None
        raise api.Refusal(L(en=f'{e}\nMeanwhile, `zc audit --offline` audits only the library of this computer, '
                               'without using the key.',
                            fr=f"{e}\nEn attendant, `zc audit --offline` fait l'audit de la seule bibliothèque "
                               'de cet ordinateur, sans se servir de la clé.')) from None
    return client


# Files found on zotero.org, attachment key -> item version. Outside `cache/*.json`, which
# `--refresh` empties for the metadata sources only.
ONLINE = Path('zotero') / 'fichiers_en_ligne.json'


def _online_files(cfg, b, keys: list[str], client=None) -> tuple[dict[str, bool] | None, str]:
    """Files missing from disk that are still stored on zotero.org (D133), or None and the reason. A file found is
    remembered with the version of its attachment and is no longer asked for as long as that does not change. A file
    not found is asked for again each time, since it may arrive from another computer before Zotero receives the new
    version, and these lost files are few."""
    from zot_clean import api
    if not keys:
        return {}, ''
    versions = {p.key: p.version for p in b.attachments.values() if p.version}  # 0: never synced
    file = cfg.cache / ONLINE
    try:
        memory = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        memory = {}
    # Only the attachments still there and unchanged remain.
    memory = {k: v for k, v in memory.items() if v and versions.get(k) == v} if isinstance(memory, dict) else {}
    res = {key: True for key in keys if key in memory}
    to_find = [key for key in keys if key not in res]

    def remember():
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(memory, sort_keys=True), encoding='utf-8')
        except OSError:
            pass  # without memory, the next audit asks for these files again

    if not to_find:
        remember()
        return res, ''
    try:
        client = client or api.from_config(cfg)
    except SystemExit:
        return None, L(en='no API key', fr='pas de clé API')
    try:
        for i, key in enumerate(to_find, 1):
            res[key] = client.file_online(key)
            if res[key] and versions.get(key):
                memory[key] = versions[key]
            if i % 50 == 0 or i == len(to_find):
                print(L(en=f'{i}/{len(to_find)} missing files looked for on zotero.org',
                        fr=f'{i}/{len(to_find)} fichiers absents cherchés sur zotero.org'), file=sys.stderr)
                remember()
    except api.APIError:
        remember()
        return None, L(en='zotero.org unreachable', fr='zotero.org injoignable')
    return res, ''


def _inbox(args, prepare: bool) -> int:
    from zot_clean import apply as a, config, api, inbox as i, reader, metadata as m, plans, sources
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        client = api.from_config(cfg)
        b = a.read_up_to_date(cfg, client, _progress, optional=prepare)  # D171, D240
        a.check_account(client.user, b.account)  # already done by `read_up_to_date`, not by the plain read
        services = sources.from_config(cfg)
        schema = reader.read_types(cfg.database)
        if prepare:
            report, listing = i.prepare(b, cfg, services, client, schema, m.show_progress)
        else:
            plan, report = i.make_plan(b, cfg, services, client, schema, m.show_progress)
        for warn_msg in services.warnings():
            _warn(warn_msg)
        if note := services.contact_note():  # optional address, a note rather than a warning (pilot bench)
            print(note)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    if prepare:
        cfg.reports.mkdir(parents=True, exist_ok=True)
        output = cfg.reports / f'inbox-{date.today():%Y-%m-%d}.md'
        output.write_text(report, encoding='utf-8')
        print(L(en=f'{len(listing)} item(s) to sort.\nReport: {output}',
                fr=f'{len(listing)} référence(s) à trier.\nRapport : {output}'))
        print(L(en='Judge the cases of the tracking files and write the filing, then `zc inbox plan`.',
                fr='Juger les cas des fichiers de suivi et écrire le rangement, puis `zc inbox plan`.'))
        return 0
    if not plan.groups:
        print(L(en='Nothing to do: no accepted decision, no certain correction for the items to sort.',
                fr='Rien à faire : aucune décision acceptée, aucune correction sûre pour les références à trier.'))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(_groups_line(plan))
    print(_plan_paths(path))
    if a._small_management_plan(plan, cfg):  # D138
        print(L(en=f'Sorting plan of fewer than {cfg.writing.small_management_plan} items, it is applied at once, '
                   f'without a trial or a recent backup. Read the report, then `zc apply {path} --all`.',
                fr=f'Plan de tri de moins de {cfg.writing.small_management_plan} fiches, il s\'applique d\'un coup, '
                   f'sans essai ni sauvegarde récente. Relire le rapport, puis `zc apply {path} --all`.'))
    else:
        print(_read_then_trial(path))
    return 0


def inbox_prepare(args) -> int:
    return _inbox(args, True)


def inbox_make_plan(args) -> int:
    return _inbox(args, False)


def make_backup(args) -> int:
    from zot_clean import config, backup
    from zot_clean.api import Refusal
    cfg = config.load(args.workspace)
    try:
        info = backup.make_backup(cfg)
    except Refusal as e:
        print(e, file=sys.stderr)
        return 1
    method = (L(en='clone of the Zotero folder', fr='clone du dossier Zotero') if info.method == 'clone'
              else L(en='copy of the database only', fr='copie de la base seule'))
    print(L(en=f'Backup done ({method}, {info.size / 1e6:.0f} MB): {info.folder}',
            fr=f'Sauvegarde faite ({method}, {info.size / 1e6:.0f} Mo) : {info.folder}'))
    return 0


def _plan_status(plan, path, cfg) -> None:
    from zot_clean import apply as a, journal
    done = journal.done_groups(cfg.journal, plan.fingerprint)
    print(L(en=f'Plan {path.name} ({plan.step}): {len(plan.groups)} group(s), {plan.n_operations} operation(s).',
            fr=f'Plan {path.name} ({plan.step}) : {len(plan.groups)} groupe(s), {plan.n_operations} opération(s).'))
    if plan.description:
        print(plan.description)
    print(L(en=f"Readable report: {path.with_suffix('.md')}", fr=f"Rapport lisible : {path.with_suffix('.md')}"))
    if len(done) == len(plan.groups):
        print(L(en='Plan fully applied.', fr='Plan entièrement appliqué.'))
    elif done:
        print(L(en=f'{len(done)} group(s) already applied. Next, `zc apply {path} --all`.',
                fr=f'{len(done)} groupe(s) déjà appliqué(s). Suite : `zc apply {path} --all`.'))
    elif a._small_management_plan(plan, cfg):
        print(L(en=f'Nothing applied. Small sorting plan, it is applied at once, without a trial, with '
                   f'`zc apply {path} --all`, then check with `zc show`.',
                fr=f'Rien d\'appliqué. Petit plan de tri, il s\'applique d\'un coup, sans essai, avec '
                   f'`zc apply {path} --all`, puis vérifier avec `zc show`.'))
    else:
        print(L(en=f'Nothing applied. Next step, `zc apply {path} --trial` '
                   f'({min(cfg.writing.trial, len(plan.groups))} group(s)), then check with `zc show`.',
                fr=f'Rien d\'appliqué. Étape suivante : `zc apply {path} --trial` '
                   f'({min(cfg.writing.trial, len(plan.groups))} groupe(s)), puis vérifier avec `zc show`.'))


def apply_plan(args) -> int:
    from zot_clean import apply as a, config, api, plans
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    path = args.plan.resolve()
    plan = plans.load(path)
    if newer := plans.newer_plans(path, plan):
        _warn(L(en=f'A more recent plan of the same step exists ({newer[-1]}). This one was probably replaced. '
                   'Apply the more recent one, unless there is a reason to keep this one.',
                fr=f'Un plan plus récent de la même étape existe ({newer[-1]}). Celui-ci a sans doute été '
                   "remplacé. Appliquer le plus récent, sauf raison de garder celui-ci."))
    if not (args.trial or args.all):
        _plan_status(plan, path, cfg)
        return 0
    from zot_clean import bbt, citation_keys
    if cfg.method.use_citation_keys and (state := bbt.detect(cfg.zotero_dir)).present and state.regenerates:
        _warn(citation_keys.regenerates())  # each record written would change key (D146)
    try:
        outcome = a.apply_plan(plan, path, api.from_config(cfg), cfg, a.TRIAL if args.trial else a.ALL)
    except (Refusal, APIError) as e:
        print(e, file=sys.stderr)
        return 1
    for warn_msg in outcome.warnings:
        _warn(warn_msg)
    if outcome.journal is None and outcome.remaining:  # D179
        print(L(en=f'The trial of this plan is already done, {outcome.remaining} group(s) remain. Check the trial with '
                   f'`zc show`, then `zc apply {path} --all`.',
                fr=f"L'essai de ce plan est déjà fait, il reste {outcome.remaining} groupe(s). Vérifier l'essai avec "
                   f"`zc show`, puis `zc apply {path} --all`."))
        return 0
    if outcome.journal is None:
        print(L(en='Nothing to apply, all the groups of this plan are already done.',
                fr='Rien à appliquer, tous les groupes de ce plan sont déjà faits.'))
        return 0
    print(L(en=f'{len(outcome.done)} group(s) applied, {outcome.items_written} element(s) modified.',
            fr=f'{len(outcome.done)} groupe(s) appliqué(s), {outcome.items_written} élément(s) modifié(s).'))
    stopped = {g: d for g, d in (outcome.conflicts | outcome.errors).items() if g in outcome.stopped}
    for title, d in ((L(en='Partly applied', fr='Appliqués en partie'), outcome.partials),
                     (L(en='Stopped after part of the writes, to check',
                        fr='Arrêtés après une partie des écritures, à vérifier'), stopped),
                     (L(en='Conflicts, left intact', fr='Conflits, laissés intacts'),
                      {g: d for g, d in outcome.conflicts.items() if g not in stopped}),
                     (L(en='Errors, left intact', fr='Erreurs, laissées intactes'),
                      {g: d for g, d in outcome.errors.items() if g not in stopped})):
        if d:
            print(L(en=f'{title}:', fr=f'{title} :'))
            for g, detail in d.items():
                print(L(en=f'  group {g}: {detail}', fr=f'  groupe {g} : {detail}'))
    print(L(en=f'Journal: {outcome.journal}', fr=f'Journal : {outcome.journal}'))
    touched = [op.key for g in plan.groups if g.id in outcome.done or g.id in outcome.partials
               for op in g.operations if op.kind == 'items']
    touched += [c for g in plan.groups if g.id in outcome.stopped for op in g.operations
                if op.kind == 'items' and (c := op.key) in outcome.stopped[g.id]]
    if touched:  # what the trial touched, to check it (D174)
        touched = list(dict.fromkeys(touched))
        print(L(en=f"Check: zc show {' '.join(touched[:20])}", fr=f"Vérifier : zc show {' '.join(touched[:20])}")
              + (L(en=f' (and {len(touched) - 20} others)', fr=f' (et {len(touched) - 20} autres)')
                 if len(touched) > 20 else ''))
    if outcome.remaining:
        follow_up = '--all' if args.trial else L(en='--all (resumes where it stopped)',
                                                 fr='--all (reprend là où il s\'est arrêté)')
        print(L(en=f'{outcome.remaining} group(s) remaining. Check the trial with `zc show`, then '
                   f'`zc apply {path} {follow_up}`.',
                fr=f'{outcome.remaining} groupe(s) restant(s). Vérifier l\'essai avec `zc show`, puis '
                   f'`zc apply {path} {follow_up}`.'))
    elif args.trial and not (outcome.conflicts or outcome.errors or outcome.partials):
        print(L(en='The plan is small, the trial applied all of it: `--all` will have nothing to do. Check with '
                   '`zc show`.',
                fr="Le plan est petit, l'essai l'a appliqué en entier : `--all` n'aura rien à faire. Vérifier avec "
                   "`zc show`."))
    return 1 if outcome.conflicts or outcome.errors else 0


def undo_plan(args) -> int:
    from zot_clean import undo, apply as a, config, api, privacy, reader, plans
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    journals = undo.targeted_journals(args.target.resolve(), cfg)
    client = api.from_config(cfg)
    try:
        b = reader.read(cfg.database)
        hidden = privacy.hidden_keys(b, cfg)
    except (FileNotFoundError, reader.UnknownSchema):
        b, hidden = None, None  # unreadable database: all records hidden in the report (D126)
    try:
        if b is not None:  # unreadable database: `zc apply`, which rereads it, will refuse if need be
            a.check_account(client.user, b.account)
        plan, report = undo.make_plan(journals, client, hidden)
    except (APIError, Refusal) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groups:
        print(L(en='Nothing to undo (no element written, or elements gone).',
                fr="Rien d'annulable (aucun élément écrit, ou éléments disparus)."))
        print(report)
        return 1
    path = plans.write(plan, cfg.plans, report)
    print(L(en=f"Undo plan: {path}\nReport: {path.with_suffix('.md')}",
            fr=f"Plan d'annulation : {path}\nRapport : {path.with_suffix('.md')}"))
    print(_read_then_trial(path))
    if note := _decisions_kept(journals):
        print(note)
    return 0


# Step of a journal (stored name, D209) -> tracking file whose decisions produced its plan, command that would plan
# them again.
_DECIDED_STEPS = {
    'tags': ('suivi/tags.toml', 'zc tags plan'),
    'doublons': ('suivi/doublons.toml', 'zc duplicates plan'),
    'pieces': ('suivi/pieces.toml', 'zc attachments plan'),
    'identifiants': ('suivi/metadonnees.toml', 'zc metadata identifiers'),
    'types': ('suivi/metadonnees.toml', 'zc metadata types'),
    'completer': ('suivi/metadonnees.toml', 'zc metadata complete'),
    'cles': ('suivi/cles.toml', 'zc citation-keys plan'),
}


def _decisions_kept(journals) -> str:
    """An undo leaves the decisions of the tracking files as they were: planning the step again would redo what was
    just undone (pilot bench, D242). Said once per step, after the undo plan."""
    from zot_clean import journal as jl
    steps = []
    for path in journals:
        lines = jl.read(path)
        if lines and (step := lines[0].get('etape')) in _DECIDED_STEPS and step not in steps:
            steps.append(step)
    notes = []
    for step in steps:
        file, plan = _DECIDED_STEPS[step]
        # The accept and reject commands refuse to overwrite a decision already taken (D172): it is changed by hand.
        notes.append(L(en=f'The decisions of {file} are unchanged: `{plan}` would propose these changes again. Before '
                          f'running it, change by hand in {file} the decision of each entry that must stay as the '
                          'undo leaves it (a decision already taken is changed in the file, not by command).',
                       fr=f'Les décisions de {file} ne changent pas : `{plan}` proposerait de nouveau ces changements. '
                          f'Avant de le relancer, changer à la main dans {file} la décision de chaque entrée qui doit '
                          "rester comme l'annulation la laisse (une décision prise se change dans le fichier, pas par "
                          'une commande).'))
    return '\n'.join(notes)


def duplicates_find(args) -> int:
    from zot_clean import config, duplicates as d, reader
    cfg = config.load(args.workspace)
    try:
        b = _read_up_to_date(cfg)
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    entries = d.find(b, cfg)
    certain = sum(1 for e in entries if e.grade == d.CERTAIN and not e.decision)
    to_judge = sum(1 for e in entries if e.grade == d.TO_JUDGE and not e.decision)
    merge = sum(1 for e in entries if e.decision == d.MERGE)
    distinct_sets = sum(1 for e in entries if e.decision == d.DISTINCT)
    print(L(en=f'{certain} certain group(s) and {to_judge} to judge without a decision, {merge} to merge, '
               f'{distinct_sets} judged distinct.',
            fr=f'{certain} groupe(s) sûr(s) et {to_judge} à juger sans décision, {merge} à fusionner, '
               f'{distinct_sets} jugé(s) distinct(s).'))
    print(L(en=f'Groups to read in {cfg.tracking / d.FILE}, decisions to write with `zc duplicates accept` ',
            fr=f'Groupes à lire dans {cfg.tracking / d.FILE}, décisions à écrire avec `zc duplicates accept` ')
          + (L(en='(--certain for all certain groups) ', fr='(--certain pour tous les groupes sûrs) ') if certain else '')
          + L(en='and `zc duplicates reject`, then `zc duplicates plan`.',
              fr='et `zc duplicates reject`, puis `zc duplicates plan`.'))
    return 0


def duplicates_make_plan(args) -> int:
    from zot_clean import apply as a, config, duplicates as d, api, reader, plans
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        b = a.read_up_to_date(cfg, api.from_config(cfg), _progress)
        plan, report = d.make_plan(cfg, api.from_config(cfg), b)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groups:
        print(L(en='No group to merge. Decide the groups with `zc duplicates accept` (--certain for all certain '
                   'groups).',
                fr='Aucun groupe à fusionner. Décider les groupes avec `zc duplicates accept` (--certain pour tous '
                   'les groupes sûrs).'))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(L(en=f'{len(plan.groups)} group(s) to merge, {plan.n_operations} operation(s).',
            fr=f'{len(plan.groups)} groupe(s) à fusionner, {plan.n_operations} opération(s).'))
    if warn_msg := d.warning(b, cfg, plan):  # files not yet downloaded (D168)
        _warn(warn_msg)
    print(_plan_paths(path))
    print(_read_then_trial(path))
    return 0


def duplicates_decide(args) -> int:
    """`zc duplicates accept` (merge) and `zc duplicates reject` (distinct), D177."""
    from zot_clean import config, duplicates as d
    cfg = config.load(args.workspace)
    reject = args.tracking_action == 'reject'
    keys = [k.upper() for k in args.keys]
    certain, keep = getattr(args, 'certain', False), [k.upper() for k in getattr(args, 'keep', [])]
    if not (keys or certain or keep):
        raise SystemExit(L(en='Give the key of one item of each group', fr='Donner la clé d\'une fiche de chaque groupe')
                         + ('.' if reject else L(en=', or --certain.', fr=', ou --certain.')))
    entries = d.load_tracking(cfg)
    if reject:
        merge, distinct_sets, taken_out = d.decide(entries, distinct=keys, reason=args.reason or '')
    else:
        merge, distinct_sets, taken_out = d.decide(entries, certain, keys, keep=keep,
                                                   except_=[k.upper() for k in args.except_])
    d.write_tracking(cfg, entries, _read_up_to_date(cfg))
    counts = []
    if merge:
        counts.append(plural(merge, en='group', fr='groupe') + L(en=' to merge', fr=' à fusionner'))
    if taken_out:  # --except on a designated group: each item judged distinct from the rest
        counts.append(L(en='1 item taken out of its group and judged distinct from the rest',
                        fr='1 fiche retirée de son groupe et jugée distincte du reste') if taken_out == 1 else
                      L(en=f'{taken_out} items taken out of their group and judged distinct from the rest',
                        fr=f'{taken_out} fiches retirées de leur groupe et jugées distinctes du reste'))
    if distinct_sets:
        counts.append(plural(distinct_sets, en='group judged distinct', fr='groupe jugé distinct',
                             en_plural='groups judged distinct'))
    print(_decisions_written(cfg.tracking / d.FILE, counts,
                             L(en='Run `zc duplicates plan` to get the plan.',
                               fr='Lancer `zc duplicates plan` pour obtenir le plan.')))
    return 0


def _decisions_written(path, counts: list[str], follow_up: str) -> str:
    """What a decision command has just written in a tracking file, and only that: the counts are those of the
    command, not the totals of the file (pilot bench)."""
    if not counts:
        return L(en=f'No new decision written to {path}. {follow_up}',
                 fr=f'Aucune décision nouvelle écrite dans {path}. {follow_up}')
    listed = ', '.join(counts)
    return L(en=f'Decisions written by this command to {path}: {listed}. {follow_up}',
             fr=f'Décisions écrites par cette commande dans {path} : {listed}. {follow_up}')


def attachments_find(args) -> int:
    from zot_clean import config, reader, attachments as p
    cfg = config.load(args.workspace)
    try:
        b = _read_up_to_date(cfg)
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    entries = p.find(b, cfg)
    to_judge = sum(1 for e in entries if not e.decision)
    print(L(en=f'{len(entries)} PDF(s) present in several copies, {to_judge} of them without a decision.',
            fr=f'{len(entries)} PDF présent(s) en plusieurs copies, dont {to_judge} sans décision.'))
    if warn_msg := p.warning(b, cfg, entries):  # missing files (D168), duplicates revealed by a PDF
        _warn(warn_msg)
    print(L(en=f'Groups to read in {cfg.tracking / p.FILE}, decisions to write with `zc attachments accept` and '
               '`zc attachments reject`, then `zc attachments plan`.',
            fr=f'Groupes à lire dans {cfg.tracking / p.FILE}, décisions à écrire avec `zc attachments accept` et '
               '`zc attachments reject`, puis `zc attachments plan`.'))
    return 0


def attachments_decide(args) -> int:
    """`zc attachments accept` (apply) and `zc attachments reject` (keep), D177."""
    from zot_clean import config, attachments as p
    cfg = config.load(args.workspace)
    entries = p.load(cfg)
    b = _read_up_to_date(cfg)
    if args.tracking_action == 'reject':
        applied, keepers = p.decide(entries, b, keep=[k.upper() for k in args.copies], reason=args.reason or '')
    else:
        move = {}
        for text in args.move:
            copy, _, item = text.partition('=')
            if not copy.strip() or not item.strip():
                raise SystemExit(L(en=f'“{text}”: write COPY=ITEM (key of the copy, key of the right item).',
                                   fr=f'« {text} » : écrire COPIE=FICHE (clé de la copie, clé de la bonne fiche).'))
            move[copy.strip().upper()] = item.strip().upper()
        if not args.trash and not move:
            raise SystemExit(L(en='Give the copies to move to the trash (--trash) or to another item (--move).',
                               fr='Donner les copies à mettre à la corbeille (--trash) ou à rattacher (--move).'))
        applied, keepers = p.decide(entries, b, [k.upper() for k in args.trash], move,
                                      reason=args.reason or '')
    p.write(cfg, entries, b)
    counts = []
    if applied:
        counts.append(plural(applied, en='group', fr='groupe') + L(en=' to apply', fr=' à appliquer'))
    if keepers:
        counts.append(plural(keepers, en='group kept as is', fr='groupe gardé tel quel',
                             en_plural='groups kept as is'))
    print(_decisions_written(cfg.tracking / p.FILE, counts,
                             L(en='Run `zc attachments plan` to get the plan.',
                               fr='Lancer `zc attachments plan` pour obtenir le plan.')))
    return 0


def attachments_make_plan(args) -> int:
    from zot_clean import apply as a, config, api, reader, attachments as p, plans
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        b = a.read_up_to_date(cfg, api.from_config(cfg), _progress)
        plan, report = p.make_plan(cfg, api.from_config(cfg), b)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groups:
        print(L(en='Nothing to do. Decide the groups with `zc attachments accept` (--trash, --move).',
                fr='Rien à faire. Décider les groupes avec `zc attachments accept` (--trash, --move).'))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(_groups_line(plan))
    print(_plan_paths(path))
    print(_read_then_trial(path))
    return 0


def _metadata(args, substep: str) -> int:
    from zot_clean import apply as a, config, api, reader, metadata as m, plans, sources
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        b = a.read_up_to_date(cfg, api.from_config(cfg), _progress)
        services = sources.from_config(cfg, args.refresh)
        client = api.from_config(cfg)
        if substep == m.TYPES:
            plan, report = m.types(b, cfg, services, client, reader.read_types(cfg.database), m.show_progress)
        else:
            func = m.identifiers if substep == m.IDENTIFIERS else m.fill_in
            plan, report = func(b, cfg, services, client, m.show_progress)
        for warn_msg in services.warnings():
            _warn(warn_msg)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    to_judge = sum(1 for c in m.load_tracking(cfg) if c.substep == substep and not c.decision)
    if to_judge:
        print(L(en=f'{to_judge} case(s) to judge in {cfg.tracking / m.FILE}, to decide with `zc metadata accept` and '
                   '`zc metadata reject`.',
                fr=f'{to_judge} cas à juger dans {cfg.tracking / m.FILE}, à décider avec `zc metadata accept` et '
                   '`zc metadata reject`.'))
    if not plan.groups:
        print(L(en='No item to modify for the moment.', fr='Aucune fiche à modifier pour le moment.'))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(L(en=f'{len(plan.groups)} item(s) to modify.', fr=f'{len(plan.groups)} fiche(s) à modifier.'))
    print(_plan_paths(path))
    print(_read_then_trial(path))
    return 0


def metadata_identifiers(args) -> int:
    return _metadata(args, 'identifiants')


def metadata_types(args) -> int:
    return _metadata(args, 'types')


def metadata_complete(args) -> int:
    return _metadata(args, 'completer')



def _decision(text: str) -> tuple[str, int | None]:
    key, _, selection = text.partition('=')
    if selection and not selection.isdigit():
        raise SystemExit(L(en=f'“{text}”: write the key alone, or KEY=number of the proposal.',
                           fr=f'« {text} » : écrire la clé seule, ou CLÉ=numéro de la proposition.'))
    key, _, problem = key.strip().partition(':')
    return key.upper() + (f':{problem}' if problem else ''), int(selection) if selection else None


def metadata_decide(args) -> int:
    from zot_clean import config, metadata as m
    cfg = config.load(args.workspace)
    cases = m.load_tracking(cfg)
    reject = args.tracking_action == 'reject'
    if not reject and not args.keys and not args.obvious:
        raise SystemExit(L(en='Give item keys (KEY or KEY=number), or --obvious.',
                           fr='Donner des clés de fiches (CLÉ ou CLÉ=numéro), ou --obvious.'))
    decisions = [_decision(t) for t in args.keys]
    if reject:
        accepted, rejected = m.decide(cases, reject=[k for k, _ in decisions])
    else:
        accepted, rejected = m.decide(cases, args.obvious, dict(decisions), except_={k.upper() for k in args.except_})
    m.write_tracking(cfg, cases, _read_up_to_date(cfg))
    counts = []
    if accepted:
        counts.append(plural(accepted, en='case accepted', fr='cas accepté', en_plural='cases accepted'))
    if rejected:
        counts.append(plural(rejected, en='case rejected', fr='cas refusé', en_plural='cases rejected'))
    print(_decisions_written(cfg.tracking / m.FILE, counts,
                             L(en='Run the substep again to get the plan.',
                               fr='Relancer la sous-étape pour obtenir le plan.')))
    return 0

def subjects_inventory(args) -> int:
    from zot_clean import config, subjects as f, reader
    cfg = config.load(args.workspace)
    if cause := f.refusal(cfg):
        print(cause, file=sys.stderr)
        return 1
    try:
        b = _read_up_to_date(cfg)  # D171, D240
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    f.track_roots(cfg)
    report, tracking, new_ones, vanished = f.inventory(b, cfg)
    f.write_tracking(cfg, tracking)
    cfg.reports.mkdir(parents=True, exist_ok=True)
    output = cfg.reports / f'fonds-inventaire-{date.today():%Y-%m-%d}.md'
    output.write_text(report, encoding='utf-8')
    no_action = sum(1 for c in tracking.collections if not c.action)
    print(L(en=f'{len(tracking.collections)} old collection(s), {no_action} of them without a fate.',
            fr=f'{len(tracking.collections)} ancienne(s) collection(s), dont {no_action} sans sort.'))
    if vanished:
        print(L(en=f'{len(vanished)} collection(s) gone since the last inventory, removed from suivi/{f.FILE}: ',
                fr=f'{len(vanished)} collection(s) disparue(s) depuis le dernier inventaire, retirée(s) de '
                   f'suivi/{f.FILE} : ') + ', '.join(c.path for c in vanished) + '.')
    print(L(en=f'Inventory: {output}\nCorrespondence to fill in: {cfg.tracking / f.FILE}',
            fr=f'Inventaire : {output}\nCorrespondance à remplir : {cfg.tracking / f.FILE}'))
    print(L(en=f'Outline to write in {cfg.workspace / f.OUTLINE}, then `zc subjects validate`.',
            fr=f'Plan à écrire dans {cfg.workspace / f.OUTLINE}, puis `zc subjects validate`.'))
    return 0


def subjects_validate(args) -> int:
    from zot_clean import config, subjects as f
    cfg = config.load(args.workspace)
    if cause := f.refusal(cfg):
        print(cause, file=sys.stderr)
        return 1
    if n := f.track_roots(cfg):
        print(L(en=f'New names of the roots carried over to {cfg.tracking / f.FILE} ({n} collection(s)).',
                fr=f'Nouveaux noms des racines reportés dans {cfg.tracking / f.FILE} ({n} collection(s)).'))
    k = f.check(cfg)
    for e in k.errors:
        _error(e)
    for a in k.warnings:
        _warn(a)
    if k.changes:
        print(L(en='Changes since the last validation:', fr='Changements depuis la dernière validation :'))
        for c in k.changes:
            print(f'  {c}')
    if k.errors:
        print(L(en=f'{len(k.errors)} error(s) to correct before validating the outline.',
                fr=f'{len(k.errors)} erreur(s) à corriger avant de valider le plan.'))
        return 1
    if k.already_validated:
        print(L(en='Outline valid, and already validated as it is.', fr='Plan valide, et déjà validé tel quel.'))
        return 0
    if not args.save:
        print(L(en='Outline without errors. Once the user has approved it, `zc subjects validate --save`.',
                fr="Plan sans erreur. Une fois que l'utilisateur l'a approuvé, `zc subjects validate --save`."))
        return 0
    f.save(cfg, k)
    print(L(en=f'Outline validated, fingerprint saved in {cfg.tracking / f.VALIDATION}.',
            fr=f'Plan validé, empreinte enregistrée dans {cfg.tracking / f.VALIDATION}.'))
    return 0


def subjects_track(args) -> int:
    from zot_clean import config, checkup as k, subjects as f, reader
    cfg = config.load(args.workspace)
    if cause := f.refusal(cfg):
        print(cause, file=sys.stderr)
        return 1
    try:
        b = _read_up_to_date(cfg)  # D171, D240
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    s = k.track(b, cfg)
    if s is None:
        print(L(en=f'Nothing to track, {f.OUTLINE} or the root “{cfg.method.subjects}” is missing.',
                fr=f"Rien à suivre, {f.OUTLINE} ou la racine « {cfg.method.subjects} » manque."), file=sys.stderr)
        return 1
    for c in s.ignored:
        print(L(en=f'Left aside (beyond {cfg.method.max_depth} levels, or parent not found): {c}',
                fr=f'Laissé de côté (au-delà de {cfg.method.max_depth} niveaux, ou parent introuvable) : {c}'))
    if not s.lines:
        print(L(en=f'{f.OUTLINE} already follows Zotero, no theme created, renamed, moved or deleted by hand.',
                fr=f'{f.OUTLINE} suit déjà Zotero, aucun thème créé, renommé, déplacé ou supprimé à la main.'))
        return 0
    print(L(en=f'Changes made in Zotero, to carry over to {f.OUTLINE}:',
            fr=f'Changements faits dans Zotero, à reporter dans {f.OUTLINE} :'))
    for l in s.lines:
        print(f'  {l}')
    if not args.save:
        print(L(en='Once the user has approved them, `zc subjects track --save`.',
                fr="Une fois que l'utilisateur les a approuvés, `zc subjects track --save`."))
        return 0
    for l in k.apply_changes(b, cfg, s):
        print(L(en=f'Removed: {l}', fr=f'Retiré : {l}'))
    check = f.check(cfg)
    for e in check.errors:
        _error(e)
    if check.errors:
        print(L(en=f'{f.OUTLINE} updated, but the validation failed. Correct, then `zc subjects validate --save`.',
                fr=f'{f.OUTLINE} mis à jour, mais la validation a échoué. Corriger, puis '
                   f'`zc subjects validate --save`.'))
        return 1
    f.save(cfg, check)
    seen = k.review(b, cfg)
    if seen:
        k.write_memory(cfg, seen[2].memory)
    print(L(en=f'{f.OUTLINE} and the tracking files updated, outline validated.',
            fr=f'{f.OUTLINE} et les fichiers de suivi mis à jour, plan validé.'))
    if s.added:
        print(L(en=f'Definitions to write in {f.OUTLINE}: ', fr=f'Définitions à écrire dans {f.OUTLINE} : ')
              + ', '.join(s.added)
              + L(en='. Then `zc subjects validate --save`.', fr='. Puis `zc subjects validate --save`.'))
    return 0


def subjects_titles(args) -> int:
    from zot_clean import config, checkup as k, subjects as f, reader
    cfg = config.load(args.workspace)
    if cause := f.refusal(cfg):
        print(cause, file=sys.stderr)
        return 1
    try:
        b = _read_up_to_date(cfg)  # D171, D240
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    try:
        report, n = k.titles(b, cfg, args.path)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    cfg.reports.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^\w-]+', '-', args.path.lower()).strip('-')
    output = cfg.reports / f'titres-{name}-{date.today():%Y-%m-%d}.md'
    output.write_text(report, encoding='utf-8')
    print(L(en=f'{n} item(s) in “{args.path}” and its subthemes: {output}',
            fr=f'{n} référence(s) dans « {args.path} » et ses sous-thèmes : {output}'))
    return 0


def subjects_pending(args) -> int:
    from zot_clean import config, subjects as f, reader, filing as r
    cfg = config.load(args.workspace)
    if cause := f.refusal(cfg):
        print(cause, file=sys.stderr)
        return 1
    try:
        b = _read_up_to_date(cfg)  # D171, D240
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    if args.abstract:
        print(r.abstract(b, cfg, args.abstract))
        return 0
    if args.reviewed:
        for path, n in r.mark_reviewed(b, cfg, args.reviewed).items():
            print(L(en=f'{path}: {n} item(s) left in place, noted in {cfg.tracking / r.REVIEWED}.',
                    fr=f'{path} : {n} fiche(s) laissée(s) en place, notées dans {cfg.tracking / r.REVIEWED}.'))
    if args.leave_out:
        keys = r.leave_out(b, cfg, args.leave_out)
        print(L(en=f'{len(keys)} item(s) left out of the subjects by decision, noted in {cfg.tracking / r.LEFT_OUT}. '
                   'They will come back if their collections change.',
                fr=f'{len(keys)} fiche(s) laissée(s) hors du fonds par décision, notées dans '
                   f'{cfg.tracking / r.LEFT_OUT}. Elles reviendront si leurs collections changent.'))
    new = not (cfg.tracking / r.FILE).is_file()
    report, bundles, additions = r.pending(b, cfg)
    cfg.reports.mkdir(parents=True, exist_ok=True)
    output = cfg.reports / f'fonds-a-ranger-{date.today():%Y-%m-%d}.md'
    output.write_text(report, encoding='utf-8')
    print(L(en=f'{sum(len(p.items) for p in bundles)} item(s) to judge in {len(bundles)} bundle(s).',
            fr=f'{sum(len(p.items) for p in bundles)} fiche(s) à juger en {len(bundles)} paquet(s).'))
    if additions:
        print(L(en=f'{additions} proposal(s) drawn from the tags added to {cfg.tracking / r.FILE}.',
                fr=f'{additions} proposition(s) tirée(s) des tags ajoutée(s) à {cfg.tracking / r.FILE}.'))
    print(L(en=f'Items: {output}\nDecisions to write in {cfg.tracking / r.FILE}',
            fr=f'Fiches : {output}\nDécisions à écrire dans {cfg.tracking / r.FILE}')
          + (L(en=', created with its header and an example', fr=', créé avec son en-tête et un exemple') if new else '')
          + L(en=', then `zc subjects plan`.', fr=', puis `zc subjects plan`.'))
    return 0


def subjects_make_plan(args) -> int:
    from zot_clean import apply as a, config, api, subjects as f, reader, plans, filing as r
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    if cause := f.refusal(cfg):
        print(cause, file=sys.stderr)
        return 1
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        client = api.from_config(cfg)
        _progress(L(en='Reading the local copy of Zotero and the server version.',
                    fr='Lecture de la copie locale de Zotero et de la version du serveur.'))
        b = a.read_up_to_date(cfg, client, _progress)
        plan, report = r.make_plan(b, cfg, client, args.roots, _progress)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groups:
        print(L(en='Nothing to file: the library is in the state aimed at by the outline and the accepted decisions.',
                fr='Rien à ranger : la bibliothèque est dans l\'état visé par le plan et par les décisions acceptées.'))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(_groups_line(plan))
    print(_plan_paths(path))
    print(_read_then_trial(path))
    if args.roots:
        print(L(en='After the full application, carry the new names of the roots over to config.toml and plan.md.',
                fr='Après l\'application complète, reporter les nouveaux noms des racines dans config.toml et '
                   'plan.md.'))
    return 0


def tags_inventory(args) -> int:
    from zot_clean import config, reader, tags as t
    cfg = config.load(args.workspace)
    try:
        b = _read_up_to_date(cfg)
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    report, tracking = t.inventory(b, cfg)
    t.write(cfg, tracking, b)
    cfg.reports.mkdir(parents=True, exist_ok=True)
    output = cfg.reports / f'tags-inventaire-{date.today():%Y-%m-%d}.md'
    output.write_text(report, encoding='utf-8')
    waiting = [e for e in tracking.tags if not e.decision]
    groups = [g for g in tracking.variants if not g.decision]
    print(tracking.automatic_summary + (L(en=f' Decision: {tracking.automatic}.', fr=f' Décision : {tracking.automatic}.')
                                        if tracking.automatic else L(en=' Rule to approve.', fr=' Règle à approuver.')))
    if tracking.imported_summary:
        print(tracking.imported_summary)
    print(L(en=f'{len(waiting)} tag(s) to judge ({sum(e.grade == t.OBVIOUS for e in waiting)} obvious), '
               f'{len(groups)} group(s) of variants ({sum(g.grade == t.OBVIOUS for g in groups)} obvious).',
            fr=f'{len(waiting)} tag(s) à juger (dont {sum(e.grade == t.OBVIOUS for e in waiting)} évident(s)), '
               f'{len(groups)} groupe(s) de variantes (dont {sum(g.grade == t.OBVIOUS for g in groups)} évident(s)).'))
    if tracking.pending:
        print(L(en=f'{len(tracking.pending)} filing proposal(s) added to {cfg.tracking / "rangement.toml"}.',
                fr=f'{len(tracking.pending)} proposition(s) de rangement ajoutée(s) à '
                   f'{cfg.tracking / "rangement.toml"}.'))
    print(L(en=f'Inventory: {output}\nRules to judge: {cfg.tracking / t.FILE}, to decide with `zc tags accept` and '
               '`zc tags reject`, then `zc tags plan`.',
            fr=f'Inventaire : {output}\nRègles à juger : {cfg.tracking / t.FILE}, à décider avec `zc tags accept` et '
               '`zc tags reject`, puis `zc tags plan`.'))
    return 0


def _tags_tracking(args):
    from zot_clean import config, reader, tags as t
    cfg = config.load(args.workspace)
    if not (cfg.tracking / t.FILE).is_file():
        raise SystemExit(L(en=f'No {cfg.tracking / t.FILE} yet. Run `zc tags inventory` first.',
                           fr=f'Pas encore de {cfg.tracking / t.FILE}. Lancer d\'abord `zc tags inventory`.'))
    return cfg, t.load(cfg), reader


def tags_decide(args) -> int:
    """`zc tags accept` and `zc tags reject` (D177)."""
    from zot_clean import tags as t
    cfg, tracking, reading = _tags_tracking(args)
    reject = args.tracking_action == 'reject'
    obvious = getattr(args, 'obvious', False)
    rules = [r for r, yes in (('automatiques', args.automatic_rule), ('importes', args.imported_rule)) if yes]
    if not (args.names or args.variants or rules or obvious):
        raise SystemExit(L(en='Give tag names, groups (--variants), a global rule (--automatic-rule, --imported-rule)',
                           fr='Donner des noms de tags, des groupes (--variants), une règle globale '
                              '(--automatic-rule, --imported-rule)')
                         + ('.' if reject else L(en=', or --obvious.', fr=', ou --obvious.')))
    n = t.decide(tracking, cfg, t.REJECT if reject else t.ACCEPT, args.names, args.variants, obvious,
                  getattr(args, 'except_', []), rules, getattr(args, 'action', '') or '', getattr(args, 'target', '') or '')
    try:
        b = reading.read(cfg.database)
    except (FileNotFoundError, reading.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    t.write(cfg, tracking, b)
    if reject:
        counts = [plural(n, en='rule rejected', fr='règle refusée', en_plural='rules rejected')] if n else []
    else:
        counts = [plural(n, en='rule accepted', fr='règle acceptée', en_plural='rules accepted')] if n else []
    print(_decisions_written(cfg.tracking / t.FILE, counts,
                             L(en='Run `zc tags plan` to get the plan.', fr='Lancer `zc tags plan` pour obtenir le plan.')))
    return 0


def tags_add(args) -> int:
    from zot_clean import tags as t
    cfg, tracking, reading = _tags_tracking(args)
    try:
        b = reading.read(cfg.database)
    except (FileNotFoundError, reading.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    n = t.add(tracking, cfg, b, args.names, args.action, args.target or '', args.user)
    t.write(cfg, tracking, b)
    rules = plural(n, en='rule', fr='règle')
    added = (L(en='added and accepted', fr='ajoutées et acceptées') if n > 1 else
             L(en='added and accepted', fr='ajoutée et acceptée'))
    print(_decisions_written(cfg.tracking / t.FILE, [f'{rules} {added}'] if n else [],
                             L(en='Run `zc tags plan` to get the plan.', fr='Lancer `zc tags plan` pour obtenir le plan.')))
    return 0


def tags_make_plan(args) -> int:
    from zot_clean import apply as a, config, api, reader, plans, tags as t
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        client = api.from_config(cfg)
        b = a.read_up_to_date(cfg, client, _progress)
        plan, report = t.make_plan(b, cfg, client)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groups:
        print(L(en='Nothing to do: the tags are in the state aimed at by the accepted rules of suivi/tags.toml.',
                fr="Rien à faire : les tags sont dans l'état visé par les règles acceptées de suivi/tags.toml."))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(_groups_line(plan))
    print(_plan_paths(path))
    print(_read_then_trial(path))
    return 0


def keys_make_plan(args) -> int:
    from zot_clean import apply as a, bbt, citation_keys as c, config, api, reader, plans
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        client = api.from_config(cfg)
        b = a.read_up_to_date(cfg, client, _progress)
        state = bbt.detect(cfg.zotero_dir)
        plan, report = c.make_plan(b, cfg, client, state)
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    for warn_msg in c.warnings(b, state):
        _warn(warn_msg)
    if not state.present:
        print(L(en='Better BibTeX is not active: only duplicate keys are settled.',
                fr="Better BibTeX n'est pas actif : seules les clés en double sont départagées."))
    if to_judge := sum(1 for e in c.load(cfg).extra if not e.decision):  # a duplicate is settled on its own
        print(L(en=f'{to_judge} case(s) that need an opinion: {cfg.tracking / c.FILE}, to decide with '
                   '`zc citation-keys decide`.',
                fr=f'{to_judge} cas qui demandent un avis : {cfg.tracking / c.FILE}, à décider avec '
                   '`zc citation-keys decide`.'))
    if not plan.groups:
        cfg.reports.mkdir(parents=True, exist_ok=True)
        output = cfg.reports / f'cles-{date.today():%Y-%m-%d}.md'
        output.write_text(report, encoding='utf-8')
        print(L(en=f'Nothing to do: no duplicate key to settle and no Extra line to tidy. Report: {output}',
                fr=f"Rien à faire : aucune clé en double à départager ni ligne d'Extra à ranger. Rapport : {output}"))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(_groups_line(plan))
    print(_plan_paths(path))
    print(_read_then_trial(path))
    return 0


def keys_decide(args) -> int:
    """`zc citation-keys decide ITEM=DECISION …` (D177). The English decision is translated into the word stored
    in the tracking file (D209, D219)."""
    from zot_clean import bbt, citation_keys as c, config, privacy
    cfg = config.load(args.workspace)
    if not (cfg.tracking / c.FILE).is_file():
        raise SystemExit(L(en=f'No {cfg.tracking / c.FILE}: no case needs an opinion. Run `zc citation-keys plan`.',
                           fr=f'Pas de {cfg.tracking / c.FILE} : aucun cas ne demande d\'avis. Lancer '
                              f'`zc citation-keys plan`.'))
    stored = {new: old for old, new in registry.VALUES['cles decider', 'decisions'].items()}
    decisions = {}
    for text in args.decisions:
        item, _, decision = text.partition('=')
        if not item.strip() or decision.strip().lower() not in stored:
            raise SystemExit(L(en=f'“{text}”: write ITEM=decision (keep, skip, native or extra).',
                               fr=f'« {text} » : écrire FICHE=décision (keep, skip, native ou extra).'))
        decisions[item.strip().upper()] = stored[decision.strip().lower()]
    tracking = c.load(cfg)
    n = c.decide(tracking, decisions, args.reason or '')
    b = _read_up_to_date(cfg)
    state = bbt.detect(cfg.zotero_dir)
    c.write(cfg, b, c.analyze(b, cfg, state, tracking, with_extra=state.present), privacy.hidden_keys(b, cfg), tracking)
    counts = [plural(n, en='case decided', fr='cas décidé', en_plural='cases decided')] if n else []
    print(_decisions_written(cfg.tracking / c.FILE, counts,
                             L(en='Run `zc citation-keys plan` to get the plan.',
                               fr='Lancer `zc citation-keys plan` pour obtenir le plan.')))
    return 0


def filenames_make_plan(args) -> int:
    from zot_clean import apply as a, bbt, config, api, reader, filenames as n, plans
    from zot_clean.api import APIError, Refusal
    cfg = config.load(args.workspace)
    try:
        if warn_msg := a.check_sync(cfg):
            _warn(warn_msg)
        client = api.from_config(cfg)
        b = a.read_up_to_date(cfg, client, _progress)
        storage = bbt.file_storage(cfg.zotero_dir)
        # A missing file is renamed only if it is stored on zotero.org and Zotero syncs there (D158).
        online, cause = (None, L(en='option --offline', fr='option --offline')) if args.offline else (
            _online_files(cfg, b, n.missing(b), client) if storage == bbt.ZOTERO_ORG else ({}, ''))
        if cause:
            print(L(en=f'Files missing from the disk not looked for on zotero.org ({cause}), they will not be renamed.',
                    fr=f'Fichiers absents du disque non cherchés sur zotero.org ({cause}), ils ne seront pas '
                       f'renommés.'))
        plan, report = n.make_plan(b, cfg, client, online, storage)
    except n.UnsupportedTemplate as e:
        print(e, file=sys.stderr)
        return 1
    except (Refusal, APIError, FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groups:
        cfg.reports.mkdir(parents=True, exist_ok=True)
        output = cfg.reports / f'noms-{date.today():%Y-%m-%d}.md'
        output.write_text(report, encoding='utf-8')
        print(L(en=f'Nothing to rename: the main files have the expected name, except the cases left aside.\n'
                   f'Report: {output}',
                fr=f'Rien à renommer : les fichiers principaux portent le nom attendu, hors cas laissés de côté.\n'
                   f'Rapport : {output}'))
        return 0
    path = plans.write(plan, cfg.plans, report)
    print(L(en=f'{len(plan.groups)} file(s) to rename.', fr=f'{len(plan.groups)} fichier(s) à renommer.'))
    print(_plan_paths(path))
    print(L(en=f'Read the report, then `zc apply {path} --trial`, sync Zotero and check with `zc show` that the '
               'files of the trial have their new name before `--all`.',
            fr=f'Relire le rapport, puis `zc apply {path} --trial`, synchroniser Zotero et vérifier avec `zc show` '
               'que les fichiers de l\'essai portent leur nouveau nom avant `--all`.'))
    return 0


def show(args) -> int:
    from zot_clean import config, reader, show as v
    if not args.keys and not args.tag:
        print(L(en='Give item keys, or a tag with --tag.', fr='Donner des clés de fiches, ou un tag avec --tag.'),
              file=sys.stderr)
        return 1
    cfg = config.load(args.workspace)
    try:
        b = _read_up_to_date(cfg)
    except (FileNotFoundError, reader.UnknownSchema) as e:
        print(e, file=sys.stderr)
        return 2
    if args.tag:
        print(v.describe_tag(b, cfg, args.tag))
    if args.keys:
        print(v.describe(b, cfg, args.keys))
    return 0


def journal(args) -> int:
    from zot_clean import config, journal as jl
    cfg = config.load(args.workspace)
    summaries = jl.all_entries(cfg.journal)
    if not summaries:
        print(L(en='No journaled write.', fr='Aucune écriture journalisée.'))
        return 0
    undone = {n for r in summaries if r.finished for n in r.header.get('annule', [])}
    for r in summaries:
        e = r.header
        statuses = list(r.groups.values())  # stored statuses (D209): « fait », « conflit », « erreur »
        state = (L(en='undone', fr='annulé') if r.path.name in undone
                 else L(en='finished', fr='terminé') if r.finished else L(en='interrupted', fr='interrompu'))
        conflicts = sum(s in ('conflit', 'erreur') for s in statuses)
        in_conflict = L(en=f', {conflicts} in conflict', fr=f', {conflicts} en conflit') if conflicts else ''
        # Stored modes (D209) « essai » and « tout », shown with the names of the options.
        mode = {'essai': L(en='trial', fr='essai'), 'tout': L(en='all', fr='tout')}.get(e.get('mode', '?'), e.get('mode', '?'))
        print(L(en=f"{r.path.name}  {mode:5}  {statuses.count('fait'):4} group(s) done"
                   f"{in_conflict}, {r.all_items} element(s), {state}",
                fr=f"{r.path.name}  {mode:5}  {statuses.count('fait'):4} groupe(s) faits"
                   f"{in_conflict}, {r.all_items} élément(s), {state}"))
    return 0


def _stored_value(table: dict[str, str]):
    """Argument type of an option whose English value (D219) is translated into the word stored in the working
    folder (D209), which the modules expect."""
    stored = {new: old for old, new in table.items()}

    def value(text: str) -> str:
        if (word := text.strip().lower()) in stored:
            return stored[word]
        raise argparse.ArgumentTypeError(f"invalid choice: {text!r} (choose from {', '.join(stored)})")
    return value


def _workspace(parser, help_text: str = 'working folder (by default, the one that contains config.toml)') -> None:
    # `dest` stays `folder`, the name `run_command` reads for every command, `zc init` included.
    parser.add_argument('--workspace', type=path, help=help_text)


def build_parser() -> argparse.ArgumentParser:
    """Commands, subcommands and options in English, as `registry.py` names them (D219). Help in English only
    (D215)."""
    p = argparse.ArgumentParser(prog='zc', description='Put and keep order in your Zotero library.')
    p.add_argument('--version', action='version', version=f'zot-clean {__version__}')
    under = p.add_subparsers(dest='command')
    s = under.add_parser('init', help='Creates a working folder (configuration, API key, instructions for the agent)')
    s.add_argument('folder', nargs='?', type=path, default=Path('.'),
                   help='folder to create (by default, the current folder)')
    s.add_argument('--zotero-dir', type=path, help='Zotero data folder (by default, ~/Zotero)')
    s.add_argument('--library-language', choices=lang.LANGUAGES,
                   help='language of the library, for a new working folder (asked in a terminal when missing)')
    s.add_argument('--update', action='store_true',
                   help="only updates the agent's instructions (AGENTS.md and skills)")
    s.set_defaults(handler=init)
    s = under.add_parser('audit', help='Read-only audit of the library')
    _workspace(s)
    s.add_argument('--no-hashes', action='store_true',
                   help='do not compare the content of the PDFs (faster on a large library)')
    s.add_argument('--offline', action='store_true', help='do not look on zotero.org for the files missing from disk')
    s.set_defaults(handler=audit)
    s = under.add_parser('backup', help='Backs up the Zotero folder (Zotero closed)')
    _workspace(s)
    s.set_defaults(handler=make_backup)
    s = under.add_parser('apply', help='Applies a plan prepared by a step (trial first)')
    s.add_argument('plan', type=path, help='plan file (plans/…json)')
    mode = s.add_mutually_exclusive_group()
    mode.add_argument('--trial', action='store_true', help='applies the first groups only')
    mode.add_argument('--all', action='store_true', help='applies the rest (after the trial and a backup)')
    _workspace(s)
    s.set_defaults(handler=apply_plan)
    s = under.add_parser('undo', help='Prepares the undoing of a write (journal or plan)')
    s.add_argument('target', type=path, help='journal (journal/…jsonl) or plan (plans/…json) to undo')
    _workspace(s)
    s.set_defaults(handler=undo_plan)
    s = under.add_parser('duplicates', help='Step 2 of the cleanup, duplicates')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('find', help='Finds the duplicates and updates suivi/doublons.toml')
    _workspace(t)
    t.set_defaults(handler=duplicates_find)
    t = ss.add_parser('plan', help='Prepares the merge plan of the decided groups')
    _workspace(t)
    t.set_defaults(handler=duplicates_make_plan)
    t = ss.add_parser('accept', help='Decides to merge groups, or all the certain groups (--certain)')
    t.add_argument('keys', nargs='*', metavar='KEY', help='key of one item of each group')
    t.add_argument('--certain', action='store_true', help='merges all the certain groups still to judge')
    t.add_argument('--except', dest='except_', nargs='+', default=[], metavar='KEY',
                   help='items to take out of the group designated by KEY or --keep, which is merged without them '
                        '(each one judged not a duplicate of the rest); with --certain, also the certain groups to '
                        'leave aside')
    t.add_argument('--keep', nargs='+', default=[], metavar='KEY',
                   help='item to keep in its group, the group being accepted at the same time')
    _workspace(t)
    t.set_defaults(handler=duplicates_decide, tracking_action='accept')
    t = ss.add_parser('reject', help='Judges groups distinct (not duplicates), which will no longer be proposed')
    t.add_argument('keys', nargs='+', metavar='KEY', help='key of one item of each group')
    t.add_argument('--reason', help='reason, kept in the file (different editions…)')
    _workspace(t)
    t.set_defaults(handler=duplicates_decide, tracking_action='reject')
    s = under.add_parser('attachments', help='Identical PDFs, extra copies or copies on the wrong item (step 2)')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('find', help='Finds the identical PDFs and updates suivi/pieces.toml')
    _workspace(t)
    t.set_defaults(handler=attachments_find)
    t = ss.add_parser('plan', help='Prepares the plan of the decided groups')
    _workspace(t)
    t.set_defaults(handler=attachments_make_plan)
    t = ss.add_parser('accept', help='Decides which copies go to the trash or to another item')
    t.add_argument('--trash', nargs='+', default=[], metavar='COPY', help='copies to move to the trash')
    t.add_argument('--move', nargs='+', default=[], metavar='COPY=ITEM', help='copies to attach to another item')
    t.add_argument('--reason', help='free note, kept in the file')
    _workspace(t)
    t.set_defaults(handler=attachments_decide, tracking_action='accept')
    t = ss.add_parser('reject', help='Keeps all the copies of these groups (wanted copies, no longer reported)')
    t.add_argument('copies', nargs='+', metavar='COPY', help='key of one copy of each group')
    t.add_argument('--reason', help='reason, kept in the file (chapter and whole book…)')
    _workspace(t)
    t.set_defaults(handler=attachments_decide, tracking_action='reject')
    s = under.add_parser('metadata', help='Step 3 of the cleanup, metadata')
    ss = s.add_subparsers(dest='subcommand', required=True)
    for name, help_text, action in (('identifiers', 'Corrects, checks and looks for DOIs', metadata_identifiers),
                                    ('types', 'Corrects the type of the items from the DOI source', metadata_types),
                                    ('complete', 'Fills in the empty fields from the DOI', metadata_complete)):
        t = ss.add_parser(name, help=help_text)
        t.add_argument('--refresh', action='store_true', help='empties the cache of the sources before starting')
        _workspace(t)
        t.set_defaults(handler=action)
    t = ss.add_parser('accept', help='Accepts cases to judge, or all the obvious ones (--obvious)')
    t.add_argument('keys', nargs='*', metavar='KEY[=N]',
                   help='item (KEY:problem for only one of its cases), with the number of the chosen proposal')
    t.add_argument('--obvious', action='store_true', help='accepts all the obvious cases still to judge')
    t.add_argument('--except', dest='except_', nargs='+', default=[], metavar='KEY',
                   help='items to leave aside with --obvious')
    _workspace(t)
    t.set_defaults(handler=metadata_decide, tracking_action='accept')
    t = ss.add_parser('reject', help='Rejects the cases to judge of these items, which will no longer be proposed')
    t.add_argument('keys', nargs='+', metavar='KEY')
    _workspace(t)
    t.set_defaults(handler=metadata_decide, tracking_action='reject')
    s = under.add_parser('inbox', help='Ongoing management, sorting of the new items (Inbox and outside the subjects)')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('prepare', help='Duplicates, metadata and neighbouring themes of the items to sort')
    _workspace(t)
    t.set_defaults(handler=inbox_prepare)
    t = ss.add_parser('plan', help='A single plan for the judged items (merges, fields, filing)')
    _workspace(t)
    t.set_defaults(handler=inbox_make_plan)
    s = under.add_parser('subjects', help='Step 4 of the cleanup, outline of the subjects (then step 5, filing)')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('inventory', help='Inventory of the existing classification, prepares suivi/fonds.toml')
    _workspace(t)
    t.set_defaults(handler=subjects_inventory)
    t = ss.add_parser('validate', help='Checks plan.md and suivi/fonds.toml')
    t.add_argument('--save', action='store_true', help='saves the validation (after the agreement of the user)')
    _workspace(t)
    t.set_defaults(handler=subjects_validate)
    t = ss.add_parser('track', help='Carries over to plan.md the themes created, renamed, moved or deleted in Zotero')
    t.add_argument('--save', action='store_true',
                   help='writes plan.md and the tracking files (after the agreement of the user)')
    _workspace(t)
    t.set_defaults(handler=subjects_track)
    t = ss.add_parser('titles', help='All the titles of a theme, to propose subthemes')
    t.add_argument('path', help='path of the theme in the subjects (“Psychology/Perception”)')
    _workspace(t)
    t.set_defaults(handler=subjects_titles)
    t = ss.add_parser('pending', help='Items to distribute or to place, in bundles (step 5)')
    t.add_argument('--abstract', metavar='KEY', help='gives the abstract of a doubtful item')
    t.add_argument('--reviewed', nargs='+', metavar='KEY',
                   help='marks these collections to distribute as entirely judged')
    t.add_argument('--leave-out', nargs='+', metavar='KEY',
                   help='notes these items without a place as seen and left out of the subjects')
    _workspace(t)
    t.set_defaults(handler=subjects_pending)
    t = ss.add_parser('plan', help='Prepares the filing plan (step 5), can be rerun after each pass')
    t.add_argument('--roots', action='store_true', help='also renames the roots after [racines] of fonds.toml')
    _workspace(t)
    t.set_defaults(handler=subjects_make_plan)
    s = under.add_parser('tags', help='Step 6 of the cleanup, tags (automatic, variants, concepts, statuses)')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('inventory', help='Inventory of the tags, prepares or completes suivi/tags.toml')
    _workspace(t)
    t.set_defaults(handler=tags_inventory)
    t = ss.add_parser('plan', help='Prepares the plan of the accepted rules, can be rerun after each pass')
    _workspace(t)
    t.set_defaults(handler=tags_make_plan)
    action = _stored_value(registry.VALUES['tags accepter', '--sort'])
    actions = ', '.join(registry.VALUES['tags accepter', '--sort'].values())
    for verb, help_text in (('accept', 'Accepts rules of suivi/tags.toml, or all the obvious ones (--obvious)'),
                            ('reject', 'Rejects rules of suivi/tags.toml')):
        t = ss.add_parser(verb, help=help_text)
        t.add_argument('names', nargs='*', metavar='NAME', help='[[tag]] entries, by their name in quotes')
        t.add_argument('--variants', nargs='+', default=[], metavar='NAME',
                       help='[[variantes]] groups, by their target or one of their names')
        t.add_argument('--automatic-rule', action='store_true', help='rule that removes the automatic tags')
        t.add_argument('--imported-rule', action='store_true', help='rule that removes the imported keywords')
        if verb == 'accept':
            t.add_argument('--obvious', action='store_true',
                           help='accepts all the obvious entries and groups still to judge')
            t.add_argument('--except', dest='except_', nargs='+', default=[], metavar='NAME',
                           help='names to leave aside with --obvious')
            t.add_argument('--action', type=action, help=f'other action for the given entries ({actions})')
            t.add_argument('--target', help='other target for the given entries and groups')
        _workspace(t)
        t.set_defaults(handler=tags_decide, tracking_action=verb)
    t = ss.add_parser('add', help='Adds to suivi/tags.toml, accepted, a rule for tags without an entry')
    t.add_argument('names', nargs='+', metavar='NAME', help='tags, by their name in quotes')
    t.add_argument('--action', type=action, required=True, help=actions)
    t.add_argument('--target', help='name aimed at by a concept, a status or a merge')
    t.add_argument('--user', action='store_true',
                   help='explicit request of the user (source « utilisateur », the only one to change a protected tag)')
    _workspace(t)
    t.set_defaults(handler=tags_add)
    s = under.add_parser('citation-keys', help='Step 7 of the cleanup, citation keys (duplicates, leftovers in Extra)')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('plan', help='Prepares the plan of the duplicate keys and of the “Citation Key:” lines of '
                                   'Extra, can be rerun after each pass')
    _workspace(t)
    t.set_defaults(handler=keys_make_plan)
    t = ss.add_parser('decide', help='Decides the cases of suivi/cles.toml (key kept, duplicate or Extra line)')
    t.add_argument('decisions', nargs='+', metavar='ITEM=DECISION',
                   help='keep (the item keeps the key of its duplicate), skip, native or extra (Extra line)')
    t.add_argument('--reason', help='free note, kept in the file')
    _workspace(t)
    t.set_defaults(handler=keys_decide)
    s = under.add_parser('filenames', help="Step 8 of the cleanup, file names after Zotero's template")
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('plan', help='Prepares the renaming of the files lagging behind, can be rerun after each pass')
    t.add_argument('--offline', action='store_true',
                   help='do not look on zotero.org for the files missing from disk (they are not renamed)')
    _workspace(t)
    t.set_defaults(handler=filenames_make_plan)
    s = under.add_parser('journal', help='Lists the journaled writes and their state')
    _workspace(s)
    s.set_defaults(handler=journal)
    s = under.add_parser('show', help='Shows items in full (fields, start of the text of the PDFs) to judge a case')
    s.add_argument('keys', nargs='*', metavar='KEY', help='keys of items or attachments')
    s.add_argument('--tag', metavar='NAME', help='shows the elements that carry this tag (step 6)')
    _workspace(s)
    s.set_defaults(handler=show)
    s = under.add_parser('config', help='Configuration of the working folder')
    ss = s.add_subparsers(dest='subcommand', required=True)
    t = ss.add_parser('show', help='Prints the effective configuration, defaults included, as TOML (read-only)')
    _workspace(t)
    t.set_defaults(handler=config_show)
    for name, (help_text, _) in UPCOMING.items():
        under.add_parser(name, help=help_text)
    return p


def path(text: str) -> Path:
    """Path given as an argument, `~` included: Windows PowerShell 5.1 does not expand it for a program (D193)."""
    return Path(text).expanduser()


def utf8_output() -> None:
    """On Windows, an output redirected to a pipe (the one an agent reads) is written in the machine's character
    set, and a Greek title or an arrow stopped the command there. It switches to UTF-8 (D193)."""
    for stream in (sys.stdout, sys.stderr):
        if (getattr(stream, 'encoding', '') or '').lower().replace('-', '') != 'utf8' and hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    argv = list(argv if argv is not None else sys.argv[1:])
    if former := former_names(argv):
        _refuse_former_names(argv, *former)
    p = build_parser()
    args = p.parse_args(argv)
    if args.command is None:
        p.print_help()
        return 0
    if hasattr(args, 'handler'):
        start = time.monotonic()
        code = run_command(args)
        _save_duration(args, argv, start, code)
        return code
    print(L(en=f'zc {args.command}: not available yet (planned for {UPCOMING[args.command][1]}).',
            fr=f'zc {args.command} : pas encore disponible (prévu pour la {UPCOMING[args.command][1]}).'),
          file=sys.stderr)
    return 1


def former_names(argv: list[str]) -> tuple[list[str], list[tuple[str, str]]] | None:
    """The command line written with the English names, and the words renamed, when `argv` uses a name of version
    0.3.2 (command, subcommand, option or option value, D213, D219). None when it uses none.

    The line is first brought back to the old command and subcommand, with the new options written under their old
    names, so that `registry.translate` finds the values to translate whatever the mix of old and new names. Since
    `translate` maps word for word, the renamed words are those that differ."""
    if not argv:
        return None
    new_commands = {new: old for old, (new, _) in registry.COMMANDS.items()}
    old = argv[0] if argv[0] in registry.COMMANDS else new_commands.get(argv[0])
    if old is None:
        return None
    under = registry.COMMANDS[old][1]
    head, rest = [old], argv[1:]
    if under and rest:
        new_under = {new: o for o, new in under.items()}
        if rest[0] in under or rest[0] in new_under:
            head.append(rest[0] if rest[0] in under else new_under[rest[0]])
            rest = rest[1:]
    new_options = {new: o for o, new in registry.OPTIONS.items()}
    former = []
    for word in rest:
        name, equals, value = word.partition('=')
        if word.startswith('--') and name not in registry.OPTIONS and name in new_options:
            word = new_options[name] + equals + value
        former.append(word)
    english = registry.translate(head + former)
    renamed = [(a, b) for a, b in zip(argv, english) if a != b]
    return (english, renamed) if renamed else None


def _shell_word(word: str) -> str:
    """`word` as typed in the user's shell. Under Windows, cmd and PowerShell take backslashes as they are and only
    double quotes protect a space; elsewhere, POSIX quoting."""
    if os.name == 'nt':
        return f'"{word}"' if not word or re.search(r'[\s&|<>()^;,%"\'`$]', word) else word
    return shlex.quote(word) if not word or re.search(r'''[\s'"`$;&|<>()*?\\!#]''', word) else word


def _refuse_former_names(argv: list[str], english: list[str], renamed: list[tuple[str, str]]) -> None:
    """Refusal of a name of version 0.3.2, with the full equivalent command line (D213), in the language of the
    working folder that the line designates, or of the current one (English outside a working folder, D222)."""
    from zot_clean import config
    folder = None
    for i, word in enumerate(argv):
        name, equals, value = word.partition('=')
        if name in ('--workspace', '--dossier'):
            value = value if equals else (argv[i + 1] if i + 1 < len(argv) else '')
            folder = path(value) if value else None
            break
    else:
        folder = config.find_workspace()
    line = 'zc ' + ' '.join(_shell_word(w) for w in english)
    with lang.language(lang.of_workspace(folder)):
        pairs = ', '.join(L(en=f'`{a}` is now `{b}`', fr=f'`{a}` devient `{b}`') for a, b in renamed)
        print(L(en=f'zc uses English names since version 0.4.0 ({pairs}). Run instead\n  {line}',
                fr=f'zc emploie des noms anglais depuis la version 0.4.0 ({pairs}). Lancer plutôt\n  {line}'),
              file=sys.stderr)
    raise SystemExit(2)


def config_show(args) -> int:
    """`zc config show`, read-only: the effective configuration, defaults included, under the sections and keys of
    config.toml (D209), so that an agent can read the language of the library (D221)."""
    from zot_clean import config
    cfg = config.load(args.workspace)
    # Pilot bench: the language and the role of each name, said in a sentence rather than left to the keys (D242).
    print(L(en='# Language of the library: English (en). Roles of the [methode] names: inbox = the Inbox, projets = '
               'the roots of the projects, fonds = the root of the subjects, archives = the root of the archives, '
               'etats = the reading statuses, autres_tags = the marks.',
            fr='# Langue de la bibliothèque : français (fr). Rôle des noms de [methode] : inbox = l\'Inbox, projets = '
               'les racines des projets, fonds = la racine du fonds, archives = la racine des archives, etats = les '
               'états de lecture, autres_tags = les marques.'))
    print(toml_text(config.to_stored(cfg)), end='')
    return 0


def toml_text(data: dict) -> str:
    """Sections of `config.to_stored` written as TOML. A value left to its computed default (None, such as the
    backup folder next to the Zotero folder) is not written."""
    def key(k: str) -> str:
        return k if re.fullmatch(r'[A-Za-z0-9_-]+', k) else json.dumps(k, ensure_ascii=False)

    def value(v) -> str:
        if isinstance(v, bool):
            return 'true' if v else 'false'
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, Path):
            return json.dumps(v.as_posix(), ensure_ascii=False)
        if isinstance(v, (list, tuple)):
            return '[' + ', '.join(value(x) for x in v) + ']'
        if isinstance(v, dict):
            return '{ ' + ', '.join(f'{key(k)} = {value(x)}' for k, x in v.items()) + ' }' if v else '{}'
        return json.dumps(str(v), ensure_ascii=False)  # TOML basic strings take the JSON escapes

    blocks = []
    for section, values in data.items():
        lines = [f'[{key(section)}]'] + [f'{key(k)} = {value(v)}' for k, v in values.items() if v is not None]
        blocks.append('\n'.join(lines) + '\n')
    return '\n'.join(blocks)


def _save_duration(args, argv: list[str], start: float, code: int) -> None:
    """One line per command in `journal/commandes.jsonl` of the working folder (D173), to know where the
    time of a session goes. The intervals between two commands give the time of the agent and of the user. Nothing
    leaves the computer, and a write failure never prevents the command."""
    from zot_clean import config
    try:
        folder = args.folder if args.command == 'init' else getattr(args, 'workspace', None) or config.find_workspace()
        if not folder or not (folder / config.FILE).is_file():
            return
        command = ' '.join(x for x in (args.command, getattr(args, 'subcommand', None)) if x)
        line = {'commande': command, 'arguments': argv[len(command.split()):],
                 'debut': datetime.now().astimezone().isoformat(timespec='seconds'),
                 'duree': round(time.monotonic() - start, 1), 'code': code}
        (folder / 'journal').mkdir(exist_ok=True)
        from zot_clean.journal import REGISTRY
        with open(folder / 'journal' / REGISTRY, 'a', encoding='utf-8') as f:
            f.write(json.dumps(line, ensure_ascii=False) + '\n')
    except (OSError, SystemExit):
        pass


INTERACTIVE_COMMANDS = {'init'}  # they ask questions, which a continuously updated line would erase


class _Screen:
    """Terminal output shared with the timer line: each write first erases that line, which the
    timer then redraws, so that the command's messages do not mix with it."""

    def __init__(self, real, timer):
        self.real, self.timer = real, timer

    def write(self, text):
        with self.timer.lock:
            self.timer.erase()
            return self.real.write(text)

    def __getattr__(self, name):
        return getattr(self.real, name)


class Timer:
    """Under a terminal, « zc audit en cours… 12 s » is shown from the start and updated every second, then
    « zc audit terminé en 14 s. » if the command took a while (D207). Nothing when the output is not a terminal (an
    agent reading the output), nor for a command that asks questions."""

    def __init__(self, name: str, stream=None, interval: float = 1.0, threshold: float = 2.0):
        self.name, self.stream, self.interval, self.threshold = name, stream or sys.stderr, interval, threshold
        self.lock, self.end, self.shown = threading.RLock(), threading.Event(), False
        self.active = hasattr(self.stream, 'isatty') and self.stream.isatty()

    def erase(self):
        if self.shown:
            self.stream.write('\r\x1b[K')
            self.shown = False

    def _draw(self):
        with self.lock:
            sys.stdout.flush()
            self.erase()
            self.stream.write(f'{self.running} {int(time.monotonic() - self.start)} s')
            self.stream.flush()
            self.shown = True

    def _loop(self):
        while not self.end.wait(self.interval):
            self._draw()

    def __enter__(self):
        self.start = time.monotonic()
        # Text chosen here, in the language of the command: the drawing thread does not see the current language.
        self.running = L(en=f'{self.name} running…', fr=f'{self.name} en cours…')
        if self.active:
            self.previous = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = _Screen(sys.stdout, self), _Screen(sys.stderr, self)
            self._draw()
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *exc):
        if not self.active:
            return False
        self.end.set()
        self.thread.join()
        with self.lock:
            self.erase()
            sys.stdout, sys.stderr = self.previous
            duration = time.monotonic() - self.start
            if duration >= self.threshold:
                self.stream.write(L(en=f'{self.name} finished in {_duration(duration)}.\n',
                                    fr=f'{self.name} terminé en {_duration(duration)}.\n'))
            self.stream.flush()
        return False


def _duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f'{m} min {s:02d} s' if m else f'{s} s'


def run_command(args) -> int:
    """Runs the command. Any refusal or failure exits with a non-zero code and its message on the error output, so
    that an agent testing the return code sees it (pilot rehearsal). Refusals from the modules go through
    `SystemExit(message)`, those from writing through `Refusal` and `APIError`. The database reads made by the
    command share a single copy (`reader.share`)."""
    from zot_clean import config, lang, reader
    from zot_clean.api import APIError, Refusal
    command = getattr(args, 'command', None)
    folder = args.folder if command == 'init' else getattr(args, 'workspace', None) or config.find_workspace()
    with lang.language(lang.of_workspace(folder)):
        return _run(args, command)


def _run(args, command) -> int:
    from zot_clean import reader
    from zot_clean.api import APIError, Refusal
    name = ' '.join(x for x in ('zc', command, getattr(args, 'subcommand', None)) if x)
    timer = Timer(name) if command not in INTERACTIVE_COMMANDS else contextlib.nullcontext()
    try:
        with reader.share(), timer:
            code = args.handler(args)
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            raise
        print(e.code, file=sys.stderr)
        return 1
    except (Refusal, APIError) as e:
        print(e, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(L(en=f'File not found: {e.filename or e}', fr=f'Fichier introuvable : {e.filename or e}'),
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(L(en='Interrupted. An interrupted command can be run again as it is.',
                fr='Interrompu. Une commande interrompue se relance telle quelle.'), file=sys.stderr)
        return 130
    return code or 0


if __name__ == '__main__':
    sys.exit(main())
