export function elapsedSeconds(base:number,startedAt:number,now:number):number {
  return Math.max(0,base+(now-startedAt)/1000)
}

export function remainingSeconds(target:number,elapsed:number):number {
  return Math.max(0,Math.ceil(target-elapsed))
}

export function interrupted(lastWall:number,lastMonotonic:number,wall:number,monotonic:number):boolean {
  const wallGap=wall-lastWall,monoGap=monotonic-lastMonotonic
  return wallGap<0 || monoGap<0 || monoGap>10_000 || wallGap-monoGap>5_000
}

export function clockText(seconds:number):string {
  const whole=Math.max(0,Math.ceil(seconds))
  return `${String(Math.floor(whole/60)).padStart(2,'0')}:${String(whole%60).padStart(2,'0')}`
}
