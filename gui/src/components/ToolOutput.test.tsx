import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ToolOutput } from './ToolOutput'

describe('tool output presentation', () => {
  it('shows diagnostic stderr as neutral, scrollable report content', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="Prepared structure" stderr="Diagnose: 0 errors, 2 warnings" />)
    expect(markup).toContain('Output &amp; diagnostics')
    expect(markup).toContain('Diagnose: 0 errors, 2 warnings')
    expect(markup).toContain('Diagnostics &amp; messages (stderr)')
    expect(markup).toContain('aria-label="Tool output and diagnostics"')
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
    expect(renderToStaticMarkup(<ToolOutput stdout="" stderr="" />)).toContain('This run produced no console output or report file.')
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

  it('places diagnostics before the report and separates sections visibly', () => {
    const markup = renderToStaticMarkup(<ToolOutput stdout="Saved file" stderr="Diagnostic messages"
      reports={[{ file: 'diagnose.txt', text: 'Report body', truncated: false }]} />)
    const diagnostics = markup.indexOf('Diagnostics &amp; messages (stderr)')
    const report = markup.indexOf('Report · diagnose.txt')
    expect(diagnostics).toBeGreaterThan(-1)
    expect(report).toBeGreaterThan(diagnostics)
    expect(markup.indexOf('Standard output')).toBeGreaterThan(report)
    expect(markup.slice(diagnostics, report)).toContain('MuiDivider-root')
  })
})
