"""
EUM wiring custom resource.

Performs the AWS End User Messaging setup around the RCS agent, so `cdk deploy`
is one command. The agent is created and registered during setup (AGENTS.md),
outside the stack. CloudFormation's AWS::SMSVOICE::RcsAgent would create a NEW
agent (its create handler calls CreateRcsAgent) rather than adopt that one, so
two-way is applied to the existing agent through the API. The configuration set
and its event destination are CloudFormation-manageable too
(AWS::SMSVOICE::ConfigurationSet, EventDestinations) but are created here so
that one resource sets up and unwinds the whole wiring:

  1. Create a configuration set (for delivery / read / fallback events).
  2. Attach an SNS event destination on it -> the inbound topic.
  3. Enable two-way messaging on the RCS agent -> the inbound topic + role.
  4. Register the agent's HELP, STOP and UNSTOP keyword replies (optional, and
     never fatal; see _register_keywords).

On stack delete, all four are unwound (best effort), except that only UNSTOP is
removed from the keywords: see _remove_unstop. A delete that finds the agent
already delivering to a different topic leaves everything alone, because another
deployment now owns it (see _two_way_moved_on). Requires modern boto3
(update_rcs_agent), supplied by the shared dependency layer.
"""

import time

import boto3

sms = boto3.client("pinpoint-sms-voice-v2")

# The keywords this stack writes: the keyword, the property carrying its reply,
# and its action. The replies come from content/brand.md through the stack.
# HELP and STOP exist on every agent already, as AUTOMATIC_RESPONSE and OPT_OUT;
# UNSTOP is the OPT_IN keyword that lets a member who texted STOP recover by text.
_KEYWORDS = (
    ("HELP", "KeywordHelpMessage", "AUTOMATIC_RESPONSE"),
    ("STOP", "KeywordStopMessage", "OPT_OUT"),
    ("UNSTOP", "KeywordUnstopMessage", "OPT_IN"),
)

# What the service replies with on a new agent until someone sets real text.
# A keyword still carrying one of these has never been customized, so replacing
# it takes nothing away from the deployer.
_AWS_DEFAULT_MESSAGES = {
    "HELP": "Default Help Message",
    "STOP": "Default Stop Message",
}

# DescribeKeywords, PutKeyword and DeleteKeyword share the control plane's
# roughly 1 request per second limit per account and Region. Every call in the
# keyword step waits this long first, which also spaces the first one from the
# update_rcs_agent call just before it. A throttled call waits twice as long on
# each retry, up to _KEYWORD_ATTEMPTS tries. The SDK retries throttles too, with
# short randomized delays, so its attempts can fall inside a single second.
_KEYWORD_PACE_SECONDS = 1.1
_KEYWORD_ATTEMPTS = 4


def on_event(event, context):
    request_type = event["RequestType"]
    props = event.get("ResourceProperties", {})
    old_props = event.get("OldResourceProperties") or {}
    agent_id = props["RcsAgentId"]
    config_set = props["ConfigurationSetName"]
    event_dest = props["EventDestinationName"]
    topic_arn = props["InboundTopicArn"]
    role_arn = props["TwoWayRoleArn"]
    event_types = props.get("MatchingEventTypes") or ["RCS_ALL"]
    agent_event_types = props.get("TwoWayRcsEventsEnabled") or ["ALL"]
    media_bucket = props.get("TwoWayMediaS3BucketName", "")
    media_role_arn = props.get("TwoWayMediaS3RoleArn", "")
    media_key_prefix = props.get("TwoWayMediaS3KeyPrefix", "")

    # Create mints the id and every later request keeps it. CloudFormation reads
    # a different id in an Update response as a replacement and then sends a
    # Delete for the old resource, which here would unwind the very agent the
    # Update has just wired (two-way off, UNSTOP gone). So the id must not follow
    # a property that legitimately changes: the agent id can change, and the
    # Update moves the wiring to the new agent in place (it receives
    # OldResourceProperties). A brand change that alters the resource-name prefix
    # never reaches this code as an Update: the prefix is part of the stack name,
    # so CloudFormation creates a second stack and this function sees a Create.
    physical_id = event.get("PhysicalResourceId") or f"eum-wiring::{agent_id}"
    print(f"{request_type} {physical_id}")

    result = {"PhysicalResourceId": physical_id}
    if request_type in ("Create", "Update"):
        _ensure_config_set(config_set)
        _ensure_event_destination(config_set, event_dest, topic_arn, event_types)
        _enable_two_way(
            agent_id, topic_arn, role_arn, media_bucket, media_role_arn, media_key_prefix,
            agent_event_types,
        )
        # Reported through Data rather than raised: the wiring above is what the
        # demo cannot run without, and a keyword problem must not fail the stack
        # or undo it.
        result["Data"] = {
            "KeywordsStatus": _register_keywords(agent_id, props, old_props)
        }
        if request_type == "Update":
            _warn_if_wiring_moved(old_props, agent_id, config_set)
    elif request_type == "Delete":
        if _two_way_moved_on(agent_id, topic_arn):
            print(
                f"leaving agent {agent_id}, its UNSTOP keyword and configuration set {config_set} "
                "alone: its two-way messaging now delivers to a different topic, so another "
                "deployment owns it"
            )
            return result
        _safe(lambda: _disable_two_way(agent_id), "disable two-way")
        _safe(
            lambda: sms.delete_event_destination(
                ConfigurationSetName=config_set, EventDestinationName=event_dest
            ),
            "delete event destination",
        )
        _safe(
            lambda: sms.delete_configuration_set(ConfigurationSetName=config_set),
            "delete configuration set",
        )
        _safe(lambda: _remove_unstop(agent_id, props), "remove UNSTOP keyword")

    return result


