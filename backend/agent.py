import os
import re
import random
import base64
from openai import AsyncOpenAI
from backend.models import ExtractedThreatIntel, TrapConversationState

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "your-key"))

PERSONA_PROMPT = """
You are 'Harold', an 78-year-old retired accountant who is slightly hard of hearing, uses glasses, and is easily confused by technology, but polite.
Your goal is to stay on the phone as long as possible with scammers without letting them know you are an AI or onto them.

RULES:
1. Speak concisely (1-2 sentences per response). Natural pauses and conversational filler are good.
2. If they ask for money, computer access, or sensitive info, don't say NO outright. Act confused, lose your glasses, misplace your wallet, or ask them to repeat the account numbers.
3. Keep asking where to send the payment or what website to go to, repeatedly writing it down wrong to force them to spell it.
4. Current Phase: {phase}
"""

def generate_offline_fallback(history: list[dict], state: TrapConversationState) -> str:
    """Intelligent fallback dialogue generator when LLM API quota is unavailable."""
    last_user_msg = ""
    for msg in reversed(history):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "").lower()
            break

    # 1. Tech Support / Remote Access / Virus Prompts
    if any(k in last_user_msg for k in ["virus", "anydesk", "teamviewer", "computer", "download", "website", "support", "hacked"]):
        responses = [
            "Oh dear, my glasses are smudged... Did you say www dot what? Can you spell that website address letter by letter for me, son?",
            "Hold on, I clicked on the blue icon on my screen, but now it's asking for a six-digit code. What button do I press next?",
            "Goodness me, twelve viruses?! My grandson told me I had an anti-virus installed. What was that link you wanted me to type in again?",
            "I'm typing it into the top bar, but it says 'Page not found'. Can you spell that web address one more time slowly?"
        ]
        return random.choice(responses)

    # 2. Financial / Wire / Bank / Gift Card Prompts
    if any(k in last_user_msg for k in ["bank", "wire", "transfer", "gift card", "account", "money", "dollar", "$", "target", "walmart"]):
        responses = [
            "Let me grab my reading glasses and my checkbook from the drawer... Could you repeat that account number slowly? I only got the first four digits.",
            "My checkbook says First National, but you mentioned another bank. Who should I make the cashier's check payable to exactly?",
            "Hold on, my pen ran out of ink! Honey, where's the pen? Okay, go ahead, what was the routing number and name on the account again?",
            "Is that the checking account or the wire transfer number? I want to make sure I write down every single number properly."
        ]
        return random.choice(responses)

    # 3. FTC / Warrant / Police / Legal Threat Prompts
    if any(k in last_user_msg for k in ["warrant", "arrest", "ftc", "police", "officer", "court", "legal", "jail", "sheriff"]):
        responses = [
            "Goodness gracious, an arrest warrant?! I've never even had a parking ticket in my 78 years! Who did you say you were with again, Officer?",
            "Please don't send the sheriff! Let me write down your badge number and office telephone so I have it for my records, what was your name?",
            "Oh dear, my blood pressure is acting up... What department did you say this was from, and what do I need to do to clear this up?"
        ]
        return random.choice(responses)

    # 4. Phase-Specific Progression
    phase_responses = {
        "hooking": [
            "Hello? Yes, this is Harold speaking... Who is this calling, please speak up a little bit.",
            "Hello there, Harold Vance here. I'm having a little trouble hearing you, what is this regarding?"
        ],
        "feigning_confusion": [
            "Oh goodness, let me adjust my hearing aid... Could you explain that one more time? I didn't quite catch what happened.",
            "I'm sorry son, technology always confuses me. What is it that you need me to do on my end?"
        ],
        "stalling": [
            "Hold on just a moment, I'm looking for my reading glasses on the kitchen counter... Are you still there?",
            "Let me find my yellow notepad. Okay, I'm ready now. Can you repeat those details from the beginning?"
        ],
        "extracting": [
            "Okay, I have my pen and paper right here. What was the exact name, website, and account number you need me to use?",
            "Can you spell out that website address and callback phone number very slowly for me so I don't misspell it?"
        ],
        "wrap_up": [
            "Alright, let me read that back to you to make sure I have every single digit right before I proceed.",
            "Thank you for being so patient with an old man. Let me verify the numbers one more time."
        ]
    }
    
    available = phase_responses.get(state.state, phase_responses["hooking"])
    return random.choice(available)

async def generate_response(history: list[dict], state: TrapConversationState) -> str:
    """Generates the low-latency dialogue response for the scammer with automatic fallback."""
    try:
        system_prompt = PERSONA_PROMPT.format(phase=state.state)
        messages = [{"role": "system", "content": system_prompt}] + history[-6:]
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.8,
            max_tokens=60
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[Agent Warning] OpenAI generation failed ({e}), using honeypot fallback.")
        return generate_offline_fallback(history, state)

async def synthesize_speech(text: str) -> str:
    """Synthesizes voice audio for Harold using OpenAI TTS or returns empty for browser WebSpeech fallback."""
    try:
        response = await client.audio.speech.create(
            model="tts-1",
            voice="onyx",
            input=text,
            response_format="mp3"
        )
        return base64.b64encode(response.content).decode("utf-8")
    except Exception as e:
        print(f"[TTS Warning] OpenAI TTS failed ({e}), client will use native voice fallback.")
        return ""
