import os
import json
import asyncio
import urllib.parse
import websockets
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

load_dotenv()

from backend.models import TrapConversationState
from backend.agent import generate_response, synthesize_speech
from backend.intel_extractor import extract_intelligence

ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")

@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse(BASE_DIR / "frontend" / "index.html")

@app.websocket("/ws/audio")
async def audio_stream_endpoint(client_ws: WebSocket):
    await client_ws.accept()

    state = TrapConversationState()
    history = []
    accumulated_transcript = ""
    turns = 0

    # AssemblyAI Streaming v3 WebSocket configuration (16kHz 16-bit PCM)
    connection_params = {
        "sample_rate": 16000,
        "format_text": "true",
    }
    aai_url = f"wss://streaming.assemblyai.com/v3/ws?{urllib.parse.urlencode(connection_params)}"
    headers = {"Authorization": ASSEMBLYAI_API_KEY}

    try:
        async with websockets.connect(aai_url, additional_headers=headers) as aai_ws:
            
            async def forward_audio_to_assemblyai():
                """Reads raw PCM binary data or manual text inputs from client."""
                try:
                    while True:
                        message = await client_ws.receive()
                        if "bytes" in message and message["bytes"]:
                            # Send raw PCM 16kHz audio frame to AssemblyAI
                            await aai_ws.send(message["bytes"])
                        elif "text" in message and message["text"]:
                            # Handle typed simulation messages directly
                            data = json.loads(message["text"])
                            if "manual_text" in data:
                                await handle_caller_turn(data["manual_text"])
                except (WebSocketDisconnect, websockets.ConnectionClosed):
                    pass

            async def handle_caller_turn(caller_text: str):
                nonlocal turns, accumulated_transcript
                if not caller_text.strip():
                    return

                turns += 1
                if turns == 2:
                    state.show_interest()
                elif turns == 4:
                    state.need_delay()
                elif turns >= 6:
                    state.go_for_details()

                history.append({"role": "user", "content": caller_text})
                accumulated_transcript += f"\nCaller: {caller_text}"

                # Send caller transcript to UI
                await client_ws.send_json({
                    "type": "caller_turn",
                    "text": caller_text
                })

                # 1. Fast Conversational Voice Generation
                try:
                    agent_text = await generate_response(history, state)
                    history.append({"role": "assistant", "content": agent_text})
                    accumulated_transcript += f"\nHarold: {agent_text}"

                    audio_b64 = ""
                    try:
                        audio_b64 = await synthesize_speech(agent_text)
                    except Exception as tts_err:
                        print(f"[TTS Warning] Could not synthesize speech: {tts_err}")

                    # Send Harold's reply and audio to browser
                    await client_ws.send_json({
                        "type": "agent_reply",
                        "text": agent_text,
                        "audio": audio_b64,
                        "phase": state.state
                    })
                except Exception as agent_err:
                    print(f"[Agent Error] Failed to generate response: {agent_err}")
                    await client_ws.send_json({
                        "type": "agent_error",
                        "error": str(agent_err)
                    })

                # 2. Asynchronous Threat Intel Extraction (does not block voice path)
                asyncio.create_task(run_intel_task(accumulated_transcript))

            async def run_intel_task(transcript: str):
                try:
                    intel = await extract_intelligence(transcript)
                    await client_ws.send_json({
                        "type": "threat_intel",
                        "intel": intel.model_dump()
                    })
                except Exception as e:
                    print(f"[Intel Extraction Error]: {e}")

            async def listen_assemblyai_results():
                """Reads live transcripts from AssemblyAI."""
                try:
                    async for msg in aai_ws:
                        res = json.loads(msg)
                        msg_type = res.get("message_type")

                        # Live partial transcripts to show real-time typing
                        if msg_type == "PartialTranscript":
                            text = res.get("text", "")
                            if text:
                                await client_ws.send_json({"type": "partial_transcript", "text": text})

                        # Finalized utterance turn
                        elif msg_type == "FinalTranscript":
                            text = res.get("text", "").strip()
                            if text:
                                await handle_caller_turn(text)

                        # Support for v3 Turn events
                        elif res.get("type") == "Turn":
                            text = res.get("transcript", "").strip()
                            if res.get("end_of_turn") and text:
                                await handle_caller_turn(text)
                            elif text:
                                await client_ws.send_json({"type": "partial_transcript", "text": text})

                except (WebSocketDisconnect, websockets.ConnectionClosed):
                    pass

            await asyncio.gather(forward_audio_to_assemblyai(), listen_assemblyai_results())

    except WebSocketDisconnect:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)