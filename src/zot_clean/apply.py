"""Application of a plan, common base of all writes (D34 to D36, D42, D46, D47, D56).

Safeguards checked here, and not by the commands, so that no step
can bypass them. The key must be that of the account Zotero syncs
on this computer, and the plan must target that account. No invalid
key must block the sync. Beyond the trial, a trial of the
same plan must have succeeded and a recent backup exist. The trial always
covers the first groups of the plan, so that a rerun `--essai` only
resumes those that remain, never moving forward in the plan (D179).

The groups are processed in bundles of about 50 operations, rank by rank.
Before each batch, the items are reread through the API. For each field, if the
current value equals the after, nothing to do. If it equals the before, we write with the
reread version. Any other value is a conflict, and the group stops (an undo
plan leaves only that field, D39). After a 412, the item is reread
and rewritten once. The groups already done according to the plan's journals
are skipped, which makes any rerun safe.

Each write is recorded in the journal before being sent (D178). If its
response is lost, or if the command is interrupted, the reread that follows (new
attempt after a 412, resumption of the plan) finds the values already written, and
the intention left without confirmation then becomes a journaled write,
hence undoable, instead of passing for « nothing to do ».

The collections (D114) follow the same rule. A collection to create that
does not exist yet is created under the plan's key. If it already exists with
the wanted values, a previous run created it, and there is
nothing to do.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from zot_clean import journal, reader, backup
from zot_clean.config import Config
from zot_clean.lang import L
from zot_clean.api import BATCH, Client, Refusal
from zot_clean.journal import Journal
from zot_clean.plans import DEFAULTS, Group, Operation, Plan, normalize, value

TRIAL, ALL = 'essai', 'tout'
GROUPS_WITHOUT_PROGRESS = 20


@dataclass
class Outcome:
    journal: Path | None = None
    done: list[str] = field(default_factory=list)
    partials: dict[str, str] = field(default_factory=dict)
    conflicts: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    # Groups in conflict or in error after part of their writes, with the keys written (D181)
    stopped: dict[str, list[str]] = field(default_factory=dict)
    items_written: int = 0
    remaining: int = 0
    warnings: list[str] = field(default_factory=list)


def compare(op: Operation, data: dict, partial: bool = False) -> tuple[dict, list[str]]:
    """Fields to write and fields in conflict, from the current values `data`."""
    to_write, conflicts = {}, []
    for field_name, new in op.after.items():
        current = value(data, field_name)
        if current == normalize(field_name, new):
            continue
        if current == normalize(field_name, op.before.get(field_name, DEFAULTS.get(field_name, ''))):
            to_write[field_name] = new
        else:
            conflicts.append(field_name)
    return to_write, conflicts


def check_sync(cfg: Config) -> str | None:
    """Refuses if invalid keys block the sync (D56), warns if items remain to be sent."""
    invalid, unsynced, annotations = reader.sync_state(cfg.database)
    if invalid:
        raise Refusal(L(
            en=f"{len(invalid)} item(s) with an invalid key block Zotero's sync "
               f"({', '.join(invalid[:5])}). Repair them before any cleanup (see `zc audit`).",
            fr=f"{len(invalid)} élément(s) à clé invalide bloquent la synchronisation de Zotero "
               f"({', '.join(invalid[:5])}). Les réparer avant tout nettoyage (voir `zc audit`)."))
    if unsynced:
        return L(en=f'{unsynced} item(s) or collection(s) not synced yet. Let Zotero sync before going on, '
                    'otherwise these local changes are not seen by the plan.',
                 fr=f'{unsynced} élément(s) ou collection(s) pas encore synchronisés. Laisser Zotero synchroniser '
                    'avant de continuer, sinon ces changements locaux ne sont pas vus par le plan.')
    if annotations:
        return L(en=f'{annotations} PDF annotation(s) not synced yet, with no effect on this plan. If this number '
                    "does not go down after a sync, Zotero cannot send them (see its sync errors), and they exist "
                    "only on this computer.",
                 fr=f'{annotations} annotation(s) de PDF pas encore synchronisée(s), sans effet sur ce plan. Si ce '
                    "nombre ne baisse pas après une synchronisation, Zotero n'arrive pas à les envoyer (voir ses "
                    "erreurs de synchronisation), et elles n'existent que sur cet ordinateur.")
    return None


def never_synced() -> str:
    return L(
        en="Zotero has never synced this library with a zotero.org account yet. But zot-clean changes the library "
           "through zotero.org, and Zotero then receives the changes by syncing. In Zotero, open Settings › Sync, "
           "sign in to your zotero.org account (create it if needed), start the sync (green arrow at the top right) "
           "and wait for it to finish.",
        fr="Zotero n'a encore jamais synchronisé cette bibliothèque avec un compte zotero.org. Or zot-clean modifie la "
           "bibliothèque en passant par zotero.org, puis Zotero reçoit les changements en synchronisant. Dans Zotero, "
           "ouvrir Réglages › Synchronisation, se connecter à son compte zotero.org (le créer au besoin), lancer la "
           "synchronisation (flèche verte en haut à droite) et attendre qu'elle se termine.")
def account_remedy() -> str:
    """Remedy proposed when the key is not that of the synced account, `{compte}` standing for the latter."""
    return L(en="Sign in to zotero.org with the account {compte}, create a key there "
                "(https://www.zotero.org/settings/keys/new, same checkboxes as the first time), then run "
                "`zc init` again in the working folder to replace the old one.",
             fr="Se connecter sur zotero.org avec le compte {compte}, y créer une clé "
                "(https://www.zotero.org/settings/keys/new, mêmes cases à cocher que la première fois), puis "
                "relancer `zc init` dans le dossier de travail pour remplacer l'ancienne.")


def check_account(user: int, account: reader.Account, remedy: str | None = None) -> None:
    """Refuses if the key (account `user`) is not that of the account Zotero syncs on this computer.
    The plans are built on the local database and written by the key: with the key of another account (personal
    and institutional, for example), they would target another library, and `read_up_to_date` would mix its
    changes in. A never-synced database does not say which account is its own, and Zotero would not receive the
    writes made through the API. Local check, without a request, done before any call to zotero.org."""
    if account.id is None:
        raise Refusal(never_synced() + L(en=' Then run the command again.', fr=' Relancer ensuite la commande.'))
    if account.id != user:
        name = (L(en=f'"{account.name}" (no. {account.id})', fr=f'« {account.name} » (n° {account.id})')
                if account.name else L(en=f'no. {account.id}', fr=f'n° {account.id}'))
        raise Refusal(L(
            en=f"The API key belongs to the zotero.org account no. {user}, while Zotero on this computer syncs the "
               f"account {name}. zot-clean reads the library of this computer and writes with the key, so it would "
               "change a different library from this one. ",
            fr=f"La clé API est celle du compte zotero.org n° {user}, alors que Zotero, sur cet "
               f"ordinateur, synchronise le compte {name}. zot-clean lit la bibliothèque de cet ordinateur "
               "et écrit avec la clé, il modifierait donc une autre bibliothèque que celle-ci. ")
            + (remedy or account_remedy()).format(compte=name))


def stale_copy(local_version: int, server: int) -> str:
    """Refusal common to the commands that read the real state on the local copy (D119, D123). Zotero, even open,
    does not always fetch by itself the collection changes made by the API, hence the manual sync."""
    return L(en=f"Zotero has not received the latest changes of the library yet (local version {local_version}, "
                f"server {server}). Start Zotero's sync by hand (green arrow at the top right), wait for it to "
                "finish, then run the command again.",
             fr=f"Zotero n'a pas encore reçu les derniers changements de la bibliothèque (version locale "
                f"{local_version}, serveur {server}). Lancer à la main la synchronisation de Zotero (flèche verte "
                "en haut à droite), attendre qu'elle se termine, puis relancer la commande.")



def read_up_to_date(cfg: Config, client: Client, notify=lambda m: None, read=None,
                optional: bool = False) -> reader.Library:
    """Up-to-date library to prepare a plan (D171). Read on the local copy (D119); if Zotero has not yet
    received the latest changes from the server (those of the previous pass, usually), they are read on zotero.org
    and carried over, instead of waiting for the sync. The base rereads each item before writing anyway.
    `optional`: zotero.org unreachable, the local copy alone is enough (commands that only read). All
    the planning goes through here, hence the check of the key's account, before any request to zotero.org."""
    from zot_clean.api import APIError
    b = (read or (lambda: reader.read(cfg.database)))()
    check_account(client.user, b.account)
    try:
        behind = client.server_version() > b.version
        ch = client.changes(b.version) if behind else None
    except APIError:
        if not optional:
            raise
        notify(L(en='zotero.org unreachable, reading the local copy only, which may not have received the latest '
                    'changes.',
                 fr='zotero.org injoignable, lecture de la seule copie locale, qui peut ne pas avoir reçu les '
                    'derniers changements.'))
        return b
    if ch:
        reader.apply_changes(b, ch, cfg.database.parent / 'storage')
        notify(L(en=f'{ch.size} change(s) not yet received by Zotero, read from zotero.org.',
                 fr=f'{ch.size} changement(s) pas encore reçus par Zotero, lus sur zotero.org.'))
    return b

