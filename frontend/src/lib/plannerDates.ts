import type { PlannerOccurrence, PlannerStats } from './api'

export const localISO = (date:Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
export const fromISO = (value:string) => {const [year,month,day]=value.split('-').map(Number);return new Date(year,month-1,day,12)}
export const addDays = (value:string,offset:number) => {const date=fromISO(value);date.setDate(date.getDate()+offset);return localISO(date)}
export const monday = (value:string) => addDays(value,-((fromISO(value).getDay()+6)%7))
export const weekDays = (value:string) => Array.from({length:7},(_,index)=>addDays(monday(value),index))
export const minutes = (value:string) => {const [hour,minute]=value.split(':').map(Number);return hour*60+minute}
export const duration = (event:PlannerOccurrence) => event.start_time&&event.end_time ? minutes(event.end_time)-minutes(event.start_time) : 0
export const plannerStats = (events:PlannerOccurrence[]):PlannerStats => ({
  planned_minutes:events.reduce((sum,event)=>sum+duration(event),0),
  completed_minutes:events.reduce((sum,event)=>sum+(event.status==='completed'?duration(event):0),0),
  completed_tasks:events.filter(event=>event.is_untimed&&event.status==='completed').length,
  total_tasks:events.filter(event=>event.is_untimed).length,
})
export const timeLabel = (total:number) => `${Math.floor(total/60)}h ${String(total%60).padStart(2,'0')}m`

export type PositionedEvent = {event:PlannerOccurrence;lane:number;lanes:number}
export function layoutDay(events:PlannerOccurrence[]):PositionedEvent[] {
  const sorted=events.filter(event=>!event.is_untimed).sort((a,b)=>minutes(a.start_time!)-minutes(b.start_time!)||minutes(a.end_time!)-minutes(b.end_time!))
  const result:PositionedEvent[]=[]
  let cluster:PositionedEvent[]=[]
  let laneEnds:number[]=[]
  let clusterEnd=-1
  const finish=()=>{for(const item of cluster)item.lanes=laneEnds.length;cluster=[];laneEnds=[]}
  for(const event of sorted){
    const start=minutes(event.start_time!),end=minutes(event.end_time!)
    if(start>=clusterEnd)finish()
    let lane=laneEnds.findIndex(value=>value<=start)
    if(lane<0){lane=laneEnds.length;laneEnds.push(end)}else laneEnds[lane]=end
    cluster.push({event,lane,lanes:1});result.push(cluster[cluster.length-1]);clusterEnd=Math.max(clusterEnd,end)
  }
  finish()
  return result
}
