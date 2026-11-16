import { useEffect, useRef, useState } from 'react'

declare global { interface Window { YT?: any; onYouTubeIframeAPIReady?: () => void } }

const errorText: Record<number, string> = {
  2: 'Invalid YouTube video ID.',
  5: 'This video could not play in the embedded player.',
  100: 'This video is unavailable or private.',
  101: 'The owner does not allow this video to play on other sites.',
  150: 'The owner does not allow this video to play on other sites.',
  153: 'YouTube could not verify this embedded player. Try opening the video on YouTube.',
}

export function YoutubePlayer({ youtubeId, start, onProgress, onPlayingChange, seekTo }: { youtubeId: string; start: number; onProgress: (time: number) => void; onPlayingChange?: (playing:boolean)=>void; seekTo?: number }) {
  const host = useRef<HTMLDivElement>(null)
  const player = useRef<any>(null)
  const [error, setError] = useState('')
  const callbacks=useRef({onProgress,onPlayingChange})
  callbacks.current={onProgress,onPlayingChange}

  useEffect(() => { if (seekTo !== undefined) player.current?.seekTo?.(seekTo, true) }, [seekTo])
  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    setError('')
    const create = () => {
      if (cancelled || !host.current || !window.YT) return
      player.current = new window.YT.Player(host.current, {
        videoId: youtubeId,
        playerVars: { start: Math.floor(start), rel: 0, origin: window.location.origin },
        events: {
          onReady: (event: any) => { if (start) event.target.seekTo(start, true) },
          onStateChange: (event: any) => {
            if (timer) clearInterval(timer)
            callbacks.current.onPlayingChange?.(event.data===1)
            if (event.data === 1) timer = window.setInterval(() => callbacks.current.onProgress(event.target.getCurrentTime()), 5000)
            else if(event.data!==-1) callbacks.current.onProgress(event.target.getCurrentTime())
          },
          onError: (event: any) => {callbacks.current.onPlayingChange?.(false);setError(errorText[event.data] ?? 'YouTube could not play this video here.')},
        },
      })
    }
    if (window.YT) create()
    else {
      const script = document.createElement('script')
      script.src = 'https://www.youtube.com/iframe_api'
      script.onerror = () => setError('The YouTube player could not load. Check your connection or open the video on YouTube.')
      document.head.appendChild(script)
      window.onYouTubeIframeAPIReady = create
    }
    const visibility=()=>callbacks.current.onPlayingChange?.(!document.hidden && player.current?.getPlayerState?.()===1)
    document.addEventListener('visibilitychange',visibility)
    return () => { cancelled = true; if (timer) clearInterval(timer); document.removeEventListener('visibilitychange',visibility); callbacks.current.onPlayingChange?.(false); player.current?.destroy?.() }
  }, [youtubeId])

  return <div className="relative aspect-video overflow-hidden rounded-xl border border-white/10 bg-black">
    <div ref={host} className="size-full" />
    {error && <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/90 p-6 text-center text-sm text-zinc-200"><p>{error}</p><a className="rounded-md bg-white px-3 py-2 font-medium text-zinc-950" href={`https://www.youtube.com/watch?v=${youtubeId}`} target="_blank" rel="noopener noreferrer">Open on YouTube</a></div>}
  </div>
}
