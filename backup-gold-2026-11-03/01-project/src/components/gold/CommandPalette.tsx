'use client'

/**
 * لوحة أوامر سريعة مثل TradingView — cmdk (⌘K)
 */
import { useEffect, useState } from 'react'
import { Command } from 'cmdk'

export interface PaletteAction {
  id: string
  label: string
  hint?: string
  group: 'تنقّل' | 'إجراءات' | 'أمثلة ذهبية'
  run: () => void
}

export default function CommandPalette({ actions }: { actions: PaletteAction[] }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const h = () => setOpen(true)
    window.addEventListener('fingpt:palette', h)
    return () => window.removeEventListener('fingpt:palette', h)
  }, [])

  const groups = ['تنقّل', 'إجراءات', 'أمثلة ذهبية'] as const

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 px-4 pt-[14vh] backdrop-blur-sm"
          onMouseDown={() => setOpen(false)}
        >
          <div
            className="w-full max-w-lg overflow-hidden rounded-2xl border border-amber-500/25 bg-[#1c1814] shadow-2xl shadow-black/60"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <Command label="لوحة الأوامر" loop>
              <div className="flex items-center gap-2 border-b border-amber-500/15 px-4">
                <span className="text-amber-400">⌘</span>
                <Command.Input
                  autoFocus
                  placeholder="ابحث عن قسم أو إجراء…"
                  className="h-12 w-full bg-transparent text-sm text-neutral-100 outline-none placeholder:text-neutral-500"
                />
                <kbd className="num rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-500" dir="ltr">
                  ESC
                </kbd>
              </div>
              <Command.List className="gold-scroll max-h-[46vh] overflow-y-auto p-2">
                <Command.Empty className="py-6 text-center text-sm text-neutral-500">
                  لا نتائج — جرّب كلمة أخرى
                </Command.Empty>
                {groups.map((g) => {
                  const items = actions.filter((a) => a.group === g)
                  if (!items.length) return null
                  return (
                    <Command.Group
                      key={g}
                      heading={g}
                      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-amber-500/80"
                    >
                      {items.map((a) => (
                        <Command.Item
                          key={a.id}
                          value={`${a.label} ${a.hint ?? ''}`}
                          onSelect={() => {
                            setOpen(false)
                            a.run()
                          }}
                          className="flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 text-sm text-neutral-200 data-[selected=true]:bg-amber-500/15 data-[selected=true]:text-amber-200"
                        >
                          <span>{a.label}</span>
                          {a.hint && <span className="text-[11px] text-neutral-500">{a.hint}</span>}
                        </Command.Item>
                      ))}
                    </Command.Group>
                  )
                })}
              </Command.List>
            </Command>
          </div>
        </div>
      )}
    </>
  )
}