MANAGEMENT_STEPS = {'inbox'}


def to_process(plan: Plan, cfg: Config, mode: str, now: datetime | None = None) -> list[Group]:
    done = journal.done_groups(cfg.journal, plan.fingerprint)
    remaining = [g for g in plan.groups if g.id not in done]
    if mode == TRIAL or len(plan.groups) <= cfg.writing.trial:
        trial = {g.id for g in plan.groups[:cfg.writing.trial]}
        return [g for g in remaining if g.id in trial]
    small = _small_management_plan(plan, cfg)
    if not small and not journal.trial_done(cfg.journal, plan.fingerprint):
        raise Refusal(L(en="No trial of this plan has succeeded. Run `zc apply <plan> --trial` first, then check "
                            "the result in Zotero.",
                        fr="Aucun essai de ce plan n'a réussi. Lancer d'abord `zc apply <plan> --trial`, "
                           "puis vérifier le résultat dans Zotero."))
    if remaining and not small and not backup.latest(cfg, now):
        raise Refusal(L(en=f'No backup less than {cfg.backup.delay_hours:g} hours old. '
                           'Close Zotero, run `zc backup`, then try again.',
                        fr=f'Aucune sauvegarde de moins de {cfg.backup.delay_hours:g} heures. '
                           'Fermer Zotero, lancer `zc backup`, puis relancer.'))
    return remaining


