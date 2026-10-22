import { useRef, useState } from 'react'

import { uploadFile } from '../api/client'
import type { UploadResponse } from '../api/types'

export interface UploadDialogProps {
  /** Whether the dialog is open. */
  open: boolean
  /** Called when the dialog should close. */
  onClose: () => void
  /** Called with the backend response after a successful upload. */
  onUploaded: (result: UploadResponse) => void
}

/**
 * Modal for uploading a document into the vault.
 */
export function UploadDialog({ open, onClose, onUploaded }: UploadDialogProps) {
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  if (!open) {
    return null
  }

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) {
      return
    }
    setBusy(true)
    setError(null)
    setProgress(0)
    try {
      for (const file of Array.from(files)) {
        const result = await uploadFile(file, setProgress)
        onUploaded(result)
      }
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
    } finally {
      setBusy(false)
      setProgress(null)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-label="上传文档"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <span className="modal-title">上传文档</span>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>

        <div className="modal-body">
          <p className="empty-hint">
            支持 Markdown / PDF / Office 文档。文件会被解析并写入知识库，随后建立索引。
          </p>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="file-input"
            onChange={(event) => void handleFiles(event.target.files)}
          />
          {progress !== null ? (
            <div className="progress">
              <div className="progress-bar" style={{ width: `${progress}%` }} />
              <span className="progress-label">{progress}%</span>
            </div>
          ) : null}
          {error ? <p className="error-text">{error}</p> : null}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => void handleFiles(inputRef.current?.files ?? null)}
          >
            {busy ? '上传中…' : '开始上传'}
          </button>
        </div>
      </div>
    </div>
  )
}