def _ensure_config_set(name):
    try:
        sms.create_configuration_set(ConfigurationSetName=name)
        print(f"created configuration set {name}")
    except sms.exceptions.ConflictException:
        print(f"configuration set {name} already exists")


def _ensure_event_destination(config_set, event_dest, topic_arn, event_types):
    # This destination carries OUTBOUND STATUS events only — delivered, read,
    # TTL expiration, fallback. Inbound interaction events (typing indicators
    # and, importantly, suggestion taps) are delivered to the agent's two-way
    # topic instead; postbacks go there *only*, never to a configuration set
    # destination (see the RCS events guide). That is why _enable_two_way
    # below is a separate, also-required call: this one buys delivery receipts,
    # that one buys button taps, and neither substitutes for the other.
    #
    # Subscribe the RCS family explicitly (RCS_ALL) rather than ALL; RCS_ALL is
    # the RCS subscription described in the RCS events guide. On a testing
    # agent, delivery events appear once the agent is launched in a country; the
    # RCSMessagesDelivered CloudWatch metric counts deliveries in the meantime.
    # After launch, compare the delivery counts in the dashboard with that
    # metric to confirm the subscription is matching events.
    # https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-events.html
    params = dict(
        ConfigurationSetName=config_set,
        EventDestinationName=event_dest,
        MatchingEventTypes=event_types,
        SnsDestination={"TopicArn": topic_arn},
    )
    try:
        sms.create_event_destination(**params)
        print(f"created event destination {event_dest} for {event_types}")
    except sms.exceptions.ConflictException:
        # Already present — repoint it at the current topic and event types.
        sms.update_event_destination(
            ConfigurationSetName=config_set,
            EventDestinationName=event_dest,
            MatchingEventTypes=event_types,
            SnsDestination={"TopicArn": topic_arn},
        )
        print(f"updated existing event destination {event_dest} for {event_types}")


def _enable_two_way(
    agent_id, topic_arn, role_arn, media_bucket="", media_role_arn="",
    media_key_prefix="", agent_event_types=("ALL",),
):
    params = dict(
        RcsAgentId=agent_id,
        TwoWayEnabled=True,
        TwoWayChannelArn=topic_arn,
        TwoWayChannelRole=role_arn,
        # The agent's own RCS event subscription (console: agent -> Two-way
        # messaging -> RCS events). Separate from, and additional to, the
        # configuration set's event destination: this one governs events the
        # agent itself forwards to the two-way topic. "ALL" means every current
        # and future type and must be the sole element. Left unset, the agent
        # forwards none of them, and an unset list is simply absent from
        # DescribeRcsAgents output rather than reported as empty.
        TwoWayRcsEventsEnabled=list(agent_event_types),
    )
    # Inbound media storage (S3 bucket + role AWS End User Messaging assumes
    # to write inbound photos/files there) is optional and configured
    # together — see "Receiving inbound RCS media". Two-way messaging must
    # already be enabled on the agent, which the params above do in the same
    # call.
    if media_bucket and media_role_arn:
        params["TwoWayMediaS3BucketName"] = media_bucket
        params["TwoWayMediaS3Role"] = media_role_arn
        if media_key_prefix:
            params["TwoWayMediaS3KeyPrefix"] = media_key_prefix
    sms.update_rcs_agent(**params)
    print(f"enabled two-way on {agent_id} -> {topic_arn}" + (f" (+ inbound media -> s3://{media_bucket}/{media_key_prefix})" if media_bucket else ""))


