"""
LiveState: mutable working copy of catalogue + goals, updated by control events.
Stage 1 reads from this, never directly from AgentConfig, so control events apply.
"""
import copy
from src.config import AgentConfig


class LiveState:
    def __init__(self, config: AgentConfig):
        # Shallow copy of dicts; titles/goals are dicts so we deepcopy for safety
        self.catalogue: dict[str, dict] = copy.deepcopy(config.catalogue_by_id)
        self.goals: dict[str, dict] = copy.deepcopy(config.goals)
        self.unavailable_deps: set[str] = set()
        # dep -> until UTC string
        self.degraded_deps: dict[str, str] = {}

    def apply(self, ce: dict) -> None:
        """Apply one control event. Call in delivery-time (at) order."""
        ctype = ce.get("type")
        if ctype == "title_withdrawn":
            self.catalogue.pop(ce.get("title_id", ""), None)
        elif ctype == "goal_rule_corrected":
            gid = ce.get("goal_id")
            if gid and gid in self.goals:
                correction = ce.get("new_success") or ce.get("correction", {})
                if correction:
                    self.goals[gid]["success"].update(correction)
        elif ctype == "dependency_unavailable":
            dep = ce.get("dependency", "")
            if dep:
                self.unavailable_deps.add(dep)
                until = ce.get("until")
                if until:
                    # Will be removed once until timestamp passes (harness clears it)
                    self.degraded_deps[dep] = until
        elif ctype == "dependency_degraded":
            dep = ce.get("dependency", "")
            until = ce.get("until", "")
            if dep:
                self.degraded_deps[dep] = until

    def clear_expired_deps(self, now_utc: str) -> None:
        """Remove dependency outages whose until has passed."""
        expired = [
            dep for dep, until in self.degraded_deps.items()
            if until and until <= now_utc
        ]
        for dep in expired:
            self.unavailable_deps.discard(dep)
            del self.degraded_deps[dep]

    def model_provider_available(self) -> bool:
        return "model_provider" not in self.unavailable_deps
