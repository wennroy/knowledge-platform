import type {
  FileDoc,
  IndexStatus,
  SearchResult,
  TreeNode,
  UploadResponse,
} from './types'

/**
 * The API is mounted on the same origin under `/v1` — NOT under the SPA's
 * `/app` base path — so every request uses an absolute path.
 */
const API_BASE = '/v1'

/** Encode a vault-relative path while keeping the `/` separators intact. */
function encodePath(path: string): string {
  return path
    .split('/')
    .filter((segment) => segment.length > 0)
    .map(encodeURIComponent)
    .join('/')
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string') {
        detail = body.detail
      } else if (body?.detail) {
        detail = JSON.stringify(body.detail)
      }
    } catch {
      // Non-JSON error body — keep the status line.
    }
    throw new Error(detail)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** `GET /v1/tree` — the nested document tree. */
export async function getTree(): Promise<TreeNode[]> {
  const data = await request<{ tree?: TreeNode[] }>(`${API_BASE}/tree`)
  return data.tree ?? []
}

/** `GET /v1/files/{path}` — one markdown document. */
export async function getFile(path: string): Promise<FileDoc> {
  return request<FileDoc>(`${API_BASE}/files/${encodePath(path)}`)
}

/** `GET /v1/search?q=` — grep-style full-text search. */
export async function search(query: string): Promise<SearchResult[]> {
  const data = await request<{ results?: SearchResult[] }>(
    `${API_BASE}/search?q=${encodeURIComponent(query)}`,
  )
  return data.results ?? []
}

/**
 * `POST /v1/files` — upload a document.
 *
 * Uses XHR (not fetch) so we can report upload progress.
 */
export async function uploadFile(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/files`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResponse)
        } catch (error) {
          reject(error)
        }
        return
      }
      reject(new Error(`upload failed with status ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('upload failed'))
    xhr.onabort = () => reject(new Error('upload aborted'))

    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

/** `DELETE /v1/files/{path}` — remove a document from the vault. */
export async function deleteFile(path: string): Promise<void> {
  await request<void>(`${API_BASE}/files/${encodePath(path)}`, {
    method: 'DELETE',
  })
}

/** `GET /admin/index/status` — indexing status of every known document. */
export async function getIndexStatus(): Promise<IndexStatus[]> {
  const data = await request<{ items?: IndexStatus[] }>('/admin/index/status')
  return data.items ?? []
}

/** `GET /healthz` — backend liveness, used for the gateway status dot. */
export async function getHealth(): Promise<boolean> {
  try {
    await request<{ ok?: boolean }>('/healthz')
    return true
  } catch {
    return false
  }
}
