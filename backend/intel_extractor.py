import os
import re
from openai import AsyncOpenAI
from backend.models import ExtractedThreatIntel

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def extract_heuristics(transcript: str) -> ExtractedThreatIntel:
    """Fallback threat extractor using regex pattern recognition and heuristic analysis."""
    text_lower = transcript.lower()

    # 1. Claimed Identity
    claimed_id = None
    if "ftc" in text_lower or "federal trade commission" in text_lower:
        claimed_id = "Federal Trade Commission (FTC)"
    elif "microsoft" in text_lower:
        claimed_id = "Microsoft Support / Windows Security"
    elif "bank of america" in text_lower:
        claimed_id = "Bank of America Fraud Dept"
    elif "irs" in text_lower or "internal revenue" in text_lower:
        claimed_id = "Internal Revenue Service (IRS)"
    elif "amazon" in text_lower:
        claimed_id = "Amazon Customer Support"
    elif "officer" in text_lower or "sheriff" in text_lower or "police" in text_lower:
        claimed_id = "Law Enforcement / Police Officer"

    # 2. Tactics Used
    tactics = []
    if any(k in text_lower for k in ["warrant", "arrest", "jail", "police", "sheriff", "lawsuit"]):
        tactics.append("Arrest / Legal Threat")
    if any(k in text_lower for k in ["immediately", "urgent", "now", "hurry", "expire", "12 hours"]):
        tactics.append("Urgency / Artificial Panic")
    if any(k in text_lower for k in ["anydesk", "teamviewer", "ultraviewer", "download", "remote"]):
        tactics.append("Remote Access Trojan / Screen Control")
    if any(k in text_lower for k in ["wire", "transfer", "bank", "account", "gift card", "target", "walmart", "$"]):
        tactics.append("Financial Extortion / Mule Transfer")
    if any(k in text_lower for k in ["virus", "infected", "trojan", "hacked", "malware"]):
        tactics.append("Fake Malware / Technical Scare")

    # 3. Bank Accounts / Wallets / Gift Cards
    accounts = []
    acct_matches = re.findall(r"(?:account|acct|acc|wire|transfer|card)?\s*(?:#|no\.?)?\s*(\b\d{8,16}\b)", transcript, re.IGNORECASE)
    for m in acct_matches:
        if m not in accounts:
            accounts.append(f"Account #{m}")
    
    amount_matches = re.findall(r"(\$\s*[\d,]+(?:\.\d{2})?)", transcript)
    for a in amount_matches:
        if a not in accounts:
            accounts.append(f"Demanded Amount: {a}")
            
    if "gift card" in text_lower or "target" in text_lower or "walmart" in text_lower:
        if "Gift Cards (Retail / Target / Walmart)" not in accounts:
            accounts.append("Target / Retail Gift Cards")

    # 4. URLs / Domains
    urls = []
    url_matches = re.findall(r"(https?://[^\s]+|www\.[^\s]+|[\w-]+\.(?:com|net|org|io|desk|tech|cc|xyz)[^\s]*)", transcript, re.IGNORECASE)
    for u in url_matches:
        clean_u = u.strip(".,;:!?\"'")
        if clean_u and clean_u not in urls:
            urls.append(clean_u)
            
    if "anydesk" in text_lower and "AnyDesk Remote" not in urls:
        urls.append("AnyDesk (Remote Access Tool)")
    if "teamviewer" in text_lower and "TeamViewer Remote" not in urls:
        urls.append("TeamViewer (Remote Access Tool)")

    # 5. Phone numbers
    phone_matches = re.findall(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", transcript)
    phones = list(set(phone_matches))

    # 6. Urgency Level
    if "warrant" in text_lower or "arrest" in text_lower or "jail" in text_lower:
        urgency = "Critical"
    elif "immediately" in text_lower or "urgent" in text_lower or "virus" in text_lower or "$" in text_lower:
        urgency = "High"
    elif tactics:
        urgency = "Medium"
    else:
        urgency = "Low"

    return ExtractedThreatIntel(
        caller_claimed_identity=claimed_id,
        tactics_used=tactics,
        mule_bank_accounts=accounts,
        phone_numbers_mentioned=phones,
        urls_or_domains=urls,
        urgency_level=urgency
    )

async def extract_intelligence(transcript: str) -> ExtractedThreatIntel:
    """Extracts forensic threat intelligence using OpenAI structured parsing with heuristic fallback."""
    try:
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Extract all indicators of compromise, scam tactics, target bank accounts, URLs, and urgency levels."
                },
                {"role": "user", "content": transcript}
            ],
            response_format=ExtractedThreatIntel,
        )
        return response.choices[0].message.parsed
    except Exception as e:
        print(f"[Intel Warning] OpenAI parse failed ({e}), using heuristic analysis.")
        return extract_heuristics(transcript)