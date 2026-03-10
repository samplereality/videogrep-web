const { spawn, execSync } = require('child_process');

function getPythonCommand() {
    for (const cmd of ['python3', 'python']) {
        try {
            execSync(`${cmd} --version`, { stdio: 'ignore' });
            return cmd;
        } catch (e) {
            continue;
        }
    }
    return 'python3';
}

const pythonCmd = getPythonCommand();

function runPythonProcess(pythonScript, options = {}, onLog = null) {
    return new Promise((resolve, reject) => {
        const process = spawn(pythonCmd, ['-c', pythonScript], options);
        let resultData = '';
        let errorOutput = '';

        process.stdout.on('data', (data) => {
            resultData += data.toString();
            console.log("PYTHON STDOUT:", data.toString())
            if (onLog) onLog(data.toString(), 'stdout');
        });

        process.stderr.on('data', (data) => {
            errorOutput += data.toString();
            console.log("PYTHON STDERR:", data.toString());
            if (onLog) onLog(data.toString(), 'stderr');
        });

        process.on('close', (code) => {
            if (code === 0) {
                try {
                    resolve({ result: resultData, error: errorOutput });
                } catch (error) {
                    reject({ error: 'Process failed', details: error });
                }
            } else {
                reject({ error: 'Process failed', code, details: errorOutput });
            }
        });

        process.on('error', (err) => {
            reject({ error: 'Failed to start process', details: err.message });
        });
    });
}

module.exports = { runPythonProcess };