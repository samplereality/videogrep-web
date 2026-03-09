const path = require('path');
const fs = require('fs');
const { upload, srtUpload } = require('../middleware/middleware');
const videoController = require('../controllers/videoController');
const clients = new Set();

function parseSRT(srtContent) {
    const segments = [];
    const blocks = srtContent.trim().replace(/\r\n/g, '\n').split(/\n\n+/);

    for (const block of blocks) {
        const lines = block.split('\n');
        if (lines.length < 3) continue;

        const timeMatch = lines[1].match(
            /(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})/
        );
        if (!timeMatch) continue;

        const start = parseInt(timeMatch[1]) * 3600 + parseInt(timeMatch[2]) * 60 +
                       parseInt(timeMatch[3]) + parseInt(timeMatch[4]) / 1000;
        const end = parseInt(timeMatch[5]) * 3600 + parseInt(timeMatch[6]) * 60 +
                     parseInt(timeMatch[7]) + parseInt(timeMatch[8]) / 1000;
        const text = lines.slice(2).join(' ').replace(/<[^>]+>/g, '').trim();

        if (text) {
            segments.push({ start, end, text });
        }
    }

    return segments;
}

function sendLogToClients(log, type) {
    console.log("SENDING TO CLIENTS:", { log, type });
    clients.forEach(client => {
        client.res.write(`data: ${JSON.stringify({log, type})}\n\n`);
    });
}


module.exports = function(app) {
    app.get('/logs', (req, res) => {
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');

        const client = { id: Date.now(), res };
        clients.add(client);

        req.on('close', () => {
            clients.delete(client);
        });
    });

    app.post('/upload', upload.array('videos'), (req, res) => {
        const files = req.files.map(file => file.path);
        res.json({ files });
    });

    app.post('/transcribe', async (req, res) => {
        try {
            const transcripts = await videoController.handleTranscribe(
            req.body.files, 
                (log, type) => sendLogToClients(log, type)
            );
            res.json(transcripts);
        } catch (error) {
            res.status(500).json({ error: 'Transcription failed', details: error });
        }
    });

    app.post('/search', async (req, res) => {
        try {
            const { files, query, searchType } = req.body;
            const results = await videoController.handleSearch(files, query, searchType);
            res.json(results);
        } catch (error) {
            res.status(500).json({ error: 'Search failed', details: error });
        }
    });

    app.post('/ngrams', async (req, res) => {
        try {
            const { files, n } = req.body;
            const results = await videoController.handleNgrams(files, n);
            res.json(results);
        } catch (error) {
            res.status(500).json({ error: 'Ngrams failed', details: error });
        }
    });

    app.post('/export', async (req, res) => {
        try {
            const { files, query, searchType, padding, resync } = req.body;
            
            if (!files?.length) {
                return res.status(400).json({ success: false, message: 'No files provided' });
            }
            if (!query) {
                return res.status(400).json({ success: false, message: 'No search query provided' });
            }

            const filename = await videoController.handleExport(
                req.body.files,
                req.body.query,
                req.body.searchType,
                req.body.padding,
                req.body.resync,
                (log, type) => sendLogToClients(log, type)
            );
            
            
            res.json({ success: true, output: filename, message: 'Supercut created successfully' });
        } catch (error) {
            res.status(500).json({ success: false, message: 'Export failed', error });
        }
    });

    app.post('/import-srt', srtUpload.single('srt'), (req, res) => {
        try {
            const videoFile = req.body.videoFile;
            if (!videoFile) {
                return res.status(400).json({ error: 'No video file path specified' });
            }
            if (!req.file) {
                return res.status(400).json({ error: 'No SRT file uploaded' });
            }

            const srtContent = fs.readFileSync(req.file.path, 'utf-8');
            const segments = parseSRT(srtContent);
            const transcriptData = segments.map(seg => ({
                content: seg.text,
                start: seg.start,
                end: seg.end
            }));

            // Save as .json next to the video so videogrep can find it
            const jsonPath = videoFile.replace(/\.[^.]+$/, '.json');
            fs.writeFileSync(jsonPath, JSON.stringify(transcriptData, null, 2));

            // Clean up the uploaded SRT file
            fs.unlinkSync(req.file.path);

            // Return in the same format as the transcribe endpoint
            const result = {};
            result[videoFile] = transcriptData;
            res.json(result);
        } catch (error) {
            console.error('SRT import failed:', error);
            res.status(500).json({ error: 'SRT import failed', details: error.message });
        }
    });

    app.get('/test-video', (req, res) => {
        const { filename } = req.query;
        if (!filename) {
            return res.status(400).send('Filename is required');
        }
        // const videoPath = path.join(__dirname, 'exports', filename);
        const videoPath = path.join(__dirname, '..', 'controllers', 'exports', filename);
        if (fs.existsSync(videoPath)) {
            res.sendFile(videoPath);
        } else {
            res.status(404).send('Video not found');
        }
    });
};