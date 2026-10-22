/** Shared loading/error helpers for the API-backed panes. */

/** Lifecycle of one remote resource. */
export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error'

/** Turn an unknown thrown value into a message we can show to the user. */
export function errorMessage(error: unknown, fallback = '请求失败'): string {
  if (error instanceof Error && error.message) {
    return error.message
  }
  if (typeof error === 'string' && error) {
    return error
  }
  return fallback
}
