import { ArrowLeft, FolderOpen, Loader2, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { EmptyState, PageHeader, Tile } from '@/components/EmptyState'
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
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useCollections,
  useCreateCollection,
  useDeleteCollection,
  useDocuments,
  useUpdateCollection,
} from '@/features/documents/api'
import { FileTypeIcon, StatusBadge } from '@/features/documents/components/bits'
import { timeAgo } from '@/features/documents/format'
import { useCurrentWorkspace } from '@/features/workspaces/current'
import { wsPath } from '@/layouts/nav'
import { toApiError } from '@/lib/api'
import { atLeast, type Collection } from '@/lib/types'

export function CollectionsPage() {
  const workspace = useCurrentWorkspace()
  const canEdit = atLeast(workspace.role, 'member')
  const { data: collections, isPending } = useCollections(workspace.id)
  const [creating, setCreating] = useState(false)

  return (
    <>
      <PageHeader
        title="Collections"
        description="Group related documents, then ask questions across the whole set."
        actions={
          canEdit ? (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden /> New collection
            </Button>
          ) : null
        }
      />
      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      ) : !collections?.length ? (
        <Tile>
          <EmptyState
            icon={FolderOpen}
            title="No collections yet"
            action={canEdit ? <Button onClick={() => setCreating(true)}>Create a collection</Button> : null}
          >
            For example “Contracts 2026” or “HR policies”. A document can be in several collections.
          </EmptyState>
        </Tile>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {collections.map((c) => (
            <li key={c.id}>
              <Link
                to={wsPath(workspace.id, `collections/${c.id}`)}
                className="bg-card hover:border-primary/40 block h-full rounded-xl border p-5 transition-colors"
              >
                <FolderOpen className="text-primary size-5" aria-hidden />
                <h2 className="mt-3 font-semibold">{c.name}</h2>
                {c.description ? <p className="text-muted-foreground mt-1 line-clamp-2 text-sm">{c.description}</p> : null}
                <p className="text-muted-foreground mt-3 text-xs">
                  {c.document_count} document{c.document_count === 1 ? '' : 's'}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <CollectionDialog open={creating} onOpenChange={setCreating} />
    </>
  )
}

export function CollectionDetailPage() {
  const workspace = useCurrentWorkspace()
  const { collectionId = '' } = useParams()
  const navigate = useNavigate()
  const { data: collections, isPending } = useCollections(workspace.id)
  const collection = collections?.find((c) => c.id === collectionId)
  const { data: docs } = useDocuments(workspace.id, { collection_id: collectionId })
  const del = useDeleteCollection(workspace.id)
  const [editing, setEditing] = useState(false)
  const canEdit = atLeast(workspace.role, 'member')

  if (isPending) return <Skeleton className="h-40 rounded-xl" />
  if (!collection) return <Navigate to={wsPath(workspace.id, 'collections')} replace />

  return (
    <>
      <Link
        to={wsPath(workspace.id, 'collections')}
        className="text-muted-foreground hover:text-foreground mb-3 inline-flex items-center gap-1 text-sm"
      >
        <ArrowLeft className="size-4" aria-hidden /> Collections
      </Link>
      <PageHeader
        title={collection.name}
        description={collection.description ?? `${collection.document_count} documents`}
        actions={
          canEdit ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Collection actions">
                  <MoreHorizontal aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditing(true)}>
                  <Pencil aria-hidden /> Edit details
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() =>
                    del.mutate(collection.id, {
                      onSuccess: () => {
                        toast.success(`Deleted ${collection.name}. Its documents are still in the workspace.`)
                        navigate(wsPath(workspace.id, 'collections'), { replace: true })
                      },
                      onError: (e) => toast.error(toApiError(e).message),
                    })
                  }
                >
                  <Trash2 aria-hidden /> Delete collection
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null
        }
      />
      <Tile>
        {!docs?.items.length ? (
          <EmptyState icon={FolderOpen} title="This collection is empty" action={
            <Button variant="outline" asChild>
              <Link to={wsPath(workspace.id, 'documents')}>Go to documents</Link>
            </Button>
          }>
            Add documents from their menu on the Documents page (Collections → {collection.name}).
          </EmptyState>
        ) : (
          <ul className="divide-y">
            {docs.items.map((doc) => (
              <li key={doc.id}>
                <Link
                  to={`${wsPath(workspace.id, 'documents')}?doc=${doc.id}`}
                  className="hover:bg-muted/50 -mx-2 flex items-center gap-3 rounded-lg px-2 py-3"
                >
                  <FileTypeIcon type={doc.file_type} className="size-9" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{doc.title}</span>
                    <span className="text-muted-foreground text-xs">Added {timeAgo(doc.created_at)}</span>
                  </span>
                  <StatusBadge doc={doc} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Tile>
      <CollectionDialog open={editing} onOpenChange={setEditing} collection={collection} />
    </>
  )
}

function CollectionDialog({
  open,
  onOpenChange,
  collection,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  collection?: Collection
}) {
  const workspace = useCurrentWorkspace()
  const create = useCreateCollection(workspace.id)
  const update = useUpdateCollection(workspace.id)
  const navigate = useNavigate()
  const [name, setName] = useState(collection?.name ?? '')
  const [description, setDescription] = useState(collection?.description ?? '')
  const [error, setError] = useState<string | null>(null)
  const pending = create.isPending || update.isPending

  const reset = () => {
    setName(collection?.name ?? '')
    setDescription(collection?.description ?? '')
    setError(null)
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const body = { name: name.trim(), description: description.trim() }
    const onError = (err: unknown) => {
      const apiError = toApiError(err)
      setError(apiError.code === 'collection_exists' ? 'A collection with this name already exists.' : apiError.message)
    }
    if (collection) {
      update.mutate({ id: collection.id, ...body }, { onSuccess: () => onOpenChange(false), onError })
    } else {
      create.mutate(body, {
        onSuccess: (c) => {
          onOpenChange(false)
          toast.success(`Created ${c.name}`)
          navigate(wsPath(workspace.id, `collections/${c.id}`))
        },
        onError,
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (onOpenChange(o), o && reset())}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="grid gap-5">
          <DialogHeader>
            <DialogTitle>{collection ? 'Edit collection' : 'New collection'}</DialogTitle>
            <DialogDescription>Collections group documents. Deleting one never deletes its documents.</DialogDescription>
          </DialogHeader>
          <Field label="Name" value={name} onChange={(e) => (setName(e.target.value), setError(null))} maxLength={80} error={error ?? undefined} autoFocus />
          <Field label="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? <Loader2 className="animate-spin" aria-hidden /> : null}
              {collection ? 'Save' : 'Create collection'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
