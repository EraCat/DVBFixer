import { afterEach, describe, expect, it } from 'vitest'
import {
  initializeDvbfixerProcessAdmission,
  getDvbfixerProcessAdmissionSnapshot,
  parseDvbfixerMaxConcurrentProcesses,
  parseDvbfixerMaxQueuedProcesses,
  resetDvbfixerProcessAdmission,
  runDvbfixerArgs,
  shutdownDvbfixerProcesses,
} from './dvbfixer-runner'

const originalEnvironment = {
  executable: process.env.DVBFIXER_EXECUTABLE,
  args: process.env.DVBFIXER_ARGS,
  maxConcurrentProcesses: process.env.DVBFIXER_MAX_CONCURRENT_PROCESSES,
  maxQueuedProcesses: process.env.DVBFIXER_MAX_QUEUED_PROCESSES,
}

afterEach(async () => {
  await shutdownDvbfixerProcesses()
  for (const [key, value] of Object.entries({
    DVBFIXER_EXECUTABLE: originalEnvironment.executable,
    DVBFIXER_ARGS: originalEnvironment.args,
    DVBFIXER_MAX_CONCURRENT_PROCESSES: originalEnvironment.maxConcurrentProcesses,
    DVBFIXER_MAX_QUEUED_PROCESSES: originalEnvironment.maxQueuedProcesses,
  })) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  resetDvbfixerProcessAdmission()
})

function useNode(script: string): void {
  process.env.DVBFIXER_EXECUTABLE = process.execPath
  process.env.DVBFIXER_ARGS = JSON.stringify(['-e', script])
}

