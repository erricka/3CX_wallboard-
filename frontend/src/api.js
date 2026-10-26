// Same origin by default (nginx / Vite proxy). Set VITE_API_URL when the backend lives elsewhere.
export const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

export function wallboardSocketUrl() {
  const base = API_URL || window.location.origin
  return base.replace(/^http/, 'ws') + '/ws/wallboard'
}
