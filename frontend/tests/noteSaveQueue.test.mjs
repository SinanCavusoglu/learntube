import test from 'node:test'
import assert from 'node:assert/strict'
import { queueNoteSave } from '../src/lib/noteSaveQueue.ts'

test('note writes stay ordered across editor remounts', async () => {
  const writes = []
  let releaseFirst
  let signalStarted
  const started = new Promise(resolve => { signalStarted = resolve })
  const first = queueNoteSave('test-video-1', () => new Promise(resolve => {
    releaseFirst = () => { writes.push('old'); resolve() }
    signalStarted()
  }))
  const second = queueNoteSave('test-video-1', async () => { writes.push('new') })
  await started
  assert.deepEqual(writes, [])
  releaseFirst()
  await Promise.all([first, second])
  assert.deepEqual(writes, ['old', 'new'])
})

test('a failed write does not block the next note edit', async () => {
  const writes = []
  const first = queueNoteSave('test-pdf-2', async () => { throw new Error('offline') })
  const second = queueNoteSave('test-pdf-2', async () => { writes.push('recovered') })
  await assert.rejects(first, /offline/)
  await second
  assert.deepEqual(writes, ['recovered'])
})
