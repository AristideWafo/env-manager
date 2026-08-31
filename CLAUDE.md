# Env Manager

Before creating or modifying frontend UI, read `design/DESIGN.md` and the
relevant sections of `design/COMPONENTS.md`. Reuse existing visual
primitives and components before introducing new patterns. Do not
reintroduce django-cotton or any other component-templating framework —
this project uses plain Django template inheritance (`{% extends %}` /
`{% block %}`) and plain CSS component classes (`static/css/theme.css`).
