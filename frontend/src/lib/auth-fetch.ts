type GetToken = (options?: { skipCache?: boolean }) => Promise<string | null>

let tokenRefreshPromise: Promise<string | null> | null = null

function tokenExpiresSoon(token: string, skewSeconds = 30) {
  const payload = token.split('.')[1]
  if (!payload) return false

  try {
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    const claims = JSON.parse(atob(padded)) as { exp?: number }
    return typeof claims.exp === 'number' && claims.exp * 1000 <= Date.now() + skewSeconds * 1000
  } catch {
    return false
  }
}

function getFreshToken(getToken: GetToken) {
  if (!tokenRefreshPromise) {
    tokenRefreshPromise = getToken({ skipCache: true }).finally(() => {
      tokenRefreshPromise = null
    })
  }
  return tokenRefreshPromise
}

export async function fetchWithAuthRetry(
  getToken: GetToken,
  input: RequestInfo | URL,
  init: RequestInit = {},
) {
  const request = async (skipCache = false) => {
    let token = skipCache ? await getFreshToken(getToken) : await getToken()
    if (token && !skipCache && tokenExpiresSoon(token)) {
      token = await getFreshToken(getToken)
    }
    const headers = new Headers(init.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(input, { ...init, headers })
  }

  const response = await request(false)
  if (response.status !== 401) return response

  return request(true)
}
