import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { getFile } from '../api/client'
import type { Citation, FileDoc } from '../api/types'
import { errorMessage, type LoadStatus } from '../lib/load'
import type { DocTarget } from '../lib/reader-target'

export interface OpenDocument {
  currentPath: string | null
  doc: FileDoc | null
  docStatus: LoadStatus
  docError: string | null
  target: DocTarget | null
  selectPath: (path: string) => void
  reloadDoc: () => void
  jumpToCitation: (citation: Citation) => void
  setTarget: (target: DocTarget | null) => void
}

/** Encode a vault-relative path for the URL, keeping the `/` separators. */
function encodeDocPath(path: string): string {
  return path
    .split('/')
    .filter((segment) => segment.length > 0)
    .map(encodeURIComponent)
    .join('/')
}

/**
 * Opens documents (`GET /v1/files/{path}`) and keeps the URL in sync.
 *
 * Selecting a document pushes `/doc/<vault-relative path>` so the reader can
 * be shared and survives a reload; a deep link in turn selects the document.
 */
export function useDocument(): OpenDocument {
  const navigate = useNavigate()
  const location = useLocation()
  const locationRef = useRef(location.pathname)

  useEffect(() => {
    locationRef.current = location.pathname
  }, [location.pathname])

  const [currentPath, setCurrentPath] = useState<string | null>(null)
  const [doc, setDoc] = useState<FileDoc | null>(null)
  const [docStatus, setDocStatus] = useState<LoadStatus>('idle')
  const [docError, setDocError] = useState<string | null>(null)
  const [target, setTarget] = useState<DocTarget | null>(null)

  const currentPathRef = useRef<string | null>(null)
  const docRef = useRef<FileDoc | null>(null)
  const docRequestRef = useRef(0)

  const selectPath = useCallback(
    (path: string) => {
      setCurrentPath(path)
      setTarget(null)

      // Keep the URL in sync so the document can be shared / reloaded.
      const url = `/doc/${encodeDocPath(path)}`
      if (locationRef.current !== url) {
        navigate(url)
      }

      // Same document, already loaded — do not request it again.
      if (
        currentPathRef.current === path &&
        docRef.current?.file_path === path
      ) {
        return
      }
      currentPathRef.current = path
      docRef.current = null
      setDoc(null)

      const requestId = ++docRequestRef.current
      setDocStatus('loading')
      setDocError(null)
      getFile(path)
        .then((file) => {
          if (requestId !== docRequestRef.current) {
            return
          }
          docRef.current = file
          setDoc(file)
          setDocStatus('ready')
        })
        .catch((error: unknown) => {
          if (requestId !== docRequestRef.current) {
            return
          }
          setDoc(null)
          setDocStatus('error')
          setDocError(errorMessage(error, '读取文档失败'))
        })
    },
    [navigate],
  )

  const reloadDoc = useCallback(() => {
    const path = currentPathRef.current
    if (!path) {
      return
    }
    docRef.current = null
    selectPath(path)
  }, [selectPath])

  const jumpToCitation = useCallback(
    (citation: Citation) => {
      selectPath(citation.file_path)
      setTarget({
        mode: 'heading',
        start: citation.start_offset,
        end: citation.end_offset,
        text: citation.text,
      })
    },
    [selectPath],
  )

  return {
    currentPath,
    doc,
    docStatus,
    docError,
    target,
    selectPath,
    reloadDoc,
    jumpToCitation,
    setTarget,
  }
}
