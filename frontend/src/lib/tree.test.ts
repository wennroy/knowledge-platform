import { describe, expect, it } from 'vitest'

import type { TreeNode } from '../api/types'
import { ancestorsOf, flattenTree } from './tree'

const tree: TreeNode[] = [
  {
    name: 'docs',
    type: 'dir',
    path: 'docs',
    children: [
      { name: 'a.md', type: 'file', path: 'docs/a.md' },
      {
        name: 'sub',
        type: 'dir',
        path: 'docs/sub',
        children: [
          { name: 'b.md', type: 'file', path: 'docs/sub/b.md' },
          { name: 'c.md', type: 'file', path: 'docs/sub/c.md' },
        ],
      },
    ],
  },
  { name: 'readme.md', type: 'file', path: 'readme.md' },
]

describe('flattenTree', () => {
  it('lists the root nodes with depth 0', () => {
    const rows = flattenTree(tree, new Set())
    expect(rows.map((row) => row.node.path)).toEqual(['docs', 'readme.md'])
    expect(rows.every((row) => row.depth === 0)).toBe(true)
  })

  it('does not expand a directory that is not expanded', () => {
    const rows = flattenTree(tree, new Set())
    expect(rows.some((row) => row.node.path === 'docs/a.md')).toBe(false)
  })

  it('expands an expanded directory with depth + 1', () => {
    const rows = flattenTree(tree, new Set(['docs']))
    expect(rows.map((row) => row.node.path)).toEqual([
      'docs',
      'docs/a.md',
      'docs/sub',
      'readme.md',
    ])
    expect(rows.find((row) => row.node.path === 'docs/a.md')?.depth).toBe(1)
  })

  it('expands nested directories', () => {
    const rows = flattenTree(tree, new Set(['docs', 'docs/sub']))
    expect(rows.map((row) => row.node.path)).toEqual([
      'docs',
      'docs/a.md',
      'docs/sub',
      'docs/sub/b.md',
      'docs/sub/c.md',
      'readme.md',
    ])
    expect(rows.find((row) => row.node.path === 'docs/sub/b.md')?.depth).toBe(2)
  })

  it('returns an empty list for an empty tree', () => {
    expect(flattenTree([], new Set(['docs']))).toEqual([])
  })
})

describe('ancestorsOf', () => {
  it('returns the directories that contain the file', () => {
    expect(ancestorsOf(tree, 'docs/a.md')).toEqual(['docs'])
  })

  it('returns every directory of a deeply nested file', () => {
    expect(ancestorsOf(tree, 'docs/sub/b.md')).toEqual(['docs', 'docs/sub'])
  })

  it('returns an empty list for a file in the root', () => {
    expect(ancestorsOf(tree, 'readme.md')).toEqual([])
  })

  it('returns an empty list for an unknown path', () => {
    expect(ancestorsOf(tree, 'docs/missing.md')).toEqual([])
    expect(ancestorsOf(tree, 'missing.md')).toEqual([])
  })

  it('does not leak the directories of a sibling branch', () => {
    expect(ancestorsOf(tree, 'readme.md')).not.toContain('docs')
  })
})
