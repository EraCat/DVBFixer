import { describe, expect, it, vi } from 'vitest'
import { loadToolReports, toolReportFiles } from './tool-output'
import type { ManagedJobRecord } from './managed-jobs'

function job(patch: Partial<ManagedJobRecord> = {}): ManagedJobRecord {
  return {
    version: 1, id: 'job-a', workspaceId: 'workspace-a', command: 'diagnose', args: [],
    status: 'succeeded', createdAt: '', startedAt: '', finishedAt: '', exitCode: 0,
    stdoutLog: 'runs/job_a/stdout.log', stderrLog: 'runs/job_a/stderr.log',
    outputDir: 'runs/job_a', outputFile: 'runs/job_a/input_diagnose.txt', ...patch,
  }
}

describe('tool report previews', () => {
  it('reads the report file independently of empty stdout/stderr', async () => {
    const fetchFile = vi.fn(async () => new Response('Diagnose report\nSummary: 0 errors, 2 warnings'))
    const reports = await loadToolReports(job(), fetchFile)
    expect(fetchFile).toHaveBeenCalledExactlyOnceWith('runs/job_a/input_diagnose.txt')
    expect(reports).toEqual([{
      file: 'runs/job_a/input_diagnose.txt', text: 'Diagnose report\nSummary: 0 errors, 2 warnings', truncated: false,
    }])
  })

  it('formats JSON without changing the diagnostic values or Unicode', async () => {
    const reports = await loadToolReports(job({ outputFile: 'diagnose.json' }), async () => new Response('{"distance":"2 Å","warnings":3}'))
    expect(reports[0].text).toBe('{\n  "distance": "2 Å",\n  "warnings": 3\n}')
  })

  it('finds postflight diagnose reports without downloading the primary structure', () => {
    const files = toolReportFiles(job({
      command: 'zbs', outputFile: 'runs/job_a/prepared.pdb',
      provenance: { outputs: [
        { artifactId: 'pdb', file: 'runs/job_a/prepared.pdb', sha256: '' },
        { artifactId: 'report', file: 'runs/job_a/prepared.diagnose.json', sha256: '' },
      ] },
    }))
    expect(files).toEqual(['runs/job_a/prepared.diagnose.json'])
  })

  it('shortens long reports and stops reading after the byte limit', async () => {
    const cancel = vi.fn()
    const stream = new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('x'.repeat(100_000))) },
      cancel,
    })
    const reports = await loadToolReports(job(), async () => new Response(stream))
    expect(reports[0].text.length).toBe(24 * 1024)
    expect(reports[0].truncated).toBe(true)
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('limits the number of visible lines', async () => {
    const reports = await loadToolReports(job(), async () => new Response(Array.from({ length: 100 }, (_, n) => `Line ${n}`).join('\n')))
    expect(reports[0].text.split('\n')).toHaveLength(45)
    expect(reports[0].truncated).toBe(true)
  })

  it('returns a visible preview failure instead of silently hiding the report', async () => {
    const reports = await loadToolReports(job(), async () => new Response('', { status: 404 }))
    expect(reports[0]).toMatchObject({ file: 'runs/job_a/input_diagnose.txt', error: 'HTTP 404' })
  })

  it('propagates cancellation so a superseded workspace cannot publish a preview', async () => {
    await expect(loadToolReports(job(), async () => { throw new DOMException('Cancelled', 'AbortError') }))
      .rejects.toMatchObject({ name: 'AbortError' })
  })

  it('does not request a binary output', async () => {
    const fetchFile = vi.fn()
    expect(await loadToolReports(job({ outputFile: 'figure.png' }), fetchFile)).toEqual([])
    expect(fetchFile).not.toHaveBeenCalled()
  })
})
