import { Type, type Static, type TSchema } from '@sinclair/typebox'
import { ManagedJobRecordSchema, ManagedJobRequestSchema } from './managed-jobs-schema'

export const VariantOverrideSchema = Type.Object({
  chainId: Type.String({ minLength: 1, maxLength: 1 }),
  residueNumber: Type.String({ pattern: '^-?\\d+$' }),
  insertionCode: Type.String({ maxLength: 1 }),
  variant: Type.Union([
    Type.Literal('HID'), Type.Literal('HIE'), Type.Literal('HIP'),
    Type.Literal('ASH'), Type.Literal('GLH'), Type.Literal('CYX'),
    Type.Literal('CYM'), Type.Literal('LYN'),
  ]),
}, { additionalProperties: false, $id: 'NamingVariantOverride' })

export const NamingConversionRequestSchema = Type.Object({
  inputArtifactId: Type.String({ minLength: 1 }),
  target: Type.Object({
    forceField: Type.Union([
      Type.Literal('amber'), Type.Literal('amber19sb'), Type.Literal('charmm'),
    ]),
    profile: Type.Union([Type.Literal('gromacs'), Type.Literal('standard')]),
  }, { additionalProperties: false }),
  variantOverrides: Type.Optional(Type.Array(VariantOverrideSchema, { maxItems: 10_000 })),
  outputName: Type.Optional(Type.String({
    minLength: 5, maxLength: 255, pattern: '^[A-Za-z0-9][A-Za-z0-9._ -]*\\.pdb$',
  })),
  dryRun: Type.Optional(Type.Boolean()),
}, { additionalProperties: false, $id: 'NamingConversionRequest' })

const NamingSummarySchema = Type.Object({
  changedAtoms: Type.Integer({ minimum: 0 }),
  changedResidues: Type.Integer({ minimum: 0 }),
  variantChanges: Type.Integer({ minimum: 0 }),
  atomNameChanges: Type.Integer({ minimum: 0 }),
}, { additionalProperties: false })

const NamingChangeSchema = Type.Object({
  model: Type.Integer({ minimum: 1 }),
  chainId: Type.String(),
  residueNumber: Type.String(),
  insertionCode: Type.String(),
  alternateLocation: Type.String(),
  atomSerial: Type.Integer(),
  sourceResidueName: Type.String(),
  targetResidueName: Type.String(),
  sourceAtomName: Type.String(),
  targetAtomName: Type.String(),
  ruleIds: Type.Array(Type.String()),
}, { additionalProperties: false })

const NamingDiagnosticSchema = Type.Object({
  code: Type.String(),
  message: Type.String(),
  residue: Type.Union([
    Type.Object({
      chainId: Type.String(), residueNumber: Type.String(), insertionCode: Type.String(),
    }, { additionalProperties: false }),
    Type.Null(),
  ]),
}, { additionalProperties: false })

const NamingResultSchema = Type.Object({
  model: Type.Integer({ minimum: 1 }),
  summary: NamingSummarySchema,
  changes: Type.Array(NamingChangeSchema),
  diagnostics: Type.Array(NamingDiagnosticSchema),
}, { additionalProperties: false })

export const NamingCliReportSchema = Type.Object({
  schemaVersion: Type.Literal(1),
  operation: Type.Literal('pdb-force-field-naming'),
  status: Type.Union([Type.Literal('success'), Type.Literal('error')]),
  tool: Type.Object({ name: Type.Literal('dvbfixer'), version: Type.String() }, { additionalProperties: false }),
  request: Type.Object({
    targetForceField: Type.Union([
      Type.Literal('amber'), Type.Literal('amber19sb'), Type.Literal('charmm'),
    ]),
    profile: Type.Union([Type.Literal('gromacs'), Type.Literal('standard')]),
    dryRun: Type.Boolean(),
    variantOverrides: Type.Array(VariantOverrideSchema),
  }, { additionalProperties: false }),
  output: Type.Object({
    path: Type.String(),
    written: Type.Boolean(),
    bytes: Type.Union([Type.Integer({ minimum: 0 }), Type.Null()]),
    sha256: Type.Union([Type.String({ pattern: '^[a-f0-9]{64}$' }), Type.Null()]),
  }, { additionalProperties: false }),
  result: Type.Union([NamingResultSchema, Type.Null()]),
  error: Type.Union([
    Type.Object({
      code: Type.String(),
      category: Type.String(),
      message: Type.String(),
      details: Type.Unknown(),
    }, { additionalProperties: false }),
    Type.Null(),
  ]),
}, { additionalProperties: false, $id: 'NamingCliReport' })

