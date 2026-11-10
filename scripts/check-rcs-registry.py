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
  * a brand with no usable `homeMenu` (missing, empty, over ten entries, a label
    over the suggestion limit, or a postback the adapter never mentions), or a
    channel_adapter.py without the `reset_conversation` postback
  * a sample phone number outside the reserved fictional range: each brand's
    `contactPhoneNumber` and `memberServicesPhone` must be +1 800 555-0100 to
    0199, equal to each other and unique across brands, and AnyWealth's
    `fraudLinePhone` (content/wealth.md) must equal its `memberServicesPhone`
  * brand isolation: a brand whose `vignettes` list is missing, empty or not the
    set the dashboard catalog (VIGNETTES) tags to it; a listed id with no
    FLOW_MAP key or AI_DRIVEN_VIGNETTES entry; a `defaultVignette` that is not
    empty or an AI-driven id the brand lists; a brand without its own member
    profile (memberName, memberPlan, memberIdMasked, memberCity), or one that
    names another brand; a grounding file that names another brand; a homeMenu
    tile whose postback opens a vignette the brand does not own
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

# The brand catalog (content/brand.md frontmatter), read through the real
# lambda/common.py accessor so this checker validates exactly what the deploy
# resolves — see check_brands.
BRAND_SOURCE = ROOT / "content" / "brand.md"
# Room photos named by content/hotels.md must live here; see check_room_photos.
CONTENT_DIR = REGISTRY.parent
ROOM_PHOTO_DIR = "media/anytravel/rooms"
# AnyWealth's fraud line lives in its own content file; see check_phone_numbers.
WEALTH_SOURCE = ROOT / "content" / "wealth.md"
# The sample phone numbers are fictional: 555-0100..0199 is the range reserved
# for fictional use, so no demo number can ring a real subscriber.
PHONE_PATTERN = re.compile(r"^\+1800555(01\d\d)$")
BRAND_PHONE_FIELDS = ("contactPhoneNumber", "memberServicesPhone")

# The RCS testing-registration fields every catalog brand must carry for its
# agent to register (design §1, "required registration fields list"). A brand
# missing any of these cannot be stood up, so a half-filled block must fail CI
# rather than fail at agent-creation time in front of the operator.
REQUIRED_REGISTRATION_FIELDS = (
    "brandName", "serviceName", "senderDisplayName", "useCase", "agentDescription",
    "accentColor", "logoImage", "bannerImage", "privacyPolicyUrl",
    "termsAndConditionsUrl", "averageMonthlyRcsFrequency", "monthlyRcsVolume",
)
# At least one contact method (value + its label) is required; any one pair
# satisfies it, matching the RCS registration's CONDITIONAL contact fields.
CONTACT_METHOD_PAIRS = (
    ("contactPhoneNumber", "contactPhoneLabel"),
    ("contactEmailAddress", "contactEmailLabel"),
    ("contactWebsite", "contactWebsiteLabel"),
)
# AWS rejects an accentColor that does not clear WCAG 4.5:1 against white at
# registration (ACCENT_COLOR_CONTRAST_INSUFFICIENT), so the catalog must too.
WCAG_AA_CONTRAST = 4.5

# The Home_Menu (conversation reset): at most ten tiles per brand, so the Start
# Over chip the adapter appends still fits the eleven-chip message cap. A tile's
# label is held to the registry's suggestion label limit, read by this key.
HOME_MENU_MAX_ENTRIES = 10
HOME_MENU_LABEL_LIMIT = "suggestionTextChars"
RESET_POSTBACK = "reset_conversation"

# Brand isolation (brand-isolation C5). The flow registry is read with ast; the
# three Home_Menu tiles that open an AI assistant are separate `if pd == …` arms
# in handle_postback rather than entries of its `home` dict, so they are listed
# here (a tile added to the dict is picked up from the source automatically).
FLOWS_INIT = LAMBDA_DIR / "flows" / "__init__.py"
HOME_SPECIAL_ARMS = {
    "home_benefits": "benefits_qa",
    "home_find_care": "find_care",
    "home_booking": "room_booking",
}
# The sample member profile each brand must define in its own block.
MEMBER_PROFILE_FIELDS = ("memberName", "memberPlan", "memberIdMasked", "memberCity")

# Limit values distinctive enough that finding one as a bare literal in the
# Lambda source is almost certainly a hardcoded RCS limit rather than a
# coincidence. Small round numbers (2, 4, 10, 25, 100…) appear all over normal
# code, so scanning for those would be noise; these do not.
LITERAL_SCAN_MIN = 1000
LITERAL_SCAN_SKIP = {2000}  # too common as a generic byte/pixel size