def _disable_two_way(agent_id):
    sms.update_rcs_agent(RcsAgentId=agent_id, TwoWayEnabled=False)
    print(f"disabled two-way on {agent_id}")


def _two_way_moved_on(agent_id, topic_arn):
    """True when the agent's two-way messaging delivers to a topic other than topic_arn.

    A Delete should unwind only what this resource set up. If the agent now
    forwards to another topic, a newer deployment (a replacement resource, or a
    second stack on the same agent) has taken it over, and disabling two-way or
    removing UNSTOP would break that one. Anything unclear (the read fails, the
    agent has no channel) counts as not moved on, so teardown unwinds as it
    always has.
    """
    try:
        agents = sms.describe_rcs_agents(RcsAgentIds=[agent_id]).get("RcsAgents", [])
    except Exception as e:  # noqa: BLE001 - teardown stays best effort
        print(f"could not read agent {agent_id} ({e}); unwinding it as this stack's")
        return False
    channel = agents[0].get("TwoWayChannelArn") if agents else None
    return bool(channel) and channel != topic_arn


def _warn_if_wiring_moved(old_props, agent_id, config_set):
    """Name what an Update that changed the agent or configuration set leaves behind.

    The wiring is moved in place (see on_event), so no Delete follows for the
    previous agent or configuration set. This function's role is scoped to the
    current ones, so it cannot unwind the previous ones itself, and trying would
    only be refused. They are named here so they can be cleaned up by hand.
    """
    old_agent = old_props.get("RcsAgentId")
    if old_agent and old_agent != agent_id:
        print(
            f"WARNING: the RCS agent changed from {old_agent} to {agent_id}. {old_agent} keeps "
            "the two-way messaging and keyword replies this stack set up on it, and this "
            "function's role cannot undo them. Disable its two-way messaging yourself: aws "
            f"pinpoint-sms-voice-v2 update-rcs-agent --rcs-agent-id {old_agent} --no-two-way-enabled"
        )
    old_set = old_props.get("ConfigurationSetName")
    old_dest = old_props.get("EventDestinationName")
    if old_set and old_set != config_set:
        print(
            f"WARNING: configuration set {old_set} is no longer used and was not removed; this "
            "function's role covers only the current one. Delete it yourself: aws "
            f"pinpoint-sms-voice-v2 delete-event-destination --configuration-set-name {old_set} "
            f"--event-destination-name {old_dest}, then delete-configuration-set "
            f"--configuration-set-name {old_set}"
        )


def _register_keywords(agent_id, props, old_props):
    """Register the HELP and STOP replies and the UNSTOP opt-in keyword.

    Returns the KeywordsStatus string reported in the custom resource's Data. It
    never raises: the agent outlives this stack and answers HELP and STOP with
    the service's default text whether or not this works, so a failure is logged
    loudly and reported, and the deploy carries on.

    The agent is created outside the stack, so what is on it may be the
    deployer's. HELP and STOP are written only while they are empty, still the
    service's default, or still the text this stack wrote on the previous
    deploy (old_props), so a brand change refreshes the stack's own text and a
    reply someone wrote by hand stays. old_props is there for every brand edit
    that keeps the resource-name prefix, because the physical id stays put and
    CloudFormation sends an Update (see on_event). It is empty on
    Create, where nothing is known to be this stack's, so a reply already on the
    agent is kept. UNSTOP is written only when it is absent or still the text
    this stack wrote. Other keywords are never touched.

    Without any Keyword*Message property (a stack from before this step, or one
    deployed with registerKeywords=false) it does nothing. Switching the option
    off later does not undo what an earlier deploy wrote.
    """
    plan = [
        (kw, action, (props.get(prop) or "").strip(), (old_props.get(prop) or "").strip())
        for kw, prop, action in _KEYWORDS
    ]
    plan = [step for step in plan if step[2]]
    if not plan:
        print("no keyword replies requested; leaving the agent's keywords alone")
        return "skipped"

    try:
        existing = _describe_keywords(agent_id)
    except Exception as e:  # noqa: BLE001 - non-fatal by design
        _keyword_failure("describe keywords", e)
        return f"error (DescribeKeywords: {_error_code(e)})"

    outcomes = {}
    for kw, action, wanted, previous in plan:
        try:
            outcomes[kw] = _reconcile_keyword(agent_id, kw, action, wanted, previous, existing.get(kw))
        except Exception as e:  # noqa: BLE001 - one keyword failing must not skip the rest
            _keyword_failure(f"put {kw}", e)
            outcomes[kw] = f"error {_error_code(e)}"

    failed = any(outcome.startswith("error") for outcome in outcomes.values())
    if failed:
        print(
            "WARNING: the HELP / STOP / UNSTOP replies were not all registered. The stack "
            "deployed anyway. Register them by hand (AGENTS.md, 'Register the keyword "
            "replies') or fix the error above and deploy again."
        )
    detail = ", ".join(f"{kw}: {outcome}" for kw, outcome in outcomes.items())
    return f"{'error' if failed else 'ok'} ({detail})"


