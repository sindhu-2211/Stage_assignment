"""
AgentConfig: loads all static data from the pack at startup.
Everything here is read-only after __init__ completes.
"""
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


class AgentConfig:
    def __init__(self, pack_root: Path):
        self.pack_root = Path(pack_root)
        self._load_goals()
        self._load_interventions()
        self._load_pricing()
        self._load_catalogue()
        self._load_episodes()
        self._load_profiles()
        self._load_arms()
        self._load_model_faults()
        self.default_dialect = self._compute_default_dialect()

    # ------------------------------------------------------------------ goals

    def _load_goals(self):
        path = self.pack_root / "config" / "goals.json"
        data = json.loads(path.read_text())
        self.goals = {g["goal_id"]: g for g in data["goals"]}

    # ---------------------------------------------------------- interventions

    def _load_interventions(self):
        path = self.pack_root / "config" / "interventions.json"
        self.interventions = json.loads(path.read_text())

        # Pre-extract frequently checked values
        push = self.interventions["push"]
        self.forbidden_phrases = [p.lower() for p in push["copy"]["forbidden_phrases"]]
        wa = self.interventions["whatsapp"]
        self.approved_templates = {t["template_id"]: t for t in wa["approved_templates"]}

    # --------------------------------------------------------------- pricing

    def _load_pricing(self):
        path = self.pack_root / "config" / "pricing.json"
        data = json.loads(path.read_text())
        self.pricing = {p["plan_id"]: p for p in data["plans"]}
        # Set of valid price strings for forbidden-phrase / price-claim checks
        self.valid_prices_inr = {str(p["price_inr"]) for p in data["plans"]}

    # -------------------------------------------------------------- catalogue

    def _load_catalogue(self):
        path = self.pack_root / "data" / "catalogue.csv"
        self.catalogue_by_id: dict[str, dict] = {}
        self.catalogue_by_dialect: dict[str, list[dict]] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["is_premium"] = row["is_premium"].strip().lower() == "true"
                self.catalogue_by_id[row["title_id"]] = row
                self.catalogue_by_dialect.setdefault(row["dialect"], []).append(row)

    # --------------------------------------------------------------- episodes

    def _load_episodes(self):
        path = self.pack_root / "data" / "episodes.csv"
        # Index by content_slug for G07 (unfinished series)
        self.episodes_by_slug: dict[str, list[dict]] = {}
        self.episode_by_id: dict[str, dict] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["season"] = int(row["season"]) if row["season"] else 0
                row["episode"] = int(row["episode"]) if row["episode"] else 0
                row["minutes"] = float(row["minutes"]) if row["minutes"] else 0.0
                slug = row["content_slug"]
                self.episodes_by_slug.setdefault(slug, []).append(row)
                self.episode_by_id[row["episode_id"]] = row

    # --------------------------------------------------------------- profiles

    def _load_profiles(self):
        path = self.pack_root / "data" / "profiles_snapshot.csv"
        # Multiple rows per user_id possible; keep all, resolve at assembly time
        self.profiles_raw: dict[str, list[dict]] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["notifications_opt_in"] = row["notifications_opt_in"].strip().lower() == "true"
                row["whatsapp_opt_in"] = row["whatsapp_opt_in"].strip().lower() == "true"
                uid = row["user_id"]
                self.profiles_raw.setdefault(uid, []).append(row)

    # ------------------------------------------------------------------ arms

    def _load_arms(self):
        path = self.pack_root / "replay" / "arms.csv"
        self.arms: dict[str, str] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.arms[row["user_id"]] = row["arm"].strip()

    # ---------------------------------------------------------- model faults

    def _load_model_faults(self):
        path = self.pack_root / "replay" / "model_faults.jsonl"
        self.model_faults: dict[str, dict] = {}
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                self.model_faults[entry["trigger_event_id"]] = entry

    # ------------------------------------------------- default dialect

    def _compute_default_dialect(self) -> str:
        counts: Counter = Counter()
        for rows in self.profiles_raw.values():
            for row in rows:
                d = row.get("preferred_dialect", "").strip()
                if d:
                    counts[d] += 1
        if counts:
            return counts.most_common(1)[0][0]
        # Fallback: most common dialect in catalogue
        cat_counts: Counter = Counter()
        for title in self.catalogue_by_id.values():
            d = title.get("dialect", "").strip()
            if d:
                cat_counts[d] += 1
        if cat_counts:
            return cat_counts.most_common(1)[0][0]
        return "d1"

    # --------------------------------------------------------- helpers

    def title_available_at(self, title: dict, at_utc: str) -> bool:
        """True if title is available at the given UTC ISO timestamp."""
        avail_from = title.get("available_from", "").strip()
        avail_until = title.get("available_until", "").strip()
        try:
            t = datetime.fromisoformat(at_utc.replace("Z", "+00:00"))
            if avail_from:
                af = datetime.fromisoformat(avail_from.replace("Z", "+00:00"))
                if t < af:
                    return False
            if avail_until:
                au = datetime.fromisoformat(avail_until.replace("Z", "+00:00"))
                if t > au:
                    return False
        except (ValueError, AttributeError):
            return False
        return True

    def titles_for_dialect(
        self,
        dialect: str,
        at_utc: str,
        subscription_status: str,
        live_catalogue: dict | None = None,
    ) -> list[dict]:
        """
        Returns titles in dialect that are available at at_utc.
        Filters out is_premium=True when subscription_status not in (active, trial_active).
        live_catalogue: dict[title_id -> title] from LiveState (post-control-events).
        """
        paid = subscription_status in ("active", "trial_active")
        source = live_catalogue if live_catalogue is not None else self.catalogue_by_id
        result = []
        for title in self.catalogue_by_dialect.get(dialect, []):
            tid = title["title_id"]
            # Skip if withdrawn by control event
            if live_catalogue is not None and tid not in live_catalogue:
                continue
            if not self.title_available_at(title, at_utc):
                continue
            if title["is_premium"] and not paid:
                continue
            result.append(title)
        return result
