import http, { type Server } from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import type { AddressInfo } from 'node:net'
import connect, { type NextFunction } from 'connect'
import serveStatic from 'serve-static'
import { registerApiRoutes, resetApiShutdown, shutdownApiWork } from './api-routes'
import type { ApiRouteHost } from './http-types'
import { parseAuthConfig, resolveLegacyWorkspaceOwner, type AuthConfig } from './auth'
import { parseCorsAllowedOrigins } from './cors'
import { parseDvbfixerMaxConcurrentProcesses, parseDvbfixerMaxQueuedProcesses } from './dvbfixer-runner'
import { parseStorageQuotaSettings, type StorageQuotaSettings } from './storage-quota'
import { parseRateLimitConfig, type RateLimitConfig } from './rate-limit'
import {
  assertDeploymentResources, parseDeploymentResourceSettings, type DeploymentResourceSettings,
} from './deployment-limits'
import { parseAccessLogConfig, type AccessLogConfig } from './request-observability'
import { parseMetricsConfig, type MetricsConfig } from './metrics'
import { parseAuditLogConfig, type AuditLogConfig } from './audit-log'
import { assertDvbfixerAvailable } from './cli-preflight'

export interface StandaloneConfig {
  host: string
  port: number
  projectRoot: string
  dataRoot: string
  staticRoot: string
  shutdownGraceMs: number
  authConfig: AuthConfig
  legacyWorkspaceOwner: string
  corsAllowedOrigins: readonly string[]
  storageQuota: StorageQuotaSettings
  maxConcurrentProcesses: number
  maxQueuedProcesses: number
  rateLimit: RateLimitConfig
  deploymentResources: DeploymentResourceSettings
  accessLog: AccessLogConfig
  metrics: MetricsConfig
  auditLog: AuditLogConfig
}

const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost'])

function normalizedRequestHost(value: string | undefined): string | null {
  if (!value) return null
  try {
    return new URL(`http://${value}`).hostname
      .replace(/^\[|\]$/g, '')
      .replace(/\.$/, '')
      .toLowerCase()
  } catch {
    return null
  }
}

function integerSetting(name: string, value: string | undefined, fallback: number, minimum: number): number {
  const parsed = value === undefined ? fallback : Number(value)
  if (!Number.isSafeInteger(parsed) || parsed < minimum) {
    throw new Error(`${name} must be an integer greater than or equal to ${minimum}`)
  }
  return parsed
}

function resolveSetting(root: string, value: string | undefined, fallback: string): string {
  const selected = value === undefined ? fallback : value.trim()
  if (!selected) throw new Error('server path settings must not be empty')
  return path.resolve(root, selected)
}

export function loadStandaloneConfig(
  environment: NodeJS.ProcessEnv = process.env,
  defaultProjectRoot = fileURLToPath(new URL('..', import.meta.url)),
): StandaloneConfig {
  const projectRoot = resolveSetting(defaultProjectRoot, environment.DVBFIXER_GUI_ROOT, '.')
  const host = (environment.DVBFIXER_HOST || '127.0.0.1').trim()
  if (!host) throw new Error('DVBFIXER_HOST must not be empty')
  const authConfig = parseAuthConfig(environment)
  if (!LOOPBACK_HOSTS.has(host) && environment.DVBFIXER_ALLOW_INSECURE_REMOTE !== '1') {
    throw new Error('non-loopback DVBFIXER_HOST requires DVBFIXER_ALLOW_INSECURE_REMOTE=1')
  }
  if (!LOOPBACK_HOSTS.has(host) && !authConfig.enabled) {
    throw new Error('non-loopback DVBFIXER_HOST requires DVBFIXER_AUTH_PRINCIPALS')
  }
  const port = integerSetting('DVBFIXER_PORT', environment.DVBFIXER_PORT, 5173, 0)
  if (port > 65535) throw new Error('DVBFIXER_PORT must be at most 65535')
  const dataRoot = resolveSetting(projectRoot, environment.DVBFIXER_GUI_DATA_DIR, 'structures')
  return {
    host,
    port,
    projectRoot,
    dataRoot,
    staticRoot: resolveSetting(projectRoot, environment.DVBFIXER_STATIC_DIR, 'dist'),
    shutdownGraceMs: integerSetting(
      'DVBFIXER_SHUTDOWN_GRACE_MS', environment.DVBFIXER_SHUTDOWN_GRACE_MS, 10_000, 1,
    ),
    authConfig,
    legacyWorkspaceOwner: resolveLegacyWorkspaceOwner(authConfig, environment),
    corsAllowedOrigins: parseCorsAllowedOrigins(environment),
    storageQuota: parseStorageQuotaSettings(environment),
    maxConcurrentProcesses: parseDvbfixerMaxConcurrentProcesses(
      environment.DVBFIXER_MAX_CONCURRENT_PROCESSES,
    ),
    maxQueuedProcesses: parseDvbfixerMaxQueuedProcesses(environment.DVBFIXER_MAX_QUEUED_PROCESSES),
    rateLimit: parseRateLimitConfig(environment),
    deploymentResources: parseDeploymentResourceSettings(environment),
    accessLog: parseAccessLogConfig(environment),
    metrics: parseMetricsConfig(environment),
    auditLog: parseAuditLogConfig(environment),
  }
}

