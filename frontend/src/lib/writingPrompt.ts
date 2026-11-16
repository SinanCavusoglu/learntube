export function buildWritingPrompt(taskType:1|2, question:string, essay:string):string {
  const firstCriterion=taskType===1?'Task Achievement':'Task Response'
  const visualReminder=taskType===1?'If this Task 1 question depends on a chart, map, diagram, or other image, I will attach the original visual separately. Do not invent or assume visual details that are not provided.\n\n':''
  return `Evaluate my IELTS Writing Task ${taskType} response. This is practice feedback; any band score is an estimate, not an official IELTS score.

Assess these four criteria separately:
1. ${firstCriterion}
2. Coherence and Cohesion
3. Lexical Resource
4. Grammatical Range and Accuracy

Please:
- Estimate an overall IELTS band range and explain the estimate.
- Give criterion-by-criterion feedback.
- Identify grammar mistakes and suggest specific corrections.
- Identify unnatural vocabulary and suggest more natural expressions.
- Evaluate paragraph organization and logical flow.
- Give practical priorities for improvement.

${visualReminder}Question (verbatim):
${question}

Essay (verbatim):
${essay}`
}
