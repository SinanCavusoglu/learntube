export const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8001'
export type Video = { id:number; youtube_id:string; url:string; title:string; created_at:string; last_watched_at?:string; playback_position:number }
export type Segment = { id:number; text:string; start:number|null; duration:number|null; is_manual:boolean }
export type Note = { content:string; updated_at?:string }
export type Vocabulary = { id:number; text:string; meaning:string; example_sentence:string; personal_note:string; part_of_speech:string; cefr_level:string; collocations:string; usage_note:string; synonyms:string; source_video_id:number|null; source_timestamp:number|null; source_pdf_id:number|null; source_pdf_title:string|null; source_page:number|null; source_note_id:number|null; source_note_title:string|null; source_episode_id:number|null; source_episode_title:string|null; source_podcast_title:string|null; source_episode_timestamp:number|null; created_at:string; status:'new'|'learning'|'reviewing'|'mastered'; review_count:number; successful_review_count:number; interval_days:number; next_review_at:string|null }
export type VocabularyStats = { total:number; new:number; learning:number; reviewing:number; mastered:number; due:number; reviewed_today:number }
export type ReviewEvent = { id:number; rating:string; reviewed_at:string; previous_status:string; next_status:string; interval_days:number }
async function request<T>(path:string, init?:RequestInit):Promise<T> { const r=await fetch(`${API}${path}`,{headers:{'Content-Type':'application/json',...init?.headers},...init}); if(!r.ok) throw new Error((await r.json().catch(()=>null))?.detail ?? 'Request failed'); return r.status===204 ? undefined as T : r.json() }
export const api={listVideos:()=>request<Video[]>('/api/videos'), addVideo:(url:string)=>request<Video>('/api/videos',{method:'POST',body:JSON.stringify({url})}), deleteVideo:(id:number)=>request<void>(`/api/videos/${id}`,{method:'DELETE'}), video:(id:string)=>request<Video>(`/api/videos/${id}`), transcript:(id:string)=>request<Segment[]>(`/api/videos/${id}/transcript`), manualTranscript:(id:number,text:string)=>request<Segment[]>(`/api/videos/${id}/transcript/manual`,{method:'PUT',body:JSON.stringify({text})}), notes:(id:string)=>request<Note>(`/api/videos/${id}/notes`), saveNotes:(id:number,content:string)=>request<Note>(`/api/videos/${id}/notes`,{method:'PUT',body:JSON.stringify({content})}), progress:(id:number,position:number)=>request<Video>(`/api/videos/${id}/progress`,{method:'PUT',body:JSON.stringify({position})}), vocabulary:(id:number)=>request<Vocabulary[]>(`/api/vocabulary?video_id=${id}`), addVocabulary:(item:Partial<Vocabulary>)=>request<Vocabulary>('/api/vocabulary',{method:'POST',body:JSON.stringify(item)})}
export type DictionaryResult = {word:string;definitions:{definition:string;part_of_speech:string}[];examples:string[]}
export const dictionaryApi = {
  lookup:async(word:string,signal?:AbortSignal):Promise<DictionaryResult>=>request<DictionaryResult>(`/api/dictionary/lookup?word=${encodeURIComponent(word)}`,{signal}),
}
export type Notebook = {id:number;name:string;description:string;created_at:string;updated_at:string}
export type NotebookNote = {id:number;notebook_id:number;title:string;content:string;is_pinned:boolean;revision:number;created_at:string;updated_at:string}
export type NotebookDraft = Pick<NotebookNote,'notebook_id'|'title'|'content'|'is_pinned'>
export const notebookApi = {
  all:()=>request<Notebook[]>('/api/notebooks'),
  create:(name:string,description='')=>request<Notebook>('/api/notebooks',{method:'POST',body:JSON.stringify({name,description})}),
  update:(id:number,name:string,description:string)=>request<Notebook>(`/api/notebooks/${id}`,{method:'PATCH',body:JSON.stringify({name,description})}),
  remove:(id:number)=>request<void>(`/api/notebooks/${id}`,{method:'DELETE'}),
  notes:(query:string,notebookId:number|null,pinned=false)=>{const params=new URLSearchParams({q:query,pinned:String(pinned)});if(notebookId!==null)params.set('notebook_id',String(notebookId));return request<NotebookNote[]>(`/api/notebooks/notes/search?${params}`)},
  note:(id:number)=>request<NotebookNote>(`/api/notebooks/notes/${id}`),
  createNote:(draft:Pick<NotebookNote,'notebook_id'|'title'|'content'>)=>request<NotebookNote>('/api/notebooks/notes',{method:'POST',body:JSON.stringify(draft)}),
  saveNote:(id:number,expected_revision:number,draft:NotebookDraft)=>request<NotebookNote>(`/api/notebooks/notes/${id}`,{method:'PATCH',body:JSON.stringify({...draft,expected_revision})}),
  removeNote:(id:number)=>request<void>(`/api/notebooks/notes/${id}`,{method:'DELETE'}),
}
export const vocabularyApi = {
  all:()=>request<Vocabulary[]>('/api/vocabulary'),
  stats:()=>request<VocabularyStats>('/api/vocabulary/stats'),
  due:()=>request<Vocabulary[]>('/api/vocabulary/review/due'),
  update:(id:number,changes:Partial<Vocabulary>)=>request<Vocabulary>(`/api/vocabulary/${id}`,{method:'PATCH',body:JSON.stringify(changes)}),
  remove:(id:number)=>request<void>(`/api/vocabulary/${id}`,{method:'DELETE'}),
  review:(id:number,rating:'again'|'good'|'easy',expected_review_count:number)=>request<Vocabulary>(`/api/vocabulary/${id}/review`,{method:'POST',body:JSON.stringify({rating,expected_review_count})}),
  history:(id:number)=>request<ReviewEvent[]>(`/api/vocabulary/${id}/reviews`),
}
export type WritingSession = { id:number; task_type:1|2; question:string; essay_content:string; notes:string; chatgpt_feedback:string; feedback_revision:number; timer_duration_seconds:number; elapsed_seconds:number; timer_status:'idle'|'running'|'paused'; timer_started_at:string|null; status:'draft'|'completed'; word_count:number; revision:number; created_at:string; updated_at:string; completed_at:string|null }
export type WritingData = Pick<WritingSession,'question'|'essay_content'|'notes'>
export const writingApi = {
  all:()=>request<WritingSession[]>('/api/writing'),
  stats:()=>request<{completed:number;active_minutes:number;task1_count:number;task2_count:number;completed_words:number}>('/api/writing/stats'),
  create:(task_type:1|2,question:string,timer_duration_seconds:number)=>request<WritingSession>('/api/writing',{method:'POST',body:JSON.stringify({task_type,question,timer_duration_seconds})}),
  get:(id:number)=>request<WritingSession>(`/api/writing/${id}`),
  save:(id:number,expected_revision:number,data:WritingData)=>request<WritingSession>(`/api/writing/${id}`,{method:'PATCH',body:JSON.stringify({...data,expected_revision})}),
  timer:(id:number,expected_revision:number,action:'start'|'pause'|'reset')=>request<WritingSession>(`/api/writing/${id}/timer`,{method:'POST',body:JSON.stringify({action,expected_revision})}),
  finish:(id:number,expected_revision:number,data:WritingData)=>request<WritingSession>(`/api/writing/${id}/finish`,{method:'POST',body:JSON.stringify({...data,expected_revision})}),
  remove:(id:number)=>request<void>(`/api/writing/${id}`,{method:'DELETE'}),
  feedback:(id:number,content:string,expected_revision:number)=>request<WritingSession>(`/api/writing/${id}/feedback`,{method:'PUT',body:JSON.stringify({content,expected_revision})}),
}
export type AIStatus = {enabled:boolean;model:string|null;daily_limit:number|null;used_today:number|null}
export type AIVocabulary = {definition:string;examples:string[]}
export const aiApi = {
  status:()=>request<AIStatus>('/api/ai/status'),
  vocabulary:(text:string)=>request<AIVocabulary>('/api/ai/explain-vocabulary',{method:'POST',body:JSON.stringify({request_id:crypto.randomUUID(),text})}),
}
export type StudyDay = { date:string; video:number; vocabulary:number; writing:number; pdf:number; podcast:number; total:number; reviews:number }
export type DashboardData = { total_seconds:number; today_seconds:number; week_seconds:number; current_streak:number; longest_streak:number; videos_saved:number; pdfs:{total:number;active_seconds:number;recent:{id:number;title:string;last_opened_at:string;last_page:number;total_pages:number}[]}; podcasts:{subscriptions:number;active_seconds:number}; vocabulary:VocabularyStats; writing:{completed:number;task1:number;task2:number;active_seconds:number;recent:{id:number;task_type:number;completed_at:string}|null}; daily:StudyDay[]; weekly:StudyDay[]; recent:{type:'video'|'vocabulary'|'writing'|'pdf'|'podcast';description:string;at:string;link:string}[] }
export const dashboardApi = { get:()=>request<DashboardData>(`/api/dashboard?timezone_name=${encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC')}`) }
export type PDFDocument = {id:number;title:string;original_filename:string;stored_filename:string;file_size_bytes:number;total_pages:number;last_page:number;reading_progress:number;zoom:number;created_at:string;updated_at:string;last_opened_at:string|null}
export const pdfApi = {
  all:()=>request<PDFDocument[]>('/api/pdfs'),
  get:(id:number)=>request<PDFDocument>(`/api/pdfs/${id}`),
  fileUrl:(id:number)=>`${API}/api/pdfs/${id}/file`,
  upload:async(file:File):Promise<PDFDocument>=>{const body=new FormData();body.append('file',file);const response=await fetch(`${API}/api/pdfs/upload`,{method:'POST',body});if(!response.ok)throw new Error((await response.json().catch(()=>null))?.detail??'PDF upload failed');return response.json()},
  remove:(id:number)=>request<void>(`/api/pdfs/${id}`,{method:'DELETE'}),
  progress:(id:number,page:number,zoom:number)=>request<PDFDocument>(`/api/pdfs/${id}/progress`,{method:'PATCH',body:JSON.stringify({page,zoom})}),
  notes:(id:number)=>request<Note>(`/api/pdfs/${id}/notes`),
  saveNotes:(id:number,content:string)=>request<Note>(`/api/pdfs/${id}/notes`,{method:'PUT',body:JSON.stringify({content})}),
  vocabulary:(id:number)=>request<Vocabulary[]>(`/api/pdfs/${id}/vocabulary`),
}
export type Podcast = {id:number;feed_url:string;title:string;description:string;image_url:string|null;publisher:string;created_at:string;refreshed_at:string;episode_count?:number;latest_episode_at?:string|null}
export type PodcastDirectoryResult = {id:number;title:string;author:string;description:string;artwork_url:string|null;store_url:string|null;has_feed:boolean}
export type PodcastRefresh = {podcast:Podcast;new_episodes:number;not_modified:boolean}
export type PodcastProgress = {id:number;episode_id:number;position_seconds:number;duration_seconds:number|null;playback_speed:number;completed:boolean;updated_at:string}
export type PodcastEpisode = {id:number;podcast_id:number;guid:string;title:string;description:string;audio_url:string|null;image_url:string|null;published_at:string|null;duration_seconds:number|null;transcript_url:string|null;transcript_type:string|null;podcast_title?:string;podcast_image_url?:string|null;progress?:PodcastProgress|null}
export type PodcastSegment = {id:number;episode_id:number;text:string;start:number|null;duration:number|null;is_manual:boolean}
export const podcastApi = {
  all:()=>request<Podcast[]>('/api/podcasts'),
  add:(feed_url:string)=>request<Podcast>('/api/podcasts',{method:'POST',body:JSON.stringify({feed_url})}),
  directory:(q:string)=>request<PodcastDirectoryResult[]>(`/api/podcasts/search?q=${encodeURIComponent(q)}`),
  addFromDirectory:(directory_id:number)=>request<Podcast>('/api/podcasts/from-directory',{method:'POST',body:JSON.stringify({directory_id})}),
  get:(id:number)=>request<Podcast>(`/api/podcasts/${id}`),
  refresh:(id:number)=>request<PodcastRefresh>(`/api/podcasts/${id}/refresh`,{method:'POST'}),
  remove:(id:number)=>request<void>(`/api/podcasts/${id}`,{method:'DELETE'}),
  episodes:(id:number,q='')=>request<PodcastEpisode[]>(`/api/podcasts/${id}/episodes?q=${encodeURIComponent(q)}`),
  search:(q:string)=>request<PodcastEpisode[]>(`/api/podcasts/episodes/search?q=${encodeURIComponent(q)}`),
  episode:(id:number)=>request<PodcastEpisode>(`/api/podcasts/episodes/${id}`),
  progress:(id:number,data:{position_seconds:number;duration_seconds:number|null;playback_speed:number;completed:boolean})=>request<PodcastProgress>(`/api/podcasts/episodes/${id}/progress`,{method:'PATCH',body:JSON.stringify(data)}),
  listened:(id:number,duration_seconds:number|null)=>request<{id:number}>(`/api/podcasts/episodes/${id}/listened`,{method:'POST',body:JSON.stringify({duration_seconds})}),
  transcript:(id:number)=>request<PodcastSegment[]>(`/api/podcasts/episodes/${id}/transcript`),
  manualTranscript:(id:number,text:string)=>request<PodcastSegment[]>(`/api/podcasts/episodes/${id}/transcript/manual`,{method:'PUT',body:JSON.stringify({text})}),
  notes:(id:number)=>request<Note>(`/api/podcasts/episodes/${id}/notes`),
  saveNotes:(id:number,content:string)=>request<Note>(`/api/podcasts/episodes/${id}/notes`,{method:'PUT',body:JSON.stringify({content})}),
  vocabulary:(id:number)=>request<Vocabulary[]>(`/api/vocabulary?episode_id=${id}`),
}
