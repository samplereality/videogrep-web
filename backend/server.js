const express = require('express');
const path = require('path');
const cors = require('cors');
const routes = require('./routes/routes');

const app = express();
const PORT = process.env.PORT || 3000;


app.use(cors());
app.use(express.json());
// app.use('/videos', express.static(path.join(__dirname, 'backend')));
app.use('/videos', express.static(path.join(__dirname, 'controllers', 'exports')));

// routes
routes(app);

// static files from react
const frontendBuildPath = path.join(__dirname, '../frontend/build');
console.log('Frontend build path:', frontendBuildPath);
app.use(express.static(frontendBuildPath));

// catch-all route
app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, '../frontend/build/index.html'));
});

const server = app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`Error: Port ${PORT} is already in use.`);
    console.error('This is common on macOS where AirPlay Receiver uses port 5000.');
    console.error(`To fix this, either:`);
    console.error(`  1. Set a different port: PORT=3001 npm start`);
    console.error(`  2. Stop the process using port ${PORT}`);
    process.exit(1);
  }
  throw err;
});