def _small_management_plan(plan: Plan, cfg: Config) -> bool:
    """Inbox sorting touching fewer than `small_management_plan` items, applied without trial or recent
    backup (D136, D138): it only files and corrects a few items, and `zc undo` undoes it."""
    items = {op.key for g in plan.groups for op in g.operations if op.kind == 'items'}
    return plan.step in MANAGEMENT_STEPS and len(items) < cfg.writing.small_management_plan


def apply_plan(plan: Plan, plan_path: Path, client: Client, cfg: Config, mode: str,
              now: datetime | None = None) -> Outcome:
    if plan.library != client.user:
        raise Refusal(L(en=f'This plan was prepared for the account {plan.library}, the key belongs to the account '
                           f'{client.user}.',
                        fr=f'Ce plan a été préparé pour le compte {plan.library}, la clé est celle du compte '
                           f'{client.user}.'))
    check_account(client.user, reader.synced_account(cfg.database))
    outcome = Outcome()
    if warn_msg := check_sync(cfg):
        outcome.warnings.append(warn_msg)
    already = journal.done_groups(cfg.journal, plan.fingerprint)
    groups = to_process(plan, cfg, mode, now)
    outcome.remaining = len(plan.groups) - len(already) - len(groups)
    if not groups:
        return outcome
    unconfirmed = journal.pending([r.path for r in journal.for_plan(cfg.journal, plan.fingerprint)])
    j = Journal(cfg.journal, plan.step)
    outcome.journal = j.path
    j.header(plan=plan_path.name, fingerprint=plan.fingerprint, step=plan.step, mode=mode,
              library=plan.library, resumed=bool(already), undoes=plan.undoes)
    handled = 0
    try:
        for n, bundle in enumerate(_group_batches(groups), 1):
            _Execution(bundle, client, j, outcome, plan.partial, unconfirmed).run()
            handled += len(bundle)
            # Progress on the error output for a long plan, every five bundles of about fifty operations.
            if len(groups) > GROUPS_WITHOUT_PROGRESS and (handled == len(groups) or n % 5 == 0):
                client.notify(L(en=f'{handled}/{len(groups)} groups processed', fr=f'{handled}/{len(groups)} groupes traités'))
    except BaseException:
        j.close()
        raise
    outcome.remaining += len(outcome.conflicts) + len(outcome.errors)
    j.end(done=len(outcome.done), partials=len(outcome.partials), conflicts=len(outcome.conflicts),
          errors=len(outcome.errors), all_items=outcome.items_written)
    return outcome


