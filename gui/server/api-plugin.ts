import type { Plugin } from 'vite'
import { registerApiRoutes, shutdownApiWork } from './api-routes'
import { parseAuthConfig, resolveLegacyWorkspaceOwner } from './auth'
import { parseCorsAllowedOrigins } from './cors'
import {
  parseDvbfixerMaxConcurrentProcesses, parseDvbfixerMaxQueuedProcesses,
} from './dvbfixer-runner'
import { parseStorageQuotaSettings } from './storage-quota'
import { parseRateLimitConfig } from './rate-limit'
import { parseAccessLogConfig } from './request-observability'
import { parseMetricsConfig } from './metrics'
import { assertDvbfixerAvailable } from './cli-preflight'

export { runDvbfixer } from './dvbfixer-runner'
export { buildArgs } from './command-args'

const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost'])

export function apiPlugin(environment: NodeJS.ProcessEnv = process.env): Plugin {
  return {
    name: 'tarantino-api',
    configureServer(server) {
      assertDvbfixerAvailable(environment)
      const authConfig = parseAuthConfig(environment)
      const corsAllowedOrigins = parseCorsAllowedOrigins(environment)
      const storageQuota = parseStorageQuotaSettings(environment)
      const rateLimit = parseRateLimitConfig(environment)
      const accessLog = parseAccessLogConfig(environment)
      const metrics = parseMetricsConfig(environment)
      const maxConcurrentProcesses = parseDvbfixerMaxConcurrentProcesses(
        environment.DVBFIXER_MAX_CONCURRENT_PROCESSES,
      )
      const maxQueuedProcesses = parseDvbfixerMaxQueuedProcesses(
        environment.DVBFIXER_MAX_QUEUED_PROCESSES,
      )
      const configuredHost = server.config.server?.host
      const remotelyBound = configuredHost === true ||
        (typeof configuredHost === 'string' && !LOOPBACK_HOSTS.has(configuredHost))
      if (remotelyBound && (!authConfig.enabled || environment.DVBFIXER_ALLOW_INSECURE_REMOTE !== '1')) {
        throw new Error(
          'remote Vite API hosting requires DVBFIXER_AUTH_PRINCIPALS and DVBFIXER_ALLOW_INSECURE_REMOTE=1',
        )
      }
      registerApiRoutes(server, {
        projectRoot: server.config.root,
        authConfig,
        legacyWorkspaceOwner: resolveLegacyWorkspaceOwner(authConfig, environment),
        corsAllowedOrigins,
        storageQuota,
        maxConcurrentProcesses,
        maxQueuedProcesses,
        rateLimit,
        accessLog,
        metrics,
      })
    },
    closeBundle: () => shutdownApiWork(),
  }
}