def _reconcile_keyword(agent_id, kw, action, wanted, previous, current):
    """Write one keyword if that does not overwrite someone's choice.

    `current` is the DescribeKeywords entry (None when absent) and `previous` the
    reply this stack wrote on the last deploy ("" when unknown). Returns a short
    outcome for KeywordsStatus.
    """
    current_message = ((current or {}).get("KeywordMessage") or "").strip()
    current_action = (current or {}).get("KeywordAction")
    if current_message == wanted and current_action == action:
        print(f"{kw} already has the requested reply")
        return "unchanged"

    placeholder = current_message == _AWS_DEFAULT_MESSAGES.get(kw)
    written_by_us = bool(previous) and current_message == previous and current_action == action
    if current_message and not placeholder and not written_by_us:
        print(f"leaving {kw} as it is: its message or action was set outside this stack")
        if kw == "UNSTOP" and current_action != "OPT_IN":
            print(
                "WARNING: UNSTOP is not an OPT_IN keyword, so the STOP reply's 'Reply UNSTOP "
                "to opt back in' will not work. Change it, or set your own STOP reply."
            )
        return "kept (set by you)"

    _keyword_call(
        sms.put_keyword,
        OriginationIdentity=agent_id,
        Keyword=kw,
        KeywordMessage=wanted,
        KeywordAction=action,
    )
    print(f"registered {kw} ({action})")
    return "created" if current is None else "registered"


def _remove_unstop(agent_id, props):
    """On stack delete, remove UNSTOP if it still holds the text this stack wrote.

    Removed only on that match, so an UNSTOP the deployer added or changed stays.
    HELP and STOP cannot be deleted, so they keep the text registered here: the
    agent was created outside the stack and outlives it. A stack with no recorded
    UNSTOP text (one that never registered keywords, or was last deployed with
    registerKeywords=false) has nothing to match against, so UNSTOP stays.
    """
    wanted = (props.get("KeywordUnstopMessage") or "").strip()
    if not wanted:
        print("no UNSTOP reply recorded for this stack; leaving the agent's keywords alone")
        return
    current = _describe_keywords(agent_id).get("UNSTOP")
    if current is None:
        print("UNSTOP is not registered; nothing to remove")
    elif (current.get("KeywordMessage") or "").strip() == wanted and current.get("KeywordAction") == "OPT_IN":
        _keyword_call(sms.delete_keyword, OriginationIdentity=agent_id, Keyword="UNSTOP")
        print("removed the UNSTOP keyword this stack registered")
    else:
        print("leaving UNSTOP: it does not hold the text this stack registered")


def _describe_keywords(agent_id):
    """Every keyword on the agent, keyed by upper-cased keyword."""
    found, token = {}, None
    while True:
        params = {"OriginationIdentity": agent_id, "MaxResults": 100}
        if token:
            params["NextToken"] = token
        page = _keyword_call(sms.describe_keywords, **params)
        for entry in page.get("Keywords", []):
            found[entry["Keyword"].upper()] = entry
        token = page.get("NextToken")
        if not token:
            return found


def _keyword_call(operation, **params):
    """Call a keyword API at a pace its per-second limit allows, retrying throttles."""
    for attempt in range(_KEYWORD_ATTEMPTS):
        time.sleep(_KEYWORD_PACE_SECONDS * 2**attempt)
        try:
            return operation(**params)
        except sms.exceptions.ThrottlingException:
            if attempt == _KEYWORD_ATTEMPTS - 1:
                raise
            print(f"{operation.__name__} throttled; retrying")


def _keyword_failure(step, error):
    # The full text goes to the log only. It names the role and the account, so
    # what is reported in Data (and so in a stack output) is just the error code.
    print(f"ERROR keyword step failed ({step}): {error}")


def _error_code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code") or type(error).__name__


def _safe(fn, label):
    try:
        fn()
        print(f"ok: {label}")
    except Exception as e:  # noqa: BLE001 - best-effort teardown
        print(f"skip ({label}): {e}")
