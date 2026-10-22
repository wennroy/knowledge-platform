import { describe, expect, it } from 'vitest'

import { errorMessage } from './load'

describe('errorMessage', () => {
  it('uses the message of an Error', () => {
    expect(errorMessage(new Error('出错了'))).toBe('出错了')
  })

  it('uses a string as it is', () => {
    expect(errorMessage('出错了')).toBe('出错了')
  })

  it('falls back for an unknown value', () => {
    expect(errorMessage(undefined)).toBe('请求失败')
    expect(errorMessage(null)).toBe('请求失败')
    expect(errorMessage({})).toBe('请求失败')
    expect(errorMessage(42)).toBe('请求失败')
  })

  it('falls back for an Error without a message', () => {
    expect(errorMessage(new Error(''))).toBe('请求失败')
  })

  it('uses a custom fallback', () => {
    expect(errorMessage(undefined, '加载文档失败')).toBe('加载文档失败')
    expect(errorMessage('', '加载文档失败')).toBe('加载文档失败')
  })
})
