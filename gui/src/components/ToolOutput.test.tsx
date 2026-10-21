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

  it('renders nothing for an empty report', () => {
    expect(renderToStaticMarkup(<ToolOutput stdout="" stderr="" />)).toBe('')
  })
})
