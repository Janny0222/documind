import { Download, FolderPlus, Loader2, MoreHorizontal, Pencil, RotateCcw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Field } from '@/components/forms/Field'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  downloadDocument,
  useCollections,
  useDeleteDocument,
  useRenameDocument,
  useReprocessDocument,
  useSetCollectionMembership,
} from '@/features/documents/api'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { toApiError } from '@/lib/api'
import { atLeast, type DocumentItem } from '@/lib/types'

export function DocumentActions({ doc, onDeleted }: { doc: DocumentItem; onDeleted?: () => void }) {
  const workspace = useCurrentWorkspace()
  const canOrganize = atLeast(workspace.role, 'member')
  const { data: collections = [] } = useCollections(workspace.id)
  const membership = useSetCollectionMembership(workspace.id)
  const reprocess = useReprocessDocument(workspace.id)
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${doc.title}`} onClick={(e) => e.stopPropagation()}>
            <MoreHorizontal aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52" onClick={(e) => e.stopPropagation()}>
          <DropdownMenuItem
            onSelect={() => void downloadDocument(workspace.id, doc.id).catch((e) => toast.error(toApiError(e).message))}
          >
            <Download aria-hidden /> Download
          </DropdownMenuItem>
          {canOrganize ? (
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <FolderPlus aria-hidden /> Collections
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="w-52">
                {collections.length === 0 ? (
                  <p className="text-muted-foreground px-2 py-1.5 text-sm">No collections yet</p>
                ) : (
                  collections.map((c) => {
                    const checked = doc.collection_ids.includes(c.id)
                    return (
                      <DropdownMenuCheckboxItem
                        key={c.id}
                        checked={checked}
                        onSelect={(e) => e.preventDefault()} // keep the menu open for several toggles
                        onCheckedChange={(add) =>
                          membership.mutate(
                            { collectionId: c.id, documentIds: [doc.id], add },
                            { onError: (err) => toast.error(toApiError(err).message) },
                          )
                        }
                      >
                        {c.name}
                      </DropdownMenuCheckboxItem>
                    )
                  })
                )}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          ) : null}
          {doc.status === 'failed' && canOrganize ? (
            <DropdownMenuItem
              onSelect={() =>
                reprocess.mutate(doc.id, {
                  onSuccess: () => toast.success('Processing again'),
                  onError: (e) => toast.error(toApiError(e).message),
                })
              }
            >
              <RotateCcw aria-hidden /> Try again
            </DropdownMenuItem>
          ) : null}
          {doc.can_edit ? (
            <>
              <DropdownMenuItem onSelect={() => setRenaming(true)}>
                <Pencil aria-hidden /> Rename
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(true)}>
                <Trash2 aria-hidden /> Delete
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
      <RenameDialog doc={doc} open={renaming} onOpenChange={setRenaming} />
      <DeleteDialog doc={doc} open={deleting} onOpenChange={setDeleting} onDeleted={onDeleted} />
    </>
  )
}

function RenameDialog({ doc, open, onOpenChange }: { doc: DocumentItem; open: boolean; onOpenChange: (o: boolean) => void }) {
  const workspace = useCurrentWorkspace()
  const rename = useRenameDocument(workspace.id)
  const [title, setTitle] = useState(doc.title)
  const trimmed = title.trim()
  return (
    <Dialog open={open} onOpenChange={(o) => (onOpenChange(o), o && setTitle(doc.title))}>
      <DialogContent className="sm:max-w-md" onClick={(e) => e.stopPropagation()}>
        <form
          className="grid gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            rename.mutate(
              { id: doc.id, title: trimmed },
              {
                onSuccess: () => (onOpenChange(false), toast.success('Renamed')),
                onError: (err) => toast.error(toApiError(err).message),
              },
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>Rename document</DialogTitle>
            <DialogDescription>The original file name stays the same for downloads.</DialogDescription>
          </DialogHeader>
          <Field label="Title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} autoFocus />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!trimmed || trimmed === doc.title || rename.isPending}>
              {rename.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteDialog({
  doc,
  open,
  onOpenChange,
  onDeleted,
}: {
  doc: DocumentItem
  open: boolean
  onOpenChange: (o: boolean) => void
  onDeleted?: () => void
}) {
  const workspace = useCurrentWorkspace()
  const del = useDeleteDocument(workspace.id)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" onClick={(e) => e.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>Delete “{doc.title}”?</DialogTitle>
          <DialogDescription>
            The file and its indexed text are removed for everyone in {workspace.name}. Past answers
            keep their quotes but can no longer open the source. This can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={del.isPending}
            onClick={() => {
              // Optimistic: close now; the list already hides the document (restored on error).
              del.mutate(doc.id, {
                onSuccess: () => toast.success(`Deleted ${doc.title}`),
                onError: (err) => toast.error(toApiError(err).message),
              })
              onOpenChange(false)
              onDeleted?.()
            }}
          >
            Delete document
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
