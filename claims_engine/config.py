"""Business knobs. Change these, not the rules code."""
from dataclasses import dataclass, field


@dataclass
class RulesConfig:
    default_window_days: int = 7                       # SOP §1
    customer_window_days: dict[str, int] = field(
        default_factory=lambda: {"Zenith Retail": 15})  # key-account window (Oct precedents)
    goodwill_threshold_inr: int = 5000                 # claims strictly below this are goodwill-approved
    manager_limit_inr: int = 50000                     # SOP §6: above this -> Meera
    manager_name: str = "Meera"
    # Customers whose claims always go on the team-alert list (decision unchanged).
    alert_customers: dict[str, str] = field(default_factory=lambda: {
        "Bluewave Electronics": "Bluewave Electronics claim: rare case, team please review "
                                "(Oct had a sales-driven exception, C-0910)",
        "Zenith Retail": "Zenith Retail (prime customer): double-check before sending",
    })
