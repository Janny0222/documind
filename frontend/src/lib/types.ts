/**
 * API types mirroring backend/app/schemas. Hand-written for Phase 3 (small surface);
 * Phase 4 switches to types generated from the FastAPI OpenAPI schema.
 */

export type Theme = 'system' | 'light' | 'dark'
export type Role = 'owner' | 'admin' | 'member' | 'viewer'
export type AssignableRole = Exclude<Role, 'owner'>

export interface User {
  id: string
  email: string
  display_name: string
  email_verified: boolean
  theme: Theme
  created_at: string
}

export interface SessionResponse {
  user: User
  access_expires_at: string
}

export interface Workspace {
  id: string
  name: string
  role: Role
  is_personal: boolean
  is_demo: boolean
  ai_consent: boolean
  member_count: number
  created_at: string
}

export interface Member {
  user_id: string
  email: string
  display_name: string
  role: Role
  joined_at: string
}

export interface Invitation {
  id: string
  email: string | null
  role: Role
  expires_at: string
  created_at: string
}

export interface InvitationCreated extends Invitation {
  token: string
  invite_url: string
}

export interface InvitationPreview {
  workspace_id: string
  workspace_name: string
  role: Role
  invited_by: string | null
  expires_at: string
}

const RANK: Record<Role, number> = { viewer: 0, member: 1, admin: 2, owner: 3 }
export const atLeast = (role: Role, min: Role) => RANK[role] >= RANK[min]

// ---------------------------------------------------------------- documents (Phase 4)

export type FileType = 'pdf' | 'docx' | 'txt'
export type DocumentStatus = 'uploaded' | 'queued' | 'processing' | 'ready' | 'failed' | 'deleting'
export type DocumentSort = 'newest' | 'oldest' | 'name' | 'size'

export interface DocumentItem {
  id: string
  title: string
  original_filename: string
  file_type: FileType
  mime_type: string
  size_bytes: number
  status: DocumentStatus
  error_code: string | null
  error_message: string | null
  page_count: number | null
  page_unit: 'page' | 'section'
  chunk_count: number | null
  collection_ids: string[]
  uploaded_by: { id: string; display_name: string } | null
  can_edit: boolean
  created_at: string
  indexed_at: string | null
}

export interface DocumentList {
  items: DocumentItem[]
  total: number
  counts: { all: number; pdf: number; docx: number; txt: number }
}

export interface UploadResult {
  filename: string
  outcome: 'created' | 'duplicate' | 'rejected'
  document: DocumentItem | null
  code: string | null
  detail: string | null
}

export interface DocumentPage {
  page_number: number
  page_count: number
  page_unit: 'page' | 'section'
  text: string
}

export interface Collection {
  id: string
  name: string
  description: string | null
  document_count: number
  created_at: string
  updated_at: string
}

export const isProcessing = (s: DocumentStatus) => s === 'queued' || s === 'processing' || s === 'uploaded'

// ---------------------------------------------------------------- AI (Phase 5)

export type Scope =
  | { type: 'workspace' }
  | { type: 'collection'; id: string }
  | { type: 'documents'; ids: string[] }

export interface Conversation {
  id: string
  title: string
  scope: Scope
  created_at: string
  updated_at: string
}

export interface Citation {
  marker: string // "S1"
  document_id: string | null // null when the document was deleted
  document_title: string
  page_number: number | null
  page_unit: 'page' | 'section'
  excerpt: string
  chunk_id: string | null
  char_start: number | null
  char_end: number | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: 'complete' | 'streaming' | 'failed' | 'not_found'
  created_at: string
  citations: Citation[]
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[]
}

export interface AiStatus {
  configured: boolean
  consent: boolean
  questions_left_today: number
  daily_limit: number
  chat_model: string
}
