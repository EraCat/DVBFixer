import { expect, it } from 'vitest'
import { buildArgs } from './command-args'

it('encodes multi-seed diffusion options as repeated numeric arguments', () => {
  expect(buildArgs('model', { '--backend': 'diffusion', '--diffusion-seed': [7, 11] }))
    .toEqual(['--backend', 'diffusion', '--diffusion-seed', '7', '--diffusion-seed', '11'])
  expect(buildArgs('model', { '--diffusion-seed': '7,11' }))
    .toEqual(['--diffusion-seed', '7', '--diffusion-seed', '11'])
})
