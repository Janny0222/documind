import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw/http'
import { describe, expect, it } from 'vitest'
import { precheck, useUploads } from '@/features/documents/uploads'
import type { DocumentItem } from '@/lib/types'
import { renderApp } from '@/test/render'
import { API, server, signedIn, testWorkspace } from '@/test/server'

const doc = (over: Partial<DocumentItem> = {}): DocumentItem => ({
  id: 'd1',
  title: 'Employee Handbook',
  original_filename: 'Employee Handbook.pdf',
  file_type: 'pdf',
  mime_type: 'application/pdf',
  size_bytes: 1_250_000,
  status: 'ready',
  error_code: null,
  error_message: null,
  page_count: 42,
  page_unit: 'page',
  chunk_count: 80,
  collection_ids: [],
  uploaded_by: { id: 'u1', display_name: 'Jan Reyes' },
  can_edit: true,
  created_at: new Date().toISOString(),
  indexed_at: new Date().toISOString(),
  ...over,
})

const list = (items: DocumentItem[]) =>
  HttpResponse.json({
    items,
    total: items.length,
    counts: {
      all: items.length,
      pdf: items.filter((d) => d.file_type === 'pdf').length,
      docx: items.filter((d) => d.file_type === 'docx').length,
      txt: items.filter((d) => d.file_type === 'txt').length,
    },
  })

const file = (name: string, size = 10, type = 'application/pdf') => new File([new Uint8Array(size)], name, { type })

describe('upload precheck', () => {
  it('accepts supported files and explains the rest', () => {
    expect(precheck(file('a.PDF'))).toBeNull()
    expect(precheck(file('a.docx'))).toBeNull()
    expect(precheck(file('old.doc'))).toMatch(/\.doc files/)
    expect(precheck(file('pic.png'))).toMatch(/Only PDF, DOCX and TXT/)
    expect(precheck(file('empty.txt', 0))).toMatch(/empty/)
    expect(precheck(file('big.pdf', 11 * 1024 * 1024))).toMatch(/10 MB/)
  })
})

async function openDocuments(path = `/w/${testWorkspace.id}/documents`) {
  const app = renderApp(path)
  await screen.findByRole('heading', { name: 'Documents' }, { timeout: 5000 })
  return app
}

describe('documents page', () => {
  it('lists documents with type counts and status', async () => {
    server.use(
      http.get(`${API}/workspaces/:id/documents`, () =>
        list([doc(), doc({ id: 'd2', title: 'Scanned contract', status: 'failed', error_message: 'No text' })]),
      ),
      ...signedIn(), // last: the handlers above take precedence
    )
    await openDocuments()
    expect(await screen.findByRole('button', { name: 'Employee Handbook' })).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^PDF/ })).toHaveTextContent('2')
  })

  it('sends filters to the API and keeps them in the URL', async () => {
    const seen: string[] = []
    server.use(
      http.get(`${API}/workspaces/:id/documents`, ({ request }) => {
        seen.push(new URL(request.url).search)
        return list([doc()])
      }),
      ...signedIn(), // last: the handlers above take precedence
    )
    const { user, router } = await openDocuments()
    await user.click(await screen.findByRole('button', { name: /^Word/ }))
    await waitFor(() => expect(router.state.location.search).toContain('type=docx'))
    await waitFor(() => expect(seen.some((s) => s.includes('type=docx'))).toBe(true))
  })

  it('uploads a file and reports the result per file', async () => {
    let received: string | null = null
    server.use(
      http.post(`${API}/workspaces/:id/documents`, async ({ request }) => {
        // Read the raw multipart body: Node's formData() parser rejects jsdom's File objects
        // (a test-environment mismatch; browsers send the same bytes).
        const body = await request.text()
        received = /filename="([^"]+)"/.exec(body)?.[1] ?? null
        return HttpResponse.json([{ filename: received, outcome: 'created', document: doc({ status: 'queued' }), code: null, detail: null }])
      }),
      ...signedIn(), // last: the handlers above take precedence
    )
    document.cookie = 'dm_csrf=t; path=/'
    const { user } = await openDocuments()
    const input = document.querySelector('input[type=file]') as HTMLInputElement
    await user.upload(input, [file('handbook.pdf', 2048), file('notes.doc', 10)])

    const tray = await screen.findByRole('complementary', { name: 'Uploads' })
    await waitFor(() => expect(within(tray).getByText('Uploaded')).toBeInTheDocument())
    // The .doc was rejected locally, before any bandwidth was spent.
    expect(within(tray).getByText(/\.doc files/)).toBeInTheDocument()
    expect(received).toBe('handbook.pdf')
    useUploads.setState({ items: [] })
  })

  it('hides upload for viewers', async () => {
    server.use(...signedIn(undefined, [{ ...testWorkspace, role: 'viewer', is_personal: false }]))
    await openDocuments()
    expect(await screen.findByText(/Members of this workspace can upload/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument()
  })
})