function jsonNotFound(response: http.ServerResponse): void {
  response.statusCode = 404
  response.setHeader('Content-Type', 'application/json')
  response.setHeader('Cache-Control', 'no-store')
  response.end(JSON.stringify({ error: 'not found' }))
}

function pathsOverlap(left: string, right: string): boolean {
  const relative = path.relative(left, right)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

function assertSeparatedRoots(staticRoot: string, dataRoot: string): void {
  if (pathsOverlap(staticRoot, dataRoot) || pathsOverlap(dataRoot, staticRoot)) {
    throw new Error('DVBFIXER_STATIC_DIR and DVBFIXER_GUI_DATA_DIR must not overlap')
  }
  if (fs.existsSync(staticRoot)) {
    const realStatic = canonicalFuturePath(staticRoot)
    const realData = canonicalFuturePath(dataRoot)
    if (pathsOverlap(realStatic, realData) || pathsOverlap(realData, realStatic)) {
      throw new Error('static and workspace data directories must not overlap through symlinks')
    }
  }
}

function canonicalFuturePath(candidate: string): string {
  const missing: string[] = []
  let existing = candidate
  while (!fs.existsSync(existing)) {
    const parent = path.dirname(existing)
    if (parent === existing) break
    missing.unshift(path.basename(existing))
    existing = parent
  }
  return path.join(fs.realpathSync(existing), ...missing)
}

export function createStandaloneApplication(config: StandaloneConfig): connect.Server {
  assertSeparatedRoots(config.staticRoot, config.dataRoot)
  assertDeploymentResources(config.dataRoot, config.deploymentResources)
  const indexFile = path.join(config.staticRoot, 'index.html')
  if (!fs.existsSync(indexFile) || !fs.statSync(indexFile).isFile()) {
    throw new Error(`static client is missing: ${indexFile}; run npm run build:client`)
  }
  const application = connect()
  if (LOOPBACK_HOSTS.has(config.host)) {
    application.use((request, response, next) => {
      const requestHost = normalizedRequestHost(request.headers.host)
      if (requestHost && LOOPBACK_HOSTS.has(requestHost)) return next()
      response.statusCode = 403
      response.setHeader('Content-Type', 'application/json')
      response.setHeader('Cache-Control', 'no-store')
      response.end(JSON.stringify({ error: 'invalid host header' }))
    })
  }
  const host: ApiRouteHost = {
    middlewares: {
      use(mount, middleware) {
        application.use(mount, (request, response, next) => {
          try {
            Promise.resolve(middleware(request, response, next)).catch(next)
          } catch (error) {
            next(error)
          }
        })
      },
    },
  }
  registerApiRoutes(host, {
    projectRoot: config.projectRoot,
    dataRoot: config.dataRoot,
    authConfig: config.authConfig,
    legacyWorkspaceOwner: config.legacyWorkspaceOwner,
    corsAllowedOrigins: config.corsAllowedOrigins,
    storageQuota: config.storageQuota,
    maxConcurrentProcesses: config.maxConcurrentProcesses,
    maxQueuedProcesses: config.maxQueuedProcesses,
    rateLimit: config.rateLimit,
    accessLog: config.accessLog,
    metrics: config.metrics,
    auditLog: config.auditLog,
  })
  application.use('/api', (_request, response) => jsonNotFound(response))
  application.use(serveStatic(config.staticRoot, {
    index: false,
    setHeaders(response, file) {
      if (path.basename(file) === 'index.html') response.setHeader('Cache-Control', 'no-cache')
      else if (file.startsWith(path.join(config.staticRoot, 'assets') + path.sep)) {
        response.setHeader('Cache-Control', 'public, max-age=31536000, immutable')
      }
    },
  }))
  application.use((request, response) => {
    const method = request.method || 'GET'
    const acceptsHtml = String(request.headers.accept || '').includes('text/html')
    if ((method === 'GET' || method === 'HEAD') && acceptsHtml) {
      response.statusCode = 200
      response.setHeader('Content-Type', 'text/html; charset=utf-8')
      response.setHeader('Cache-Control', 'no-cache')
      if (method === 'HEAD') return response.end()
      return fs.createReadStream(indexFile).pipe(response)
    }
    response.statusCode = 404
    response.end('Not found')
  })
  application.use((
    error: unknown,
    _request: http.IncomingMessage,
    response: http.ServerResponse,
    _next: NextFunction,
  ) => {
    console.error('[server] request failed:', error)
    if (response.headersSent) return response.end()
    response.statusCode = 500
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ error: 'internal server error' }))
  })
  return application
}

