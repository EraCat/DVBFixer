import { expect, it } from 'vitest'
import { workflowValues } from './workflow-backend-options'

it('removes inactive Modeller defaults when selecting diffusion', () => {
  expect(workflowValues('model', { '--backend': 'diffusion', '--md-level': 'fast', '--num-loops': 2, '--diffusion-seed': '7,11' }))
    .toEqual({ '--backend': 'diffusion', '--diffusion-seed': '7,11' })
})

it('keeps ZBS prepare backend separate from its model backend', () => {
  expect(workflowValues('zbs', { '--model-backend': 'diffusion', '--backend': 'legacy', '--num-output': 1, '--diffusion-model': 'protenix' }))
    .toEqual({ '--model-backend': 'diffusion', '--backend': 'legacy', '--diffusion-model': 'protenix' })
})
