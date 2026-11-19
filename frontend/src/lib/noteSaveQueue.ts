const writes = new Map<string, Promise<void>>()

// Keep writes for the same note in order, including across route remounts.
export function queueNoteSave(key: string, save: () => Promise<unknown>): Promise<void> {
  const previous = writes.get(key) ?? Promise.resolve()
  const next = previous.catch(() => undefined).then(save).then(() => undefined)
  writes.set(key, next)
  void next.finally(() => {
    if (writes.get(key) === next) writes.delete(key)
  }).catch(() => undefined)
  return next
}