function wait(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

describe('DVBfixer runner', () => {
  it('keeps the executable separate from its JSON argument prefix', async () => {
    useNode('console.log(JSON.stringify(process.argv.slice(1)))')
    const result = await runDvbfixerArgs('doctor', ['--format', 'json'])
    expect(result).toMatchObject({ code: 0, started: true })
    expect(JSON.parse(result.stdout.trim())).toEqual(['doctor', '--format', 'json'])
  })

  it('caps captured process output', async () => {
    useNode("process.stdout.write('x'.repeat(4096))")
    const result = await runDvbfixerArgs('doctor', [], process.cwd(), { maxOutputBytes: 128 })
    expect(Buffer.byteLength(result.stdout)).toBeLessThan(180)
    expect(result.stdout).toContain('[output truncated]')
  })

  it('terminates a timed-out process', async () => {
    useNode("process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)")
    const started = Date.now()
    const result = await runDvbfixerArgs(
      'doctor', [], process.cwd(), { timeoutMs: 30, killGraceMs: 30 },
    )
    expect(result).toMatchObject({ started: true, failure: 'timeout' })
    expect(result.code).not.toBe(0)
    expect(result.stderr).toContain('timed out')
    expect(Date.now() - started).toBeLessThan(1_000)
  })

  it('enforces the configured process cap', async () => {
    resetDvbfixerProcessAdmission(2)
    useNode('setTimeout(() => {}, Number(process.argv[1]))')
    const starts: string[] = []
    const runs = ['first', 'second', 'third'].map(name => runDvbfixerArgs(
      '100', [], process.cwd(), { onStart: () => starts.push(name) },
    ))

    await wait(30)
    expect(starts).toEqual(['first', 'second'])
    await Promise.all(runs)
    expect(starts).toEqual(['first', 'second', 'third'])
  })

  it('admits queued runs FIFO and calls onStart only after admission', async () => {
    resetDvbfixerProcessAdmission(1)
    useNode('setTimeout(() => {}, Number(process.argv[1]))')
    const starts: string[] = []
    const first = runDvbfixerArgs('60', [], process.cwd(), { onStart: () => starts.push('first') })
    const second = runDvbfixerArgs('0', [], process.cwd(), { onStart: () => starts.push('second') })
    const third = runDvbfixerArgs('0', [], process.cwd(), { onStart: () => starts.push('third') })

    expect(starts).toEqual(['first'])
    await Promise.all([first, second, third])
    expect(starts).toEqual(['first', 'second', 'third'])
  }, 30_000)

  it('bounds the waiting queue and reports live admission pressure', async () => {
    resetDvbfixerProcessAdmission(1, 2)
    useNode('setTimeout(() => {}, Number(process.argv[1]))')
    const first = runDvbfixerArgs('80', [])
    const second = runDvbfixerArgs('0', [])
    const third = runDvbfixerArgs('0', [])
    await expect(runDvbfixerArgs('0', [])).resolves.toMatchObject({
      code: -1, started: false, failure: 'overloaded', stderr: expect.stringContaining('queue is full'),
    })
    expect(getDvbfixerProcessAdmissionSnapshot()).toEqual({
      active: 1, queued: 2, limit: 1, queueLimit: 2, accepting: true,
    })
    await Promise.all([first, second, third])
    expect(getDvbfixerProcessAdmissionSnapshot()).toMatchObject({ active: 0, queued: 0 })
  }, 15_000)

  it('cancels a queued run without spawning it', async () => {
    resetDvbfixerProcessAdmission(1)
    useNode('setTimeout(() => {}, Number(process.argv[1]))')
    const blocker = runDvbfixerArgs('80', [])
    const controller = new AbortController()
    let started = false
    const queued = runDvbfixerArgs('0', [], process.cwd(), {
      signal: controller.signal,
      onStart: () => { started = true },
    })

    controller.abort()
    await expect(queued).resolves.toEqual({
      code: -1,
      stdout: '',
      stderr: 'DVBfixer run cancelled',
      started: false,
      failure: 'cancelled',
    })
    expect(started).toBe(false)
    await blocker
  })

  it('rejects queued work and terminates active work during shutdown', async () => {
    resetDvbfixerProcessAdmission(1)
    useNode("process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)")
    const running = runDvbfixerArgs(
      'active', [], process.cwd(), { timeoutMs: 10_000, killGraceMs: 30 },
    )
    let queuedStarted = false
    const queued = runDvbfixerArgs('queued', [], process.cwd(), {
      onStart: () => { queuedStarted = true },
    })

    await wait(30)
    await shutdownDvbfixerProcesses()
    const [activeResult, queuedResult] = await Promise.all([running, queued])
    expect(activeResult).toMatchObject({ started: true, failure: 'shutdown' })
    expect(activeResult.stderr).toContain('server shutdown')
    expect(queuedResult).toMatchObject({ code: -1, started: false, failure: 'shutdown' })
    expect(queuedStarted).toBe(false)
    await expect(runDvbfixerArgs('doctor', [])).resolves.toMatchObject({
      code: -1,
      started: false,
      failure: 'shutdown',
      stderr: expect.stringContaining('shutting down'),
    })
  })

  it('releases one permit for every terminal process outcome', async () => {
    resetDvbfixerProcessAdmission(1)
    useNode(`
      const mode = process.argv[1]
      if (mode === 'nonzero') process.exit(7)
      if (mode === 'hang') setInterval(() => {}, 1000)
    `)
    const starts: string[] = []
    const success = runDvbfixerArgs('success', [], process.cwd(), {
      onStart: () => starts.push('success'),
    })
    const nonzero = runDvbfixerArgs('nonzero', [], process.cwd(), {
      onStart: () => starts.push('nonzero'),
    })
    const timeout = runDvbfixerArgs('hang', [], process.cwd(), {
      timeoutMs: 20,
      killGraceMs: 20,
      onStart: () => starts.push('timeout'),
    })
    const controller = new AbortController()
    const aborted = runDvbfixerArgs('hang', [], process.cwd(), {
      signal: controller.signal,
      killGraceMs: 20,
      onStart: () => {
        starts.push('abort')
        controller.abort()
      },
    })
    process.env.DVBFIXER_EXECUTABLE = '/definitely/missing/dvbfixer-test-executable'
    process.env.DVBFIXER_ARGS = '[]'
    const spawnError = runDvbfixerArgs('doctor', [], process.cwd(), {
      onStart: () => starts.push('spawn-error'),
    })
    useNode('process.exit(0)')
    const follower = runDvbfixerArgs('follower', [], process.cwd(), {
      onStart: () => starts.push('follower'),
    })

    const results = await Promise.all([success, nonzero, timeout, aborted, spawnError, follower])
    expect(starts).toEqual(['success', 'nonzero', 'timeout', 'abort', 'spawn-error', 'follower'])
    expect(results.map(result => result.failure)).toEqual([
      undefined, 'nonzero-exit', 'timeout', 'cancelled', 'spawn-error', undefined,
    ])
    expect(results.at(-1)).toMatchObject({ code: 0, started: true })
    expect(results[4].stderr).toContain('DVBFIXER_EXECUTABLE')
    expect(results[4].stderr).toContain('Activate the dvbfixer environment')
  }, 15_000)

  it('strictly validates and initializes the concurrency configuration', async () => {
    expect(parseDvbfixerMaxConcurrentProcesses(undefined)).toBe(1)
    expect(parseDvbfixerMaxConcurrentProcesses('64')).toBe(64)
    expect(parseDvbfixerMaxQueuedProcesses(undefined)).toBe(16)
    expect(parseDvbfixerMaxQueuedProcesses('256')).toBe(256)
    for (const value of ['', '0', '-1', '1.5', ' 2', '2 ', '+2', '65', '9007199254740992']) {
      expect(() => parseDvbfixerMaxConcurrentProcesses(value)).toThrow(
        'DVBFIXER_MAX_CONCURRENT_PROCESSES',
      )
    }
    for (const value of ['', '0', '-1', '1.5', ' 2', '2 ', '+2', '257', '9007199254740992']) {
      expect(() => parseDvbfixerMaxQueuedProcesses(value)).toThrow('DVBFIXER_MAX_QUEUED_PROCESSES')
    }

    initializeDvbfixerProcessAdmission('2', '3')
    expect(getDvbfixerProcessAdmissionSnapshot()).toMatchObject({ limit: 2, queueLimit: 3 })
    useNode('setTimeout(() => {}, 50)')
    const running = runDvbfixerArgs('doctor', [])
    expect(() => resetDvbfixerProcessAdmission(1)).toThrow('until all work is drained')
    await running
    resetDvbfixerProcessAdmission(1)
  })
})
