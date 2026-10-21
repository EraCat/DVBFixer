import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import InputAdornment from '@mui/material/InputAdornment'
import Paper from '@mui/material/Paper'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import LogoutIcon from '@mui/icons-material/Logout'
import { apiFetch, clearApiToken, getApiToken, setApiToken } from '../lib/api-client'
import { useApiToken } from '../hooks/useApiToken'

interface HealthResponse {
  authenticationRequired?: boolean
}

type GatePhase = 'probing' | 'signed-out' | 'validating' | 'authenticated' | 'unavailable'

export interface AuthGateProps {
  children: ReactNode
  showLogout?: boolean
}

async function validateSession(signal?: AbortSignal): Promise<Response> {
  return apiFetch('/api/session', { cache: 'no-store', signal, headers: { Accept: 'application/json' } })
}

export function AuthGate({ children, showLogout = true }: AuthGateProps) {
  const storedToken = useApiToken()
  const [phase, setPhase] = useState<GatePhase>('probing')
  const [authenticationRequired, setAuthenticationRequired] = useState<boolean | null>(null)
  const [tokenInput, setTokenInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [probeAttempt, setProbeAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setPhase('probing')
    setError(null)
    void (async () => {
      try {
        // Health is intentionally public and must never receive a bearer token.
        const response = await fetch('/api/health', {
          cache: 'no-store',
          signal: controller.signal,
          headers: { Accept: 'application/json' },
        })
        if (!response.ok) throw new Error(`Health check failed: HTTP ${response.status}`)
        const health = await response.json() as HealthResponse
        const required = health.authenticationRequired === true
        setAuthenticationRequired(required)
        if (!required) {
          setPhase('authenticated')
          return
        }

        const token = getApiToken()
        if (!token) {
          setPhase('signed-out')
          return
        }
        setPhase('validating')
        const session = await validateSession(controller.signal)
        if (session.ok) setPhase('authenticated')
        else {
          setPhase('signed-out')
          setError(session.status === 401 ? 'Your session has expired. Enter a valid access token.' : `Session check failed: HTTP ${session.status}`)
        }
      } catch (reason) {
        if (controller.signal.aborted) return
        setPhase('unavailable')
        setError(reason instanceof Error ? reason.message : String(reason))
      }
    })()
    return () => controller.abort()
  }, [probeAttempt])

  useEffect(() => {
    if (authenticationRequired && !storedToken && phase === 'authenticated') {
      setTokenInput('')
      setPhase('signed-out')
    }
  }, [authenticationRequired, phase, storedToken])

  const submitToken = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const candidate = tokenInput.trim()
    if (!candidate) {
      setError('Enter an access token.')
      return
    }
    setError(null)
    setPhase('validating')
    setApiToken(candidate)
    try {
      const response = await validateSession()
      if (!response.ok) {
        if (response.status !== 401) clearApiToken()
        setPhase('signed-out')
        setError(response.status === 401 ? 'The access token was not accepted.' : `Session check failed: HTTP ${response.status}`)
        return
      }
      setTokenInput('')
      setPhase('authenticated')
    } catch (reason) {
      clearApiToken()
      setPhase('signed-out')
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  const logout = () => {
    clearApiToken()
    setTokenInput('')
    setError(null)
    setPhase('signed-out')
  }

  if (phase === 'authenticated') {
    return (
      <>
        {children}
        {authenticationRequired && showLogout && (
          <Button
            aria-label="Sign out"
            color="inherit"
            onClick={logout}
            startIcon={<LogoutIcon />}
            sx={{
              position: 'fixed', top: 8, right: 12, zIndex: theme => theme.zIndex.tooltip - 1,
              color: 'common.white', borderColor: 'rgba(255,255,255,0.4)',
              '&:hover': { borderColor: 'common.white', backgroundColor: 'rgba(255,255,255,0.1)' },
            }}
            variant="outlined"
          >
            Sign out
          </Button>
        )}
      </>
    )
  }

  const busy = phase === 'probing' || phase === 'validating'
  return (
    <Box sx={{
      alignItems: 'center', display: 'flex', height: '100%', justifyContent: 'center', p: 3,
      background: 'radial-gradient(circle at 50% 20%, #f7f9fc 0%, #e8ecf1 58%, #d9e0e9 100%)',
    }}>
      <Paper elevation={8} sx={{ maxWidth: 420, overflow: 'hidden', width: '100%' }}>
        <Box sx={{ height: 5, background: 'linear-gradient(90deg, primary.main, secondary.main)' }} />
        <Box sx={{ p: 4 }}>
          <Box sx={{
            alignItems: 'center', bgcolor: 'primary.main', borderRadius: '50%', color: 'primary.contrastText',
            display: 'flex', height: 48, justifyContent: 'center', mb: 2.5, width: 48,
          }}>
            <LockOutlinedIcon />
          </Box>
          <Typography component="h1" variant="h5" sx={{ fontWeight: 650, mb: 0.75 }}>
            DVBfixer workspace
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 3 }}>
            Enter the access token provided by your administrator. It is kept only for this browser session.
          </Typography>

          {error && <Alert severity={phase === 'unavailable' ? 'error' : 'warning'} sx={{ mb: 2 }}>{error}</Alert>}

          {phase === 'unavailable' ? (
            <Button fullWidth onClick={() => setProbeAttempt(attempt => attempt + 1)} variant="contained">
              Retry connection
            </Button>
          ) : (
            <Box component="form" onSubmit={submitToken}>
              <TextField
                autoComplete="current-password"
                autoFocus
                disabled={busy}
                fullWidth
                label="Access token"
                onChange={event => setTokenInput(event.target.value)}
                type="password"
                value={tokenInput}
                slotProps={{
                  input: {
                    startAdornment: <InputAdornment position="start"><LockOutlinedIcon fontSize="small" /></InputAdornment>,
                  },
                }}
              />
              <Button disabled={busy || !tokenInput.trim()} fullWidth sx={{ mt: 2 }} type="submit" variant="contained">
                {busy ? <CircularProgress color="inherit" size={20} /> : 'Continue'}
              </Button>
            </Box>
          )}
        </Box>
      </Paper>
    </Box>
  )
}
