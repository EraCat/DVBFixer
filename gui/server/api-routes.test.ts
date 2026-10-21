import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { apiPlugin } from './api-plugin'
import { readServiceVersion, registerApiRoutes } from './api-routes'
import type { ApiMiddleware } from './http-types'
import { assertDvbfixerAvailable } from './cli-preflight'

// Route composition is independent of a developer's activated scientific env.
// cli-preflight.test.ts separately verifies the actual probe/error contract.
vi.mock('./cli-preflight', () => ({ assertDvbfixerAvailable: vi.fn() }))
beforeEach(() => { vi.mocked(assertDvbfixerAvailable).mockReset().mockReturnValue('dvbfixer 0.9.0') })

const temporaryDirectories: string[] = []

function temp(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'dvbfixer-api-routes-test-'))
  temporaryDirectories.push(directory)
  fs.writeFileSync(path.join(directory, 'package.json'), JSON.stringify({ version: 'test' }))
  return directory
}

function registrar() {
  const mounts: string[] = []
  const host = {
    middlewares: {
      use: (mount: string, _middleware: ApiMiddleware) => { mounts.push(mount) },
    },
  }
  return { host, mounts }
}

afterEach(() => temporaryDirectories.splice(0).forEach(directory =>
  fs.rmSync(directory, { recursive: true, force: true })))

describe('host-neutral API composition', () => {
  it('registers the complete route surface in stable order', () => {
    const projectRoot = temp()
    const { host, mounts } = registrar()

    registerApiRoutes(host, { projectRoot, dataRoot: path.join(projectRoot, 'data') })

    expect(mounts).toEqual([
      '/api',
      '/api',
      '/api',
      '/api',
      '/api/health',
      '/api/session',
      '/api/workspaces',
      '/api/homology',
      '/api/v1',
      '/api/v1',
      '/api/dvbfixer-spec',
      '/api/v1',
    ])
  })

  it('keeps Vite as a thin adapter over the shared composition', () => {
    const projectRoot = temp()
    const { host, mounts } = registrar()
    const plugin = apiPlugin()

    plugin.configureServer?.({
      config: { root: projectRoot },
      middlewares: host.middlewares,
    } as never)

    expect(mounts).toContain('/api/v1')
    expect(mounts).toContain('/api/workspaces')
    expect(assertDvbfixerAvailable).toHaveBeenCalledOnce()
  })

  it('does not initialize routes when the CLI startup prerequisite fails', () => {
    const projectRoot = temp()
    const { host, mounts } = registrar()
    vi.mocked(assertDvbfixerAvailable).mockImplementation(() => { throw new Error('CLI unavailable') })
    const plugin = apiPlugin({})
    expect(() => plugin.configureServer?.({
      config: { root: projectRoot }, middlewares: host.middlewares,
    } as never)).toThrow('CLI unavailable')
    expect(mounts).toEqual([])
  })

  it('rejects remotely bound Vite API hosting without authentication', () => {
    const projectRoot = temp()
    const { host } = registrar()
    const plugin = apiPlugin({})
    expect(() => plugin.configureServer?.({
      config: { root: projectRoot, server: { host: '0.0.0.0' } },
      middlewares: host.middlewares,
    } as never)).toThrow(/AUTH_PRINCIPALS/)
  })

  it('requires authoritative package version metadata', () => {
    const projectRoot = temp()
    expect(readServiceVersion(projectRoot)).toBe('test')

    fs.writeFileSync(path.join(projectRoot, 'package.json'), JSON.stringify({ version: '' }))
    expect(() => readServiceVersion(projectRoot)).toThrow(/service version/)

    fs.rmSync(path.join(projectRoot, 'package.json'))
    const { host } = registrar()
    expect(() => registerApiRoutes(host, { projectRoot })).toThrow(/service version/)
  })
})
