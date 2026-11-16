import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('LearnTube failed to render:', error, info)
  }

  render() {
    if (this.state.error) {
      return <main style={{ padding: 32, color: '#f4f4f5', fontFamily: 'system-ui', background: '#101012', minHeight: '100vh' }}><h1>LearnTube could not load</h1><p style={{ color: '#fda4af' }}>{this.state.error.message}</p><button onClick={() => window.location.reload()}>Reload page</button></main>
    }
    return this.props.children
  }
}