export interface StandaloneServer {
  server: Server
  start(): Promise<AddressInfo>
  close(): Promise<void>
}

export function createStandaloneServer(config: StandaloneConfig): StandaloneServer {
  resetApiShutdown()
  const application = createStandaloneApplication(config)
  const server = http.createServer(application)
  let closePromise: Promise<void> | null = null
  return {
    server,
    start: () => new Promise<AddressInfo>((resolve, reject) => {
      const fail = (error: Error) => reject(error)
      server.once('error', fail)
      server.listen(config.port, config.host, () => {
        server.off('error', fail)
        const address = server.address()
        if (!address || typeof address === 'string') return reject(new Error('server has no TCP address'))
        resolve(address)
      })
    }),
    close: () => {
      if (closePromise) return closePromise
      closePromise = (async () => {
        const closed = new Promise<void>((resolve, reject) => {
          if (!server.listening) return resolve()
          server.close(error => error ? reject(error) : resolve())
        })
        const timer = setTimeout(() => server.closeAllConnections(), config.shutdownGraceMs)
        timer.unref()
        try {
          await Promise.all([closed, shutdownApiWork()])
        } finally {
          clearTimeout(timer)
        }
      })()
      return closePromise
    },
  }
}

async function main(): Promise<void> {
  assertDvbfixerAvailable()
  const instance = createStandaloneServer(loadStandaloneConfig())
  const address = await instance.start()
  console.log(`DVBFixer server listening on http://${address.address}:${address.port}`)
  let stopping = false
  const shutdown = async (signal: string) => {
    if (stopping) return
    stopping = true
    console.log(`Received ${signal}; shutting down`)
    try { await instance.close() } catch (error) {
      console.error('[server] shutdown failed:', error)
      process.exitCode = 1
    }
  }
  process.once('SIGINT', () => { void shutdown('SIGINT') })
  process.once('SIGTERM', () => { void shutdown('SIGTERM') })
}

const entry = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : ''
if (import.meta.url === entry) {
  main().catch(error => {
    console.error('[server] startup failed:', error)
    process.exitCode = 1
  })
}
