"""Small style-lookup filters for the cotton/ui/* components. Kept as plain
Django filters rather than nested {% if %}/{% with %} in the templates —
much easier to read and to extend with a new variant/tone/size."""

from django import template

register = template.Library()

_BUTTON_TONES = {
    "primary": "bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-950/40 focus:ring-indigo-500",
    "danger": "bg-rose-600/90 hover:bg-rose-500 text-white shadow-lg shadow-rose-950/40 focus:ring-rose-500",
    "ghost": "bg-transparent hover:bg-white/5 text-slate-300 hover:text-white focus:ring-slate-600",
    "secondary": "bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700 focus:ring-slate-500",
}

_BUTTON_SIZES = {
    "sm": "text-xs px-3 py-1.5",
    "md": "text-sm px-4 py-2.5",
}

_BADGE_TONES = {
    "slate": "bg-slate-800 text-slate-300 ring-1 ring-inset ring-slate-700",
    "indigo": "bg-indigo-500/10 text-indigo-300 ring-1 ring-inset ring-indigo-500/30",
    "emerald": "bg-emerald-500/10 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
    "amber": "bg-amber-500/10 text-amber-300 ring-1 ring-inset ring-amber-500/30",
    "rose": "bg-rose-500/10 text-rose-300 ring-1 ring-inset ring-rose-500/30",
}

_ALERT_TONES = {
    "error": ("bg-rose-500/10 border-rose-500/30 text-rose-300", "icon.x_circle"),
    "success": ("bg-emerald-500/10 border-emerald-500/30 text-emerald-300", "icon.check_circle"),
}


@register.filter
def button_tone(variant):
    return _BUTTON_TONES.get(variant, _BUTTON_TONES["secondary"])


@register.filter
def button_size(size):
    return _BUTTON_SIZES.get(size, _BUTTON_SIZES["md"])


@register.filter
def badge_tone(tone):
    return _BADGE_TONES.get(tone, _BADGE_TONES["slate"])


@register.filter
def alert_tone(tone):
    return _ALERT_TONES.get(tone, _ALERT_TONES["error"])[0]
