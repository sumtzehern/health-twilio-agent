#main.py

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse
from agent import run_agent
import argparse
import json
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/")
async def start_call():
    print("Start call")
    with open("templates/streams.xml") as f:
        return HTMLResponse(content=f.read(), media_type="application/xml")


@app.websocket("/audio-stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # wait for the start message
    message_stream = websocket.iter_text()
    await message_stream.__anext__()
    call_start = json.loads(await message_stream.__anext__())
    stream_sid = call_start["start"]["streamSid"]

    print("Call started. Stream SID:", stream_sid, flush=True)
    await run_agent(websocket, stream_sid, app.state.testing)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Twilio Chatbot Server")
    parser.add_argument(
        "-t", "--test", action="store_true", default=False, help="set the server in testing mode"
    )
    args, _ = parser.parse_known_args()

    app.state.testing = args.test

    uvicorn.run(app, host="0.0.0.0", port=8765)