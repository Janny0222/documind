import { FileText, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Logo } from '@/components/brand/Logo'

interface AuthLayoutProps {
  title: string
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
}

/**
 * Split layout: the form on the right, and on large screens a quiet panel that shows what
 * DocuMind is for - a real-looking answer that cites its source. On mobile only the form shows.
 */
export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <aside className="bg-accent/60 relative hidden overflow-hidden border-r lg:flex lg:flex-col lg:justify-between lg:p-12">
        <Link to="/" className="w-fit rounded-md">
          <Logo />
        </Link>
        <div className="mx-auto w-full max-w-md">
          <h2 className="text-[2.15rem] leading-[1.12] font-bold">
            Your documents.
            <br />
            Your knowledge.
            <br />
            Answers you can check.
          </h2>
          <SampleAnswer />
        </div>
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <ShieldCheck className="size-4" aria-hidden />
          Every answer links to the passage it came from.
        </p>
      </aside>

      <main className="flex flex-col px-4 py-8 sm:px-8 lg:px-16">
        <Link to="/" className="mb-10 w-fit rounded-md lg:hidden">
          <Logo />
        </Link>
        <div className="my-auto w-full max-w-sm self-center">
          <h1 className="text-[1.75rem] leading-tight font-bold">{title}</h1>
          {subtitle ? <p className="text-muted-foreground mt-2">{subtitle}</p> : null}
          <div className="mt-8">{children}</div>
          {footer ? <div className="text-muted-foreground mt-8 text-sm">{footer}</div> : null}
        </div>
      </main>
    </div>
  )
}

function SampleAnswer() {
  return (
    <figure aria-label="Example of a cited answer" className="mt-10 space-y-3">
      <div className="bg-card ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md border px-4 py-2.5 text-sm shadow-[var(--shadow-soft)]">
        How much notice do I need to give before resigning?
      </div>
      <div className="ring-ai rounded-2xl rounded-bl-md p-4 text-sm leading-relaxed shadow-[var(--shadow-lift)]">
        <p>
          Employees give <strong>30 days&apos; written notice</strong>; managers give 60 days
          <sup className="text-primary ml-0.5 font-semibold">1</sup>.
        </p>
        <div className="bg-muted mt-3 flex items-start gap-3 rounded-lg p-3">
          <FileText className="text-file-pdf mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium">Employee Handbook.pdf, page 12</p>
            <p className="text-muted-foreground mt-1 text-[0.8rem]">
              &ldquo;…employees shall provide no less than thirty (30) days written notice…&rdquo;
            </p>
          </div>
        </div>
      </div>
    </figure>
  )
}
