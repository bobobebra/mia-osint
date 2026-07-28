const headers = { 'Content-Type': 'application/json' }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const payload = await response.json()
      message = payload.detail || message
    } catch {
      // keep status text
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body) }),
  upload: async <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
}
