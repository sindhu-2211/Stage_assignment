"""ViewerBrief: clean, conflict-resolved viewer context handed to Stage 2."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EligibleGoal:
    goal_id: str
    name: str
    measurable: bool
    evidence: list[str]
    assumption: Optional[str] = None


@dataclass
class ViewerBrief:
    user_id: str
    trigger_event_id: str
    deliver_at: str
    assembled_at: str
    holdout: bool = False

    # Dialect
    dialect: str = ""
    dialect_source: str = ""
    dialect_conflicts: dict = field(default_factory=dict)

    # Subscription
    subscription_status: str = "never"
    subscription_source: str = "profile_snapshot"

    # Profile facts
    platform: str = ""
    signup_at: str = ""
    signup_age_days: float = 0.0
    notifications_opt_in: bool = False
    whatsapp_opt_in: bool = False

    # Behavioural facts
    event_types_seen: set = field(default_factory=set)
    play_days_14d: list = field(default_factory=list)   # distinct IST date strings
    unfinished_series: list = field(default_factory=list)  # list of content_slug
    days_since_last_app_open: float = 9999.0
    last_play_received_at: Optional[str] = None

    # Goals
    eligible_goals: list = field(default_factory=list)  # list[EligibleGoal]

    # Available content
    available_titles: list = field(default_factory=list)  # list[dict] from catalogue

    # Intervention constraints
    messages_sent_today_count: int = 0
    structural_constraints: dict = field(default_factory=dict)

    # Key event IDs that informed this decision (for machine-parseable evidence)
    key_event_ids: list = field(default_factory=list)

    # Audit
    assumptions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "user_id": self.user_id,
            "trigger_event_id": self.trigger_event_id,
            "deliver_at": self.deliver_at,
            "assembled_at": self.assembled_at,
            "holdout": self.holdout,
            "dialect": self.dialect,
            "dialect_source": self.dialect_source,
            "dialect_conflicts": self.dialect_conflicts,
            "subscription_status": self.subscription_status,
            "subscription_source": self.subscription_source,
            "platform": self.platform,
            "signup_at": self.signup_at,
            "signup_age_days": round(self.signup_age_days, 1),
            "notifications_opt_in": self.notifications_opt_in,
            "whatsapp_opt_in": self.whatsapp_opt_in,
            "event_types_seen": sorted(self.event_types_seen),
            "play_days_14d": self.play_days_14d,
            "unfinished_series": self.unfinished_series,
            "days_since_last_app_open": round(self.days_since_last_app_open, 1),
            "last_play_received_at": self.last_play_received_at,
            "eligible_goals": [
                {
                    "goal_id": g.goal_id,
                    "name": g.name,
                    "measurable": g.measurable,
                    "evidence": g.evidence,
                    "assumption": g.assumption,
                }
                for g in self.eligible_goals
            ],
            "available_titles_count": len(self.available_titles),
            "available_titles": [
                {
                    "title_id": t["title_id"],
                    "content_slug": t["content_slug"],
                    "title": t["title"],
                    "content_type": t["content_type"],
                    "genres": t.get("genres", ""),
                    "is_premium": t["is_premium"],
                    "release_date": t.get("release_date", ""),
                }
                for t in self.available_titles[:20]  # cap to keep prompt size sane
            ],
            "messages_sent_today_count": self.messages_sent_today_count,
            "structural_constraints": self.structural_constraints,
            "assumptions": self.assumptions,
        }
        return d