# ── no-brand-literal scan (design §8 / Property 10, R11.1, R11.2) ────────────
# Brand identity lives only in content/brand.md. A brand *display name* baked
# into the runtime or config source — a message body, a themed string, a CDK
# resource description — is the bug this scan catches: re-theming the demo by
# editing one file would then silently leave that literal behind. The scan is a
# source-of-truth check, not a style rule, so it mirrors the hardcoded-limit
# scan above: a universal pass over the source, reporting file:line and the
# literal found, exiting non-zero on any finding.
#
# SCOPE — only where a brand literal would be a real runtime/config bug:
#   lambda/ (the bundled Python, minus the staged _content copy), the CDK
#   TypeScript (cdk/lib, cdk/bin) and the dashboard source (web/src). It
#   deliberately does NOT touch content/ (that IS the source of truth), the
#   prose docs (README/SETUP/AGENTS/docs — owned by other tasks), this
#   scripts/ directory, build output, or node_modules.
BRAND_LITERAL_SCAN = (
    (LAMBDA_DIR, (".py",)),
    (ROOT / "cdk" / "lib", (".ts",)),
    (ROOT / "cdk" / "bin", (".ts",)),
    (ROOT / "web" / "src", (".ts", ".tsx")),
)
# What the scan distinguishes a *hardcoded* literal from (design §8):
#   • comments and docstrings — documentation, not a display/logic value. The
#     Python half parses with ast, so comments never reach it, and module /
#     class / function docstrings are skipped explicitly. The TypeScript half
#     strips `//` and `/* … */` comments before it looks.
#   • a documented fallback DEFAULT — the legacy R11.3 fallbacks that tasks
#     4.1 / 8.2 keep on purpose, e.g. `brand().get("brandName", "AnyHealth")`
#     in Python and `brand.brandName || 'AnyHealth'` in TypeScript. These are
#     allowed: the literal is the value used only when the source of truth is
#     absent, never the live brand.
# Only proper-case brand DISPLAY names are scanned (derived from the catalog's
# displayName/brandName). Lowercase ids such as the `anyhealth_phone`
# localStorage key and the `anyhealth-handover-banner` CSS class (task 8.4,
# intentionally internal identifiers) do not match, so they are not flagged.
# A trailing `# brand-literal-ok` / `// brand-literal-ok` marker on the line is
# an explicit escape hatch for any other reviewed, legitimate use.
BRAND_LITERAL_OK_MARKER = "brand-literal-ok"
# Python call targets whose 2nd positional arg is a documented default value.
DEFAULT_VALUE_CALLS = {"get", "getattr"}

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