def _group_batches(groups: list[Group]):
    bundle, n = [], 0
    for g in groups:
        bundle.append(g)
        n += len(g.operations)
        if n >= BATCH:
            yield bundle
            bundle, n = [], 0
    if bundle:
        yield bundle


def _batches(ops: list[tuple[Group, Operation]]):
    """Batches of at most 50 operations, of a single kind (items or collections), without the same item twice."""
    batches: list[list] = []
    for g, op in ops:
        for batch in batches:
            if len(batch) < BATCH and batch[0][1].kind == op.kind and all(o.key != op.key for _, o in batch):
                batch.append((g, op))
                break
        else:
            batches.append([(g, op)])
    return batches


class _Execution:
    def __init__(self, bundle: list[Group], client: Client, j: Journal, outcome: Outcome, partial: bool,
                 unconfirmed: dict[tuple[str, str], dict]):
        self.bundle, self.client, self.j, self.outcome, self.partial = bundle, client, j, outcome, partial
        self.unconfirmed = unconfirmed  # (group, key) -> unconfirmed intention, from this journal or a previous one
        self.failure: dict[str, tuple[str, str]] = {}  # group -> (status, detail)
        self.left_aside: dict[str, list[str]] = {g.id: [] for g in bundle}
        self.writes: dict[str, list[str]] = {g.id: [] for g in bundle}

    def run(self):
        for rank in sorted({op.rank for g in self.bundle for op in g.operations}):
            ops = [(g, op) for g in self.bundle if g.id not in self.failure for op in g.operations if op.rank == rank]
            for batch in _batches(ops):
                self._batch(batch)
        for g in self.bundle:
            if g.id in self.failure:
                status, detail = self.failure[g.id]
                if self.writes[g.id]:  # a rank already written: the group is not intact (D181)
                    self.outcome.stopped[g.id] = self.writes[g.id]
                    detail += L(en=f", after writing {', '.join(self.writes[g.id])}",
                                fr=f", après l'écriture de {', '.join(self.writes[g.id])}")
                (self.outcome.conflicts if status == 'conflit' else self.outcome.errors)[g.id] = detail
            elif self.left_aside[g.id]:
                status = 'partiel'
                detail = L(en='fields left as they were: ', fr="champs laissés en l'état : ") + ', '.join(self.left_aside[g.id])
                self.outcome.partials[g.id] = detail
            else:
                status, detail = 'fait', ''
                self.outcome.done.append(g.id)
            self.j.group(g.id, status, detail)

    def _batch(self, batch: list[tuple[Group, Operation]], second: bool = False):
        kind = batch[0][1].kind
        cur = self.client.read([op.key for _, op in batch], kind)
        objects, waiting = [], {}
        for g, op in batch:
            if g.id in self.failure:
                continue
            d = cur.get(op.key)
            if op.create:
                if d is None:
                    objects.append({'key': op.key, 'version': 0, **op.after})
                    waiting[op.key] = (g, op, {'key': op.key}, op.after)
                elif any(value(d, c) != normalize(c, v) for c, v in op.after.items()):
                    self.failure[g.id] = ('conflit', L(en=f'{op.key} already exists, with other values',
                                                   fr=f"{op.key} existe déjà, avec d'autres valeurs"))
                else:
                    self._confirm(g, op, d['version'], kind)
                continue
            if d is None:
                self.failure[g.id] = ('conflit', L(en=f'{op.key} no longer exists (permanently deleted?)',
                                               fr=f"{op.key} n'existe plus (supprimé définitivement ?)"))
                continue
            if cause := self._precondition(op, d, kind):
                self.failure[g.id] = ('conflit', cause)
                continue
            to_write, conflicts = compare(op, d, self.partial)
            if conflicts and not self.partial:
                self.failure[g.id] = ('conflit', L(en=f"{op.key} modified since the plan ({', '.join(conflicts)})",
                                                   fr=f"{op.key} modifié depuis le plan ({', '.join(conflicts)})"))
                continue
            self.left_aside[g.id] += [f'{op.key}.{c}' for c in conflicts]
            if not to_write and not conflicts:
                self._confirm(g, op, d['version'], kind)
            if to_write:
                objects.append({'key': op.key, 'version': d['version'], **to_write})
                waiting[op.key] = (g, op, d, to_write)
        for g, op, d, to_write in waiting.values():
            self.unconfirmed[g.id, op.key] = self.j.intention(g.id, op.rank, d, to_write, kind, op.create)
        res = self.client.write(objects, kind)
        to_redo = []
        for key, (g, op, d, to_write) in waiting.items():
            if key in res.succeeded:
                self._log(g, op.rank, d, to_write, res.succeeded[key]['version'], kind, op.create)
            elif key in res.unchanged:
                continue
            elif key in res.failures and res.failures[key][0] == 412 and not second:
                to_redo.append((g, op))
            elif key in res.failures:
                code, message = res.failures[key]
                self.failure[g.id] = ('conflit' if code == 412 else 'erreur',
                                      L(en=f'{key}: {code} {message}', fr=f'{key} : {code} {message}'))
            else:
                self.failure[g.id] = ('erreur', L(en=f"{key}: Zotero's response says nothing about this item",
                                                fr=f'{key} : réponse de Zotero sans nouvelle de cet élément'))
        if to_redo:
            self._batch(to_redo, second=True)

    def _precondition(self, op: Operation, d: dict, kind: str) -> str:
        """What the plan still requires at the time of writing. The fields of `requires` have kept their value, and an
        item going to the trash contains nothing the plan did not know (D182, D183). The reread
        happens right before the write, only the instant that separates them remains."""
        gaps = [c for c, v in (op.requires or {}).items() if value(d, c) != normalize(c, v)]
        if gaps:
            return L(en=f"{op.key} modified since ({', '.join(gaps)}), left as it is",
                     fr=f"{op.key} modifié depuis ({', '.join(gaps)}), laissé tel quel")
        if op.children is None or op.after.get('deleted') is not True or value(d, 'deleted'):
            return ''
        new_ones = [k for k in self.client.content(op.key, kind) if k not in op.children]
        if not new_ones:
            return ''
        what = (L(en='item(s) or subcollection(s)', fr='fiche(s) ou sous-collection(s)') if kind == 'collections'
                else L(en='attachment(s), note(s) or annotation(s)', fr='pièce(s) jointe(s), note(s) ou annotation(s)'))
        return L(en=f"{op.key} contains {len(new_ones)} {what} added since the plan ({', '.join(new_ones[:5])}), "
                    'left out of the trash',
                 fr=f"{op.key} contient {len(new_ones)} {what} ajoutée(s) depuis le plan ({', '.join(new_ones[:5])}), "
                    'laissé hors de la corbeille')

    def _log(self, g: Group, rank: int, before: dict, written: dict, version: int, kind: str, created: bool):
        self.j.item(g.id, rank, before, written, version, kind, created)
        self.unconfirmed.pop((g.id, before['key']), None)
        self.writes[g.id].append(before['key'])
        self.outcome.items_written += 1

    def _confirm(self, g: Group, op: Operation, version: int, kind: str):
        """Values already written: if an intention of this plan was waiting for them, it is that write, made by
        zotero.org without its response arriving (D178). Without an intention, nothing is attributed to `zc`."""
        if i := self.unconfirmed.get((g.id, op.key)):
            self._log(g, op.rank, i['avant'], i['ecrit'], version, kind, bool(i.get('cree')))
