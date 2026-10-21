import { describe, expect, it } from 'vitest'
import { createManagedJobRequest, isActiveManagedJob, managedJobStatusLabel, mergeManagedJobHistory, outputMatchesManagedJob, selectRestoredManagedJob, selectToolManagedJob, type ManagedJobRecord } from './managed-jobs'

function job(status: ManagedJobRecord['status'], id: string = status): ManagedJobRecord {
  return {
    version: 1, id, workspaceId: 'workspace', status,
    createdAt: '2026-01-01T00:00:00Z', startedAt: null, finishedAt: null,
    command: 'prepare', args: [], exitCode: status === 'failed' ? 2 : null,
    stdoutLog: 'runs/stdout.log', stderrLog: 'runs/stderr.log',
    outputDir: 'runs/job', outputFile: status === 'succeeded' ? 'runs/job/out.pdb' : null,
  }
}

describe('managed job UI helpers', () => {
  it('includes the selected command in the managed-job request', () => {
    expect(createManagedJobRequest('prepare', {
      workspaceId: 'workspace-1', inputFile: 'input.pdb', inputs: {},
      values: {}, fastaContent: '',
    })).toMatchObject({ command: 'prepare', workspaceId: 'workspace-1' })
  })

  it('restores an active job ahead of a newer terminal record', () => {
    expect(selectRestoredManagedJob([job('succeeded'), job('running')])?.status).toBe('running')
    expect(selectRestoredManagedJob([])).toBeNull()
  })

  it('identifies only queued and running records as active', () => {
    expect(isActiveManagedJob(job('queued'))).toBe(true)
    expect(isActiveManagedJob(job('running'))).toBe(true)
    expect(isActiveManagedJob(job('cancelled'))).toBe(false)
  })

  it('formats concise terminal status', () => {
    expect(managedJobStatusLabel(job('succeeded'))).toContain('out.pdb')
    expect(managedJobStatusLabel(job('failed'))).toContain('exit 2')
  })

  it('restores the latest run of the selected tool, not the latest workspace run', () => {
    const diagnose = { ...job('succeeded', 'diagnose-old'), command: 'diagnose' }
    const cluster = { ...job('succeeded', 'cluster-new'), command: 'cluster', createdAt: '2026-02-01T00:00:00Z' }
    const newerDiagnose = { ...diagnose, id: 'diagnose-new', createdAt: '2026-03-01T00:00:00Z' }
    const jobs = [diagnose, cluster, newerDiagnose]
    expect(selectToolManagedJob(jobs, 'workspace', 'diagnose')?.id).toBe('diagnose-new')
    expect(selectToolManagedJob(jobs, 'workspace', 'cluster')?.id).toBe('cluster-new')
    expect(selectToolManagedJob(jobs, 'workspace', 'prepare')).toBeNull()
    expect(selectToolManagedJob(jobs, 'different-workspace', 'diagnose')).toBeNull()
  })

  it('keeps previous tool runs when a new run updates the tracked job', () => {
    const diagnose = { ...job('succeeded', 'diagnose'), command: 'diagnose' }
    const running = job('running', 'prepare')
    const completed = { ...running, status: 'succeeded' as const }
    const history = mergeManagedJobHistory(mergeManagedJobHistory([diagnose], running), completed)
    expect(history).toHaveLength(2)
    expect(selectToolManagedJob(history, 'workspace', 'diagnose')).toBe(diagnose)
    expect(selectToolManagedJob(history, 'workspace', 'prepare')?.status).toBe('succeeded')
  })

  it('never displays stale output while a tool or workspace selection is changing', () => {
    const selected = { ...job('succeeded', 'diagnose'), command: 'diagnose' }
    expect(outputMatchesManagedJob({ jobId: 'diagnose', workspaceId: 'workspace' }, selected, 'workspace')).toBe(true)
    expect(outputMatchesManagedJob({ jobId: 'cluster', workspaceId: 'workspace' }, selected, 'workspace')).toBe(false)
    expect(outputMatchesManagedJob({ jobId: 'diagnose', workspaceId: 'other' }, selected, 'workspace')).toBe(false)
    expect(outputMatchesManagedJob({ jobId: 'diagnose', workspaceId: 'workspace' }, selected, 'other')).toBe(false)
    expect(outputMatchesManagedJob({ jobId: 'diagnose', workspaceId: 'workspace' }, null, 'workspace')).toBe(false)
  })
})
