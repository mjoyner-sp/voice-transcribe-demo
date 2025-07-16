# main.py

import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent
import uvicorn

REGION = "us-west-2"  # Change to your AWS region

app = FastAPI()
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")

class MyEventHandler(TranscriptResultStreamHandler):
    def __init__(self, output_stream, websocket):
        super().__init__(output_stream)
        self.websocket = websocket

    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        for result in transcript_event.transcript.results:
            print(result)  # Debug: See the actual attributes
            if result.alternatives: 
                transcript = result.alternatives[0].transcript
                if transcript:
                    # Determine is_final based on available attributes
                    is_final = getattr(result, "is_partial", None)
                    if is_final is not None:
                        is_final = not is_final  # True if not partial
                    else:
                        is_final = getattr(result, "result_type", "") == "FINAL"
                    try:
                        await self.websocket.send_json({
                            "text": transcript,
                            "is_final": is_final
                        })
                    except Exception:
                        return

async def stream_input(input_stream, websocket):
    try:
        while True:
            data = await websocket.receive_bytes()
            await input_stream.send_audio_event(audio_chunk=data)
    except Exception:
        pass
    await input_stream.end_stream()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client = TranscribeStreamingClient(region=REGION)
    stream = await client.start_stream_transcription(
        language_code="en-US",
        media_sample_rate_hz=16000,
        media_encoding="pcm"
    )
    handler = MyEventHandler(stream.output_stream, websocket)
    await asyncio.gather(
        handler.handle_events(),
        stream_input(stream.input_stream, websocket)
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
