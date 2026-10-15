#!/usr/bin/env python3
"""Check content/rcs-features.json against the code that consumes it.

No network access, no AWS credentials, standard library only — safe to run in CI
on every commit. Catches the ways the registry and the code drift apart:

  * a vignette referencing a feature key that does not exist (would 500
    /api/vignettes at runtime, and the card would just quietly lose its
    teaching content if the resolver were more forgiving)
  * a feature whose limitRefs name a limit that does not exist
  * a registry entry nothing references and no status explains
  * a `surfaces` claim that no longer holds — each one names a file and a
    literal string that must still be in it
  * a documented limit hardcoded as a literal somewhere in lambda/ instead of
    being read from the registry — the single failure mode that makes an AWS
    limit change invisible
  * a chip that runs a native action on the handset (map, calendar, webview,
    dial) whose tap is not listed in channel_adapter.ACTION_ONLY_POSTBACKS —
    the phone reports that tap to the adapter too, and an unlisted one ends up
    as an unrelated reply from the AI assistant
  * the same for the chips the AI builds: common.build_suggestions must give
    every native-action chip its reserved id whatever id the model supplied, the
    adapter must stay silent for those ids (and for the legacy ones old cards
    still carry), and the AI prompt must not ask the model to invent one
  * missing required fields, so a half-added entry cannot ship
  * a `reviewedOn` that is missing, not a YYYY-MM-DD date, or in the future

Most checks read the source with `ast`. The chip checks also run the code:
lambda/common.py and lambda/channel_adapter.py are imported as the Lambda
imports them, with boto3 and botocore replaced by unittest.mock stand-ins and
the environment pinned (see lambda_modules), so the functions under test are the
real ones and the AWS SDK, credentials and network are never involved. The
SDK is replaced even when it is installed.

Exits non-zero on any finding, and non-zero if it cannot find what it expects
to check — a checker that reports "0 things checked, OK" is worse than no
checker at all.

Usage: python3 scripts/check-rcs-registry.py
"""

import ast
import contextlib
import datetime
import importlib
import json
import os
import pathlib
import re
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "content" / "rcs-features.json"
DASHBOARD = ROOT / "lambda" / "dashboard_handler.py"
LAMBDA_DIR = ROOT / "lambda"

CHANNEL_ADAPTER = LAMBDA_DIR / "channel_adapter.py"
COMMON = LAMBDA_DIR / "common.py"

# What lambda/common.py and lambda/channel_adapter.py import that the Lambda
# runtime provides rather than this repository: the AWS SDK. lambda_modules
# replaces each name, installed or not, so importing the modules cannot build a
# real client, look for credentials or open a socket.
STAND_INS = (
    "boto3", "boto3.dynamodb", "boto3.dynamodb.conditions",
    "botocore", "botocore.config", "botocore.exceptions",
)
# The variables the modules read when they are imported (the CDK stack sets the
# real ones). Every read has a default, so none is needed for the import to
# work; they are fixed placeholders so the result does not depend on the shell
# running the check. AWS_DEFAULT_REGION is what a real boto3 would fall back on.
IMPORT_ENV = {
    "AWS_REGION": "us-east-1",
    "AWS_DEFAULT_REGION": "us-east-1",
    "DYNAMODB_TABLE": "check-rcs-registry",
    "S3_BUCKET": "check-rcs-registry",
    "RCS_AGENT_ID": "check-rcs-registry",
    "CONFIG_SET_NAME": "check-rcs-registry",
}

# Suggestion types that perform an action on the handset. The phone does the
# work and still reports the tap, so the adapter has to know to stay quiet.
ACTION_CHIP_KINDS = {"OpenUrl", "DialPhone", "ShowLocation", "CreateCalendarEvent", "RequestLocation"}
# Action chips the dispatcher answers on purpose, so they are not "action only":
# tapping Secure Upload opens the webview and sends the upload card as well.
ACTION_CHIPS_WITH_HANDLERS = {"photo_secure_upload"}

