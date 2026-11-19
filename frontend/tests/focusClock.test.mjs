import test from 'node:test'
import assert from 'node:assert/strict'
import { elapsedSeconds, remainingSeconds, interrupted, clockText } from '../src/lib/focusClock.ts'

test('deadline calculation survives delayed ticks and never goes negative', () => {
  assert.equal(remainingSeconds(1200,elapsedSeconds(60,5000,65000)),1080)
  assert.equal(remainingSeconds(1200,elapsedSeconds(0,0,1300000)),0)
  assert.equal(clockText(1199.2),'20:00')
})

test('sleep and clock changes require recovery', () => {
  assert.equal(interrupted(0,0,1000,1000),false)
  assert.equal(interrupted(0,0,30000,1000),true)
  assert.equal(interrupted(0,0,11000,11000),false)
  assert.equal(interrupted(0,0,60000,60000),false)
  assert.equal(interrupted(0,0,20000,30000),true)
  assert.equal(interrupted(1000,1000,0,2000),true)
})
