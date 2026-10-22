import { useEffect, useRef, useState } from 'react'

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

/** The outcome of an upload, ready to be shown to the user. */
interface UploadOutcome {
  tone: 'ok' | 'warn' | 'error'
  message: string
}

/**
 * Maps the backend's `status` onto a message.
 *
 * The backend parses *and* indexes synchronously before it answers, so
 * `ok` means "fully done". `skipped` is a duplicate file, `failed` carries
 * the reason in `error`.
 */
function describeUpload(result: UploadResponse): UploadOutcome {
  const detail = result.error?.trim()
  switch (result.status) {
    // The backend reports the *index* status, which is `ok` / `failed`.
    // `indexed` is accepted too, in case the backend ever switches to it.
    case 'ok':
    case 'indexed':
      return {
        tone: 'ok',
        message: `已上传并建立索引（${result.chunks} 个片段）${
          result.file_path ? `：${result.file_path}` : ''
        }`,
      }
    case 'skipped':
      return {
        tone: 'warn',
        message: `已上传：重复文件，已跳过${detail ? `（${detail}）` : ''}`,
      }
    case 'failed':
      return {
        tone: 'error',
        message: `上传失败${detail ? `：${detail}` : ''}`,
      }
    default:
      return {
        tone: 'ok',
        message: `已上传（状态：${result.status}）`,
      }
  }
}

/**
 * Modal for uploading a document into the vault.
 *
 * The backend accepts one file per request (`POST /v1/files`), so the dialog
 * works with a single file — dropped onto the zone or picked with the file
 * input.
 */
export function UploadDialog({ open, onClose, onUploaded }: UploadDialogProps) {
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<UploadOutcome | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  /** True once the bytes are sent and the backend is parsing / indexing. */
  const [parsing, setParsing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Reset the dialog state when it is closed, so the next upload starts
  // from a clean slate.
  useEffect(() => {
    if (open) {
      return
    }
    setProgress(null)
    setError(null)
    setOutcome(null)
    setBusy(false)
    setDragging(false)
    setParsing(false)
  }, [open])

  if (!open) {
    return null
  }

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    setOutcome(null)
    setParsing(false)
    setProgress(0)
    try {
      const result = await uploadFile(file, (percent) => {
        setProgress(percent)
        // The body is on the wire — the backend now parses and indexes it,
        // which can take a while for a big PDF.
        if (percent >= 100) {
          setParsing(true)
        }
      })
      setOutcome(describeUpload(result))
      onUploaded(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
    } finally {
      setBusy(false)
      setProgress(null)
      setParsing(false)
    }
  }

  const handleFiles = (files: FileList | File[] | null) => {
    if (!files) {
      return
    }
    const list = Array.from(files)
    if (list.length === 0) {
      return
    }
    // The backend takes one file per request — extra files are ignored.
    void upload(list[0])
  }

  return (
    <div
      className="modal-backdrop"
      onClick={() => {
        // Do not close the dialog while an upload is running.
        if (!busy) {
          onClose()
        }
      }}
    >
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
            支持 Markdown / PDF / Office / TXT 文档。文件会被解析并写入知识库，随后建立索引。
          </p>

          <div
            className={`dropzone${dragging ? ' is-dragging' : ''}`}
            role="button"
            tabIndex={0}
            aria-label="拖拽文件到此处上传"
            onClick={() => inputRef.current?.click()}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                inputRef.current?.click()
              }
            }}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              handleFiles(event.dataTransfer?.files ?? null)
            }}
          >
            <p className="dropzone-title">把文件拖到这里</p>
            <p className="dropzone-hint">或点击选择文件</p>
            <input
              ref={inputRef}
              type="file"
              className="file-input"
              aria-label="选择要上传的文件"
              onClick={(event) => {
                // The dropzone opens the file chooser itself — without this
                // the click would bubble up and open a second one.
                event.stopPropagation()
              }}
              onChange={(event) => {
                handleFiles(event.target.files)
                // Allow picking the same file again after a reset.
                event.target.value = ''
              }}
            />
          </div>

          {progress !== null ? (
            <div className="progress">
              <div className="progress-bar" style={{ width: `${progress}%` }} />
              <span className="progress-label">{progress}%</span>
            </div>
          ) : null}

          {parsing ? (
            <p className="upload-hint">已上传，正在解析并建立索引…</p>
          ) : null}

          {outcome ? (
            <p
              className={
                outcome.tone === 'error'
                  ? 'error-text'
                  : outcome.tone === 'warn'
                    ? 'upload-warn'
                    : 'upload-ok'
              }
            >
              {outcome.message}
            </p>
          ) : null}

          {error ? <p className="error-text">上传失败：{error}</p> : null}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {outcome ? '完成' : '取消'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? '上传中…' : '选择文件'}
          </button>
        </div>
      </div>
    </div>
  )
}
