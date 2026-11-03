'use client'

import { useEffect, useRef, useState } from 'react'
import { animate, useMotionValue } from 'motion/react'

/** عدّاد متحرك (Motion) للأسعار — count-up سلس عند تغيّر القيمة */
export function CountUp({
  value,
  decimals = 0,
  prefix = '',
  suffix = '',
  duration = 1.4,
  className = '',
}: {
  value: number
  decimals?: number
  prefix?: string
  suffix?: string
  duration?: number
  className?: string
}) {
  const mv = useMotionValue(0)
  const started = useRef(false)
  const [display, setDisplay] = useState(() => (0).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }))

  useEffect(() => {
    const from = started.current ? mv.get() : 0
    started.current = true
    mv.set(from)
    const controls = animate(mv, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) =>
        setDisplay(
          v.toLocaleString('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
          })
        ),
    })
    return () => controls.stop()
  }, [value, decimals, duration])

  return (
    <span dir="ltr" className={`num ${className}`}>
      {prefix}
      {display}
      {suffix}
    </span>
  )
}