const OutputArtifactSchema = Type.Object({
  id: Type.String(),
  file: Type.String(),
  name: Type.String(),
  kind: Type.Literal('structure'),
}, { additionalProperties: false })

export const NamingConversionResponseSchema = Type.Object({
  operationId: Type.String(),
  status: Type.Literal('succeeded'),
  sourceArtifactId: Type.String(),
  outputArtifact: Type.Union([OutputArtifactSchema, Type.Null()]),
  output: Type.Object({
    bytes: Type.Integer({ minimum: 0 }),
    sha256: Type.String({ pattern: '^[a-f0-9]{64}$' }),
  }, { additionalProperties: false }),
  result: NamingResultSchema,
}, { additionalProperties: false, $id: 'NamingConversionResponse' })

export const ApiErrorSchema = Type.Object({
  error: Type.Object({
    code: Type.String(),
    message: Type.String(),
    details: Type.Optional(Type.Unknown()),
    requestId: Type.String(),
  }, { additionalProperties: false }),
}, { additionalProperties: false, $id: 'ApiError' })

export type NamingConversionRequest = Static<typeof NamingConversionRequestSchema>
export type NamingCliReport = Static<typeof NamingCliReportSchema>
export type NamingConversionResponse = Static<typeof NamingConversionResponseSchema>

export const NAMING_REQUEST_EXAMPLE: NamingConversionRequest = {
  inputArtifactId: '2a4d4d4e-2c82-4ea0-98ef-92df4cdd57f0',
  target: { forceField: 'amber', profile: 'gromacs' },
  variantOverrides: [{
    chainId: 'H', residueNumber: '82', insertionCode: 'A', variant: 'HIE',
  }],
  outputName: 'complex_gromacs.pdb',
  dryRun: false,
}

function openApiSchema(schema: TSchema): Record<string, unknown> {
  const value = JSON.parse(JSON.stringify(schema)) as Record<string, unknown>
  delete value.$id
  return value
}