REQUIRED_FEATURE_FIELDS = ("key", "name", "kind", "blurb", "status")
VALID_KINDS = {"rcs-api", "demo-pattern", "caveat"}
VALID_STATUSES = {"demonstrated", "not-demonstrated", "planned-by-aws"}

# Limit values distinctive enough that finding one as a bare literal in the
# Lambda source is almost certainly a hardcoded RCS limit rather than a
# coincidence. Small round numbers (2, 4, 10, 25, 100…) appear all over normal
# code, so scanning for those would be noise; these do not.
LITERAL_SCAN_MIN = 1000
LITERAL_SCAN_SKIP = {2000}  # too common as a generic byte/pixel size

errors: list[str] = []
checked = 0


def fail(msg: str) -> None:
    errors.append(msg)


def native_action_postbacks(kinds: set[str] = ACTION_CHIP_KINDS) -> dict[str, str]:
    """Every literal PostbackData on a chip of the given kinds (by default the
    native-action ones) under lambda/.

    Parses the source of every module rather than importing it. Chips whose
    postback is built at runtime are invisible to this scan.
    """
    found: dict[str, str] = {}
    for py in sorted(LAMBDA_DIR.rglob("*.py")):
        if "_content" in py.parts or py.name.startswith("."):
            continue
        for node in ast.walk(ast.parse(py.read_text())):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and key.value in kinds
                        and isinstance(value, ast.Dict)):
                    continue
                for k, v in zip(value.keys, value.values):
                    if (isinstance(k, ast.Constant) and k.value == "PostbackData"
                            and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                        found.setdefault(v.value, f"{py.relative_to(ROOT)}:{v.lineno}")
    return found


def listed_action_postbacks() -> set[str]:
    """The literal members of channel_adapter.ACTION_ONLY_POSTBACKS."""
    for node in ast.walk(ast.parse(CHANNEL_ADAPTER.read_text())):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "ACTION_ONLY_POSTBACKS"):
            call = node.value
            if isinstance(call, ast.Call) and call.args:
                return set(ast.literal_eval(call.args[0]))
    sys.exit("FATAL: ACTION_ONLY_POSTBACKS not found in lambda/channel_adapter.py")


@contextlib.contextmanager
def lambda_modules():
    """Yield the real lambda/common.py and lambda/channel_adapter.py, imported
    the way the Lambda imports them, with nothing from AWS behind them.

    The Lambda puts its own directory first on sys.path, and the modules import
    each other by bare name (`import common as c`, `from flows import ...`), so
    this does the same. boto3 and botocore are replaced by MagicMock stand-ins
    for the duration, and sys.modules, sys.path, the environment and the
    bytecode setting (no __pycache__ written into lambda/) are put back
    afterwards, so nothing leaks into the rest of this script.

    An import that fails, or a module name that resolves to some other file,
    stops the check with a message instead of passing silently.
    """
    saved_modules = dict(sys.modules)
    saved_path = list(sys.path)
    saved_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(LAMBDA_DIR))
        for name in STAND_INS:
            sys.modules[name] = mock.MagicMock(name=name)
        with mock.patch.dict(os.environ, IMPORT_ENV):
            try:
                common = importlib.import_module("common")
                adapter = importlib.import_module("channel_adapter")
            except Exception as e:  # noqa: BLE001
                sys.exit(f"FATAL: could not import lambda/common.py and lambda/channel_adapter.py with "
                         f"the AWS SDK replaced ({type(e).__name__}: {e}); extend STAND_INS or "
                         f"IMPORT_ENV in this script")
            for module, path in ((common, COMMON), (adapter, CHANNEL_ADAPTER)):
                if pathlib.Path(module.__file__).resolve() != path.resolve():
                    sys.exit(f"FATAL: imported {module.__file__} where {path.relative_to(ROOT)} was expected")
            if getattr(adapter, "c", None) is not common:
                sys.exit("FATAL: lambda/channel_adapter.py no longer imports lambda/common.py as `c`; the "
                         "adapter checks would run against some other module")
            # The Lambda bundle carries a copy of content/ staged at synth
            # (lambda/_content, untracked), so a fresh checkout has none. Point
            # the real reader at the source directory the stack copies from.
            required_names(common, COMMON, ["_CONTENT_DIR"])
            common._CONTENT_DIR = str(REGISTRY.parent)
            yield common, adapter
    finally:
        sys.dont_write_bytecode = saved_bytecode
        sys.path[:] = saved_path
        for name in STAND_INS:
            if name in saved_modules:
                sys.modules[name] = saved_modules[name]
            else:
                sys.modules.pop(name, None)
        for name, module in list(sys.modules.items()):
            origin = getattr(module, "__file__", None)
            if (name not in saved_modules and origin
                    and pathlib.Path(origin).resolve().is_relative_to(LAMBDA_DIR)):
                del sys.modules[name]


