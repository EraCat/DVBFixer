import { describe, expect, it } from 'vitest'
import viteConfig from '../vite.config'
import { apiPlugin } from './api-plugin'

describe('Vite test isolation', () => {
  it.each(['test', 'development', 'production'])('selects API plugins safely in %s mode', async mode => {
    const config = await viteConfig({ mode, command: 'serve', isPreview: false, isSsrBuild: false })
    const names = config.plugins?.flat().flatMap(plugin =>
      plugin && typeof plugin === 'object' && 'name' in plugin ? [plugin.name] : [])
    if (mode === 'test') expect(names).not.toContain(apiPlugin().name)
    else expect(names).toContain(apiPlugin().name)
    expect(config.server?.open).toBe(mode !== 'test' && !process.env.CI)
  })
})
