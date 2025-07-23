require('dotenv').config();
const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const { 
  TranscribeStreamingClient, 
  StartStreamTranscriptionCommand 
} = require('@aws-sdk/client-transcribe-streaming');

// Config
const PORT = process.env.PORT || 8000;
const AWS_REGION = process.env.AWS_REGION || 'us-west-2';
const LANGUAGE_CODE = process.env.LANGUAGE_CODE || 'en-US';
const SAMPLE_RATE = parseInt(process.env.SAMPLE_RATE || '16000');

// Set up Express app and static file serving
const app = express();
app.use(express.static(path.join(__dirname, 'static')));

// Create HTTP server
const server = http.createServer(app);

// Set up WebSocket server
const wss = new WebSocket.Server({ server });

// Handle WebSocket connections
wss.on('connection', async (ws) => {
  console.log('Client connected');
  
  let transcribeClient;
  let streamFinished = false;
  
  // Create Transcribe client
  transcribeClient = new TranscribeStreamingClient({ region: AWS_REGION });
  
  // Audio stream generator
  const audioGenerator = async function* () {
    try {
      while (!streamFinished) {
        // Wait for audio chunks from the WebSocket
        const audioChunk = await new Promise((resolve, reject) => {
          const messageHandler = (message) => {
            ws.removeListener('message', messageHandler);
            resolve(message);
          };
          
          const closeHandler = () => {
            streamFinished = true;
            ws.removeListener('close', closeHandler);
            resolve(null);
          };
          
          ws.on('message', messageHandler);
          ws.once('close', closeHandler);
        });
        
        // If we got data and the stream is still open, yield it for Transcribe
        if (audioChunk && !streamFinished) {
          yield { AudioEvent: { AudioChunk: audioChunk } };
        } else if (!audioChunk) {
          break;
        }
      }
    } catch (error) {
      console.error('Error in audio generator:', error);
      streamFinished = true;
    }
  };
  
  // Start transcription
  try {
    const command = new StartStreamTranscriptionCommand({
      LanguageCode: LANGUAGE_CODE,
      MediaSampleRateHertz: SAMPLE_RATE,
      MediaEncoding: 'pcm',
      AudioStream: audioGenerator()
    });
    
    const response = await transcribeClient.send(command);
    
    // Process transcription results
    for await (const event of response.TranscriptResultStream) {
      if (streamFinished) break;
      
      if (event?.TranscriptEvent?.Transcript?.Results) {
        const results = event.TranscriptEvent.Transcript.Results;
        
        for (const result of results) {
          if (result.Alternatives?.[0]?.Transcript) {
            const transcript = result.Alternatives[0].Transcript;
            const isPartial = result.IsPartial === true;
            
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({
                text: transcript,
                is_final: !isPartial
              }));
            }
          }
        }
      }
    }
  } catch (error) {
    console.error('Transcription error:', error);
    
    try {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ 
          error: 'Transcription service error', 
          errorType: error.name 
        }));
      }
    } catch (wsError) {
      console.error('Error sending message to client:', wsError);
    }
  }
  
  // Handle WebSocket close
  ws.on('close', () => {
    console.log('Client disconnected');
    streamFinished = true;
    
    if (transcribeClient) {
      try {
        transcribeClient.destroy();
      } catch (err) {
        console.error('Error destroying transcribe client:', err);
      }
    }
  });
});

// Start the server
server.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});

// Handle graceful shutdown
process.on('SIGINT', () => {
  console.log('Shutting down...');
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});
