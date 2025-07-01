# main.py

import asyncio
import sounddevice as sd
import numpy as np
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

REGION = "us-west-2"  # Change to your AWS region if needed

class MyEventHandler(TranscriptResultStreamHandler):
    async def handle_transcript_event(self, transcript_event: TranscriptEvent):
        for result in transcript_event.transcript.results:
            if result.alternatives:
                transcript = result.alternatives[0].transcript
                if transcript:
                    print(f"> {transcript}")

async def mic_stream_generator():
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()

    def callback(indata, frames, time, status):
        if status:
            print(status)
        loop.call_soon_threadsafe(q.put_nowait, indata.copy())

    stream = sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="int16",
        blocksize=3200,  # 100ms of audio at 16kHz mono 16-bit
        callback=callback
    )
    stream.start()

    try:
        while True:
            indata = await q.get()
            pcm_data = indata.flatten().tobytes()
            yield pcm_data
    except asyncio.CancelledError:
        stream.stop()
        raise

async def main():
    client = TranscribeStreamingClient(region=REGION)
    stream = await client.start_stream_transcription(
        language_code="en-US",
        media_sample_rate_hz=16000,
        media_encoding="pcm"
    )

    handler = MyEventHandler(stream.output_stream)
    await asyncio.gather(
        handler.handle_events(),
        stream_input(stream.input_stream)
    )

async def stream_input(input_stream):
    async for chunk in mic_stream_generator():
        await input_stream.send_audio_event(audio_chunk=chunk)
    await input_stream.end_stream()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Stopped]")