def required_names(module, path: pathlib.Path, names: list[str]) -> list:
    """The named attributes of an imported lambda module. A name that no longer
    exists stops the check with a message instead of skipping what it verified."""
    missing = [n for n in names if not hasattr(module, n)]
    if missing:
        sys.exit(f"FATAL: {path.relative_to(ROOT)} no longer defines {missing}")
    return [getattr(module, n) for n in names]


def builder_suggestion_kinds() -> set[str]:
    """Every `type` value common.build_suggestions branches on (`kind == "dial"`)."""
    for node in ast.parse(COMMON.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_suggestions":
            return {
                c.comparators[0].value
                for c in ast.walk(node)
                if isinstance(c, ast.Compare) and isinstance(c.left, ast.Name) and c.left.id == "kind"
                and len(c.ops) == 1 and isinstance(c.ops[0], ast.Eq)
                and isinstance(c.comparators[0], ast.Constant) and isinstance(c.comparators[0].value, str)
            }
    sys.exit("FATAL: build_suggestions not found in lambda/common.py")


def non_reserved_name_uses(tree: ast.AST, name: str, inside: str) -> list[int]:
    """Line numbers where `name` is read outside the function called `inside`."""
    allowed = {id(n) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == inside
               for n in ast.walk(f)}
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load) and id(n) not in allowed]


def prompt_postbacks_on_action_chips(kinds: set[str]) -> list[int]:
    """Lines of channel_adapter.py whose prompt text hands the model an action
    chip with a `postback` in it. Prompt text is built from implicit string
    concatenation and f-strings, so each literal is joined (with a placeholder for
    every f-string expression) before it is searched."""
    hits = []
    pattern = re.compile(r'"type":\s*"(?:%s)"[^}]*?"postback"' % "|".join(sorted(kinds)))
    for node in ast.walk(ast.parse(CHANNEL_ADAPTER.read_text())):
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "\0" for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        if pattern.search(text):
            hits.append(node.lineno)
    return sorted(set(hits))


