export function elapsedSeconds(base:number,startedAt:number,now:number):number {
  return Math.max(0,base+(now-startedAt)/1000)
}

export function remainingSeconds(target:number,elapsed:number):number {
  return Math.max(0,Math.ceil(target-elapsed))
}

export function interrupted(lastWall:number,lastMonotonic:number,wall:number,monotonic:number):boolean {
  const wallGap=wall-lastWall,monoGap=monotonic-lastMonotonic
  // A background tab can delay callbacks for a minute or more while both clocks
  // keep advancing. That is normal elapsed time, not evidence of computer sleep.
  return wallGap<0 || monoGap<0 || Math.abs(wallGap-monoGap)>5_000
}

export function clockText(seconds:number):string {
  const whole=Math.max(0,Math.ceil(seconds))
  return `${String(Math.floor(whole/60)).padStart(2,'0')}:${String(whole%60).padStart(2,'0')}`
}
