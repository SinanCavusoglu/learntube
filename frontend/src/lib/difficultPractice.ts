export type PracticeState = {
  queue:number[]
  repeats:Record<number,number>
  practiced:number[]
  gotIt:number[]
  needsMore:number[]
}

export const startPractice = (ids:number[]):PracticeState => ({queue:[...ids],repeats:{},practiced:[],gotIt:[],needsMore:[]})

export const matchesDifficulty = (id:number, filter:string, difficultIds:readonly number[]):boolean =>
  filter==='all'||difficultIds.includes(id)

export function answerPractice(state:PracticeState, rating:'again'|'got-it'):PracticeState {
  const [id,...rest]=state.queue
  if(id===undefined) return state
  const practiced=state.practiced.includes(id)?state.practiced:[...state.practiced,id]
  if(rating==='got-it') return {...state,queue:rest,practiced,gotIt:[...state.gotIt,id]}
  const count=state.repeats[id]??0
  if(count>=2) return {...state,queue:rest,practiced,needsMore:[...state.needsMore,id]}
  return {...state,queue:[...rest,id],practiced,repeats:{...state.repeats,[id]:count+1}}
}