def check_ai_action_chips() -> None:
    """The chips the AI builds, end to end: builder, router and prompt."""
    global checked
    with lambda_modules() as (common, adapter):
        reserved, build = required_names(common, COMMON, ["AI_ACTION_POSTBACKS", "build_suggestions"])
        reserved_ids = set(reserved.values())
        if not reserved or len(reserved_ids) != len(reserved):
            fail("common.AI_ACTION_POSTBACKS is empty or maps two kinds to one id")

        # No flow may use a reserved id for a chip of its own: the adapter is silent for them.
        flow_ids = native_action_postbacks(ACTION_CHIP_KINDS | {"Reply"})
        for postback in sorted(reserved_ids & set(flow_ids)):
            fail(f"{flow_ids[postback]}: PostbackData {postback!r} is reserved for AI-built action chips "
                 f"(common.AI_ACTION_POSTBACKS), so the adapter would never answer it")

        # Builder: every kind it branches on, fed a hostile id.
        hostile = "hostile_model_id"
        kinds = builder_suggestion_kinds()
        if not kinds:
            sys.exit("FATAL: found no `kind == ...` branch in common.build_suggestions — has its shape "
                     "changed? This check would otherwise pass vacuously.")
        for kind in sorted(kinds):
            checked += 1
            sample = {"type": kind, "text": "Label", "postback": hostile, "url": "https://example.com",
                      "phone_number": "+12065550100", "latitude": 1.0, "longitude": 2.0}
            try:
                chips = build([sample])
            except Exception as e:  # noqa: BLE001
                fail(f"common.build_suggestions raised {type(e).__name__} for type {kind!r} with a complete "
                     f"sample ({e}); extend the sample in check_ai_action_chips")
                continue
            if len(chips) != 1 or len(chips[0]) != 1:
                fail(f"common.build_suggestions built {chips!r} for type {kind!r}, expected one chip")
                continue
            (chip_kind, body), = chips[0].items()
            got = body.get("PostbackData")
            if chip_kind == "Reply":
                if got != hostile:
                    fail(f"a model 'reply' chip must keep its own postback, got {got!r}")
                clash = build([{"type": "reply", "text": "Label", "postback": next(iter(reserved_ids))}])
                if clash[0]["Reply"]["PostbackData"] in reserved_ids:
                    fail("a model 'reply' chip can claim a reserved id, and its tap would then be silenced")
            elif chip_kind in ACTION_CHIP_KINDS:
                if reserved.get(kind) != got:
                    fail(f"common.build_suggestions gave the {chip_kind} chip for type {kind!r} PostbackData "
                         f"{got!r}, not its reserved id {reserved.get(kind)!r}: a model-chosen id would reach "
                         f"the AI when tapped. Add the kind to common.AI_ACTION_POSTBACKS")
            else:
                fail(f"common.build_suggestions builds a {chip_kind!r} chip for type {kind!r}; add it to "
                     f"ACTION_CHIP_KINDS in this script if it runs an action on the handset")

        # Router: silent for the reserved and legacy ids, and for nothing else.
        *_, is_silent = required_names(
            adapter, CHANNEL_ADAPTER,
            ["ACTION_ONLY_POSTBACKS", "LEGACY_AI_ACTION_POSTBACKS", "_is_action_only_postback"],
        )
        for postback in sorted(reserved_ids | {"call", "find_care_location"}):
            checked += 1
            if not is_silent(postback):
                fail(f"channel_adapter does not treat {postback!r} as an action-only tap — a reserved AI id, "
                     f"or an id older cards still carry, would reach the assistant")
        for postback in (hostile, "call_911", "directions_main_clinic", "home_menu"):
            checked += 1
            if is_silent(postback):
                fail(f"channel_adapter treats {postback!r} as an action-only tap; the AI family must be a "
                     f"fixed set, not a pattern a model or a reply chip can hit")
        tree = ast.parse(CHANNEL_ADAPTER.read_text())
        for lineno in non_reserved_name_uses(tree, "ACTION_ONLY_POSTBACKS", "_is_action_only_postback"):
            checked += 1
            fail(f"lambda/channel_adapter.py:{lineno} reads ACTION_ONLY_POSTBACKS directly; use "
                 f"_is_action_only_postback so the AI family is covered too")

        # Prompt: no postback on an action chip the model is asked to write.
        for lineno in prompt_postbacks_on_action_chips(set(reserved)):
            checked += 1
            fail(f"lambda/channel_adapter.py:{lineno}: the AI prompt shows an action chip with a "
                 f'"postback"; the builder ignores it, so do not suggest the model should invent one')


def load_registry() -> dict:
    if not REGISTRY.exists():
        sys.exit(f"FATAL: {REGISTRY.relative_to(ROOT)} is missing")
    try:
        return json.loads(REGISTRY.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"FATAL: {REGISTRY.relative_to(ROOT)} is not valid JSON: {e}")


