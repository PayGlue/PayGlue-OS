// Copyright (c) 2026 PayGlue by André Nünninghoff
// Licensed under the Business Source License 1.1, see LICENSE.md

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { AxiosError } from 'axios'
import { api, ApiHttpError, setAuthErrorHandler } from '../api'

describe('api auth interceptor', () => {
  beforeEach(() => {
    setAuthErrorHandler(null)
  })

  it('calls auth error handler on 401 only', async () => {
    const handler = vi.fn()
    setAuthErrorHandler(handler)

    const handlers = api.interceptors.response.handlers
    if (!handlers) {
      throw new Error('Missing response interceptors')
    }
    const interceptor = handlers[0]
    if (!interceptor?.rejected) {
      throw new Error('Missing rejected interceptor')
    }

    const unauthorized = new AxiosError('Unauthorized', undefined, undefined, undefined, {
      status: 401,
      statusText: 'Unauthorized',
      config: { headers: {} as never } as never,
      headers: {},
      data: {},
    })

    const forbidden = new AxiosError('Forbidden', undefined, undefined, undefined, {
      status: 403,
      statusText: 'Forbidden',
      config: { headers: {} as never } as never,
      headers: {},
      data: {},
    })

    await expect(interceptor.rejected(unauthorized)).rejects.toBeInstanceOf(AxiosError)
    expect(handler).toHaveBeenCalledTimes(1)

    await expect(interceptor.rejected(forbidden)).rejects.toBeInstanceOf(AxiosError)
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('keeps ApiHttpError shape compatibility', () => {
    const error = new ApiHttpError('Bad request', 400)
    expect(error.message).toBe('Bad request')
    expect(error.status).toBe(400)
  })
})
