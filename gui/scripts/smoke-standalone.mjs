import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dvbfixer-standalone-smoke-'))
// This checks the Node host, not scientific execution; CI builds it without the
// scientific environment. Supply an explicit version-only CLI test double.
const cliStub = path.join(dataRoot, 'cli-version.cjs')
fs.writeFileSync(cliStub, 'if (process.argv[2] !== "--version") process.exit(1); console.log("dvbfixer 0.0.0 (host smoke stub)")\n')
const child = spawn(process.execPath, ['--enable-source-maps', 'dist-server/server.js'], {
  cwd: path.resolve(import.meta.dirname, '..'),
  env: {
    ...process.env,
    DVBFIXER_HOST: '127.0.0.1',
    DVBFIXER_PORT: '0',
    DVBFIXER_GUI_DATA_DIR: dataRoot,
    DVBFIXER_EXECUTABLE: process.execPath,
    DVBFIXER_ARGS: JSON.stringify([cliStub]),
  },
  stdio: ['ignore', 'pipe', 'pipe'],
})

let stderr = ''
child.stderr.on('data', chunk => { stderr += String(chunk) })

try {
  const port = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('standalone server did not start')), 10_000)
    child.once('exit', code => reject(new Error(`standalone server exited ${code}: ${stderr}`)))
    child.stdout.on('data', chunk => {
      const match = String(chunk).match(/listening on http:\/\/[^:]+:(\d+)/)
      if (!match) return
      clearTimeout(timeout)
      resolve(Number(match[1]))
    })
  })
  const response = await fetch(`http://127.0.0.1:${port}/api/health`)
  if (!response.ok) throw new Error(`health check returned ${response.status}`)
  child.kill('SIGTERM')
  let shutdownTimer
  const code = await Promise.race([
    new Promise(resolve => child.once('exit', resolve)),
    new Promise((_, reject) => {
      shutdownTimer = setTimeout(() => reject(new Error('standalone shutdown timed out')), 10_000)
    }),
  ]).finally(() => clearTimeout(shutdownTimer))
  if (code !== 0) throw new Error(`standalone server shutdown exited ${code}: ${stderr}`)
  console.log('Standalone server smoke test passed.')
} finally {
  if (child.exitCode === null) child.kill('SIGKILL')
  fs.rmSync(dataRoot, { recursive: true, force: true })
}