def wcag_contrast_vs_white(hex_color: str) -> float | None:
    """WCAG 2.x contrast ratio of a `#RRGGBB` color against white, or None if
    the string is not a hex color this can parse.

    The ratio is (L1 + 0.05) / (L2 + 0.05) with white's relative luminance of
    1.0 as L1, so it reduces to 1.05 / (Lcolor + 0.05). Channel linearization
    follows the WCAG definition. This is the same bound AWS enforces on
    accentColor at registration, computed here so the catalog fails in CI first.
    """
    s = (hex_color or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return 1.05 / (luminance + 0.05)


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


def vignette_brands() -> list[tuple[str, str | None]]:
    """(vignette id, brand) for every VIGNETTES entry, read out of
    dashboard_handler.py with the same ast scan as vignette_feature_keys.

    `brand` is None when the entry omits the key — reported as "exactly one
    brand must own each vignette" rather than crashing on a missing key.
    """
    tree = ast.parse(DASHBOARD.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "VIGNETTES" for t in node.targets
        ):
            vignettes = ast.literal_eval(node.value)
            return [(v["id"], v.get("brand")) for v in vignettes]
    sys.exit(
        f"FATAL: could not find the VIGNETTES assignment in "
        f"{DASHBOARD.relative_to(ROOT)} — this checker verifies nothing until "
        f"that is fixed"
    )


def content_frontmatter_scan() -> dict:
    """A tiny, standard-library read of the top-level scalar keys this checker
    needs from content/brand.md's YAML frontmatter — currently just
    `defaultBrand`. Reads the lines between the opening `---` and the next `---`
    and picks up top-level `key: value` pairs (no indentation), stripping inline
    `#` comments and surrounding quotes. Deliberately shallow: the nested
    `brands:` map is read through common.brand_catalog(), not here."""
    text = BRAND_SOURCE.read_text()
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        fm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not fm:
            continue
        value = re.sub(r"\s+#.*$", "", fm.group(2)).strip().strip('"').strip("'")
        if value:
            out[fm.group(1)] = value
    return out


def load_brand_catalog() -> dict:
    """The resolved brand catalog (id -> identity block) from content/brand.md,
    read through the real lambda/common.py accessor with the AWS SDK replaced.

    Reusing common.brand_catalog() means the checker validates exactly the
    blocks the deploy resolves — the per-brand overlay, the legacy one-entry
    fallback, everything — rather than a second, drifting parse of the YAML.
    """
    if not BRAND_SOURCE.exists():
        sys.exit(f"FATAL: {BRAND_SOURCE.relative_to(ROOT)} is missing")
    with lambda_modules() as (common, _adapter):
        (brand_catalog,) = required_names(common, COMMON, ["brand_catalog"])
        try:
            catalog = brand_catalog()
        except Exception as e:  # noqa: BLE001
            sys.exit(f"FATAL: common.brand_catalog() raised {type(e).__name__}: {e} — "
                     f"the brand catalog in {BRAND_SOURCE.relative_to(ROOT)} cannot be read")
    if not isinstance(catalog, dict) or not catalog:
        sys.exit(f"FATAL: {BRAND_SOURCE.relative_to(ROOT)} yields no brands — "
                 f"this check would otherwise pass vacuously")
    return catalog


def brand_display_names(catalog: dict) -> list[str]:
    """The proper-case brand display names to scan for, taken from the catalog
    itself (each block's displayName and brandName) so a fifth brand is covered
    the moment it is added, with no second list to keep in step.

    Only multi-cased, single-word names are kept (`AnyHealth`, `AnyWealth`,
    `AnyHR`): a word-boundary search for one of those cannot collide with the
    lowercase ids used as internal identifiers (`anyhealth_phone`,
    `anyhealth-handover-banner`), which the scan deliberately leaves alone
    (task 8.4). A name with internal whitespace (e.g. "AnyHealth Member
    Services") is reduced to nothing here; its distinctive token is the plain
    brandName, which is already in the set.
    """
    names: set[str] = set()
    for block in catalog.values():
        if not isinstance(block, dict):
            continue
        for key in ("displayName", "brandName"):
            value = str(block.get(key) or "").strip()
            # One token, mixed-case, with a letter — excludes "MULTI_USE"-style
            # constants and lowercase ids, keeps "AnyHealth"/"AnyHR".
            if (value and not any(ch.isspace() for ch in value)
                    and value != value.lower() and value != value.upper()
                    and any(ch.isalpha() for ch in value)):
                names.add(value)
    if not names:
        sys.exit("FATAL: the brand catalog yields no scannable display names — "
                 "the no-brand-literal scan would otherwise pass vacuously")
    return sorted(names)


def _python_default_arg_strings(tree: ast.AST) -> set[int]:
    """ids() of the string Constant nodes that sit in the documented fallback
    default position of a `.get(...)` or `getattr(...)` call — the last
    positional arg (`brand().get("brandName", "AnyHealth")`,
    `getattr(o, "n", "AnyHealth")`). A literal there is the value used only
    when the source of truth is absent, so it is allowed."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if name not in DEFAULT_VALUE_CALLS:
            continue
        # `d.get(key, default)` → default is arg 1; `getattr(obj, name, default)`
        # → default is arg 2. In both the last positional arg is the default.
        default_index = 2 if name == "getattr" else 1
        if len(node.args) <= default_index:
            continue
        default = node.args[default_index]
        if isinstance(default, ast.Constant) and isinstance(default.value, str):
            allowed.add(id(default))
    return allowed


def _python_docstring_strings(tree: ast.AST) -> set[int]:
    """ids() of the module/class/function docstring Constant nodes. Docstrings
    are documentation, not a display or logic value, so a brand name in one is
    allowed just as a comment is (ast never surfaces comments at all)."""
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    allowed.add(id(first.value))
    return allowed


def _scan_python_brand_literals(path: pathlib.Path, pattern: re.Pattern) -> list[tuple[int, str]]:
    """(line, literal) for every brand display name that appears in a real
    string literal in a .py file, skipping documented `.get`/`getattr` defaults
    and docstrings. Parsing with ast means comments never reach the scan."""
    source = path.read_text()
    tree = ast.parse(source)
    allowed = _python_default_arg_strings(tree) | _python_docstring_strings(tree)
    lines = source.splitlines()
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in allowed:
            continue
        line = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
        if BRAND_LITERAL_OK_MARKER in line:
            continue
        for m in pattern.finditer(node.value):
            hits.append((node.lineno, m.group(0)))
    return hits


def _strip_ts_comments(source: str) -> str:
    """Blank out `//` line comments and `/* … */` block comments in TypeScript
    source while preserving line count and columns, and without touching
    comment-like text inside string or template literals.

    Processed line by line: a `'`/`"` string literal cannot cross a newline in
    JS/TS, so quote state resets at each line, which stops one stray apostrophe
    in a comment from cascading over the rest of the file. A `/* … */` block
    carries across lines through the `in_block` flag. A `//` or an unclosed
    `/*` only starts a comment when it is not inside a quote. This is good
    enough for a literal scan: it keeps a `//` inside a URL string intact and a
    brand name inside any comment out."""
    out_lines: list[str] = []
    in_block = False
    in_template = False                              # a backtick ` … ` literal spanning lines
    for line in source.splitlines():
        out = []
        i, n = 0, len(line)
        quote: str | None = None
        while i < n:
            ch = line[i]
            if in_block:
                if line[i:i + 2] == "*/":
                    out.append("  ")
                    in_block = False
                    i += 2
                else:
                    out.append(" ")
                    i += 1
                continue
            if in_template:
                out.append(ch)
                if ch == "\\" and i + 1 < n:
                    out.append(line[i + 1])
                    i += 2
                    continue
                if ch == "`":
                    in_template = False
                i += 1
                continue
            if quote:
                out.append(ch)
                if ch == "\\" and i + 1 < n:         # keep escaped char as-is
                    out.append(line[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            two = line[i:i + 2]
            if two == "//":
                out.append(" " * (n - i))
                break
            if two == "/*":
                in_block = True
                out.append("  ")
                i += 2
                continue
            if ch == "`":
                in_template = True
            elif ch in "\"'":
                quote = ch
            out.append(ch)
            i += 1
        out_lines.append("".join(out))
    return "\n".join(out_lines)


def _scan_ts_brand_literals(path: pathlib.Path, pattern: re.Pattern,
                            alternation: str) -> list[tuple[int, str]]:
    """(line, literal) for every brand display name in a .ts/.tsx file, after
    comments are stripped and documented `|| 'Brand'` / `?? 'Brand'` fallback
    defaults are allowed. There is no standard-library TypeScript parser, so
    this is a comment-aware line scan rather than an AST walk."""
    code = _strip_ts_comments(path.read_text())
    # A brand name preceded by a `||` or `??` default operator (optionally
    # quoted) is the allowed fallback position, e.g. `brand.brandName || 'AnyHealth'`.
    default_default = re.compile(r"(?:\|\||\?\?)\s*['\"`]?(?:%s)['\"`]?" % alternation)
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(code.splitlines(), 1):
        if BRAND_LITERAL_OK_MARKER in line:
            continue
        allowed_spans = [m.span() for m in default_default.finditer(line)]
        for m in pattern.finditer(line):
            if any(s <= m.start() and m.end() <= e for s, e in allowed_spans):
                continue
            hits.append((lineno, m.group(0)))
    return hits


def check_no_brand_literals(catalog: dict) -> None:
    """No brand display name is hardcoded in the runtime or config source
    outside content/brand.md and the documented fallback allowlist (R11.1,
    R11.2). Reports each offending file:line and the literal, so a brand name
    baked into code fails CI instead of surviving a re-theme.
    """
    global checked
    names = brand_display_names(catalog)
    alternation = "|".join(re.escape(n) for n in names)
    pattern = re.compile(r"\b(?:%s)\b" % alternation)
    scanned = 0
    for base, suffixes in BRAND_LITERAL_SCAN:
        if not base.exists():
            continue
        for src in sorted(base.rglob("*")):
            if (not src.is_file() or src.suffix not in suffixes
                    or "_content" in src.parts or "node_modules" in src.parts
                    or src.name.startswith(".") or src.name.endswith(".d.ts")):
                continue
            scanned += 1
            checked += 1
            try:
                if src.suffix == ".py":
                    hits = _scan_python_brand_literals(src, pattern)
                else:
                    hits = _scan_ts_brand_literals(src, pattern, alternation)
            except SyntaxError as e:
                fail(f"{src.relative_to(ROOT)} could not be parsed for the brand-literal "
                     f"scan ({e}); fix the syntax or the scan cannot vouch for the file")
                continue
            for lineno, literal in hits:
                fail(f"{src.relative_to(ROOT)}:{lineno} hardcodes brand name {literal!r} — "
                     f"brand identity lives only in content/brand.md; read it from the "
                     f"source of truth (e.g. c.brand_name()), keep it as a documented "
                     f"fallback default, or mark a reviewed use with # {BRAND_LITERAL_OK_MARKER}")
    if scanned == 0:
        sys.exit("FATAL: the no-brand-literal scan found no source files to scan — "
                 "has the tree moved? This check would otherwise pass vacuously")


def check_brands(catalog: dict) -> None:
    """Every catalog brand can register its RCS agent and theme the demo:
    all required registration fields present, a contact method with its label,
    an accentColor that clears WCAG 4.5:1 vs white, defaultBrand a real key,
    media files present, and grounding files present under content/.
    """
    global checked
    fm = content_frontmatter_scan()
    default_brand = fm.get("defaultBrand")
    if default_brand is not None:
        checked += 1
        if default_brand not in catalog:
            fail(f"{BRAND_SOURCE.relative_to(ROOT)}: defaultBrand {default_brand!r} is not a "
                 f"catalog brand (have: {', '.join(sorted(catalog))})")

    for brand_id in sorted(catalog):
        block = catalog[brand_id]
        label = f"brand {brand_id!r}"

        # Required registration fields, reported by name.
        for field in REQUIRED_REGISTRATION_FIELDS:
            checked += 1
            if not str(block.get(field) or "").strip():
                fail(f"{label} is missing required registration field {field!r} — "
                     f"its RCS agent cannot be registered without it")

        # At least one contact method together with its label.
        checked += 1
        if not any(
            str(block.get(value) or "").strip() and str(block.get(lbl) or "").strip()
            for value, lbl in CONTACT_METHOD_PAIRS
        ):
            pairs = ", ".join(f"{v}+{l}" for v, l in CONTACT_METHOD_PAIRS)
            fail(f"{label} has no contact method with its label — set at least one of: {pairs}")

        # accentColor must clear WCAG 4.5:1 vs white (AWS rejects it otherwise).
        accent = str(block.get("accentColor") or "").strip()
        if accent:
            checked += 1
            ratio = wcag_contrast_vs_white(accent)
            if ratio is None:
                fail(f"{label} accentColor {accent!r} is not a #RRGGBB hex color")
            elif ratio < WCAG_AA_CONTRAST:
                fail(f"{label} accentColor {accent} has WCAG contrast {ratio:.2f}:1 vs white, "
                     f"below the required {WCAG_AA_CONTRAST}:1 — AWS would reject it at registration")

        # Media: the brand's own logo and banner must exist in the repo.
        for field in ("logoImage", "bannerImage"):
            rel = str(block.get(field) or "").strip()
            if not rel:
                continue  # already reported as a missing required field above
            checked += 1
            if not (ROOT / rel).is_file():
                fail(f"{label} {field} names {rel} which does not exist in the repo")

        # The optional card image (welcome / check-in cards), when set, must exist.
        card_rel = str(block.get("cardImage") or "").strip()
        if card_rel:
            checked += 1
            if not (ROOT / card_rel).is_file():
                fail(f"{label} cardImage names {card_rel} which does not exist in the repo")

        # Grounding files must exist under content/.
        grounding = block.get("groundingFiles")
        if isinstance(grounding, list):
            for name in grounding:
                if not isinstance(name, str) or not name.strip():
                    continue
                checked += 1
                if not (BRAND_SOURCE.parent / name).is_file():
                    fail(f"{label} groundingFile {name!r} does not exist under "
                         f"{BRAND_SOURCE.parent.relative_to(ROOT)}/")


def check_room_photos() -> None:
    """Every Room_Type in content/hotels.md has exactly two photos, and each is
    a file under ROOM_PHOTO_DIR that exists in the repo (anytravel-hotel-vignettes
    R21.1, R21.9). Each Room_Type, each photo count and each photo path counts
    as one registry fact; a finding names the Room_Type and the path.

    Reads the file through the real common.content_frontmatter, not the
    brand-guarded common.room_types(), so the check does not depend on which
    brand is selected. Skipped when hotels.md does not exist (no brand grounds
    on it); an existing hotels.md with no Room_Types stops the check.
    """
    global checked
    hotels = CONTENT_DIR / "hotels.md"
    if not hotels.is_file():
        return
    with lambda_modules() as (common, _adapter):
        content_frontmatter, room_photos = required_names(
            common, COMMON, ["content_frontmatter", "room_photos"])
        rooms = content_frontmatter("hotels.md").get("roomTypes")
        if not isinstance(rooms, list) or not rooms:
            sys.exit(f"FATAL: {hotels.relative_to(ROOT)} has no roomTypes — the room photo check "
                     f"would otherwise pass vacuously")
        for i, room in enumerate(rooms, 1):
            rid = room.get("id") if isinstance(room, dict) else None
            label = f"Room_Type {rid!r}" if rid else f"Room_Type #{i}"
            raw = room.get("photos") if isinstance(room, dict) else None
            photos = room_photos(room)

            checked += 1
            if not isinstance(raw, list) or len(photos) != 2 or len(raw) != 2:
                fail(f"{hotels.relative_to(ROOT)} {label} must have exactly two non-empty `photos` "
                     f"(card photo, then detail photo), got {raw!r}")

            for rel in photos:
                checked += 1
                path = ROOT / rel
                if not pathlib.PurePosixPath(rel).is_relative_to(ROOM_PHOTO_DIR):
                    fail(f"{hotels.relative_to(ROOT)} {label} photo {rel!r} is not under {ROOM_PHOTO_DIR}/")
                elif not path.is_file():
                    fail(f"{hotels.relative_to(ROOT)} {label} photo {rel!r} does not exist in the repo")


def check_vignette_brands(catalog: dict) -> None:
    """Every VIGNETTES entry names exactly one brand, and that brand is a real
    catalog key. "Exactly one" is structural — the entry carries a single
    `brand` string — so the failure to guard against is an absent or unknown
    brand, each reported with the offending vignette.
    """
    global checked
    for vid, brand_id in vignette_brands():
        checked += 1
        if brand_id is None:
            fail(f"vignette {vid!r} has no brand — exactly one brand must own each vignette")
        elif brand_id not in catalog:
            fail(f"vignette {vid!r} references unknown brand {brand_id!r} "
                 f"(have: {', '.join(sorted(catalog))})")


def string_literals(path: pathlib.Path) -> set[str]:
    """Every string constant in a Python source file, found with ast. An f-string
    contributes only its literal parts, so a postback built at runtime is not
    counted as present."""
    return {n.value for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def check_home_menu_and_reset(catalog: dict, limits: dict) -> None:
    """Every brand's Home_Menu is well formed and routable, and the Reset
    postback exists (conversation-reset R5.6, R7.2, R7.3).

    For each catalog brand `homeMenu` must be a non-empty list of at most
    HOME_MENU_MAX_ENTRIES mappings. Each mapping needs a non-empty string `label`
    within the registry's suggestionTextChars limit and a non-empty string
    `postback` that is a string literal in lambda/channel_adapter.py, so a tile
    cannot ship that the adapter would never route. Separately,
    `reset_conversation` must be a string literal in the adapter.
    """
    global checked
    limit = (limits.get(HOME_MENU_LABEL_LIMIT) or {}).get("value")
    if not isinstance(limit, int):
        sys.exit(f"FATAL: limit {HOME_MENU_LABEL_LIMIT!r} is missing from the registry or not an "
                 f"integer — the homeMenu label check cannot run")
    adapter_literals = string_literals(CHANNEL_ADAPTER)
    if not adapter_literals:
        sys.exit("FATAL: found no string literals in lambda/channel_adapter.py — has the file moved? "
                 "The homeMenu postback check would otherwise pass vacuously.")

    checked += 1
    if RESET_POSTBACK not in adapter_literals:
        fail(f"lambda/channel_adapter.py has no string literal {RESET_POSTBACK!r} — the Start Over chip "
             f"and the Reset routing depend on it")

    for brand_id in sorted(catalog):
        block = catalog[brand_id]
        label = f"brand {brand_id!r}"
        menu = block.get("homeMenu") if isinstance(block, dict) else None

        checked += 1
        if not isinstance(menu, list) or not menu:
            fail(f"{label} has no homeMenu (or it is empty) — add a non-empty list of "
                 f"{{label, postback}} entries to its block in content/brand.md")
            continue
        if len(menu) > HOME_MENU_MAX_ENTRIES:
            fail(f"{label} homeMenu has {len(menu)} entries, more than the {HOME_MENU_MAX_ENTRIES} "
                 f"allowed (one chip is left for Start Over)")

        for i, entry in enumerate(menu):
            where = f"{label} homeMenu entry #{i}"
            if not isinstance(entry, dict):
                checked += 1
                fail(f"{where} is {type(entry).__name__}, not a {{label, postback}} mapping")
                continue

            checked += 1
            text = entry.get("label")
            if not isinstance(text, str) or not text.strip():
                fail(f"{where} has no label (a non-empty string is required)")
            elif len(text) > limit:
                fail(f"{where} label {text!r} is {len(text)} characters, over the {limit}-character "
                     f"suggestion limit ({HOME_MENU_LABEL_LIMIT})")

            checked += 1
            postback = entry.get("postback")
            if not isinstance(postback, str) or not postback.strip():
                fail(f"{where} has no postback (a non-empty string is required)")
            elif postback not in adapter_literals:
                fail(f"{where} postback {postback!r} is not a string literal in "
                     f"lambda/channel_adapter.py — tapping it would not reach a flow")


def check_phone_numbers(catalog: dict) -> None:
    """Every brand's sample phone numbers are fictional, consistent and unique
    (anytravel-hotel-vignettes R19).

    For each catalog brand `contactPhoneNumber` and `memberServicesPhone` must
    each match +1 800 555-0100..0199, be equal to each other, and differ from
    every other brand's number. AnyWealth's `fraudLinePhone`, read from
    content/wealth.md, must equal that brand's `memberServicesPhone`. Each
    number checked counts as one registry fact; a finding names the brand, the
    field and the value.
    """
    global checked
    owners: dict[str, str] = {}
    for brand_id in sorted(catalog):
        block = catalog[brand_id]
        if not isinstance(block, dict):
            continue
        values: dict[str, str] = {}
        for field in BRAND_PHONE_FIELDS:
            checked += 1
            value = block.get(field)
            if not isinstance(value, str) or not PHONE_PATTERN.match(value):
                fail(f"brand {brand_id!r} {field} is {value!r}, not a +1800555 number in "
                     f"555-0100..0199 (the range reserved for fictional use)")
                continue
            values[field] = value
        if len(values) == len(BRAND_PHONE_FIELDS) and len(set(values.values())) != 1:
            fail(f"brand {brand_id!r} has different numbers: contactPhoneNumber "
                 f"{values['contactPhoneNumber']!r} != memberServicesPhone "
                 f"{values['memberServicesPhone']!r}")
        member = values.get("memberServicesPhone")
        if member:
            checked += 1
            other = owners.setdefault(member, brand_id)
            if other != brand_id:
                fail(f"brand {brand_id!r} memberServicesPhone {member!r} is already used by "
                     f"brand {other!r} — each brand needs its own number")

    wealth = catalog.get("anywealth")
    if not isinstance(wealth, dict):
        return
    checked += 1
    m = re.search(r'^fraudLinePhone:\s*["\']?([^"\'\s#]+)', WEALTH_SOURCE.read_text(), re.M) \
        if WEALTH_SOURCE.exists() else None
    fraud = m.group(1) if m else None
    expected = wealth.get("memberServicesPhone")
    if fraud is None:
        fail(f"{WEALTH_SOURCE.relative_to(ROOT)} has no fraudLinePhone for brand 'anywealth'")
    elif fraud != expected:
        fail(f"brand 'anywealth' fraudLinePhone is {fraud!r} but its memberServicesPhone is "
             f"{expected!r} — they must be the same number")


def flow_registry_ids() -> tuple[set[str], set[str]]:
    """(FLOW_MAP keys, AI_DRIVEN_VIGNETTES members) from lambda/flows/__init__.py,
    read with ast so the flow modules (and their imports) are never loaded. Stops
    the check with a message if either literal cannot be found."""
    tree = ast.parse(FLOWS_INIT.read_text())
    flow_keys: set[str] | None = None
    ai_ids: set[str] | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "FLOW_MAP" and isinstance(node.value, ast.Dict):
                flow_keys = {k.value for k in node.value.keys
                             if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            elif target.id == "AI_DRIVEN_VIGNETTES":
                try:
                    ai_ids = {str(v) for v in ast.literal_eval(node.value)}
                except (ValueError, SyntaxError):
                    ai_ids = None
    if not flow_keys or ai_ids is None:
        sys.exit(f"FATAL: could not find the FLOW_MAP dict and the AI_DRIVEN_VIGNETTES set in "
                 f"{FLOWS_INIT.relative_to(ROOT)} — the brand-isolation flow check verifies "
                 f"nothing until that is fixed")
    return flow_keys, ai_ids


def adapter_home_tile_map() -> dict[str, str]:
    """The `home_*` postback -> vignette id mapping of lambda/channel_adapter.py's
    handle_postback: the `home` dict literal, plus the arms that route to the AI
    assistants (HOME_SPECIAL_ARMS). Stops the check if the dict cannot be found."""
    tree = ast.parse(CHANNEL_ADAPTER.read_text())
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "handle_postback"):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                    and any(isinstance(t, ast.Name) and t.id == "home" for t in node.targets)):
                try:
                    mapping = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    break
                if mapping and all(isinstance(k, str) and isinstance(v, str)
                                   for k, v in mapping.items()):
                    return {**mapping, **HOME_SPECIAL_ARMS}
    sys.exit(f"FATAL: could not find the `home` dict literal in handle_postback in "
             f"{CHANNEL_ADAPTER.relative_to(ROOT)} — the brand-isolation tile check "
             f"verifies nothing until that is fixed")


def load_raw_brand_blocks() -> tuple[dict, frozenset]:
    """(each brand's own block exactly as written in content/brand.md, the
    vignettes every brand opens). Read through the real common.py reader but
    WITHOUT the shared top-level overlay that brand_catalog() applies, so a
    brand that forgets a key cannot pass on the shared fallback's value."""
    with lambda_modules() as (common, _adapter):
        (universal,) = required_names(common, COMMON, ["UNIVERSAL_VIGNETTES"])
        brands = common.content_frontmatter("brand.md").get("brands")
        if not isinstance(brands, dict) or not brands:
            sys.exit(f"FATAL: {BRAND_SOURCE.relative_to(ROOT)} has no `brands` map — "
                     f"the brand-isolation checks would otherwise pass vacuously")
        return {bid: (blk if isinstance(blk, dict) else {}) for bid, blk in brands.items()}, \
            frozenset(universal)


def check_brand_isolation(catalog: dict) -> None:
    """Each brand owns its vignettes, profile and grounding, and nothing of
    another brand shows through (brand-isolation R1.6, R5.3, R6.3, R10.3).

    Counted as registry facts (one per brand per check, one per item):
      1. `vignettes` is a non-empty list of non-empty strings whose set equals
         the dashboard catalog's VIGNETTES entries tagged with that brand.
      2. Every listed id is a FLOW_MAP key or an AI_DRIVEN_VIGNETTES member.
      3. `defaultVignette` is "" or an AI-driven id the brand also lists.
      4. memberName/memberPlan/memberIdMasked/memberCity are set in the brand's
         own block and name no other brand.
      5. Each groundingFiles entry names no other brand.
      6. Each homeMenu postback that opens a vignette opens one the brand owns.
    """
    global checked
    raw, universal = load_raw_brand_blocks()
    tags = vignette_brands()
    tagged_to = {vid: b for vid, b in tags}
    flow_ids, ai_ids = flow_registry_ids()
    tile_map = adapter_home_tile_map()
    names = brand_display_names(catalog)

    def other_names(brand_id: str) -> list[str]:
        block = catalog.get(brand_id) or {}
        own = {str(block.get(k) or "").strip() for k in ("displayName", "brandName")}
        return [n for n in names if n not in own]

    def foreign_hits(text: str, brand_id: str) -> list[str]:
        others = other_names(brand_id)
        if not others:
            return []
        pattern = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in others))
        return sorted(set(pattern.findall(text)))

    for brand_id in sorted(raw):
        block = raw[brand_id]
        label = f"brand {brand_id!r}"

        # 1. The vignette list matches the dashboard catalog's tags exactly.
        checked += 1
        listed = block.get("vignettes")
        valid_list = (isinstance(listed, list) and bool(listed)
                      and all(isinstance(v, str) and v.strip() for v in listed))
        if not valid_list:
            fail(f"{label} `vignettes` must be a non-empty list of vignette ids, got {listed!r}")
            listed_ids: list[str] = []
        else:
            listed_ids = [v.strip() for v in listed]
            for vid in sorted(set(listed_ids)):
                checked += 1
                if vid not in tagged_to:
                    fail(f"{label} lists vignette {vid!r}, which is not in the dashboard "
                         f"catalog (VIGNETTES in lambda/dashboard_handler.py)")
                elif tagged_to[vid] != brand_id:
                    fail(f"{label} lists vignette {vid!r}, which the dashboard catalog tags to "
                         f"brand {tagged_to[vid]!r}")
            for vid in sorted(v for v, b in tagged_to.items() if b == brand_id and v not in listed_ids):
                checked += 1
                fail(f"{label} omits vignette {vid!r}, which the dashboard catalog tags to it")

        # 2. Every listed id exists at runtime.
        checked += 1
        for vid in sorted(set(listed_ids)):
            checked += 1
            if vid not in flow_ids and vid not in ai_ids:
                fail(f"{label} lists vignette {vid!r}, which is neither a FLOW_MAP key nor in "
                     f"AI_DRIVEN_VIGNETTES in {FLOWS_INIT.relative_to(ROOT)} — it has no runtime route")

        # 3. defaultVignette is empty, or an AI assistant the brand owns.
        checked += 1
        default = block.get("defaultVignette")
        if not isinstance(default, str):
            fail(f"{label} `defaultVignette` must be a string (use \"\" for none), got {default!r}")
        elif default.strip():
            default = default.strip()
            if default not in ai_ids:
                fail(f"{label} defaultVignette {default!r} is not an AI-driven vignette "
                     f"(AI_DRIVEN_VIGNETTES: {', '.join(sorted(ai_ids))})")
            if default not in listed_ids:
                fail(f"{label} defaultVignette {default!r} is not in the brand's own `vignettes`")

        # 4. The member profile is the brand's own and names no other brand.
        for field in MEMBER_PROFILE_FIELDS:
            checked += 1
            value = block.get(field)
            if not isinstance(value, str) or not value.strip():
                fail(f"{label} must define its own {field!r} in its block in content/brand.md "
                     f"(got {value!r}); the shared top-level value is another brand's")
                continue
            for hit in foreign_hits(value, brand_id):
                fail(f"{label} {field} {value!r} names another brand, {hit!r}")

        # 5. Grounding files name no other brand.
        grounding = block.get("groundingFiles")
        for name in grounding if isinstance(grounding, list) else []:
            if not isinstance(name, str) or not name.strip():
                continue
            path = BRAND_SOURCE.parent / name
            if not path.is_file():
                continue  # reported by check_brands
            checked += 1
            for hit in foreign_hits(path.read_text(encoding="utf-8"), brand_id):
                fail(f"{label} grounding file {name!r} names another brand, {hit!r} — "
                     f"its AI would answer with a foreign brand's content")

        # 6. Home-menu tiles open only vignettes the brand owns.
        menu = block.get("homeMenu")
        for i, entry in enumerate(menu if isinstance(menu, list) else []):
            postback = entry.get("postback") if isinstance(entry, dict) else None
            if not isinstance(postback, str) or postback not in tile_map:
                continue
            checked += 1
            vid = tile_map[postback]
            if vid not in listed_ids and vid not in universal:
                fail(f"{label} homeMenu entry #{i} postback {postback!r} opens vignette "
                     f"{vid!r}, which the brand does not own")


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

    # ── brand catalog + vignette ownership ──────────────────────────────────
    catalog = load_brand_catalog()
    check_brands(catalog)
    check_vignette_brands(catalog)
    check_home_menu_and_reset(catalog, limits)
    check_phone_numbers(catalog)
    check_room_photos()
    check_brand_isolation(catalog)

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

    # ── hardcoded brand display names in the runtime/config source ───────────
    check_no_brand_literals(catalog)

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

    print(f"checked {checked} registry facts across {len(features)} features, "
          f"{len(limits)} limits and {len(catalog)} brands")
    if errors:
        print(f"\n{len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
