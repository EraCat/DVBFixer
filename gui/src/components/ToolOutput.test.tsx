import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ToolOutput } from './ToolOutput'

describe('tool output presentation', () => {
  it('shows diagnostic stderr as neutral, scrollable report content', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="Prepared structure" stderr="Diagnose: 0 errors, 2 warnings" />)
    expect(markup).toContain('Output &amp; diagnostics')
    expect(markup).toContain('Diagnose: 0 errors, 2 warnings')
    expect(markup).toContain('Diagnostics &amp; messages (stderr)')
    expect(markup).toContain('aria-label="Run log"')
    expect(markup).toContain('tabindex="0"')
    expect(markup).toContain('overflow:auto')
    expect(markup).not.toContain('#fff5f5')
    expect(markup).not.toContain('role="alert"')
  })

  it('does not hide real error text or interpret log content as HTML', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="" stderr={'ERROR: failed\n<script>alert(1)</script>'} />)
    expect(markup).toContain('ERROR: failed')
    expect(markup).toContain('&lt;script&gt;')
    expect(markup).not.toContain('<script>')
  })

  it('offers full-log navigation only when logs are available', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="Report" stderr="" onOpenLog={vi.fn()} />)
    expect(markup).toContain('Open in Text Files')
    expect(renderToStaticMarkup(<ToolOutput stdout="Report" stderr="" />)).not.toContain('Open in Text Files')
  })

  it('explains an empty run instead of hiding the output block', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="" stderr="" />)
    expect(markup).toContain('This run produced no report file.')
    expect(markup).toContain('This run produced no console output.')
  })

  it('previews an output report even when both process streams are empty', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="" stderr="" onOpenFile={vi.fn()}
      reports={[{ file: 'runs/diagnose/input_diagnose.txt', text: 'Summary: 2 warnings, 0 errors', truncated: true }]} />)
    expect(markup).toContain('Report · input_diagnose.txt')
    expect(markup).toContain('Summary: 2 warnings, 0 errors')
    expect(markup).toContain('Open in Text Files')
    expect(markup).toContain('Preview shortened')
  })

  it('keeps the report link when its preview could not be loaded', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="" stderr="" onOpenFile={vi.fn()}
      reports={[{ file: 'diagnose.json', text: '', truncated: false, error: 'HTTP 404' }]} />)
    expect(markup).toContain('Preview unavailable: HTTP 404')
    expect(markup).toContain('Open in Text Files')
  })

  it('renders the diagnostic report and run log in two independent scroll regions', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="Saved file" stderr="Diagnostic messages"
      reports={[{ file: 'diagnose.txt', text: 'Report body', truncated: false }]} />)
    const report = markup.indexOf('Report · diagnose.txt')
    const diagnostics = markup.indexOf('Diagnostics &amp; messages (stderr)')
    expect(report).toBeGreaterThan(-1)
    expect(diagnostics).toBeGreaterThan(report)
    expect(markup.indexOf('Standard output')).toBeGreaterThan(report)
    expect(markup).toContain('aria-label="Diagnostic report"')
    expect(markup).toContain('aria-label="Run log"')
    expect(markup.match(/role="region"/g)).toHaveLength(2)
    expect(markup.match(/tabindex="0"/g)).toHaveLength(2)
    expect(markup.slice(report, diagnostics)).toContain('aria-label="Run log"')
  })
})
