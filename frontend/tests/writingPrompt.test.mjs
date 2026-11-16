import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildWritingPrompt } from '../src/lib/writingPrompt.ts'

test('Task 1 uses achievement and reminds users to attach the original visual', () => {
  const question = 'Describe the chart.\nKeep its values unchanged.'
  const essay = 'My response has  two spaces.\nAnd another line.'
  const prompt = buildWritingPrompt(1, question, essay)
  assert.match(prompt, /Task Achievement/)
  assert.doesNotMatch(prompt, /Task Response/)
  assert.match(prompt, /attach the original visual separately/)
  assert.match(prompt, /not an official IELTS score/)
  assert.ok(prompt.endsWith(`Question (verbatim):\n${question}\n\nEssay (verbatim):\n${essay}`))
})

test('Task 2 uses response and preserves the original essay', () => {
  const question = 'Do you agree?'
  const essay = 'First paragraph.\n\nSecond paragraph.'
  const prompt = buildWritingPrompt(2, question, essay)
  assert.match(prompt, /Task Response/)
  assert.doesNotMatch(prompt, /Task Achievement/)
  assert.doesNotMatch(prompt, /attach the original visual/)
  assert.ok(prompt.endsWith(`Question (verbatim):\n${question}\n\nEssay (verbatim):\n${essay}`))
})
