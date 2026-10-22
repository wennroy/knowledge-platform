import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearMarks,
  deriveHeading,
  findHeadingElement,
  findTextRange,
  normalizeText,
  resolveRange,
} from './reader-target'

/** Build a detached DOM element with the given html. */
function dom(html: string): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = html
  document.body.appendChild(root)
  return root
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('normalizeText', () => {
  it('drops punctuation and lower-cases the rest', () => {
    expect(normalizeText('Hello, World!')).toBe('helloworld')
  })

  it('drops every kind of whitespace', () => {
    expect(normalizeText('  多  空格\t换行\n结束  ')).toBe('多空格换行结束')
  })

  it('trims the leading and trailing whitespace', () => {
    expect(normalizeText('   spaced   ')).toBe('spaced')
  })

  it('keeps CJK characters', () => {
    expect(normalizeText('技术栈')).toBe('技术栈')
  })

  it('keeps ASCII letters and digits', () => {
    expect(normalizeText('abc123')).toBe('abc123')
  })

  it('keeps full-width letters and drops full-width punctuation', () => {
    expect(normalizeText('ＡＢＣ！')).toBe('ａｂｃ')
  })

  it('returns an empty string for text without significant characters', () => {
    expect(normalizeText('!!! ??? ---')).toBe('')
  })

  it('returns an empty string for empty input', () => {
    expect(normalizeText('')).toBe('')
  })

  it('is idempotent', () => {
    const once = normalizeText('Hello, World!')
    expect(normalizeText(once)).toBe(once)
  })
})

describe('deriveHeading', () => {
  const content = [
    '# 一级标题',
    '',
    '正文一',
    '',
    '## 二级标题',
    '',
    '正文二',
  ].join('\n')

  it('finds the heading of the first section for offset 0', () => {
    expect(deriveHeading(content, 0)).toBe('一级标题')
  })

  it('finds the heading that contains the offset', () => {
    expect(deriveHeading(content, content.indexOf('正文二'))).toBe('二级标题')
  })

  it('finds the heading for an offset inside the heading line itself', () => {
    expect(deriveHeading(content, content.indexOf('二级标题') + 1)).toBe('二级标题')
  })

  it('keeps the first heading for an offset before the second one', () => {
    expect(deriveHeading(content, content.indexOf('正文一'))).toBe('一级标题')
  })

  it('returns null for an offset before the first heading', () => {
    expect(deriveHeading('前言\n# 标题', 0)).toBeNull()
  })

  it('returns null for an offset inside the text before the first heading', () => {
    expect(deriveHeading('前言\n# 标题', 2)).toBeNull()
  })

  it('returns null for an empty document', () => {
    expect(deriveHeading('', 0)).toBeNull()
  })
})

describe('resolveRange', () => {
  const content = 'hello world'

  it('clamps a negative start to 0', () => {
    expect(resolveRange(content, { mode: 'exact', start: -10, end: 5 })).toEqual({
      start: 0,
      end: 5,
    })
  })

  it('clamps an end beyond the content length', () => {
    expect(resolveRange(content, { mode: 'exact', start: 6, end: 999 })).toEqual({
      start: 6,
      end: 11,
    })
  })

  it('clamps both ends when they are out of range', () => {
    expect(resolveRange(content, { mode: 'exact', start: -5, end: 999 })).toEqual({
      start: 0,
      end: 11,
    })
  })

  it('clamps a start beyond the content length', () => {
    expect(resolveRange(content, { mode: 'exact', start: 999, end: 999 })).toEqual({
      start: 11,
      end: 11,
    })
  })

  it('never returns an end before the start', () => {
    expect(resolveRange(content, { mode: 'exact', start: 8, end: 3 })).toEqual({
      start: 8,
      end: 8,
    })
  })

  it('does not throw for a negative offset', () => {
    expect(() =>
      resolveRange(content, { mode: 'exact', start: -1, end: -1 }),
    ).not.toThrow()
    expect(resolveRange(content, { mode: 'exact', start: -1, end: -1 })).toEqual({
      start: 0,
      end: 0,
    })
  })

  it('returns null for a target without any offset', () => {
    expect(resolveRange(content, { mode: 'exact', text: 'hello' })).toBeNull()
  })

  it('returns null for an empty body', () => {
    expect(resolveRange('', { mode: 'heading' })).toBeNull()
  })

  it('clamps the offsets of an empty body to zero', () => {
    expect(resolveRange('', { mode: 'exact', start: 0, end: 42 })).toEqual({
      start: 0,
      end: 0,
    })
  })

  it('resolves a 1-based line number', () => {
    const doc = '第一行\n第二行\n第三行'
    expect(resolveRange(doc, { mode: 'heading', line: 2 })).toEqual({
      start: 4,
      end: 7,
    })
  })

  it('returns null for a line number beyond the document', () => {
    expect(resolveRange(content, { mode: 'heading', line: 99 })).toBeNull()
  })

  it('returns null for a line number below 1', () => {
    expect(resolveRange(content, { mode: 'heading', line: 0 })).toBeNull()
  })
})

