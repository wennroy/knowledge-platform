import { describe, expect, it } from 'vitest'

import type { IndexStatus } from '../api/types'
import { mapIndexStatus } from './use-index-status'

function row(filePath: string): IndexStatus {
  return {
    file_path: filePath,
    file_hash: 'hash',
    chunk_count: 3,
    status: 'indexed',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

describe('mapIndexStatus', () => {
  it('maps a vault-relative path onto itself', () => {
    const status = row('notes/a.md')
    const map = mapIndexStatus([status], ['notes/a.md'])
    expect(map.get('notes/a.md')).toBe(status)
  })

  it('maps an absolute path onto the vault-relative one', () => {
    const status = row('/srv/vault/notes/a.md')
    const map = mapIndexStatus([status], ['notes/a.md'])
    expect(map.get('notes/a.md')).toBe(status)
  })

  it('maps a windows path onto the vault-relative one', () => {
    const status = row('C:\\vault\\notes\\a.md')
    const map = mapIndexStatus([status], ['notes/a.md'])
    expect(map.get('notes/a.md')).toBe(status)
  })

  it('prefers the longest matching path', () => {
    const status = row('/srv/vault/team/api.md')
    const map = mapIndexStatus([status], ['api.md', 'team/api.md'])
    expect(map.get('team/api.md')).toBe(status)
    expect(map.get('api.md')).toBeUndefined()
  })

  it('ignores a row that matches no path', () => {
    const map = mapIndexStatus([row('/srv/vault/other.md')], ['notes/a.md'])
    expect(map.size).toBe(0)
  })

  it('returns an empty map for an empty list of rows', () => {
    expect(mapIndexStatus([], ['notes/a.md']).size).toBe(0)
  })
})
