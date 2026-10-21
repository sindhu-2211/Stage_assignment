"""Provider ABC and DecisionDraft dataclass."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class ProviderError(Exception):
    pass


class ProviderTimeoutError(ProviderError):
    pass


@dataclass
class DecisionDraft:
    goal_id: Optional[str] = None
    action_type: str = "no_action"  # home_page|push|whatsapp|in_app_message|no_action
    title_id: Optional[str] = None
    content_slug: Optional[str] = None   # for G07
    row_types: list = field(default_factory=list)  # for home_page rows
    confidence: float = 0.0
    reasoning: str = ""
    raw_response: Optional[str] = None
    # Populated by Stage 3 verifier
    checks_passed: list = field(default_factory=list)
    checks_failed: list = field(default_factory=list)


class ModelProvider(ABC):
    @abstractmethod
    def decide(self, viewer_brief_json: dict, trigger_event_id: str) -> DecisionDraft:
        """Make a decision for this viewer. May raise ProviderError or ProviderTimeoutError."""
        ...
