import test from 'node:test'
import assert from 'node:assert/strict'
import {addDays, fromISO, layoutDay, localISO, monday, plannerStats, weekDays} from '../src/lib/plannerDates.ts'

const timed=(id,date,start,end,status='planned')=>({plan_id:id,occurrence_date:date,date,title:`Plan ${id}`,category:'Writing',description:'',start_time:start,end_time:end,is_untimed:false,recurring:false,recurrence:'none',timezone:'Europe/Berlin',status,resource_type:null,resource_id:null,destination_url:'/writing',resource_missing:false})
const task=(id,date,status='planned')=>({...timed(id,date,null,null,status),is_untimed:true})

test('Monday week navigation crosses month, year, and leap day',()=>{
  assert.equal(monday('2027-01-01'),'2026-12-28')
  assert.equal(addDays('2028-02-28',1),'2028-02-29')
  assert.deepEqual(weekDays('2027-01-01'),['2026-12-28','2026-12-29','2026-12-30','2026-12-31','2027-01-01','2027-01-02','2027-01-03'])
  assert.equal(localISO(fromISO('2027-03-28')),'2027-03-28')
})

test('overlapping events receive separate lanes and non-overlapping ones reuse a lane',()=>{
  const day='2026-11-19'
  const rows=layoutDay([timed(1,day,'09:00','10:00'),timed(2,day,'09:30','10:30'),timed(3,day,'11:00','12:00'),task(4,day)])
  assert.deepEqual(rows.map(row=>[row.event.plan_id,row.lane,row.lanes]),[[1,0,2],[2,1,2],[3,0,1]])
})

test('planned totals do not treat tasks or skipped plans as actual activity',()=>{
  const day='2026-11-19'
  assert.deepEqual(plannerStats([timed(1,day,'09:00','10:00','completed'),timed(2,day,'09:30','10:00','skipped'),task(3,day,'completed'),task(4,day)]),
    {planned_minutes:90,completed_minutes:60,completed_tasks:1,total_tasks:2})
})
