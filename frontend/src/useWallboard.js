import { useEffect, useState } from 'react'
import { wallboardSocketUrl } from './api.js'

// Live wallboard snapshot pushed by the backend over a WebSocket; reconnects with backoff.
export function useWallboard() {
  const [snapshot, setSnapshot] = useState(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let socket
    let timer
    let attempt = 0
    let stopped = false

    const connect = () => {
      socket = new WebSocket(wallboardSocketUrl())
      socket.onopen = () => {
        attempt = 0
        setConnected(true)
      }
      socket.onmessage = (event) => setSnapshot(JSON.parse(event.data))
      socket.onclose = () => {
        setConnected(false)
        if (!stopped) timer = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 15000))
      }
      socket.onerror = () => socket.close()
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [])

  return { snapshot, connected }
}
