import { spawnSync } from 'node:child_process'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assertDvbfixerAvailable } from './cli-preflight'

vi.mock('node:child_process', () => ({ spawn: vi.fn(), spawnSync: vi.fn() }))

describe('GUI CLI startup prerequisite', () => {
  beforeEach(() => {
    vi.mocked(spawnSync).mockReset()
    vi.mocked(spawnSync).mockReturnValue({
      pid: 1, output: [], stdout: 'dvbfixer 0.9.1\n', stderr: '', status: 0, signal: null,
    })
  })

  it('checks the CLI version with no scientific work or shell', () => {
    const environment = { PATH: '/active-environment/bin' }
    expect(assertDvbfixerAvailable(environment)).toBe('dvbfixer 0.9.1')
    expect(spawnSync).toHaveBeenCalledWith('dvbfixer', ['--version'], {
      env: environment, encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024,
    })
  })

  it('honors an explicit launcher and JSON argument prefix', () => {
    assertDvbfixerAvailable({ DVBFIXER_EXECUTABLE: '/custom/python', DVBFIXER_ARGS: '["/custom/cli.py"]' })
    expect(spawnSync).toHaveBeenCalledWith('/custom/python', ['/custom/cli.py', '--version'], expect.any(Object))
  })

  it('stops startup with activation instructions if the CLI is missing', () => {
    vi.mocked(spawnSync).mockReturnValue({
      pid: 0, output: [], stdout: '', stderr: '', status: null, signal: null,
      error: Object.assign(new Error('spawn dvbfixer ENOENT'), { code: 'ENOENT' }),
    })
    expect(() => assertDvbfixerAvailable({})).toThrow('micromamba activate dvbfixer')
  })

  it('rejects an unusable installation', () => {
    vi.mocked(spawnSync).mockReturnValue({
      pid: 1, output: [], stdout: '', stderr: 'No module named dvbfixer', status: 1, signal: null,
    })
    expect(() => assertDvbfixerAvailable({})).toThrow('No module named dvbfixer')
  })

  it('rejects an unrelated executable even if it exits successfully', () => {
    vi.mocked(spawnSync).mockReturnValue({
      pid: 1, output: [], stdout: 'v24.9.0', stderr: '', status: 0, signal: null,
    })
    expect(() => assertDvbfixerAvailable({})).toThrow('did not return a dvbfixer version')
  })

  it('rejects malformed prefix configuration before running anything', () => {
    expect(() => assertDvbfixerAvailable({ DVBFIXER_ARGS: 'not-json' })).toThrow('DVBFIXER_ARGS')
    expect(spawnSync).not.toHaveBeenCalled()
  })
})
