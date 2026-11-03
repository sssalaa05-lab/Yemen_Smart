#!/usr/bin/env python3
"""تحويل قيم oklch في الثيم إلى hex للتوثيق والمعاينة."""

def oklch_to_hex(L, C, H):
    """oklch -> sRGB hex (matrix from Björn Ottosson's reference)."""
    import math
    h = math.radians(H)
    a = C * math.cos(h)
    b = C * math.sin(h)

    # encode linear -> sRGB (صحيح: ضرب في 12.92 للقيم الداكنة وليس قسمة)
    encode = lambda c: c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055

    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l, m, s = l_**3, m_**3, s_**3

    r = encode(+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)
    g = encode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)
    bl = encode(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)

    def clamp(x):
        return max(0, min(1, x))

    return "#{:02x}{:02x}{:02x}".format(
        round(clamp(r) * 255), round(clamp(g) * 255), round(clamp(bl) * 255)
    )


TOKENS = {
    "background": (0.16, 0.01, 85),
    "foreground": (0.93, 0.012, 85),
    "card": (0.2, 0.012, 85),
    "card-foreground": (0.93, 0.012, 85),
    "popover": (0.19, 0.012, 85),
    "popover-foreground": (0.93, 0.012, 85),
    "primary (ذهبي)": (0.78, 0.145, 82),
    "primary-foreground": (0.18, 0.03, 82),
    "secondary": (0.26, 0.015, 85),
    "secondary-foreground": (0.93, 0.012, 85),
    "muted": (0.25, 0.012, 85),
    "muted-foreground": (0.66, 0.02, 85),
    "accent": (0.28, 0.025, 82),
    "accent-foreground": (0.95, 0.03, 85),
    "destructive": (0.704, 0.191, 22.216),
    "light": (0.985, 0, 0),
    "dark-fg-base": (0.145, 0, 0),
    "border-white9": None,
}

if __name__ == "__main__":
    for name, v in TOKENS.items():
        if v is None:
            print(f"{name:24s} = oklch(1 0 0 / 9%)  (شفاف)")
            continue
        L, C, H = v
        print(f"{name:24s} = oklch({L} {C} {H})  = {oklch_to_hex(L, C, H)}")
    # تدرجات gold-text
    print("--- gold-text gradient ---")
    print("fde68a -> f59e0b -> d97706 (ثابتة بالفعل)")
    # tailwind amber/emerald/red المستخدمة
    print("--- tailwind classes المستخدمة (معروفة) ---")
    print("amber-300 #fcd34d | amber-400 #fbbf24 | amber-500 #f59e0b | amber-600 #d97706 | amber-950 #451a03")
    print("emerald-400 #34d399 | emerald-600 #059669 | red-400 #f87171 | red-500 #ef4444")
    print("neutral-400 #a3a3a3 | neutral-500 #737373 | neutral-700 #404040 | neutral-800 #262626 | neutral-900 #171717")
