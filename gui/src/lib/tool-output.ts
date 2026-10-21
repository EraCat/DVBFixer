import type { ManagedJobRecord } from './managed-jobs'

export interface ToolReportPreview {
  file: string
  text: string
  truncated: boolean
  error?: string
}

const TEXT_REPORT = /\.(txt|json|md|log|csv|tsv|fasta|fa|faa|pir|aln|dat|top|itp|mdp|ya?ml|toml|xml)$/i
const DIAGNOSTIC_REPORT = /(?:^|[/. _-])diagnose\.(json|txt|md)$/i

export function toolReportFiles(job: ManagedJobRecord): string[] {
  const primary = job.outputFile && TEXT_REPORT.test(job.outputFile) ? [job.outputFile] : []
  const diagnostics = (job.provenance?.outputs || []).map(output => output.file)
    .filter(file => DIAGNOSTIC_REPORT.test(file))
  return [...new Set([...primary, ...diagnostics])].slice(0, 3)
}

/** Read only a small preview; never download a large topology/report just to summarize it. */
async function readPreview(response: Response, maxBytes = 24 * 1024): Promise<{ text: string; truncated: boolean }> {
  if (!response.body) return { text: '', truncated: false }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let text = ''
  let remaining = maxBytes
  let truncated = false
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      const kept = value.subarray(0, remaining)
      text += decoder.decode(kept, { stream: true })
      remaining -= kept.length
      if (value.length > kept.length || !remaining) {
        truncated = true
        await reader.cancel()
        break
      }
    }
    if (!truncated) text += decoder.decode()
  } finally { reader.releaseLock() }
  // JSON formatting is presentation only; do not reinterpret diagnostic findings.
  if (!truncated && (text.trimStart().startsWith('{') || text.trimStart().startsWith('['))) {
    try { text = JSON.stringify(JSON.parse(text), null, 2) } catch { /* retain original text */ }
  }
  const lines = text.split('\n')
  return { text: lines.slice(0, 45).join('\n'), truncated: truncated || lines.length > 45 }
}

export async function loadToolReports(
  job: ManagedJobRecord,
  fetchFile: (file: string) => Promise<Response>,
): Promise<ToolReportPreview[]> {
  return Promise.all(toolReportFiles(job).map(async file => {
    try {
      const response = await fetchFile(file)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return { file, ...await readPreview(response) }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error
      return { file, text: '', truncated: false, error: error instanceof Error ? error.message : String(error) }
    }
  }))
}
