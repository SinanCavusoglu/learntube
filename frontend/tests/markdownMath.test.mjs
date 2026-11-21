import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

test('Notebook Markdown renders inline and multiline equations beside normal formatting', async t => {
  const server=await createServer({server:{middlewareMode:true},appType:'custom'})
  t.after(()=>server.close())
  const {SafeMarkdown}=await server.ssrLoadModule('/src/components/SafeMarkdown.tsx')
  const source='**Bold $x^2$** and `$literal$`.\n\n$$\n\\frac{a}{b}\n$$'
  const html=renderToStaticMarkup(createElement(SafeMarkdown,{source}))
  assert.match(html,/<strong>Bold /)
  assert.match(html,/<span class="katex"/)
  assert.match(html,/katex-display/)
  assert.match(html,/<code[^>]*>\$literal\$<\/code>/)
})

test('untrusted LaTeX cannot create a JavaScript link', async t => {
  const server=await createServer({server:{middlewareMode:true},appType:'custom'})
  t.after(()=>server.close())
  const {SafeMarkdown}=await server.ssrLoadModule('/src/components/SafeMarkdown.tsx')
  const html=renderToStaticMarkup(createElement(SafeMarkdown,{source:'$\\href{javascript:alert(1)}{click}$'}))
  assert.doesNotMatch(html,/<a[^>]+href="javascript:/i)
})
