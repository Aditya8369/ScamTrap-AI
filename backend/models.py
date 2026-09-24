from pydantic import BaseModel, Field
from typing import List, Optional
from transitions import Machine

class ExtractedThreatIntel(BaseModel):
    caller_claimed_identity: Optional[str] = Field(None, description="Who the scammer claims to be")
    tactics_used: List[str] = Field(default_factory=list, description="Tactics detected (e.g. Urgency, Arrest Threats)")
    mule_bank_accounts: List[str] = Field(default_factory=list, description="Bank accounts, crypto wallets, or payment targets")
    phone_numbers_mentioned: List[str] = Field(default_factory=list, description="Callback phone numbers")
    urls_or_domains: List[str] = Field(default_factory=list, description="Remote access tools, malicious links, or websites")
    urgency_level: str = Field("Low", description="Low, Medium, High, or Critical")

class TrapConversationState:
    states = ["hooking", "feigning_confusion", "stalling", "extracting", "wrap_up"]

    def __init__(self):
        self.machine = Machine(model=self, states=TrapConversationState.states, initial="hooking")
        self.machine.add_transition(trigger="show_interest", source="hooking", dest="feigning_confusion")
        self.machine.add_transition(trigger="need_delay", source=["feigning_confusion", "extracting"], dest="stalling")
        self.machine.add_transition(trigger="go_for_details", source=["feigning_confusion", "stalling"], dest="extracting")
        self.machine.add_transition(trigger="terminate", source="*", dest="wrap_up")