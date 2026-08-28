# Template partials

Template partials define reusable template fragments within a template file. They are self-contained components that can be rendered multiple times within the same template, helping to avoid repetition and maintain consistent output.

## Basic syntax

A partial can be defined using the partialdef tag:

authors.html

```
{% partialdef user-info %}
    <div id="user-info-{{ user.username }}">
        <h3>{{ user.name }}</h3>
        <p>{{ user.bio }}</p>
    </div>
{% endpartialdef %}
```

For extra readability, the name can be included in the {% endpartialdef %} closing tag:

```
{% partialdef user-info %}
    {# ... #}
{% endpartialdef user-info %}
```

The template fragment can be rendered using the partial tag:

```
{% partial user-info %}
```

## Fragment reuse

A template fragment can be reused multiple times:

authors.html

```
{% block content %}
    <h2>Authors</h2>
    {% for user in authors %}
        {% partial user-info %}
    {% endfor %}

    <h2>Editors</h2>
    {% for user in editors %}
        {% partial user-info %}
    {% endfor %}
{% endblock %}
```

The partial content is rendered each time the named partial is used, with the current template context.

## Inline partials

A template fragment can be defined and rendered in-place using the inline argument. This defines the partial for later reuse while also rendering it immediately at its definition:

```
{# Define and render immediately. #}
{% partialdef user-info inline %}
    <div id="user-info-{{ user.username }}">
        <h3>{{ user.name }}</h3>
        <p>{{ user.bio }}</p>
    </div>
{% endpartialdef %}

{# Other page content here. #}

{# Reuse later elsewhere in the template. #}
<section class="featured-authors">
    <h2>Featured Authors</h2>
    {% for user in featured %}
        {% partial user-info %}
    {% endfor %}
</section>
```

## Accessing partials directly

Template fragments defined with partialdef can be accessed directly via template loading or inclusion using the `template.html#partial_name` syntax.

For example, using the render() shortcut, the following code renders only the partial named user-info defined in the authors.html template:

```
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render


def user_info_partial(request, user_id):
    user = get_object_or_404(User, id=user_id)
    return render(request, "authors.html#user-info", {"user": user})
```

This approach is particularly useful for AJAX-style requests that update only specific portions of a page with the rendered template fragment.

Template partials can also be included using the include template tag with the same # directive:

```
{% include "authors.html#user-info" %}
```

## Context handling

Template partials are rendered with the current template context. They work as expected in loops and with context variables:

```
{% for user in users %}
    {% partial user-info %}
{% endfor %}
```

Context variables can be adjusted using the with tag:

```
{% with user=featured_author %}
    <h2>Featured Author of the Month</h2>
    {% partial user-info %}
{% endwith %}
```