def vignette_feature_keys() -> dict[str, list[str]]:
    """The feature keys each vignette claims, read out of dashboard_handler.py.

    Parsed with ast: VIGNETTES is a literal, so there is no reason to import
    dashboard_handler.py and everything it pulls in.
    """
    tree = ast.parse(DASHBOARD.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "VIGNETTES" for t in node.targets
        ):
            vignettes = ast.literal_eval(node.value)
            return {v["id"]: list(v.get("features", [])) for v in vignettes}
    sys.exit(
        f"FATAL: could not find the VIGNETTES assignment in "
        f"{DASHBOARD.relative_to(ROOT)} — this checker verifies nothing until "
        f"that is fixed"
    )


def check_surfaces(key: str, surfaces: list) -> None:
    """Verify each `surfaces` entry still points at something that exists.

    `surfaces` is the escape hatch that lets a feature be marked demonstrated
    without a vignette claiming it. It used to be free text, and that is exactly
    how `verified_identity` sat marked demonstrated for months while claiming a
    surface — "Your handset — the agent header on every message" — that was
    outside the app entirely: true of RCS, and no part of this demo. Any
    non-empty string satisfied the old check, so the escape hatch could not
    fail.

    So an entry now has to name a `file` and a literal `evidence` string that
    must still appear in it. That does not prove the feature is well taught, but
    it does mean deleting the panel, renaming the column header, or moving the
    code breaks the build instead of quietly leaving a false claim behind.
    """
    global checked
    for i, s in enumerate(surfaces):
        checked += 1
        if not isinstance(s, dict):
            fail(
                f"feature {key!r} surface #{i} is {type(s).__name__}, not an object — "
                f'use {{"where": …, "file": …, "evidence": …}} so the claim is checkable'
            )
            continue
        for field in ("where", "file", "evidence"):
            if not s.get(field):
                fail(f"feature {key!r} surface #{i} is missing {field!r}")
        where, rel, evidence = s.get("where"), s.get("file"), s.get("evidence")
        if not (rel and evidence):
            continue
        # Deliberately not restricted to web/src: a surface can legitimately be
        # a code path (the CDK event-destination wiring is not a screen).
        path = ROOT / rel
        if not path.is_file():
            fail(
                f"feature {key!r} surface {where!r} names {rel} which does not "
                f"exist — the surface moved or was deleted"
            )
        elif evidence not in path.read_text():
            fail(
                f"feature {key!r} surface {where!r} claims {rel} contains "
                f"{evidence!r}, and it does not — either the surface changed or "
                f"the registry is now advertising something the demo no longer does"
            )


