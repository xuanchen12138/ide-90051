"""Network-free evaluator with explicit hysteresis/dwell memory."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.models import SensorReading, iso


STATES = ("NORMAL", "WATCH", "WARNING", "CRITICAL")


@dataclass(frozen=True)
class TransitionState:
    hazard: str = "UNKNOWN"
    candidate: str | None = None
    candidate_since: datetime | None = None


def _timestamp(value: Any) -> datetime | None:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None and result.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def classify_service(transport: dict, now: datetime) -> tuple[str, str, list[str], list[str]]:
    feeds = transport.get("feeds", {})
    alerts_health = feeds.get("serviceAlerts", {}).get("freshness", transport.get("freshness", "unavailable"))
    source = feeds.get("serviceAlerts", {}).get("source", transport.get("source", "transport-victoria"))
    if source == "mock":
        return "UNKNOWN", source, ["MOCK_TRANSPORT_NO_OFFICIAL_STATUS"], ["Demonstration transport data is active; the official service status is unknown. No official alert is simulated."]
    if alerts_health != "fresh":
        return "UNKNOWN", source, ["TRANSPORT_ALERTS_UNAVAILABLE"], ["Current service status is unknown because the service-alert feed is stale or unavailable."]
    alerts = []
    for alert in transport.get("alerts", []):
        periods = alert.get("activePeriods", [])
        if periods and not any((not _timestamp(period.get("start")) or _timestamp(period.get("start")) <= now) and
                               (not _timestamp(period.get("end")) or _timestamp(period.get("end")) > now) for period in periods):
            continue
        start = _timestamp(alert.get("activeFrom"))
        end = _timestamp(alert.get("activeUntil"))
        if start and start > now or end and end <= now:
            continue
        alerts.append(alert)
    effects = {str(alert.get("effect", "")).upper() for alert in alerts}
    prefix = "Demonstration alert fixture" if source == "fixture" else "Official transport alert"
    if "NO_SERVICE" in effects:
        return "SUSPENDED", source, ["OFFICIAL_NO_SERVICE" if source != "fixture" else "FIXTURE_NO_SERVICE"], [f"{prefix} reports no service for the affected Route 58 context."]
    if effects & {"REDUCED_SERVICE", "DETOUR", "STOP_MOVED", "MODIFIED_SERVICE", "SIGNIFICANT_DELAYS"}:
        return "DISRUPTED", source, ["SERVICE_DISRUPTION"], [f"{prefix} reports a service disruption."]
    updates_health = feeds.get("tripUpdates", {}).get("freshness", transport.get("freshness", "unavailable"))
    current_updates = [update for update in transport.get("tripUpdates", []) if update.get("freshness", "fresh") == "fresh"]
    if updates_health == "fresh" and any(update.get("scheduleRelationship") in {"CANCELED", "DELETED"} for update in current_updates):
        return "DISRUPTED", source, ["OBSERVED_CANCELED_TRIP"], ["Realtime trip updates report a canceled trip; this does not establish a route-wide suspension."]
    delays = []
    for update in current_updates:
        if update.get("stopScheduleRelationship") in {"NO_DATA", "SKIPPED"}:
            continue
        stop_delays = [value for value in (update.get("arrivalDelaySeconds"), update.get("departureDelaySeconds")) if isinstance(value, (float, int))]
        delays.extend(stop_delays or ([update["tripDelaySeconds"]] if isinstance(update.get("tripDelaySeconds"), (int, float)) else []))
    if updates_health == "fresh" and any(value >= 60 for value in delays):
        return "DELAYED", source, ["OBSERVED_DELAY"], ["Realtime trip updates report a delay of at least one minute; no flood cause is inferred."]
    if alerts:
        return "NORMAL", source, ["SERVICE_INFORMATION"], [f"{prefix} contains information without a classified service suspension."]
    return "NORMAL", source, ["NO_REPORTED_DISRUPTION"], ["No relevant disruption is reported in the fresh service-alert feed; this does not guarantee normal operation."]


def evaluate_status(
    sensor: SensorReading | dict | None,
    transport: dict,
    config: dict,
    now: datetime,
    previous: TransitionState | None = None,
    *,
    site_id: str = "city-rd-kings-way-116",
    impact_scope: str = "local_segment",
    simulated: bool | None = None,
) -> tuple[dict, TransitionState]:
    """Return status and next memory. Inputs remain untouched; caller owns time."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluation time must include timezone")
    reading = sensor.model_dump(mode="python") if isinstance(sensor, SensorReading) else sensor
    previous = previous or TransitionState()
    codes: list[str] = []
    reasons: list[str] = []
    freshness = "unavailable"
    valid = False
    age = None
    if reading is None:
        codes.append("SENSOR_MISSING")
        reasons.append("No sensor observation is available for this operating mode.")
    else:
        observed = _timestamp(reading.get("observedAt"))
        age = (now - observed).total_seconds() if observed else None
        quality = reading.get("quality", "unknown")
        if age is None:
            codes.append("SENSOR_TIMESTAMP_INVALID")
            reasons.append("The observation timestamp is missing or has no timezone.")
        elif age < -float(config.get("futureToleranceSeconds", 5)):
            codes.append("SENSOR_FUTURE")
            reasons.append("The sensor observation is in the future beyond the allowed clock tolerance.")
        elif quality == "fault":
            codes.append("SENSOR_FAULT")
            reasons.append("The sensor reports a fault; the hazard cannot be assessed.")
        elif quality == "unknown":
            codes.append("SENSOR_QUALITY_UNKNOWN")
            reasons.append("The sensor quality is unknown; the hazard cannot be assessed.")
        elif quality == "stale" or age > float(config.get("sensorStaleSeconds", 30)):
            freshness = "stale"
            codes.append("SENSOR_STALE")
            reasons.append("The sensor observation is stale; the last level cannot establish current hazard.")
        elif quality == "valid":
            freshness = "fresh"
            valid = True
    next_memory = TransitionState()
    hazard = "UNKNOWN"
    if valid:
        level = float(reading["scenarioLevel"])
        thresholds = config.get("thresholds", {"WATCH": 25, "WARNING": 50, "CRITICAL": 75})
        limits = [float(thresholds[state]) for state in STATES[1:]]
        rank = sum(level >= limit for limit in limits)
        desired = STATES[rank]
        if previous.hazard in STATES:
            current_rank = STATES.index(previous.hazard)
            if rank < current_rank:
                # Step down one state at a time after the recovery dwell.
                boundary = limits[current_rank - 1] - float(config.get("hysteresis", 3))
                desired = STATES[current_rank - 1] if level < boundary else previous.hazard
            if desired != previous.hazard:
                rising = STATES.index(desired) > current_rank
                dwell = float(config.get("riseDwellSeconds" if rising else "recoveryDwellSeconds", 3 if rising else 5))
                since = previous.candidate_since if previous.candidate == desired else now
                if since is not None and (now - since).total_seconds() >= dwell:
                    hazard = desired
                    next_memory = TransitionState(hazard)
                else:
                    hazard = previous.hazard
                    next_memory = TransitionState(hazard, desired, since)
                    codes.append("TRANSITION_DWELL")
                    reasons.append(f"Waiting for the configured {'rising' if rising else 'recovery'} dwell before changing to {desired.lower()}.")
            else:
                hazard = previous.hazard
                next_memory = TransitionState(hazard)
        else:
            hazard = desired
            next_memory = TransitionState(hazard)
        codes.insert(0, f"HAZARD_{hazard}")
        kind = "Simulated" if reading.get("source") == "mock" else "Observed"
        reasons.insert(0, f"{kind} water level is {level:g}/100 ({reading.get('trend', 'unknown')}), evaluated against demonstration thresholds.")
    service, service_source, service_codes, service_reasons = classify_service(transport, now)
    codes.extend(service_codes)
    reasons.extend(service_reasons)
    if impact_scope == "full_route_demo":
        codes.append("SIMULATED_FULL_ROUTE_IMPACT")
        reasons.append("Simulated impact — not an official service status. Full-route colouring is a presentation scenario.")
    actions = {
        "NORMAL": "Continue monitoring the local water observation and transport information.",
        "WATCH": "Monitor rising water and prepare to review local operating conditions.",
        "WARNING": "Review local disruption risk with the responsible operator; these thresholds are unvalidated.",
        "CRITICAL": "Escalate for operator review; suspension may be required. The prototype does not control services.",
        "UNKNOWN": "Restore trustworthy sensor observations before assessing the current hazard.",
    }
    status = {
        "siteId": site_id,
        "hazardState": hazard,
        "serviceState": service,
        "serviceSource": service_source,
        "displayState": hazard,
        "impactScope": impact_scope,
        "simulated": simulated if simulated is not None else bool(reading and reading.get("source") == "mock"),
        "reasons": reasons,
        "reasonCodes": codes,
        "recommendedAction": actions[hazard],
        "evaluatedAt": iso(now),
        "dataFreshness": {"sensor": freshness, "transport": transport.get("freshness", "unavailable")},
    }
    return status, next_memory