describe('findTextRange', () => {
  it('finds a plain text', () => {
    const root = dom('<p>Hello <strong>World</strong></p>')
    const range = findTextRange(root, 'Hello World')
    expect(range).not.toBeNull()
    expect(range?.toString()).toBe('Hello World')
  })

  it('matches through markdown syntax that disappears in the DOM', () => {
    const root = dom('<p>Hello <strong>World</strong></p>')
    const range = findTextRange(root, '**World**')
    expect(range?.toString()).toBe('World')
  })

  it('is insensitive to the case and to whitespace', () => {
    const root = dom('<p>Hello World</p>')
    expect(findTextRange(root, 'hello world')?.toString()).toBe('Hello World')
    expect(findTextRange(root, 'hello    world')?.toString()).toBe('Hello World')
  })

  it('returns null when the text is not in the DOM', () => {
    const root = dom('<p>Hello World</p>')
    expect(findTextRange(root, 'missing')).toBeNull()
  })

  it('returns null for a needle without significant characters', () => {
    const root = dom('<p>Hello World</p>')
    expect(findTextRange(root, '   ')).toBeNull()
  })

  it('skips the text before the `after` element', () => {
    const root = dom('<p id="a">first</p><p id="b">second</p><p id="c">third</p>')
    const after = root.querySelector('#b')
    // The text before `after` is not searched any more …
    expect(findTextRange(root, 'first', after)).toBeNull()
    // … the text after it is.
    expect(findTextRange(root, 'third', after)?.toString()).toBe('third')
  })

  it('still searches the text inside the `after` element itself', () => {
    const root = dom('<p id="a">first</p><p id="b">second</p>')
    const after = root.querySelector('#a')
    expect(findTextRange(root, 'first', after)?.toString()).toBe('first')
    expect(findTextRange(root, 'second', after)?.toString()).toBe('second')
  })

  it('ignores the content of script and style elements', () => {
    const root = dom('<script>var hidden = 1</script><p>visible</p>')
    expect(findTextRange(root, 'hidden')).toBeNull()
    expect(findTextRange(root, 'visible')?.toString()).toBe('visible')
  })
})

describe('findHeadingElement', () => {
  it('finds the heading with the given text', () => {
    const root = dom('<h2>技术栈</h2><h3>数据库</h3>')
    expect(findHeadingElement(root, '技术栈')?.tagName).toBe('H2')
    expect(findHeadingElement(root, '数据库')?.tagName).toBe('H3')
  })

  it('ignores whitespace inside the heading text', () => {
    const root = dom('<h2>技术 栈</h2>')
    expect(findHeadingElement(root, '技术栈')?.tagName).toBe('H2')
  })

  it('returns null when there is no such heading', () => {
    const root = dom('<h2>技术栈</h2>')
    expect(findHeadingElement(root, '不存在')).toBeNull()
  })

  it('returns null for an empty text', () => {
    const root = dom('<h2>技术栈</h2>')
    expect(findHeadingElement(root, '')).toBeNull()
  })
})

describe('clearMarks', () => {
  it('removes the mark and keeps the text', () => {
    const root = dom('<p>a <mark class="hl">b</mark> c</p>')
    clearMarks(root, 'hl')
    expect(root.querySelectorAll('mark.hl')).toHaveLength(0)
    expect(root.textContent).toBe('a b c')
  })

  it('keeps the child elements of the mark', () => {
    const root = dom('<p><mark class="hl"><em>bold</em></mark></p>')
    clearMarks(root, 'hl')
    expect(root.querySelectorAll('mark')).toHaveLength(0)
    expect(root.querySelector('em')).not.toBeNull()
    expect(root.textContent).toBe('bold')
  })

  it('does not touch a mark with a different class', () => {
    const root = dom('<p><mark class="other">x</mark></p>')
    clearMarks(root, 'hl')
    expect(root.querySelectorAll('mark.other')).toHaveLength(1)
    expect(root.textContent).toBe('x')
  })

  it('removes every mark of the class', () => {
    const root = dom(
      '<p><mark class="hl">one</mark> <mark class="hl">two</mark></p>',
    )
    clearMarks(root, 'hl')
    expect(root.querySelectorAll('mark.hl')).toHaveLength(0)
    expect(root.textContent).toBe('one two')
  })

  it('does nothing when there is no mark', () => {
    const root = dom('<p>plain</p>')
    clearMarks(root, 'hl')
    expect(root.innerHTML).toBe('<p>plain</p>')
  })
})