def main() -> int:
    global checked
    reg = load_registry()
    limits = reg.get("limits") or {}
    features = reg.get("features") or []
    if not limits or not features:
        sys.exit("FATAL: registry has no limits or no features")

    if not reg.get("docBaseUrl", "").startswith("https://"):
        fail("docBaseUrl must be an absolute https:// URL")

    # reviewedOn is typed in by hand after a read of the AWS user guide, and the
    # Guide tab shows it, so a malformed or future date would mislead a reader.
    # One day of slack covers an author whose local date is ahead of UTC.
    reviewed = reg.get("reviewedOn", "")
    try:
        reviewed_on = datetime.date.fromisoformat(reviewed)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", reviewed):
            raise ValueError(reviewed)
    except (TypeError, ValueError):
        fail(f"reviewedOn must be a YYYY-MM-DD date, got {reviewed!r}")
    else:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        if reviewed_on > today + datetime.timedelta(days=1):
            fail(f"reviewedOn {reviewed} is in the future")

    # ── limits ──────────────────────────────────────────────────────────────
    for key, lim in limits.items():
        checked += 1
        for field in ("value", "label", "unit", "doc"):
            if field not in lim:
                fail(f"limit {key!r} is missing required field {field!r}")
        if not isinstance(lim.get("value"), int):
            fail(f"limit {key!r} value must be an integer, got {lim.get('value')!r}")

    # ── features ────────────────────────────────────────────────────────────
    seen_keys: set[str] = set()
    for f in features:
        checked += 1
        key = f.get("key", "<no key>")
        for field in REQUIRED_FEATURE_FIELDS:
            if not f.get(field):
                fail(f"feature {key!r} is missing required field {field!r}")
        if key in seen_keys:
            fail(f"duplicate feature key {key!r}")
        seen_keys.add(key)
        if f.get("kind") not in VALID_KINDS:
            fail(f"feature {key!r} has unknown kind {f.get('kind')!r}")
        if f.get("status") not in VALID_STATUSES:
            fail(f"feature {key!r} has unknown status {f.get('status')!r}")
        if f.get("status") != "demonstrated" and not f.get("statusNote"):
            fail(
                f"feature {key!r} is {f.get('status')!r} but has no statusNote "
                f"explaining what a builder should do instead"
            )
        if f.get("kind") == "rcs-api" and not f.get("doc"):
            fail(f"feature {key!r} is an AWS API feature but has no doc link")
        for ref in f.get("limitRefs", []):
            if ref not in limits:
                fail(f"feature {key!r} references unknown limit {ref!r}")
        check_surfaces(key, f.get("surfaces") or [])

    # ── vignette wiring ─────────────────────────────────────────────────────
    used: set[str] = set()
    for vid, keys in vignette_feature_keys().items():
        if not keys:
            fail(f"vignette {vid!r} has no feature keys")
        for key in keys:
            checked += 1
            used.add(key)
            if key not in seen_keys:
                fail(
                    f"vignette {vid!r} references unknown feature key {key!r} — "
                    f"/api/vignettes will fail at runtime"
                )

    for f in features:
        if f.get("key") in used or f.get("surfaces"):
            continue
        # A feature no vignette claims must account for itself: either its
        # status says the demo doesn't show it (the Guide tab lists those
        # deliberately, so a builder can see what the service offers beyond
        # this demo), or `surfaces` names where in the demo it does show up —
        # delivery receipts live on the Recipients tab, not on a vignette card.
        if f.get("status") == "demonstrated":
            fail(
                f"feature {f.get('key')!r} is marked demonstrated but no vignette "
                f"references it and it lists no surfaces — wire it up, name the "
                f"surface, or change its status"
            )

    # ── hardcoded limits in the Lambda source ───────────────────────────────
    scan_values = {
        lim["value"]: key
        for key, lim in limits.items()
        if isinstance(lim.get("value"), int)
        and lim["value"] >= LITERAL_SCAN_MIN
        and lim["value"] not in LITERAL_SCAN_SKIP
    }
    for py in sorted(LAMBDA_DIR.rglob("*.py")):
        if "_content" in py.parts or py.name.startswith("."):
            continue
        for lineno, line in enumerate(py.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for value, key in scan_values.items():
                if re.search(rf"(?<![\w.]){value}(?![\w.])", line):
                    fail(
                        f"{py.relative_to(ROOT)}:{lineno} hardcodes {value}, which "
                        f"is the documented limit {key!r} — read it with "
                        f"c.rcs_limit({key!r}) so an AWS change lands in one place"
                    )

    # ── native-action chips ─────────────────────────────────────────────────
    action_chips = native_action_postbacks()
    if not action_chips:
        sys.exit("FATAL: found no native-action chips under lambda/ — has the "
                 "suggestion shape changed? This check would otherwise pass vacuously.")
    listed = listed_action_postbacks()
    for postback, where in sorted(action_chips.items()):
        checked += 1
        if postback not in listed and postback not in ACTION_CHIPS_WITH_HANDLERS:
            fail(
                f"{where}: native-action chip {postback!r} is not in "
                f"channel_adapter.ACTION_ONLY_POSTBACKS — its tap would reach the AI "
                f"assistant and produce an unrelated reply. Add it there (or give it "
                f"a handler and list it in ACTION_CHIPS_WITH_HANDLERS in this script)"
            )
    for postback in sorted(listed - set(action_chips)):
        checked += 1
        fail(
            f"channel_adapter.ACTION_ONLY_POSTBACKS lists {postback!r}, but no "
            f"native-action chip under lambda/ uses it — remove the stale entry"
        )

    check_ai_action_chips()

    print(f"checked {checked} registry facts across {len(features)} features "
          f"and {len(limits)} limits")
    if errors:
        print(f"\n{len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
