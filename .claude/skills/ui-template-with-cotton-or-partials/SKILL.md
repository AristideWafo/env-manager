---
name: ui-template-with-cotton-or-partials
description: Creates Django template UI using Cotton components and/or Django partials for DRY, reusable code.
allowed-tools: Read, Grep, Glob, Bash(bash scripts/*), Bash(git clone:*github.com/wrabit/django-cotton*)
---

# Django Template Author with Cotton or Django Partials

https://github.com/wrabit/django-cotton

## Make sure that documentation is present

To use documentation make sure that Cotton's documentation is present and has been updated in the last two weeks. Use `scripts/update_cotton_documentation.bash` for this, it is idempotent and can be run before consulting documentation.

## Read Documentation When Needed

Documentation for cotton is available in the "documentation" directory.
Documentation for Django's templates is available in `reference/django_template_partial.md`

## Purpose

Create DRY code with regards to template UI so that when we change elements there will not be inconsistencies. Also reuse UI code to have the same UI elements within the application

- When UI code is to be used within the same template, use a Django Partial
- If a component is to be used in different places and different templates, then it should live in a Cotton component

## Cotton Installation

If pip is used:

```shell
pip install django-cotton
```

If uv is used:

```shell
uv add django-cotton
```

In `settings.py` make sure that `INSTALLED_APPS` contains 'django_cotton'.

## Usage Instructions
   
Create UI elements per usual for Django. Then for each one which is used more than once contemplate if it should be abstracted to a partial or to a Cotton component as described above.

Check if Tailwind CSS is present in the project. If so, use it as much as you can while creating UI code. Check for existing CSS, usually an `input.css` in the project which may contain classes and definitions of the project; use those everywhere you can on generated code.

Request the user to have Django 5.2+ installed to be able to use partials. Install Cotton if it is not there. Write cotton components in the appropriate directory for the module, "COTTON_DIR" in settings or default to "cotton". Refer to the documentation for tool's usage.

Do not suggest to create cotton components in layout files inherited from other templates.