export const NAMING_OPENAPI_DOCUMENT = {
  openapi: '3.1.0',
  info: { title: 'DVBFixer API', version: '1.0.0' },
  paths: {
    '/api/v1/workspaces/{workspaceId}/naming-conversions': {
      post: {
        operationId: 'createNamingConversion',
        summary: 'Convert force-field residue and atom names',
        security: [{ bearerAuth: [] }],
        parameters: [{
          name: 'workspaceId', in: 'path', required: true,
          schema: { type: 'string', pattern: '^[a-zA-Z0-9_-]+$' },
        }],
        requestBody: {
          required: true,
          content: { 'application/json': {
            schema: { $ref: '#/components/schemas/NamingConversionRequest' },
            example: NAMING_REQUEST_EXAMPLE,
          } },
        },
        responses: {
          '200': { description: 'Dry-run result', content: { 'application/json': { schema: { $ref: '#/components/schemas/NamingConversionResponse' } } } },
          '201': { description: 'Created naming artifact', content: { 'application/json': { schema: { $ref: '#/components/schemas/NamingConversionResponse' } } } },
          '400': { description: 'Invalid request', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '401': { description: 'Missing or invalid bearer credential', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '403': { description: 'Workspace write access required', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '404': { description: 'Workspace or artifact not found', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '409': { description: 'Workspace operation conflict', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '413': { description: 'Request or source too large', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '415': { description: 'Unsupported media type or source format', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '405': { description: 'Method not allowed', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '422': { description: 'Unsafe conversion', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '500': { description: 'Internal failure', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '504': { description: 'Naming conversion timed out', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
        },
      },
    },
    '/api/v1/workspaces/{workspaceId}/jobs': {
      get: {
        operationId: 'listManagedJobs', summary: 'List managed scientific jobs',
        security: [{ bearerAuth: [] }],
        parameters: [{ name: 'workspaceId', in: 'path', required: true, schema: { type: 'string', pattern: '^[a-zA-Z0-9_-]+$' } }],
        responses: {
          '200': { description: 'Managed jobs', content: { 'application/json': { schema: { type: 'array', items: { $ref: '#/components/schemas/ManagedJobRecord' } } } } },
          '401': { description: 'Missing or invalid bearer credential', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '404': { description: 'Workspace not found', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
        },
      },
      post: {
        operationId: 'createManagedJob', summary: 'Start an asynchronous scientific workflow',
        security: [{ bearerAuth: [] }],
        parameters: [{ name: 'workspaceId', in: 'path', required: true, schema: { type: 'string', pattern: '^[a-zA-Z0-9_-]+$' } }],
        requestBody: { required: true, content: { 'application/json': { schema: { $ref: '#/components/schemas/ManagedJobRequest' } } } },
        responses: {
          '202': { description: 'Job accepted', content: { 'application/json': { schema: { $ref: '#/components/schemas/ManagedJobRecord' } } } },
          '400': { description: 'Invalid request', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '401': { description: 'Missing or invalid bearer credential', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '403': { description: 'Workspace write access required', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '404': { description: 'Workspace not found', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '409': { description: 'Workspace operation conflict', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '413': { description: 'Request too large', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '415': { description: 'Unsupported media type', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '422': { description: 'Unsupported operation', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
          '500': { description: 'Internal failure', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
        },
      },
    },
    '/api/v1/workspaces/{workspaceId}/jobs/{jobId}': {
      get: {
        operationId: 'getManagedJob', summary: 'Get managed-job state', security: [{ bearerAuth: [] }],
        parameters: [
          { name: 'workspaceId', in: 'path', required: true, schema: { type: 'string' } },
          { name: 'jobId', in: 'path', required: true, schema: { type: 'string', format: 'uuid' } },
        ],
        responses: {
          '200': { description: 'Managed job', content: { 'application/json': { schema: { $ref: '#/components/schemas/ManagedJobRecord' } } } },
          '404': { description: 'Workspace or job not found', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
        },
      },
      delete: {
        operationId: 'cancelManagedJob', summary: 'Request managed-job cancellation', security: [{ bearerAuth: [] }],
        parameters: [
          { name: 'workspaceId', in: 'path', required: true, schema: { type: 'string' } },
          { name: 'jobId', in: 'path', required: true, schema: { type: 'string', format: 'uuid' } },
        ],
        responses: {
          '202': { description: 'Cancellation requested', content: { 'application/json': { schema: { $ref: '#/components/schemas/ManagedJobRecord' } } } },
          '404': { description: 'Workspace or job not found', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
        },
      },
    },
    '/api/v1/workspaces/{workspaceId}/jobs/{jobId}/events': {
      get: {
        operationId: 'streamManagedJobEvents', summary: 'Stream persisted managed-job state',
        security: [{ bearerAuth: [] }],
        parameters: [
          { name: 'workspaceId', in: 'path', required: true, schema: { type: 'string' } },
          { name: 'jobId', in: 'path', required: true, schema: { type: 'string', format: 'uuid' } },
        ],
        responses: {
          '200': { description: 'Server-sent managed-job records', content: { 'text/event-stream': { schema: { type: 'string' } } } },
          '404': { description: 'Workspace or job not found', content: { 'application/json': { schema: { $ref: '#/components/schemas/ApiError' } } } },
        },
      },
    },
  },
  components: {
    securitySchemes: {
      bearerAuth: { type: 'http', scheme: 'bearer' },
    },
    schemas: {
      NamingConversionRequest: openApiSchema(NamingConversionRequestSchema),
      NamingConversionResponse: openApiSchema(NamingConversionResponseSchema),
      ManagedJobRequest: openApiSchema(ManagedJobRequestSchema),
      ManagedJobRecord: openApiSchema(ManagedJobRecordSchema),
      ApiError: openApiSchema(ApiErrorSchema),
    },
  },
} as const
