import test from 'node:test'
import assert from 'node:assert/strict'
import {answerPractice, matchesDifficulty, startPractice} from '../src/lib/difficultPractice.ts'

test('difficult filter keeps only classified IDs',()=>{
  assert.equal(matchesDifficulty(1,'all',[2]),true)
  assert.equal(matchesDifficulty(1,'difficult',[2]),false)
  assert.equal(matchesDifficulty(2,'difficult',[2]),true)
})

test('Again requeues and Got It advances',()=>{
  let state=startPractice([1,2])
  state=answerPractice(state,'again')
  assert.deepEqual(state.queue,[2,1])
  state=answerPractice(state,'got-it')
  assert.deepEqual(state.queue,[1])
  state=answerPractice(state,'got-it')
  assert.deepEqual(state.queue,[])
  assert.equal(state.practiced.length,2)
  assert.equal(state.gotIt.length,2)
})

test('repeat limit ends a one-card session with accurate summary',()=>{
  let state=startPractice([7])
  for(let i=0;i<3;i++)state=answerPractice(state,'again')
  assert.deepEqual(state.queue,[])
  assert.deepEqual(state.practiced,[7])
  assert.deepEqual(state.needsMore,[7])
  assert.deepEqual(state.gotIt,[])
  assert.deepEqual(answerPractice(state,'got-it'),state)
})
