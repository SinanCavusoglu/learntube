import type { ReactNode } from 'react'

function inline(text:string):ReactNode[] {
  const result:ReactNode[]=[]
  const pattern=/\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g
  let cursor=0,match:RegExpExecArray|null
  while((match=pattern.exec(text))!==null){
    if(match.index>cursor)result.push(text.slice(cursor,match.index))
    if(match[1]!==undefined){
      const url=match[2].trim()
      result.push(/^https?:\/\//i.test(url)?<a key={match.index} href={url} target="_blank" rel="noopener noreferrer" className="text-indigo-300 underline">{match[1]}</a>:match[0])
    }else if(match[3]!==undefined)result.push(<strong key={match.index}>{match[3]}</strong>)
    else if(match[4]!==undefined)result.push(<em key={match.index}>{match[4]}</em>)
    else result.push(<code key={match.index} className="rounded bg-white/10 px-1">{match[5]}</code>)
    cursor=pattern.lastIndex
  }
  if(cursor<text.length)result.push(text.slice(cursor))
  return result
}

export function SafeMarkdown({source}:{source:string}) {
  const lines=source.split(/\r?\n/)
  const blocks:ReactNode[]=[]
  let index=0
  while(index<lines.length){
    const line=lines[index]
    if(!line.trim()){index++;continue}
    const heading=/^(#{1,6})\s+(.+)$/.exec(line)
    if(heading){const size=heading[1].length;blocks.push(<div key={index} role="heading" aria-level={size} className={`${size<=2?'text-xl font-semibold':'text-base font-semibold'} mt-5 mb-2`}>{inline(heading[2])}</div>);index++;continue}
    if(/^>\s?/.test(line)){blocks.push(<blockquote key={index} className="my-3 border-l-2 border-indigo-300/60 pl-4 text-zinc-300">{inline(line.replace(/^>\s?/,''))}</blockquote>);index++;continue}
    const bullet=/^\s*[-*+]\s+/.test(line),numbered=/^\s*\d+\.\s+/.test(line)
    if(bullet||numbered){const items:ReactNode[]=[];const start=index;while(index<lines.length&&(bullet?/^\s*[-*+]\s+/.test(lines[index]):/^\s*\d+\.\s+/.test(lines[index]))){items.push(<li key={index}>{inline(lines[index].replace(bullet?/^\s*[-*+]\s+/:/^\s*\d+\.\s+/,''))}</li>);index++}blocks.push(bullet?<ul key={start} className="my-3 list-disc space-y-1 pl-6">{items}</ul>:<ol key={start} className="my-3 list-decimal space-y-1 pl-6">{items}</ol>);continue}
    const paragraph:string[]=[];const start=index
    while(index<lines.length&&lines[index].trim()&&!/^(#{1,6}\s+|>\s?|\s*[-*+]\s+|\s*\d+\.\s+)/.test(lines[index])){paragraph.push(lines[index]);index++}
    blocks.push(<p key={start} className="my-3 whitespace-pre-wrap leading-7">{inline(paragraph.join('\n'))}</p>)
  }
  return <div className="break-words text-sm text-zinc-200">{blocks}</div>
}
