import { describe, expect, it } from 'vitest'

import {
  KB_SCHEME,
  parseWikilinks,
  preprocessWikilinks,
  splitWikilinks,
} from './wikilink'

/** Build a markdown document out of raw lines. */
const md = (...lines: string[]): string => lines.join('\n')

describe('parseWikilinks', () => {
  it('parses a plain [[target]]', () => {
    expect(parseWikilinks('[[tech-stack]]')).toEqual([{ target: 'tech-stack' }])
  })

  it('parses [[target|alias]] and keeps the alias', () => {
    expect(parseWikilinks('[[tech-stack|技术栈]]')).toEqual([
      { target: 'tech-stack', alias: '技术栈' },
    ])
  })

  it('parses several links in one text', () => {
    expect(parseWikilinks('[[a]] then [[b]]')).toEqual([
      { target: 'a' },
      { target: 'b' },
    ])
  })

  it('trims the target and the alias', () => {
    expect(parseWikilinks('[[  spaced target  |  别名  ]]')).toEqual([
      { target: 'spaced target', alias: '别名' },
    ])
  })

  it('ignores an empty link [[]]', () => {
    expect(parseWikilinks('[[]]')).toEqual([])
  })

  it('ignores an unclosed link [[target', () => {
    expect(parseWikilinks('[[target')).toEqual([])
  })

  it('ignores a link with an empty target [[|alias]]', () => {
    expect(parseWikilinks('[[|alias]]')).toEqual([])
  })

  it('ignores a link that spans a line break', () => {
    expect(parseWikilinks('[[tar\nget]]')).toEqual([])
  })

  it('ignores text without any link', () => {
    expect(parseWikilinks('just plain text')).toEqual([])
  })
})

describe('splitWikilinks', () => {
  it('splits plain text and links into segments', () => {
    expect(splitWikilinks('a [[x]] b')).toEqual([
      { type: 'text', value: 'a ' },
      { type: 'link', value: { target: 'x' } },
      { type: 'text', value: ' b' },
    ])
  })

  it('returns a single link segment when the text is only a link', () => {
    expect(splitWikilinks('[[x]]')).toEqual([
      { type: 'link', value: { target: 'x' } },
    ])
  })

  it('returns a single text segment when there is no link', () => {
    expect(splitWikilinks('plain')).toEqual([
      { type: 'text', value: 'plain' },
    ])
  })

  it('alternates between text and link segments', () => {
    expect(splitWikilinks('one [[a]] two [[b]] three')).toEqual([
      { type: 'text', value: 'one ' },
      { type: 'link', value: { target: 'a' } },
      { type: 'text', value: ' two ' },
      { type: 'link', value: { target: 'b' } },
      { type: 'text', value: ' three' },
    ])
  })

  it('keeps the alias in the link segment', () => {
    expect(splitWikilinks('[[a|b]]')).toEqual([
      { type: 'link', value: { target: 'a', alias: 'b' } },
    ])
  })
})

describe('preprocessWikilinks', () => {
  it('rewrites a wikilink of the running text into a kb:// link', () => {
    expect(preprocessWikilinks('See [[target]] here')).toBe(
      `See [target](${KB_SCHEME}target) here`,
    )
  })

  it('keeps the alias text when rewriting [[target|alias]]', () => {
    expect(preprocessWikilinks('See [[target|alias]] here')).toBe(
      `See [alias](${KB_SCHEME}target) here`,
    )
  })

  it('percent-encodes the target in the href', () => {
    expect(preprocessWikilinks('[[my doc]]')).toBe(
      `[my doc](${KB_SCHEME}my%20doc)`,
    )
  })

  it('rewrites several links on one line', () => {
    expect(preprocessWikilinks('[[a]] and [[b]]')).toBe(
      `[a](${KB_SCHEME}a) and [b](${KB_SCHEME}b)`,
    )
  })

  it('leaves a fenced code block untouched', () => {
    const source = md('```js', 'const a = [[target]]', '```')
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves a tilde fenced code block untouched', () => {
    const source = md('~~~', '[[target]]', '~~~')
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves an unclosed fence untouched (everything below it is code)', () => {
    const source = md('```', '[[target]]', 'still code')
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves an indented code block untouched', () => {
    const source = md('text', '', '    const a = [[target]]')
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves a tab-indented code block untouched', () => {
    const source = md('text', '', '\tconst a = [[target]]')
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves an inline code span untouched', () => {
    const source = 'use `[[target]]` here'
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves an inline code span with a double backtick untouched', () => {
    const source = 'use ``[[target]]`` here'
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves a fenced code block inside a list item untouched', () => {
    const source = md(
      '- item',
      '',
      '  ```js',
      '  const a = [[target]]',
      '  ```',
    )
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('leaves a fenced code block inside a nested list item untouched', () => {
    const source = md(
      '- item',
      '  - nested',
      '',
      '    ```js',
      '    const a = [[target]]',
      '    ```',
    )
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('still rewrites the text around a code block', () => {
    const source = md('before [[target]]', '', '```', '[[inside]]', '```')
    expect(preprocessWikilinks(source)).toBe(
      md(
        `before [target](${KB_SCHEME}target)`,
        '',
        '```',
        '[[inside]]',
        '```',
      ),
    )
  })

  it('does not break ordinary markdown syntax', () => {
    const source = md(
      '# 标题',
      '',
      'A [link](https://example.com) and some `code`.',
      '',
      '| a | b |',
      '| - | - |',
      '| 1 | 2 |',
      '',
      '- list item',
      '> quote',
    )
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('rewrites a wikilink inside a markdown link label', () => {
    expect(preprocessWikilinks('[[target]]')).toBe(
      `[target](${KB_SCHEME}target)`,
    )
  })

  it('keeps the number of lines', () => {
    const source = md('[[a]]', '', '```', '[[b]]', '```', '', '[[c]]')
    const out = preprocessWikilinks(source)
    expect(out.split('\n')).toHaveLength(source.split('\n').length)
  })
})

describe('preprocessWikilinks — list context', () => {
  it('leaves an indented code block inside a list item untouched', () => {
    // CommonMark: 6 spaces inside `- item` (content column 2) is a code
    // block, so the wikilink is literal text, not a link.
    const source = '- item\n\n      [[target]]\n'
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('recognises a fence nested inside a list item', () => {
    // The fence is indented to the list item's content column (4 spaces),
    // which CommonMark allows — the wikilink inside it must stay literal.
    const source = '- item\n\n    ```\n  [[target]]\n    ```\n'
    expect(preprocessWikilinks(source)).toBe(source)
  })

  it('still rewrites a wikilink directly under a list item', () => {
    const source = '- item\n\n  [[target]]\n'
    expect(preprocessWikilinks(source)).toContain('kb://target')
  })
})
